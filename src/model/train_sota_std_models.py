import numpy as np
import tensorflow as tf

import random
import pandas as pd

from sklearn.model_selection import train_test_split
from sksurv.metrics import concordance_index_censored, concordance_index_ipcw
from sksurv.metrics import integrated_brier_score
from utility.survival import convert_to_structured
from utility.training import get_data_loader, scale_data, make_time_event_split
from tools.model_builder import make_cox_model, make_coxnet_model, make_rsf_model, make_dsm_model, make_dcph_model
from utility.risk import _make_riskset
from utility.loss import CoxPHLoss
from pathlib import Path
import paths as pt
import joblib
import os
from time import time
from utility.config import load_config
from sksurv.linear_model.coxph import BreslowEstimator

np.random.seed(0)
tf.random.set_seed(0)
random.seed(0)

DATASETS = ["WHAS500", "SEER", "GBSG2", "FLCHAIN", "SUPPORT", "METABRIC"]
MODEL_NAMES = ["Cox", "CoxNet", "RSF"]
results = pd.DataFrame()
loss_fn = CoxPHLoss()

if __name__ == "__main__":
    # For each dataset, train three models (Cox, CoxNet, RSF)
    for dataset_name in DATASETS:
        print(f"Now training dataset {dataset_name}")
        
        # Load data
        dl = get_data_loader(dataset_name).load_data()
        X, y = dl.get_data()
        num_features, cat_features = dl.get_features()

        # Split data in train and test set
        X_train, X_test, y_train, y_test = train_test_split(X, y, train_size=0.7, random_state=0)

        # Scale data
        X_train, X_test = scale_data(X_train, X_test, cat_features, num_features)

        # Make time/event split
        t_train, e_train = make_time_event_split(y_train)
        t_test, e_test = make_time_event_split(y_test)
        
        # Make event times
        lower, upper = np.percentile(t_test[t_test.dtype.names], [10, 90])
        event_times = np.arange(lower, upper+1)

        # Load training parameters
        rsf_config = load_config(pt.RSF_CONFIGS_DIR, f"{dataset_name.lower()}.yaml")
        cox_config = load_config(pt.COX_CONFIGS_DIR, f"{dataset_name.lower()}.yaml")
        coxnet_config = load_config(pt.COXNET_CONFIGS_DIR, f"{dataset_name.lower()}.yaml")

        # Make models
        rsf_model = make_rsf_model(rsf_config)
        cox_model = make_cox_model(cox_config)
        coxnet_model = make_coxnet_model(coxnet_config)
    
        # Train models
        print("Now training Cox")
        cox_train_start_time = time()
        cox_model.fit(X_train, y_train)
        cox_train_time = time() - cox_train_start_time
        print(f"Finished training Cox in {cox_train_time}")

        print("Now training CoxNet")
        coxnet_train_start_time = time()
        coxnet_model.fit(X_train, y_train)
        coxnet_train_time = time() - coxnet_train_start_time
        print(f"Finished training CoxNet in {coxnet_train_time}")

        print("Now training RSF")
        rsf_train_start_time = time()
        rsf_model.fit(X_train, y_train)
        rsf_train_time = time() - rsf_train_start_time
        print(f"Finished training RSF in {rsf_train_time}")

        trained_models = [cox_model, coxnet_model, rsf_model]
        train_times = [cox_train_time, coxnet_train_time, rsf_train_time]

        # Compute scores
        lower, upper = np.percentile(t_test[t_test.dtype.names], [10, 90])
        times = np.arange(lower, upper+1)
        y_train_struc = convert_to_structured(t_train, e_train)
        y_test_struc = convert_to_structured(t_test, e_test)
        event_set = tf.expand_dims(e_test.astype(np.int32), axis=1)
        risk_set = tf.convert_to_tensor(_make_riskset(t_test), dtype=np.bool_)
        for model, model_name, train_time in zip(trained_models, MODEL_NAMES, train_times):
            # Make predictions
            test_start_time = time()
            if model_name == "DSM":
                preds = model.predict_risk(X_test.astype(np.float64), times=y_test['time'].max()).flatten()
            elif model_name == "DCPH":
                preds = model.predict_risk(np.array(X_test), t=y_test['time'].max()).flatten()
            else:
                preds = model.predict(X_test)
            test_time = time() - test_start_time

            # Compute loss
            if model_name in ["Cox", "CoxNet"]:
                print(f"Computing loss for {model_name}")
                preds_tn = tf.convert_to_tensor(preds.reshape(len(preds), 1).astype(np.float32))
                loss = loss_fn(y_true=[event_set, risk_set], y_pred=preds_tn).numpy()
            else:
                loss = np.nan

            # Compute CI/CTD
            ci = concordance_index_censored(y_test["event"], y_test["time"], preds)[0]
            ctd = concordance_index_ipcw(y_train_struc, y_test_struc, preds)[0]
            
            # Compute IBS
            if model_name == "DSM":
                train_predictions = model.predict_risk(X_train.astype(np.float64), y_test['time'].max()).reshape(-1) # TODO
                test_predictions = model.predict_risk(X_test.astype(np.float64), y_test['time'].max()).reshape(-1)
                breslow = BreslowEstimator().fit(train_predictions, e_train, t_train)
                test_surv_fn = breslow.get_survival_function(test_predictions)
            elif model_name == "DCPH":
                train_predictions = model.predict_risk(np.array(X_train), y_test['time'].max())
                test_predictions = model.predict_risk(np.array(X_test), y_test['time'].max())
                breslow = BreslowEstimator().fit(train_predictions, e_train, t_train)
                test_surv_fn = breslow.get_survival_function(test_predictions)
            elif model_name == "RSF": # use KM estimator instead
                test_surv_fn = model.predict_survival_function(X_test)
            else:
                train_predictions = model.predict(X_train).reshape(-1)
                test_predictions = model.predict(X_test).reshape(-1)
                breslow = BreslowEstimator().fit(train_predictions, e_train, t_train)
                test_surv_fn = breslow.get_survival_function(test_predictions)
            surv_preds = np.row_stack([fn(times) for fn in test_surv_fn])
            ibs = integrated_brier_score(y_train_struc, y_test_struc, surv_preds, list(times))

            # Save to df
            res_df = pd.DataFrame(np.column_stack([loss, ci, ctd, ibs, train_time, test_time]),
                                  columns=["TestLoss", "TestCI", "TestCTD", "TestIBS",
                                           "TrainTime", "TestTime"])
            res_df['ModelName'] = model_name
            res_df['DatasetName'] = dataset_name
            results = pd.concat([results, res_df], axis=0)

            # Save model
            path = Path.joinpath(pt.MODELS_DIR, f"{model_name.lower()}.joblib")
            joblib.dump(model, path)

    # Save results
    results.to_csv(Path.joinpath(pt.RESULTS_DIR, f"sota_std_results.csv"), index=False)

