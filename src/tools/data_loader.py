import numpy as np
import pandas as pd
from sksurv.datasets import load_veterans_lung_cancer, load_gbsg2, load_aids
from auton_survival import datasets
from sklearn.model_selection import train_test_split
import shap
from abc import ABC, abstractmethod
from typing import Tuple, List
from tools.preprocessor import Preprocessor

class BaseDataLoader(ABC):
    """
    Base class for data loaders.
    """
    def __init__(self):
        """Initilizer method that takes a file path, file name,
        settings and optionally a converter"""
        self.X: pd.DataFrame = None
        self.y: np.ndarray = None
        self.num_features: List[str] = None
        self.cat_features: List[str] = None
        
    @abstractmethod
    def load_data(self) -> None:
        """Loads the data from a data set at startup"""
    
    @abstractmethod
    def make_time_event_split(self, y_train, y_valid, y_test) -> None:
        """Makes time/event split of y"""

    def get_data(self) -> Tuple[pd.DataFrame, np.ndarray]:
        """
        This method returns the features and targets
        :return: X and y
        """
        return self.X, self.y

    def get_features(self) -> List[str]:
        """
        This method returns the feature names
        :return: the columns of X as a list
        """
        return self.X.columns

    def prepare_data(self, test_size: float = 0.7) -> Tuple[np.ndarray, np.ndarray,
                                                      np.ndarray, np.ndarray]:
        """
        This method prepares and splits the data from a data set
        :param test_size: the size of the test set
        :return: a split train and test dataset
        """
        X = self.X
        y = self.y
        cat_features = self.cat_features
        num_features = self.num_features
        
        X_train, X_rem, y_train, y_rem = train_test_split(X, y, train_size=test_size, random_state=0)
        X_valid, X_test, y_valid, y_test = train_test_split(X_rem, y_rem, test_size=0.5, random_state=0)
        
        preprocessor = Preprocessor(cat_feat_strat='ignore', num_feat_strat='mean')
        transformer = preprocessor.fit(X_train, cat_feats=cat_features, num_feats=num_features,
                                       one_hot=True, fill_value=-1)
        X_train = transformer.transform(X_train)
        X_valid = transformer.transform(X_valid)
        X_test = transformer.transform(X_test)
    
        X_train = np.array(X_train)
        X_valid = np.array(X_valid)
        X_test = np.array(X_test)

        return X_train, X_valid, X_test, y_train, y_valid, y_test
    
class SupportDataLoader(BaseDataLoader):
    """
    Data loader for SUPPORT dataset
    """
    def load_data(self):
        outcomes, features = datasets.load_dataset("SUPPORT")
        self.X = pd.DataFrame(features)
        self.y = np.array(outcomes)
        self.num_features = self.X.select_dtypes(include=np.number).columns.tolist()
        self.cat_features = self.X.select_dtypes(['category']).columns.tolist()
        return self
    
    def make_time_event_split(self, y_train, y_valid, y_test) -> None:
        t_train = np.array(y_train['time'])
        t_valid = np.array(y_valid['time'])
        t_test = np.array(y_test['time'])
        e_train = np.array(y_train['event'])
        e_valid = np.array(y_valid['event'])
        e_test = np.array(y_test['event'])
        return t_train, t_valid, t_test, e_train, e_valid, e_test
    
class NhanesDataLoader(BaseDataLoader):
    """
    Data loader for NHANES dataset
    """
    def load_data(self):
        nhanes_X, nhanes_y = shap.datasets.nhanesi()
        self.X = pd.DataFrame(nhanes_X)
        self.y = np.array(nhanes_y)
        self.num_features = self.X.select_dtypes(include=np.number).columns.tolist()
        self.cat_features = self.X.select_dtypes(['category']).columns.tolist()
        return self
    
    def make_time_event_split(self, y_train, y_valid, y_test) -> None:
        t_train = np.array(y_train)
        t_valid = np.array(y_valid)
        t_test = np.array(y_test)
        e_train = np.array([True if x > 0 else False for x in y_train])
        e_valid = np.array([True if x > 0 else False for x in y_valid])
        e_test = np.array([True if x > 0 else False for x in y_test])
        return t_train, t_valid, t_test, e_train, e_valid, e_test

class AidsDataLoader(BaseDataLoader):
    def load_data(self) -> None:
        aids_X, aids_y = load_aids()
        self.X = aids_X
        self.y = aids_y
        self.num_features = self.X.select_dtypes(include=np.number).columns.tolist()
        self.cat_features = self.X.select_dtypes(['category']).columns.tolist()
        return self

    def make_time_event_split(self, y_train, y_valid, y_test) -> None:
        t_train = np.array(y_train['time'])
        t_valid = np.array(y_valid['time'])
        t_test = np.array(y_test['time'])
        e_train = np.array(y_train['censor'])
        e_valid = np.array(y_valid['censor'])
        e_test = np.array(y_test['censor'])
        return t_train, t_valid, t_test, e_train, e_valid, e_test

class CancerDataLoader(BaseDataLoader):
    def load_data(self) -> BaseDataLoader:
        gbsg_X, gbsg_y = load_gbsg2()
        self.X = gbsg_X
        self.y = gbsg_y
        self.num_features = self.X.select_dtypes(include=np.number).columns.tolist()
        self.cat_features = self.X.select_dtypes(['category']).columns.tolist()
        return self
    
    def make_time_event_split(self, y_train, y_valid, y_test) -> Tuple[np.ndarray, np.ndarray,
                                                                       np.ndarray, np.ndarray,
                                                                       np.ndarray, np.ndarray]:
        t_train = np.array(y_train['time'])
        t_valid = np.array(y_valid['time'])
        t_test = np.array(y_test['time'])
        e_train = np.array(y_train['cens'])
        e_valid = np.array(y_valid['cens'])
        e_test = np.array(y_test['cens'])
        return t_train, t_valid, t_test, e_train, e_valid, e_test
    
class VeteransDataLoader(BaseDataLoader):
    def load_data(self) -> None:
        data_x, data_y = load_veterans_lung_cancer()
        self.X = data_x
        self.y = data_y
        self.num_features = self.X.select_dtypes(include=np.number).columns.tolist()
        self.cat_features = self.X.select_dtypes(['category']).columns.tolist()
        return self
    
    def make_time_event_split(self, y_train, y_valid, y_test) -> None:
        t_train = np.array(y_train['Survival_in_days'])
        t_valid = np.array(y_valid['Survival_in_days'])
        t_test = np.array(y_test['Survival_in_days'])
        e_train = np.array(y_train['Status'])
        e_valid = np.array(y_valid['Status'])
        e_test = np.array(y_test['Status'])
        return t_train, t_valid, t_test, e_train, e_valid, e_test