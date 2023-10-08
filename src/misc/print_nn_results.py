import pandas as pd
import paths as pt
from pathlib import Path
import glob
import os

if __name__ == "__main__":
    path = pt.RESULTS_DIR    
    all_files = glob.glob(os.path.join(path , "mlp*.csv")) + glob.glob(os.path.join(path , "bnn*.csv"))
    
    li = []

    for filename in all_files:
        df = pd.read_csv(filename, index_col=None, header=0)
        li.append(df)

    results = pd.concat(li, axis=0, ignore_index=True)
    results = results.round(3)
    
    model_names = ["MLP"] #"MLP-ALEA", "VI", "VI-EPI", "MCD"
    dataset_name = ["WHAS500"] #"SEER", "GBSG2", "FLCHAIN", "SUPPORT", "METABRIC"
    metrics = ["TestLoss", "TestCTD", "TestIBS", "TestINBLL"]
    
    for dataset_name in dataset_name:
        for index, model_name in enumerate(model_names):
            if index > 0:
                text = "+ "
            else:
                text = ""
            res = results.loc[(results['DatasetName'] == dataset_name) & (results['ModelName'] == model_name)]
            best_ep = res.iloc[0]['BestEP']
            best_obs = res.groupby(['ModelName', 'DatasetName'])[metrics].nth(best_ep-1)
            t_train = res.groupby(['ModelName', 'DatasetName'])['TrainTime'].nth(range(best_ep-1)).sum()            
            ctd = float(best_obs['TestCTD'])
            ibs = float(best_obs['TestIBS'])
            loss = float(best_obs['TestLoss'])
            if model_name == "MLP":
                model_name = "Baseline (MLP)"
            text += f"{model_name} & "
            text += f"{t_train} & {ctd} & {ibs} & {loss} \\\\"
            print(text)
        print()
        