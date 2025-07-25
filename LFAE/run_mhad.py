import os
import sys
import math
import yaml
from argparse import ArgumentParser
from shutil import copy
import torch
import torch.nn as nn

from LFAE.mhad_dataset import FramesDataset

from LFAE.modules.generator import Generator
from LFAE.modules.bg_motion_predictor import BGMotionPredictor
from LFAE.modules.region_predictor import RegionPredictor
from LFAE.modules.avd_network import AVDNetwork

import torch
import torch.backends.cudnn as cudnn
import numpy as np
import random

from LFAE.train import train


class Logger(object):
    def __init__(self, filename='default.log', stream=sys.stdout):
        self.terminal = stream
        self.log = open(filename, 'w')

    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)

    def flush(self):
        pass


def setup_seed(seed):
    torch.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    np.random.seed(seed)
    random.seed(seed)
    torch.backends.cudnn.deterministic = True


if __name__ == "__main__":
    os.environ["CUDA_VISIBLE_DEVICES"] = "0"
    cudnn.enabled = True
    cudnn.benchmark = True

    parser = ArgumentParser()
    parser.add_argument("--postfix", default="")
    parser.add_argument("--random-seed", default=1234)
    parser.add_argument("--set-start", default=False)
    parser.add_argument("--config",
                        default="config/mhad128.yaml",
                        help="path to config")
    parser.add_argument("--mode", default="train", choices=["train"])
    parser.add_argument("--log_dir",
                        default='log',
                        help="path to log into")
    parser.add_argument("--checkpoint", # use the pretrained Taichi model provided by Snap
                        default=None,
                        help="path to checkpoint to restore")
    parser.add_argument("--device_ids", default="0", type=lambda x: list(map(int, x.split(','))),
                        help="Names of the devices comma separated.")
    parser.add_argument("--verbose", dest="verbose", default=False, help="Print model architecture")
    parser.set_defaults(verbose=False)

    opt = parser.parse_args()

    setup_seed(opt.random_seed)

    with open(opt.config) as f:
        config = yaml.safe_load(f)

    log_dir = os.path.join(opt.log_dir, os.path.basename(opt.config).split('.')[0]+opt.postfix)
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)
    if not os.path.exists(os.path.join(log_dir, os.path.basename(opt.config))):
        copy(opt.config, log_dir)

    # the directory to save checkpoints
    config["snapshots"] = os.path.join(log_dir, 'snapshots'+opt.postfix)
    os.makedirs(config["snapshots"], exist_ok=True)
    # the directory to save images of training results
    config["imgshots"] = os.path.join(log_dir, 'imgshots'+opt.postfix)
    os.makedirs(config["imgshots"], exist_ok=True)
    config["set_start"] = opt.set_start
    log_txt = os.path.join(log_dir,
                           "B"+format(config['train_params']['batch_size'], "04d")+
                           "E"+format(config['train_params']['max_epochs'], "04d")+".log")
    sys.stdout = Logger(log_txt, sys.stdout)

    print("postfix:", opt.postfix)
    print("checkpoint:", opt.checkpoint)
    print("batch size:", config['train_params']['batch_size'])

    generator = Generator(num_regions=config['model_params']['num_regions'],
                          num_channels=config['model_params']['num_channels'],
                          revert_axis_swap=config['model_params']['revert_axis_swap'],
                          **config['model_params']['generator_params'])

    if torch.cuda.is_available():
        generator.to(opt.device_ids[0])
    if opt.verbose:
        print(generator)

    region_predictor = RegionPredictor(num_regions=config['model_params']['num_regions'],
                                       num_channels=config['model_params']['num_channels'],
                                       estimate_affine=config['model_params']['estimate_affine'],
                                       **config['model_params']['region_predictor_params'])

    if torch.cuda.is_available():
        region_predictor.to(opt.device_ids[0])

    if opt.verbose:
        print(region_predictor)

    bg_predictor = BGMotionPredictor(num_channels=config['model_params']['num_channels'],
                                     **config['model_params']['bg_predictor_params'])
    if torch.cuda.is_available():
        bg_predictor.to(opt.device_ids[0])
    if opt.verbose:
        print(bg_predictor)

    avd_network = AVDNetwork(num_regions=config['model_params']['num_regions'],
                             **config['model_params']['avd_network_params'])
    if torch.cuda.is_available():
        avd_network.to(opt.device_ids[0])
    if opt.verbose:
        print(avd_network)

    dataset = FramesDataset(**config['dataset_params'])
    config["num_example_per_epoch"] = config['train_params']['num_repeats'] * len(dataset)
    config["num_step_per_epoch"] = math.ceil(config["num_example_per_epoch"]/float(config['train_params']['batch_size']))
    config["save_ckpt_freq"] = config["num_step_per_epoch"] * (config['train_params']['max_epochs'] // 10)
    # save 10 checkpoints in total
    print("save ckpt freq:", config["save_ckpt_freq"])

    print("Training...")
    train(config, generator, region_predictor, bg_predictor, opt.checkpoint, log_dir, dataset, opt.device_ids)

