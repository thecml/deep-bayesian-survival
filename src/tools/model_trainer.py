import tensorflow as tf
import numpy as np
from utility.metrics import CindexMetric

class Trainer:
    def __init__(self, model, train_dataset, valid_dataset,
                 test_dataset, optimizer, loss_function, num_epochs):
        self.num_epochs = num_epochs
        self.model = model

        self.train_ds = train_dataset
        self.valid_ds = valid_dataset
        self.test_ds = test_dataset

        self.optimizer = optimizer
        self.loss_fn = loss_function

        self.train_loss_scores = list()
        self.valid_loss_scores, self.valid_ci_scores = list(), list()

        self.train_loss_metric = tf.keras.metrics.Mean(name="train_loss")
        self.train_cindex_metric = CindexMetric()

        self.valid_loss_metric = tf.keras.metrics.Mean(name="val_loss")
        self.valid_cindex_metric = CindexMetric()
        
        self.test_loss_metric = tf.keras.metrics.Mean(name="test_loss")
        self.test_cindex_metric = CindexMetric()

        self.train_loss_scores, self.train_ci_scores = list(), list()
        self.valid_loss_scores, self.valid_ci_scores = list(), list()
        self.test_loss_scores, self.test_ci_scores = list(), list()
        
    def train_and_evaluate(self):
        for _ in range(self.num_epochs):
            self.train()
            if self.valid_ds is not None:
                self.validate()
            if self.test_ds is not None:
                self.test()
            self.cleanup()

    def train(self):
        for x, y in self.train_ds:
            y_event = tf.expand_dims(y["label_event"], axis=1)
            with tf.GradientTape() as tape:
                logits = self.model(x, training=True)
                loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits)
                self.train_loss_metric.update_state(loss)
                self.train_cindex_metric.update_state(y, logits)

            with tf.name_scope("gradients"):
                grads = tape.gradient(loss, self.model.trainable_weights)
                self.optimizer.apply_gradients(zip(grads, self.model.trainable_weights))

        epoch_loss = self.train_loss_metric.result()
        epoch_ci = self.train_cindex_metric.result()['cindex']
        self.train_loss_scores.append(float(epoch_loss))
        self.train_ci_scores.append(float(epoch_ci))

    def validate(self):
        for x, y in self.valid_ds:
            y_event = tf.expand_dims(y["label_event"], axis=1)
            logits = self.model(x, training=False)
            loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=logits)
            self.valid_loss_metric.update_state(loss)
            self.valid_cindex_metric.update_state(y, logits)

        epoch_valid_loss = self.valid_loss_metric.result()
        epoch_valid_ci = self.valid_cindex_metric.result()['cindex']
        self.valid_loss_scores.append(float(epoch_valid_loss))
        self.valid_ci_scores.append(float(epoch_valid_ci))

    def cleanup(self):
        self.train_loss_metric.reset_states()
        self.train_cindex_metric.reset_states()
        self.valid_loss_metric.reset_states()
        self.valid_cindex_metric.reset_states()
        self.test_loss_metric.reset_states()
        self.test_cindex_metric.reset_states()

    def test(self):
        for x, y in self.test_ds:
            y_event = tf.expand_dims(y["label_event"], axis=1)
            runs = 100
            logits_cpd = np.zeros((runs, len(x)), dtype=np.float32)
            for i in range(0, runs):
                logits_cpd[i,:] = np.reshape(self.model(x, training=False).sample(), len(x))
            mean_logits = tf.transpose(tf.reduce_mean(logits_cpd, axis=0, keepdims=True))
            loss = self.loss_fn(y_true=[y_event, y["label_riskset"]], y_pred=mean_logits)
            self.test_loss_metric.update_state(loss)
            self.test_cindex_metric.update_state(y, mean_logits)
            
        epoch_test_loss = self.test_loss_metric.result()
        epoch_test_ci = self.test_cindex_metric.result()['cindex']
        self.test_loss_scores.append(float(epoch_test_loss))
        self.test_ci_scores.append(float(epoch_test_ci))