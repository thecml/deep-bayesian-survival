import tensorflow as tf
import numpy as np
import paths as pt
from utility.loss import CoxPHLoss, CoxPHLossLLA

class Trainer:
    def __init__(self, model, model_name, train_dataset, valid_dataset,
                 test_dataset, optimizer, loss_function, num_epochs, early_stop,
                 patience, n_samples_train, n_samples_valid, n_samples_test):
        self.num_epochs = num_epochs
        self.model = model
        self.model_name = model_name

        self.train_ds = train_dataset
        self.valid_ds = valid_dataset
        self.test_ds = test_dataset

        self.optimizer = optimizer
        self.loss_fn = loss_function
        
        self.n_samples_train = n_samples_train
        self.n_samples_valid = n_samples_valid
        self.n_samples_test = n_samples_test

        # Loss
        self.train_loss_metric = tf.keras.metrics.Mean(name="train_loss")
        self.valid_loss_metric = tf.keras.metrics.Mean(name="valid_loss")
        self.test_loss_metric = tf.keras.metrics.Mean(name="test_loss")
        self.train_loss_scores, self.valid_loss_scores, self.test_loss_scores = list(), list(), list()
        
        self.test_variance = list()
        
        self.early_stop = early_stop
        self.patience = patience
        
        self.best_val_nll = np.inf
        self.best_ep = -1
        
        self.checkpoint = tf.train.Checkpoint(optimizer=self.optimizer, model=self.model)
        self.manager = tf.train.CheckpointManager(self.checkpoint, directory=f"{pt.MODELS_DIR}", max_to_keep=num_epochs)
        
    def train_and_evaluate(self):
        stop_training = False
        for epoch in range(1, self.num_epochs+1):
            if epoch > 0 and self.model_name == "SNGP":
                self.model.layers[-1].reset_covariance_matrix() # reset covmat for SNGP
            self.train(epoch)
            if self.valid_ds is not None:
                stop_training = self.validate(epoch)
            if self.test_ds is not None:
                self.test()
            if stop_training:
                self.cleanup()
                break
            self.cleanup()

    def train(self, epoch):
        for x, y in self.train_ds:
            y_event = tf.expand_dims(y["label_event"], axis=1)
            with tf.GradientTape() as tape:
                if self.model_name in ["MLP-ALEA", "VI", "VI-EPI", "MCD-EPI", "MCD"]:
                    runs = self.n_samples_train
                    logits_cpd = tf.zeros((runs, y_event.shape[0]), dtype=np.float32)
                    output_list = []
                    tensor_shape = logits_cpd.get_shape()
                    for i in range(tensor_shape[0]):
                        y_pred = self.model(x, training=True)
                        if self.model_name in ["MLP-ALEA", "VI", "MCD"]:
                            output_list.append(tf.reshape(y_pred.sample(), y_pred.shape[0]))
                        else:
                            output_list.append(tf.reshape(y_pred, y_pred.shape[0]))
                    logits_cpd = tf.stack(output_list)
                    if isinstance(self.loss_fn, CoxPHLoss):
                        logits = tf.transpose(tf.reduce_mean(logits_cpd, axis=0, keepdims=True))
                        loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits)
                        self.train_loss_metric.update_state(loss)
                    elif self.model_name in ["VI", "VI-EPI"]:
                        cox_loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits_cpd)
                        logits = tf.transpose(tf.reduce_mean(logits_cpd, axis=0, keepdims=True))
                        loss = cox_loss + tf.reduce_mean(self.model.losses) # CoxPHLoss + KL-divergence
                        self.train_loss_metric.update_state(cox_loss)
                    else:
                        loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits_cpd)
                        logits = tf.transpose(tf.reduce_mean(logits_cpd, axis=0, keepdims=True))
                        self.train_loss_metric.update_state(loss)
                elif self.model_name == "SNGP":
                    logits = self.model(x, training=True)[0]
                    loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits)
                    self.train_loss_metric.update_state(loss)
                else:
                    logits = self.model(x, training=True)
                    loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits)
                    self.train_loss_metric.update_state(loss)
            with tf.name_scope("gradients"):
                grads = tape.gradient(loss, self.model.trainable_weights)
                self.optimizer.apply_gradients(zip(grads, self.model.trainable_weights))
        print(f"Completed {self.model_name} epoch {epoch}/{self.num_epochs}")
        epoch_loss = self.train_loss_metric.result()
        self.train_loss_scores.append(float(epoch_loss))
        self.manager.save()

    def validate(self, epoch):
        stop_training = False
        for x, y in self.valid_ds:
            y_event = tf.expand_dims(y["label_event"], axis=1)
            if self.model_name in ["MLP-ALEA", "VI", "VI-EPI", "MCD-EPI", "MCD"]:
                runs = self.n_samples_valid
                logits_cpd = np.zeros((runs, len(x)), dtype=np.float32)
                for i in range(0, runs):
                    if self.model_name in ["MLP-ALEA", "VI", "MCD"]:
                        logits_cpd[i,:] = np.reshape(self.model(x, training=False).sample(), len(x))
                    else:
                        logits_cpd[i,:] = np.reshape(self.model(x, training=False), len(x))
                logits_mean = tf.transpose(tf.reduce_mean(logits_cpd, axis=0, keepdims=True))
                if isinstance(self.loss_fn, CoxPHLoss):
                    loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits_mean)
                else:
                    logits = self.model(x, training=False)
                    loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits_cpd)
                self.valid_loss_metric.update_state(loss)
            elif self.model_name == "SNGP":
                logits = self.model(x, training=False)[0]
                loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits)
                self.valid_loss_metric.update_state(loss)
            else:
                logits = self.model(x, training=False)
                loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits)
                self.valid_loss_metric.update_state(loss)
        epoch_loss = self.valid_loss_metric.result()
        self.valid_loss_scores.append(float(epoch_loss))

        # Early stopping
        if self.early_stop:
            print(f'Best Val NLL: {self.best_val_nll}, epoch Val NNL: {epoch_loss}')
            if self.best_val_nll > epoch_loss:
                self.best_val_nll = epoch_loss
                self.best_ep = epoch
            if (epoch - self.best_ep) > self.patience:
                print(f"Validation loss converges at {self.best_ep}th epoch.")
                stop_training = True
            else:
                stop_training = False
                
        return stop_training

    def test(self):
        batch_variances = list()
        for x, y in self.test_ds:
            y_event = tf.expand_dims(y["label_event"], axis=1)
            if self.model_name in ["MLP-ALEA", "VI", "VI-EPI", "MCD-EPI", "MCD"]:
                runs = self.n_samples_test
                logits_cpd = np.zeros((runs, len(x)), dtype=np.float32)
                for i in range(0, runs):
                    if self.model_name in ["MLP-ALEA", "VI", "MCD"]:
                        logits_cpd[i,:] = np.reshape(self.model(x, training=False).sample(), len(x))
                    else:
                        logits_cpd[i,:] = np.reshape(self.model(x, training=False), len(x))
                logits_mean = tf.transpose(tf.reduce_mean(logits_cpd, axis=0, keepdims=True))
                batch_variances.append(np.mean(tf.math.reduce_variance(logits_cpd, axis=0, keepdims=True)))
                
                #logits = self.model(x, training=False)
                if isinstance(self.loss_fn, CoxPHLoss):
                    loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits_mean)
                else:
                    loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits_cpd)
                self.test_loss_metric.update_state(loss)
            elif self.model_name == "SNGP":
                logits, covmat = self.model(x, training=False)
                batch_variances.append(np.mean(tf.linalg.diag_part(covmat)[:, None]))
                loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits)
                self.test_loss_metric.update_state(loss)
            else:
                logits = self.model(x, training=False)
                batch_variances.append(0) # zero variance for MLP
                loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits)
                self.test_loss_metric.update_state(loss)
         
        # Track variance
        if len(batch_variances) > 0:
            self.test_variance.append(float(np.mean(batch_variances)))

        epoch_loss = self.test_loss_metric.result()
        self.test_loss_scores.append(float(epoch_loss))

    def cleanup(self):
        self.train_loss_metric.reset_states()
        self.valid_loss_metric.reset_states()
        self.test_loss_metric.reset_states()
