# This source code is licensed under the Apache License found in the
# LICENSE file in the current directory.
"""
The code has been adopted from Kandinsky-3
(https://github.com/ai-forever/Kandinsky-3/blob/main/kandinsky3/t2i_pipeline.py)
"""

from typing import List, Callable, Optional, Union
import PIL
import io
import os
import math
import random

import numpy as np
import pandas as pd
from tqdm import tqdm
from PIL import Image, ImageDraw, ImageFont

import torch
import torchvision.transforms as T
from torch import einsum
from einops import repeat

from models.model_30.kandinsky3.model.unet import UNet
from models.model_30.kandinsky3.movq import MoVQ
from models.model_30.kandinsky3.condition_encoders import T5TextConditionEncoder
from models.model_30.kandinsky3.condition_processors import T5TextConditionProcessor
from models.model_30.kandinsky3.model.diffusion import (
    BaseDiffusion,
    get_named_beta_schedule,
)
from models.model_30.kandinsky3.utils import release_vram, vram_info
from utils.logging import k_log


class Kandinsky3T2IOptimizedPipeline:
    def __init__(
        self,
        device: Union[str, torch.device],
        unet_loader: Callable[[], UNet],
        null_embedding: torch.Tensor,
        t5_processor: T5TextConditionProcessor,
        t5_encoder_loader: Callable[[], T5TextConditionEncoder],
        movq_loader: Callable[[], MoVQ],
        fp16: bool = True,
    ):
        k_log("running low vram t2i pipeline")

        self.device = device
        self.fp16 = fp16
        self.to_pil = T.ToPILImage()

        self.unet_loader = unet_loader
        self.null_embedding = null_embedding
        self.t5_processor = t5_processor
        self.t5_encoder_loader = t5_encoder_loader
        self.movq_loader = movq_loader

    def __call__(
        self,
        text: str,
        negative_text: str = None,
        images_num: int = 1,
        bs: int = 1,
        width: int = 1024,
        height: int = 1024,
        guidance_scale: float = 3.0,
        steps: int = 50,
        seed: int | None = None,
    ) -> List[PIL.Image.Image]:
        if seed is not None:
            torch.manual_seed(seed)
            random.seed(seed)
            np.random.seed(seed)

        betas = get_named_beta_schedule("cosine", steps)
        base_diffusion = BaseDiffusion(betas, 0.99)

        (
            condition_model_input,
            negative_condition_model_input,
        ) = self.t5_processor.encode(text, negative_text)

        for key in condition_model_input:
            for input_type in condition_model_input[key]:
                condition_model_input[key][input_type] = (
                    condition_model_input[key][input_type].unsqueeze(0).to(self.device)
                )

        if negative_condition_model_input is not None:
            for key in negative_condition_model_input:
                for input_type in negative_condition_model_input[key]:
                    negative_condition_model_input[key][input_type] = (
                        negative_condition_model_input[key][input_type]
                        .unsqueeze(0)
                        .to(self.device)
                    )

        pil_images = []

        with torch.autocast("cuda"):
            with torch.no_grad():
                vram_info("prepared encoder")

                self.t5_encoder = self.t5_encoder_loader()
                context, context_mask = self.t5_encoder(condition_model_input)
                if negative_condition_model_input is not None:
                    negative_context, negative_context_mask = self.t5_encoder(
                        negative_condition_model_input
                    )
                else:
                    negative_context, negative_context_mask = None, None

                vram_info("used encoder")
                self.t5_encoder.to("cpu")
                self.t5_encoder = None
                release_vram()
                vram_info("flushed encoder")

                k, m = images_num // bs, images_num % bs
                for minibatch in [bs] * k + [m]:
                    if minibatch == 0:
                        continue
                    bs_context = repeat(context, "1 n d -> b n d", b=minibatch)
                    bs_context_mask = repeat(context_mask, "1 n -> b n", b=minibatch)
                    if negative_context is not None:
                        bs_negative_context = repeat(
                            negative_context, "1 n d -> b n d", b=minibatch
                        )
                        bs_negative_context_mask = repeat(
                            negative_context_mask, "1 n -> b n", b=minibatch
                        )
                    else:
                        bs_negative_context, bs_negative_context_mask = None, None

                    vram_info("prepared unet")
                    self.unet = self.unet_loader()
                    images = base_diffusion.p_sample_loop(
                        self.unet,
                        (minibatch, 4, height // 8, width // 8),
                        self.device,
                        bs_context,
                        bs_context_mask,
                        self.null_embedding,
                        guidance_scale,
                        negative_context=bs_negative_context,
                        negative_context_mask=bs_negative_context_mask,
                    )

                    vram_info("used unet")
                    self.unet.to("cpu")
                    self.unet = None
                    release_vram()
                    vram_info("flushed unet")

                    vram_info("prepared movq")
                    self.movq = self.movq_loader()
                    images = torch.cat(
                        [self.movq.decode(image) for image in images.chunk(2)]
                    )

                    vram_info("used movq")
                    self.movq.to("cpu")
                    self.movq = None
                    release_vram()
                    vram_info("flushed movq")

                    images = torch.clip((images + 1.0) / 2.0, 0.0, 1.0)
                    for images_chunk in images.chunk(1):
                        pil_images += [self.to_pil(image) for image in images_chunk]

        return pil_images
