import sys

import copy
import functools
import os
import numpy as np
import torch
from torch import nn
from tqdm import tqdm
from kandinsky2.vqgan.autoencoder import VQModelInterface, AutoencoderKL, MOVQ
from train_modules.train_utils.utils import generate_mask, get_image_mask
import clip


def prepare_image(batch, image_encoder, scale=1):
    with torch.no_grad():
        batch = batch.half()
        batch = image_encoder.encode(batch)
        batch = batch * scale
    return batch.float()


def prepare_cond(cond, text_encoder, clip_model):
    mask = None
    new_cond = {}
    for key in cond.keys():
        if key not in ["tokens", "mask", "clip_image"]:
            new_cond[key] = cond[key]
    if "mask" in cond:
        mask = cond["mask"]
    with torch.no_grad():
        new_cond["image_emb"] = clip_model.encode_image(cond["clip_image"]).float()
    with torch.no_grad():
        new_cond["full_emb"], new_cond["pooled_emb"] = text_encoder(
            cond["tokens"].long(), mask
        )
        new_cond["full_emb"] = new_cond["full_emb"].float()
        new_cond["pooled_emb"] = new_cond["pooled_emb"].float()
    del cond
    return new_cond


def train_unclip(
    unet,
    diffusion,
    image_encoder,
    clip_model,
    text_encoder,
    optimizer,
    lr_scheduler=None,
    schedule_sampler=None,
    train_loader=None,
    val_loader=None,
    scale=1,
    num_epochs=2,
    save_every=1000,
    save_epoch=1,
    save_name="model",
    save_path="",
    inpainting=False,
    device="cuda:0",
):
    assert train_loader is not None
    assert schedule_sampler is not None
    train_epoch = 0
    train_step = 0

    for epoch in range(num_epochs):
        train_epoch += 1

        progress = tqdm(
            total=len(train_loader),
            desc=f"finetuning unclip model, epoch {train_epoch}/{num_epochs}",
            position=0,
            leave=True,
        )
        for batch in train_loader:
            optimizer.zero_grad()
            image, cond = batch
            image = image.to(device)
            for key in cond.keys():
                cond[key] = cond[key].to(device)
            image = prepare_image(image, image_encoder, scale=scale)
            if inpainting:
                image_mask = get_image_mask(image.shape[0], image.shape[-2:])
                image_mask = image_mask.to(image.device).unsqueeze(1).to(image.dtype)
                image_mask = 1.0 - image_mask
                cond["inpaint_image"] = image * image_mask
                cond["inpaint_mask"] = image_mask
            cond = prepare_cond(cond, text_encoder, clip_model)
            t, weights = schedule_sampler.sample(image.shape[0], image.device)
            compute_losses = functools.partial(
                diffusion.training_losses,
                unet,
                image,
                t,
                model_kwargs=cond,
            )
            losses = compute_losses()
            loss = losses["loss"].mean()  # type: ignore
            loss.backward()
            optimizer.step()
            if lr_scheduler is not None:
                lr_scheduler.step()

            train_step += 1
            if save_every != 0 and train_step % save_every == 0:
                print("\nsaving unclip checkpoint")
                torch.save(
                    unet.state_dict(),
                    os.path.join(
                        save_path,
                        save_name + f"{epoch + 1}_{str(train_step)}" + ".ckpt",
                    ),
                )
            progress.set_postfix(
                {"step": f"{train_step}/{len(train_loader)}", "loss": loss.item()}
            )
            progress.update()

        if (train_epoch == num_epochs) or (
            save_epoch != 0 and train_epoch % save_epoch
        ) == 0:
            print("\nsaving unclip checkpoint")
            torch.save(
                unet.state_dict(),
                os.path.join(save_path, save_name + f"{epoch + 1}" + ".ckpt"),
            )
