import gradio as gr
from ui_blocks.shared.samplers import samplers_controls
from ui_blocks.shared.ui_shared import SharedUI
from utils.gradio_ui import click_and_disable
from utils.logging import k_log
import os
from PIL import Image


def i2i_ui(generate_fn, shared: SharedUI, tabs, session):
    augmentations = shared.create_ext_augment_blocks("i2i")

    with gr.Row() as i2i_block:
        with gr.Column(scale=2) as i2i_params:
            augmentations["ui_before_prompt"]()

            with gr.Tabs():
                with gr.TabItem("Single image"):
                    with gr.Row():
                        with gr.Column(scale=1):
                            shared.input_i2i_image.render()
                        with gr.Column(scale=1):
                            prompt = gr.TextArea(
                                "", placeholder="", label="Prompt", lines=2
                            )
                            strength = gr.Slider(
                                0,
                                1,
                                0.3,
                                step=0.05,
                                label="Transformation strength",
                                info=shared.info(
                                    "Reference image transformation strength"
                                ),
                            )

                    augmentations["ui_before_cnet"]()

                    with gr.Accordion("ControlNet", open=False) as i2i_cnet:
                        cnet_enable = gr.Checkbox(
                            False, label="Enable", elem_classes=["cnet-enable"]
                        )

                        with gr.Row():
                            with gr.Column():
                                cnet_img_reuse = gr.Checkbox(
                                    True,
                                    label="Reuse input image for ControlNet condition",
                                )
                                shared.input_cnet_i2i_image.render()
                                with gr.Row():
                                    cnet_condition = gr.Radio(
                                        choices=["depth-map"],
                                        value="depth-map",
                                        label="Condition",
                                    )
                                    cnet_depth_estimator = gr.Dropdown(
                                        choices=[
                                            "Intel/dpt-hybrid-midas",
                                            "Intel/dpt-large",
                                        ],
                                        value="Intel/dpt-large",
                                        label="Depth estimator",
                                    )

                            cnet_img_reuse.change(
                                lambda x: gr.update(visible=not x),
                                inputs=[cnet_img_reuse],
                                outputs=[shared.input_cnet_i2i_image],
                            )

                            with gr.Column():
                                cnet_emb_transform_strength = gr.Slider(
                                    0, 1, 0.85, step=0.05, label="Embedding strength"
                                )

                                cnet_neg_emb_transform_strength = gr.Slider(
                                    0,
                                    1,
                                    1,
                                    step=0.05,
                                    label="Negative prior embedding strength",
                                )

                                cnet_img_strength = gr.Slider(
                                    0,
                                    1,
                                    0.5,
                                    step=0.05,
                                    label="Image strength",
                                )

                    i2i_cnet.elem_classes = ["control-net"]

                with gr.TabItem("Batch"):
                    with gr.Row():
                        input_folder = gr.Textbox(
                            label="Folder with input images",
                            info=shared.info("Folder to read images from"),
                        )
                        output_folder = gr.Textbox(
                            label="Folder with output images",
                            info=shared.info(
                                "If empty, the default img2img folder will be used"
                            ),
                        )
                    batch_prompt = gr.TextArea(
                        "", placeholder="", label="Prompt", lines=2
                    )
                    with gr.Row():
                        img_extension = gr.Textbox(
                            ".jpg;.jpeg;.png;.bmp",
                            label="File extension filter",
                            info=shared.info(
                                "Only use images with the following extensions"
                            ),
                        )
                        batch_strength = gr.Slider(
                            0,
                            1,
                            0.3,
                            step=0.05,
                            label="Input image strength",
                            info=shared.info("Reference image transformation strength"),
                        )
                    with gr.Row():
                        generate_batch_i2i = gr.Button(
                            "🖼️ Execute batch processing", variant="secondary"
                        )
                        show_processed_i2i = gr.Button(
                            "🔍 Show images from output folder", variant="secondary"
                        )
                    batch_progress = gr.HTML(label="Batch progress")

            augmentations["ui_before_params"]()

            with gr.Accordion(
                "Advanced params", open=not shared.ui_params("collapse_advanced_params")
            ) as i2i_advanced_params:
                with gr.Row():
                    steps = gr.Slider(
                        1,
                        200,
                        shared.ui_params("decoder_steps_default"),
                        step=1,
                        label="Steps",
                        elem_classes=["inline-flex"],
                    )
                    guidance_scale = gr.Slider(
                        1,
                        30,
                        4,
                        step=1,
                        label="Guidance scale",
                        elem_classes=["inline-flex"],
                    )
                    batch_count = gr.Slider(
                        1,
                        shared.ui_params("max_batch_count"),
                        4,
                        step=1,
                        label="Batch count",
                    )

                with gr.Row():
                    width = gr.Slider(
                        shared.ui_params("image_width_min"),
                        shared.ui_params("image_width_max"),
                        shared.ui_params("image_width_default"),
                        step=shared.ui_params("image_width_step"),
                        label="Width",
                    )
                    width.elem_classes = ["inline-flex"]
                    height = gr.Slider(
                        shared.ui_params("image_height_min"),
                        shared.ui_params("image_height_max"),
                        shared.ui_params("image_height_default"),
                        step=shared.ui_params("image_height_step"),
                        label="Height",
                    )
                    height.elem_classes = ["inline-flex"]
                    aspect_ratio = gr.Dropdown(
                        choices=["none", "1:1", "16:9", "9:16", "3:2", "2:3"],
                        value="none",
                        label="Aspect ratio",
                        elem_id="i2i-aspect",
                    )

                with gr.Row(equal_height=True):
                    (
                        sampler_20,
                        sampler_21_native,
                        sampler_diffusers,
                    ) = samplers_controls()
                    seed = gr.Number(-1, label="Seed", precision=0)
                    batch_size = gr.Slider(1, 16, 1, step=1, label="Batch size")
                    batch_size.elem_classes = ["unsupported_20", "inline-flex"]

                with gr.Row() as prior_block:
                    prior_scale = gr.Slider(
                        1,
                        30,
                        4,
                        step=1,
                        label="Prior scale",
                        elem_classes=["inline-flex"],
                    )
                    prior_steps = gr.Slider(
                        2,
                        100,
                        25,
                        step=1,
                        label="Prior steps",
                        elem_classes=["inline-flex"],
                    )
                    negative_prior_prompt = gr.TextArea(
                        "",
                        label="Negative prior prompt",
                        elem_classes=["inline-flex"],
                        lines=2,
                    )
                prior_block.elem_classes = ["unsupported_20"]

            augmentations["ui"]()

        with gr.Column(scale=1):
            generate_i2i = gr.Button("Generate", variant="primary")
            i2i_output = gr.Gallery(
                label="Generated Images",
                columns=2,
                preview=True,
                elem_classes="i2i-output",
            )

            i2i_output.select(
                fn=None,
                _js=f"() => kubin.UI.setImageIndex('i2i-output')",
                show_progress=False,
                outputs=gr.State(None),
            )

            shared.create_base_send_targets(i2i_output, "i2i-output", tabs)
            shared.create_ext_send_targets(i2i_output, "i2i-output", tabs)

            def generate(
                session,
                image,
                prompt,
                negative_prior_prompt,
                strength,
                steps,
                batch_count,
                batch_size,
                guidance_scale,
                width,
                height,
                sampler_20,
                sampler_21_native,
                sampler_diffusers,
                prior_scale,
                prior_steps,
                seed,
                cnet_enable,
                cnet_img_reuse,
                cnet_image,
                cnet_condition,
                cnet_depth_estimator,
                cnet_emb_transform_strength,
                cnet_neg_emb_transform_strength,
                cnet_img_strength,
                *injections,
            ):
                sampler = shared.select_sampler(
                    sampler_20, sampler_21_native, sampler_diffusers
                )

                cnet_target_image = image
                if cnet_enable:
                    if not cnet_img_reuse and cnet_image is None:
                        k_log(
                            "No image selected for ControlNet input, using original image instead"
                        )
                    elif not cnet_img_reuse:
                        cnet_target_image = cnet_image

                params = {
                    ".session": session,
                    "init_image": image,
                    "prompt": prompt,
                    "negative_prior_prompt": negative_prior_prompt,
                    "strength": strength,
                    "num_steps": steps,
                    "batch_count": batch_count,
                    "batch_size": batch_size,
                    "guidance_scale": guidance_scale,
                    "w": width,
                    "h": height,
                    "sampler": sampler,
                    "prior_cf_scale": prior_scale,
                    "prior_steps": prior_steps,
                    "input_seed": seed,
                    "cnet_enable": cnet_enable,
                    "cnet_image": cnet_target_image,
                    "cnet_condition": cnet_condition,
                    "cnet_depth_estimator": cnet_depth_estimator,
                    "cnet_emb_transform_strength": cnet_emb_transform_strength,
                    "cnet_neg_emb_transform_strength": cnet_neg_emb_transform_strength,
                    "cnet_img_strength": cnet_img_strength,
                    "negative_prompt": "",
                }

                params = augmentations["exec"](params, injections)
                return generate_fn(params)

            click_and_disable(
                element=generate_i2i,
                fn=generate,
                inputs=[
                    session,
                    shared.input_i2i_image,
                    prompt,
                    negative_prior_prompt,
                    strength,
                    steps,
                    batch_count,
                    batch_size,
                    guidance_scale,
                    width,
                    height,
                    sampler_20,
                    sampler_21_native,
                    sampler_diffusers,
                    prior_scale,
                    prior_steps,
                    seed,
                    cnet_enable,
                    cnet_img_reuse,
                    shared.input_cnet_i2i_image,
                    cnet_condition,
                    cnet_depth_estimator,
                    cnet_emb_transform_strength,
                    cnet_neg_emb_transform_strength,
                    cnet_img_strength,
                ]
                + augmentations["injections"],
                outputs=i2i_output,
                js=[
                    "args => kubin.UI.taskStarted('Image To Image')",
                    "args => kubin.UI.taskFinished('Image To Image')",
                ],
            )

            def generate_batch(
                session,
                input_folder,
                output_folder,
                extensions,
                batch_prompt,
                batch_strength,
                steps,
                batch_count,
                batch_size,
                guidance_scale,
                width,
                height,
                sampler_20,
                sampler_21_native,
                sampler_diffusers,
                prior_scale,
                prior_steps,
                seed,
                *injections,
            ):
                sampler = shared.select_sampler(
                    sampler_20, sampler_21_native, sampler_diffusers
                )

                if not os.path.exists(input_folder):
                    return "Input folder does not exist"

                if input_folder == output_folder:
                    return "Input and output folder cannot be the same"

                i2i_source = []
                for filename in os.listdir(input_folder):
                    if filename.endswith(tuple(extensions.split(";"))):
                        i2i_source.append(filename)

                k_log(f"found {len(i2i_source)} images for i2i processing")

                for index, imagename in enumerate(i2i_source):
                    imagepath = f"{input_folder}/{imagename}"
                    image = Image.open(imagepath)

                    params = {
                        ".session": session,
                        "init_image": image,
                        "prompt": batch_prompt,
                        "strength": batch_strength,
                        "num_steps": steps,
                        "batch_count": batch_count,
                        "batch_size": batch_size,
                        "guidance_scale": guidance_scale,
                        "w": width,
                        "h": height,
                        "sampler": sampler,
                        "prior_cf_scale": prior_scale,
                        "prior_steps": prior_steps,
                        "input_seed": seed,
                    }

                    params = augmentations["exec"](params, injections)
                    if output_folder != "":
                        params[".output_dir"] = output_folder

                    k_log(f"{index+1}/{len(i2i_source)}: processing {imagepath}")
                    _ = generate_fn(params)
                return f"{len(i2i_source)} images successfully processed"

            click_and_disable(
                generate_batch_i2i,
                generate_batch,
                [
                    session,
                    input_folder,
                    output_folder,
                    img_extension,
                    batch_prompt,
                    batch_strength,
                    steps,
                    batch_count,
                    batch_size,
                    guidance_scale,
                    width,
                    height,
                    sampler_20,
                    sampler_21_native,
                    sampler_diffusers,
                    prior_scale,
                    prior_steps,
                    seed,
                ]
                + augmentations["injections"],
                [batch_progress],
            )

            def show_processed_images(output_folder, extensions):
                if not os.path.exists(output_folder):
                    return [
                        gr.Gallery.update(visible=True),
                        "Output folder does not exist",
                    ]

                output_images = []
                for filename in os.listdir(output_folder):
                    if filename.endswith(tuple(extensions.split(";"))):
                        output_images.append(f"{output_folder}/{filename}")

                return [output_images, ""]

            click_and_disable(
                show_processed_i2i,
                fn=show_processed_images,
                inputs=[output_folder, img_extension],
                outputs=[i2i_output, batch_progress],
            )

        i2i_params.elem_classes = ["block-params i2i_params"]
        i2i_advanced_params.elem_classes = ["block-advanced-params i2i_advanced_params"]
    return i2i_block
