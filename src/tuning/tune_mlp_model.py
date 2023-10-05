"""
tune_mlp_model.py
====================================
Tuning script for mlp model
--dataset: Dataset name, one of "SUPPORT", "NHANES", "GBSG2", "WHAS500", "FLCHAIN", "METABRIC"
"""

import numpy as np
import os
import tensorflow as tf
from tools.model_builder import make_mlp_model
from utility.risk import InputFunction
from utility.loss import CoxPHLoss
from tools import data_loader, model_trainer
import os
import random
from sklearn.model_selection import train_test_split, KFold
from tools.preprocessor import Preprocessor
from utility.tuning import get_mlp_sweep_config
import argparse
from utility.survival import compute_survival_function
import pandas as pd
from pycox.evaluation import EvalSurv

os.environ["WANDB_SILENT"] = "true"
import wandb

N_RUNS = 10
N_EPOCHS = 10
N_SPLITS = 5
PROJECT_NAME = "baysurv_bo_mlp"

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--dataset', type=str,
                        required=True,
                        default=None)
    args = parser.parse_args()
    global dataset
    if args.dataset:
        dataset = args.dataset

    sweep_config = get_mlp_sweep_config()
    sweep_id = wandb.sweep(sweep_config, project=PROJECT_NAME)
    wandb.agent(sweep_id, train_model, count=N_RUNS)

def train_model():
    config_defaults = {
        'network_layers': [32],
        'learning_rate': [0.001],
        'momentum': [0.0],
        'optimizer': ["Adam"],
        'activation_fn': ["relu"],
        'weight_decay': [None],
        'dropout': [None],
        'l2_reg': [None]
    }

    # Initialize a new wandb run
    wandb.init(config=config_defaults, group=dataset)
    wandb.config.epochs = N_EPOCHS

    # Load data
    if dataset == "SUPPORT":
        dl = data_loader.SupportDataLoader().load_data()
    elif dataset == "GBSG2":
        dl = data_loader.GbsgDataLoader().load_data()
    elif dataset == "WHAS500":
        dl = data_loader.WhasDataLoader().load_data()
    elif dataset == "FLCHAIN":
        dl = data_loader.FlchainDataLoader().load_data()
    elif dataset == "METABRIC":
        dl = data_loader.MetabricDataLoader().load_data()
    elif dataset == "SEER":
        dl = data_loader.SeerDataLoader().load_data()
    else:
        raise ValueError("Dataset not found")

    num_features, cat_features = dl.get_features()
    X, y = dl.get_data()

    # Split data in T1 and HOS
    X_train, X_test, y_train, y_test = train_test_split(X, y, train_size=0.7, random_state=0)
    T1, HOS = (X_train, y_train), (X_test, y_test)

    # Perform K-fold cross-validation
    c_indicies = list()
    kf = KFold(n_splits=N_SPLITS, shuffle=True, random_state=0)
    for train, test in kf.split(T1[0], T1[1]):
        ti_X = T1[0].iloc[train]
        ti_y = T1[1][train]
        cvi_X = T1[0].iloc[test]
        cvi_y = T1[1][test]

        # Scale data split
        preprocessor = Preprocessor(cat_feat_strat='mode', num_feat_strat='mean')
        transformer = preprocessor.fit(ti_X, cat_feats=cat_features, num_feats=num_features,
                                       one_hot=True, fill_value=-1)
        ti_X = np.array(transformer.transform(ti_X))
        cvi_X = np.array(transformer.transform(cvi_X))

        # Make time event split
        t_train = np.array(ti_y['time'])
        t_valid = np.array(cvi_y['time'])
        e_train = np.array(ti_y['event'])
        e_valid = np.array(cvi_y['event'])

        # Make event times
        lower, upper = np.percentile(t_train[t_train.dtype.names], [10, 90])
        event_times = np.arange(lower, upper+1)

        # Set batch size
        if dataset in ["FLCHAIN", "SEER", "SUPPORT"]:
            batch_size = 128
        else:
            batch_size = 32

        train_ds = InputFunction(ti_X, t_train, e_train, batch_size=batch_size,
                                 drop_last=True, shuffle=True)()
        valid_ds = InputFunction(cvi_X, t_valid, e_valid, batch_size=batch_size)()

        # Make model
        model = make_mlp_model(input_shape=ti_X.shape[1:],
                               output_dim=1,
                               layers=wandb.config['network_layers'],
                               activation_fn=wandb.config['activation_fn'],
                               dropout_rate=wandb.config['dropout'],
                               regularization_pen=wandb.config['l2_reg'])

        # Define optimizer
        if wandb.config['optimizer'] == "Adam":
            optimizer = tf.keras.optimizers.Adam(learning_rate=wandb.config.learning_rate,
                                                 weight_decay=wandb.config.weight_decay)
        elif wandb.config['optimizer'] == "SGD":
            optimizer = tf.keras.optimizers.SGD(learning_rate=wandb.config.learning_rate,
                                                weight_decay=wandb.config.weight_decay,
                                                momentum=wandb.config.momentum)
        elif wandb.config['optimizer'] == "RMSprop":
            optimizer = tf.keras.optimizers.RMSprop(learning_rate=wandb.config.learning_rate,
                                                    weight_decay=wandb.config.weight_decay,
                                                    momentum=wandb.config.momentum)

        # Train model
        loss_fn = CoxPHLoss()
        trainer = model_trainer.Trainer(model=model,
                                        model_type="MLP",
                                        train_dataset=train_ds,
                                        valid_dataset=None,
                                        test_dataset=None,
                                        optimizer=optimizer,
                                        loss_function=loss_fn,
                                        num_epochs=N_EPOCHS,
                                        event_times=event_times)
        trainer.train_and_evaluate()
        
        # Compute survival function
        model = trainer.model
        lower, upper = np.percentile(y['time'], [10, 90])
        times = np.arange(lower, upper+1)
        test_surv_fn = compute_survival_function(model, ti_X, cvi_X, ti_y['event'], ti_y['time'], times)
        surv_preds = np.row_stack([fn(times) for fn in test_surv_fn])
        
        # Compute CTD
        surv_test = pd.DataFrame(surv_preds, columns=times)
        ev = EvalSurv(surv_test.T, cvi_y["time"], cvi_y["event"], censor_surv="km")
        ctd = ev.concordance_td()
        c_indicies.append(ctd)

    mean_ci = np.nanmean(c_indicies)

    # Log to wandb
    wandb.log({"val_ci": mean_ci})

if __name__ == "__main__":
    main()