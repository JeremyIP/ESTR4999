import argparse
import importlib
import importlib.util
import os
import subprocess

import lightning.pytorch as L
from lightning.pytorch.callbacks import LearningRateMonitor, ModelCheckpoint, EarlyStopping
from lightning.pytorch.loggers import CSVLogger, WandbLogger

from core.data_runner import DataInterface
from core.ltsf_runner import LTSFRunner
from core.util import cal_conf_hash
from core.util import load_module_from_path

# Modified Code to invoke call back to print the loss per epoch
from lightning.pytorch.callbacks import Callback
class TrainLossLoggerCallback(Callback):
    def __init__(self):
        super().__init__()
        self.train_losses = []

    def on_train_epoch_end(self, trainer, pl_module):
        """
        Called at the end of the training epoch.
        Collects the average training loss and appends it to the train_losses list.
        """
        # Retrieve the average training loss from callback_metrics
        avg_loss = trainer.callback_metrics.get('train/loss')
        if avg_loss is not None:
            # Append the average loss to the list
            self.train_losses.append(avg_loss.item())
            # Print the average loss for the epoch
            print(f"Epoch {trainer.current_epoch + 1}: Average Train Loss = {avg_loss.item():.4f}")

    def on_train_end(self, trainer, pl_module):
        """
        Called at the end of training.
        Prints the list of average training losses per epoch.
        """
        print("\nTraining Loss per Epoch:")
        for epoch, loss in enumerate(self.train_losses, 1):
            print(f"Epoch {epoch}: {loss:.4f}")


def load_config(exp_conf_path):
    # 加载 exp_conf
    exp_conf = load_module_from_path("exp_conf", exp_conf_path).exp_conf

    # 加载 task_conf
    task_conf_module = importlib.import_module('config.base_conf.task')
    task_conf = task_conf_module.task_conf

    # 加载 data_conf
    data_conf_module = importlib.import_module('config.base_conf.datasets')
    data_conf = eval('data_conf_module.{}_conf'.format(exp_conf['dataset_name']))

    # conf 融合，参数优先级: exp_conf > task_conf = data_conf
    fused_conf = {**task_conf, **data_conf}
    fused_conf.update(exp_conf)

    return fused_conf


def train_func(hyper_conf, conf):
    if hyper_conf is not None:
        for k, v in hyper_conf.items():
            conf[k] = v
    conf['conf_hash'] = cal_conf_hash(conf, hash_len=10)

    L.seed_everything(conf["seed"])
    save_dir = os.path.join(conf["save_root"], '{}_{}'.format(conf["model_name"], conf["dataset_name"]))
    if "use_wandb" in conf and conf["use_wandb"]:
        run_logger = WandbLogger(save_dir=save_dir, name=conf["conf_hash"], version='seed_{}'.format(conf["seed"]))
    else:
        run_logger = CSVLogger(save_dir=save_dir, name=conf["conf_hash"], version='seed_{}'.format(conf["seed"]))
    conf["exp_dir"] = os.path.join(save_dir, conf["conf_hash"], 'seed_{}'.format(conf["seed"]))

    callbacks = [
        # ModelCheckpoint(
        #     monitor=conf["val_metric"],
        #     mode="min",
        #     save_top_k=1,
        #     save_last=False,
        #     every_n_epochs=1,
        # ),
        # EarlyStopping(
        #     monitor=conf["val_metric"],
        #     mode='min',
        #     patience=conf["es_patience"],
        # ),
        LearningRateMonitor(logging_interval="epoch"),
        TrainLossLoggerCallback(), # Modified Code to invoke call back to print the loss per epoch
    ]


    trainer = L.Trainer(
        devices=conf["devices"],
        precision=conf["precision"] if "precision" in conf else "32-true",
        logger=run_logger,
        callbacks=callbacks,
        max_epochs=conf["max_epochs"],
        gradient_clip_algorithm=conf["gradient_clip_algorithm"] if "gradient_clip_algorithm" in conf else "norm",
        gradient_clip_val=conf["gradient_clip_val"],
        default_root_dir=conf["save_root"],
        limit_val_batches=0, # Disable validation
        check_val_every_n_epoch=0, # No validation every n epoch
    )

    data_module = DataInterface(**conf)
    model = LTSFRunner(**conf)

    trainer.fit(model=model, datamodule=data_module)
    #trainer.test(model, datamodule=data_module, ckpt_path='best')
    trainer.test(model, datamodule=data_module)


    # model.plot_losses()


# Directory for saving configuration files
output_dir = '/config/reproduce_conf/RMoK'

# Template content
template_content = """exp_conf = dict(
    model_name="DenseRMoK",
    dataset_name='{dataset}',     # Set to {dataset} to point to your new dataset

    hist_len=60,
    pred_len=1,

    revin_affine=False,       # Retain other configurations as in ETTh1

    lr=0.001,                 # Learning rate
)
"""

# List of ticker symbols
ticker_symbols = [
    'AAPL', 'MSFT', 'ORCL', 'AMD', 'CSCO', 'ADBE', 
    'IBM', 'TXN', 'AMAT', 'MU', 'ADI', 'INTC', 
    'LRCX', 'KLAC', 'MSI', 'GLW', 'HPQ', 'TYL', 
    'PTC', 'WDC'
]

def generate_config_files():
    """Generates configuration files for each stock symbol."""
    os.makedirs(output_dir, exist_ok=True)  # Ensure the output directory exists

    for symbol in ticker_symbols:
        new_content = template_content.format(dataset=symbol)
        new_file_name = os.path.join(output_dir, f"{symbol}_30for1.py")

        with open(new_file_name, 'w') as new_file:
            new_file.write(new_content)

        print(f"Created configuration file: {new_file_name}")


if __name__ == '__main__':
    # Generate configuration files
    generate_config_files()

    parser = argparse.ArgumentParser()
    parser.add_argument("-c", "--config", type=str)
    parser.add_argument("-d", "--data_root", default="dataset", type=str, help="data root")
    parser.add_argument("-s", "--save_root", default="save", help="save root")
    parser.add_argument("--devices", default='0,', type=str, help="device' id to use")
    parser.add_argument("--use_wandb", default=0, type=int, help="use wandb")
    parser.add_argument("--seed", type=int, default=1, help="seed")
    args = parser.parse_args()

    training_conf = {
        "seed": int(args.seed),
        "data_root": args.data_root,
        "save_root": args.save_root,
        "devices": args.devices,
        "use_wandb": args.use_wandb,
    }

    for symbol in ticker_symbols:
        data_root = f"/dataset/{symbol}"
        config_file = f"/config/reproduce_conf/RMoK/{symbol}_30for1.py"

        training_conf = {
            "seed": int(args.seed),
            "data_root": data_root,
            "save_root": args.save_root,
            "devices": args.devices,
            "use_wandb": args.use_wandb,
        }

        init_exp_conf = load_config(config_file)
        train_func(training_conf, init_exp_conf)