import gc
import itertools
import os
import secrets
from PIL import Image, ImageOps
import numpy as np
import torch
import torch.backends
from params import KubinParams
from kandinsky2 import CONFIG_2_1
from utils.env_data import load_env_value
from utils.yaml import flatten_yaml
from utils.file_system import save_output
from utils.logging import k_log
from utils.image import (
    composite_images,
    create_inpaint_targets,
    create_outpaint_targets,
    images_or_texts,
    round_to_nearest,
)


class Model_KD21:
    def __init__(self, params: KubinParams):
        from kandinsky2 import Kandinsky2_1

        k_log("using pipeline: native (2.1)")
        self.params = params

        self.kd21: Kandinsky2_1 | None = None
        self.kd21_inpaint: Kandinsky2_1 | None = None

        self.system_config = flatten_yaml(CONFIG_2_1)

    def prepare_model(self, task):
        from model_utils.kd21_utils import get_checkpoint

        k_log(f"task queued: {task}")
        assert task in ["text2img", "img2img", "mix", "inpainting", "outpainting"]

        clear_vram_on_switch = True

        cache_dir = self.params("general", "cache_dir")
        cache_dir = load_env_value("KD21_CACHE_DIR", cache_dir)

        device = self.params("general", "device")

        # use_flash_attention = self.params("native", "flash_attention")
        use_flash_attention = "kd21_flash_attention" in [
            value.strip()
            for value in self.params("native", "optimization_flags").split(";")
        ]

        if task == "text2img" or task == "img2img" or task == "mix":
            if self.kd21 is None:
                if clear_vram_on_switch:
                    self.flush()

                self.kd21 = get_checkpoint(
                    device,
                    use_auth_token=None,
                    task_type="text2img",
                    default_cache_dir=cache_dir,
                    use_flash_attention=use_flash_attention,
                    checkpoint_info=self.params.checkpoint,
                )

                # self.kd21.model.to(device)
                # self.kd21.prior.to(device)

        elif task == "inpainting" or task == "outpainting":
            if self.kd21_inpaint is None:
                if clear_vram_on_switch:
                    self.flush()

                self.kd21_inpaint = get_checkpoint(
                    device,
                    use_auth_token=None,
                    task_type="inpainting",
                    default_cache_dir=cache_dir,
                    use_flash_attention=use_flash_attention,
                    checkpoint_info=self.params.checkpoint,
                )

                # self.kd21_inpaint.model.to(device)
                # self.kd21_inpaint.prior.to(device)

        return self

    def flush(self, target=None):
        k_log(f"clearing memory")

        if target is None or target in ["text2img", "img2img", "mix"]:
            if self.kd21 is not None:
                self.kd21.model.to("cpu")
                self.kd21.prior.to("cpu")
                self.kd21 = None

        if target is None or target in ["inpainting", "outpainting"]:
            if self.kd21_inpaint is not None:
                self.kd21_inpaint.model.to("cpu")
                self.kd21_inpaint.prior.to("cpu")
                self.kd21_inpaint = None

        gc.collect()

        if self.params("general", "device") == "cuda":
            if torch.cuda.is_available():
                with torch.cuda.device("cuda"):
                    torch.cuda.empty_cache()
                    torch.cuda.ipc_collect()

    def prepare_params(self, params):
        input_seed = params["input_seed"]
        seed = secrets.randbelow(99999999999) if input_seed == -1 else input_seed
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)

        k_log(f"seed generated: {seed}")
        params["input_seed"] = seed
        params["model_name"] = "kd2.1"
        return params

    def t2i(self, params):
        params = self.prepare_model("text2img").prepare_params(params)
        assert self.kd21 is not None

        images = []
        for _ in itertools.repeat(None, params["batch_count"]):
            current_batch = self.kd21.generate_text2img(
                prompt=params["prompt"],
                num_steps=params["num_steps"],
                batch_size=params["batch_size"],
                guidance_scale=params["guidance_scale"],
                h=params["h"],
                w=params["w"],
                sampler=params["sampler"],
                prior_cf_scale=params["prior_cf_scale"],
                prior_steps=str(params["prior_steps"]),
                negative_prior_prompt=params["negative_prior_prompt"],
                negative_decoder_prompt=params["negative_prompt"],
            )
            output_dir = params.get(
                ".output_dir",
                os.path.join(self.params("general", "output_dir"), "text2img"),
            )
            saved_batch = save_output(output_dir, current_batch, params)
            images = images + saved_batch
        return images

    def i2i(self, params):
        params = self.prepare_model("img2img").prepare_params(params)
        assert self.kd21 is not None

        output_size = (params["w"], params["h"])
        image = params["init_image"]

        images = []
        for _ in itertools.repeat(None, params["batch_count"]):
            current_batch = self.kd21.generate_img2img(
                prompt=params["prompt"],
                pil_img=image,
                strength=params["strength"],
                num_steps=params["num_steps"],
                batch_size=params["batch_size"],
                guidance_scale=params["guidance_scale"],
                h=params["h"],
                w=params["w"],
                sampler=params["sampler"],
                prior_cf_scale=params["prior_cf_scale"],
                prior_steps=str(params["prior_steps"]),
            )

            output_dir = params.get(
                ".output_dir",
                os.path.join(self.params("general", "output_dir"), "img2img"),
            )
            saved_batch = save_output(output_dir, current_batch, params)
            images = images + saved_batch
        return images

    def mix(self, params):
        params = self.prepare_model("mix").prepare_params(params)
        assert self.kd21 is not None

        mix_image_count = params.get("mix_image_count", 2)

        images_list = []
        texts_list = []
        weights_list = []

        for i in range(1, mix_image_count + 1):
            images_list.append(params.get(f"image_{i}"))
            texts_list.append(params.get(f"text_{i}", ""))
            weights_list.append(params.get(f"weight_{i}", 0.5))

        images = []
        for _ in itertools.repeat(None, params["batch_count"]):
            images_texts = images_or_texts(images_list, texts_list)

            current_batch = self.kd21.mix_images(
                images_texts=images_texts,
                weights=weights_list,
                num_steps=params["num_steps"],
                batch_size=params["batch_size"],
                guidance_scale=params["guidance_scale"],
                h=params["h"],
                w=params["w"],
                sampler=params["sampler"],
                prior_cf_scale=params["prior_cf_scale"],
                prior_steps=str(params["prior_steps"]),
                negative_prior_prompt=params["negative_prior_prompt"],
                negative_decoder_prompt=params["negative_prompt"],
            )
            output_dir = params.get(
                ".output_dir", os.path.join(self.params("general", "output_dir"), "mix")
            )
            saved_batch = save_output(output_dir, current_batch, params)
            images = images + saved_batch
        return images

    def inpaint(self, params):
        params = self.prepare_model("inpainting").prepare_params(params)
        assert self.kd21_inpaint is not None

        image_mask = params["image_mask"]

        pil_img = image_mask["image"]
        width, height = (
            (
                round_to_nearest(pil_img.width, 64)
                if params["infer_size"]
                else params["w"]
            ),
            (
                round_to_nearest(pil_img.height, 64)
                if params["infer_size"]
                else params["h"]
            ),
        )
        output_size = (width, height)
        mask = image_mask["mask"]
        inpaint_region = params["region"]
        inpaint_target = params["target"]

        image, mask = create_inpaint_targets(
            pil_img,
            mask,
            output_size,
            inpaint_region,
            invert_mask=inpaint_target == "all but mask",
        )

        images = []
        for _ in itertools.repeat(None, params["batch_count"]):
            current_batch = self.kd21_inpaint.generate_inpainting(
                prompt=params["prompt"],
                pil_img=image,
                img_mask=mask,
                num_steps=params["num_steps"],
                batch_size=params["batch_size"],
                guidance_scale=params["guidance_scale"],
                h=height,
                w=width,
                sampler=params["sampler"],
                prior_cf_scale=params["prior_cf_scale"],
                prior_steps=str(params["prior_steps"]),
                negative_prior_prompt=params["negative_prior_prompt"],
                negative_decoder_prompt=params["negative_prompt"],
            )

            if inpaint_region == "mask":
                current_batch_composed = []
                for inpainted_image in current_batch:
                    merged_image = composite_images(pil_img, inpainted_image, mask)
                    current_batch_composed.append(merged_image)
                current_batch = current_batch_composed

            output_dir = params.get(
                ".output_dir",
                os.path.join(self.params("general", "output_dir"), "inpainting"),
            )
            saved_batch = save_output(output_dir, current_batch, params)
            images = images + saved_batch
        return images

    def outpaint(self, params):
        params = self.prepare_model("outpainting").prepare_params(params)
        assert self.kd21_inpaint is not None

        image = params["image"]
        offset = params["offset"]
        infer_size = params["infer_size"]
        width = params["w"]
        height = params["h"]

        image, mask, width, height = create_outpaint_targets(
            image, offset, infer_size, width, height
        )

        images = []
        for _ in itertools.repeat(None, params["batch_count"]):
            current_batch = self.kd21_inpaint.generate_inpainting(
                prompt=params["prompt"],
                pil_img=image,
                img_mask=mask,
                num_steps=params["num_steps"],
                batch_size=params["batch_size"],
                guidance_scale=params["guidance_scale"],
                h=width,
                w=height,
                sampler=params["sampler"],
                prior_cf_scale=params["prior_cf_scale"],
                prior_steps=str(params["prior_steps"]),
                negative_prior_prompt=params["negative_prior_prompt"],
                negative_decoder_prompt=params["negative_prompt"],
            )

            output_dir = params.get(
                ".output_dir",
                os.path.join(self.params("general", "output_dir"), "outpainting"),
            )
            saved_batch = save_output(
                output_dir,
                current_batch,
                params,
            )
            images = images + saved_batch
        return images
