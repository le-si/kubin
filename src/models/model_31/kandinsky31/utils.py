# This source code is licensed under the Apache License found in the
# LICENSE file in the current directory.
"""
The code has been adopted from Kandinsky-3
(https://github.com/ai-forever/Kandinsky-3/blob/main/kandinsky3/utils.py)
"""
import math
import gc
import sys
from typing import Any, Callable
from omegaconf import OmegaConf
import numpy as np
from scipy import ndimage
import torch
import torch.nn as nn
from skimage.transform import resize

from utils.logging import k_log


def release_vram():
    gc.collect()
    torch.cuda.empty_cache()
    torch.cuda.ipc_collect()


def report_mem_usage(stage):
    stage = f" ({stage})" if stage else ""
    in_mb = lambda bytes: round(bytes / (1024**2))

    total_memory = in_mb(torch.cuda.get_device_properties(0).total_memory)
    reserved_memory = in_mb(torch.cuda.memory_reserved(0))
    allocated_memory = in_mb(torch.cuda.memory_allocated(0))

    reserved_percentage = math.ceil((reserved_memory / total_memory) * 100)

    message = f"vram usage{stage} -> total: {total_memory} MB / reserved: {reserved_memory} MB ({reserved_percentage}%) / allocated: {allocated_memory} MB"
    k_log(message)


def load_conf(config_path):
    conf = OmegaConf.load(config_path)
    conf.data.tokens_length = conf.common.tokens_length
    conf.data.processor_names = conf.model.encoders.model_names
    conf.data.dataset.seed = conf.common.seed
    conf.data.dataset.image_size = conf.common.image_size

    conf.trainer.trainer_params.max_steps = conf.common.train_steps
    conf.scheduler.params.total_steps = conf.common.train_steps
    conf.logger.tensorboard.name = conf.common.experiment_name

    conf.model.encoders.context_dim = conf.model.unet_params.context_dim
    return conf


def freeze(model):
    for p in model.parameters():
        p.requires_grad = False
    return model


def unfreeze(model):
    for p in model.parameters():
        p.requires_grad = True
    return model


def zero_module(module):
    for p in module.parameters():
        nn.init.zeros_(p)
    return module


def resize_mask_for_diffusion(mask):
    reduce_factor = max(1, (mask.size / 1024**2) ** 0.5)
    resized_mask = resize(
        mask,
        (
            (round(mask.shape[0] / reduce_factor) // 64) * 64,
            (round(mask.shape[1] / reduce_factor) // 64) * 64,
        ),
        preserve_range=True,
        anti_aliasing=False,
    )

    return resized_mask


def resize_image_for_diffusion(image):
    reduce_factor = max(1, (image.size[0] * image.size[1] / 1024**2) ** 0.5)
    image = image.resize(
        (
            (round(image.size[0] / reduce_factor) // 64) * 64,
            (round(image.size[1] / reduce_factor) // 64) * 64,
        )
    )

    return image


def prepare_mask(mask):
    ker = (
        np.array(
            [
                [1, 1, 1, 1, 1],
                [1, 5, 5, 5, 1],
                [1, 5, 44, 5, 1],
                [1, 5, 5, 5, 1],
                [1, 1, 1, 1, 1],
            ]
        )
        / 100
    )
    out = ndimage.convolve(mask, ker)
    out = ndimage.convolve(out, ker)
    out = ndimage.convolve(out, ker)

    mask = (out > 0).astype(int)
    return mask
