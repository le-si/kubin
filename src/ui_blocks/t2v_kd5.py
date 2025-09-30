import asyncio
import os
import gradio as gr
from omegaconf import OmegaConf
from ui_blocks.shared.ui_shared import SharedUI
from utils.gradio_ui import click_and_disable
from utils.storage import get_value
from utils.text import generate_prompt_from_wildcard

block = "t2v_kd5"


def load_config_defaults(config_name):
    """Load default values from config YAML file"""
    try:
        current_dir = os.path.dirname(os.path.abspath(__file__))
        config_path = os.path.join(
            current_dir,
            "..",
            "models",
            "model_50",
            "configs",
            f"config_{config_name}.yaml",
        )
        return OmegaConf.load(config_path)
    except Exception as e:
        print(f"Error loading config {config_name}: {e}")
        return None


def get_variant_defaults(config_defaults, variant):
    """Get default values for a specific variant"""
    cfg = config_defaults.get(variant)

    if cfg:
        return {
            "prompt": "A closeshot of beautiful blonde woman standing under the sun at the beach. Soft waves lapping at her feet and vibrant palm trees lining the distant coastline under a clear blue sky.",
            "width": 512,
            "height": 512,
            "duration": 5,
            "seed": -1,
            "num_steps": cfg.model.num_steps,
            "guidance_weight": cfg.model.guidance_weight,
            "expand_prompts": True,
            "use_offload": True,
            "use_magcache": False,
            "use_dit_int8_ao_quantization": False,
            "use_save_quantized_weights": False,
            "in_visual_dim": cfg.model.dit_params.in_visual_dim,
            "out_visual_dim": cfg.model.dit_params.out_visual_dim,
            "time_dim": cfg.model.dit_params.time_dim,
            "model_dim": cfg.model.dit_params.model_dim,
            "ff_dim": cfg.model.dit_params.ff_dim,
            "num_text_blocks": cfg.model.dit_params.num_text_blocks,
            "num_visual_blocks": cfg.model.dit_params.num_visual_blocks,
            "patch_size": str(cfg.model.dit_params.patch_size),
            "axes_dims": str(cfg.model.dit_params.axes_dims),
            "visual_cond": cfg.model.dit_params.visual_cond,
            "in_text_dim": cfg.model.dit_params.in_text_dim,
            "in_text_dim2": cfg.model.dit_params.in_text_dim2,
            "attention_type": cfg.model.attention.type,
            "attention_causal": cfg.model.attention.causal,
            "attention_local": cfg.model.attention.local,
            "attention_glob": cfg.model.attention.glob,
            "attention_window": cfg.model.attention.window,
            "nabla_P": cfg.model.attention.get("P", 0.9),
            "nabla_wT": cfg.model.attention.get("wT", 11),
            "nabla_wW": cfg.model.attention.get("wW", 3),
            "nabla_wH": cfg.model.attention.get("wH", 3),
            "nabla_add_sta": cfg.model.attention.get("add_sta", True),
            "nabla_method": cfg.model.attention.get("method", "topcdf"),
            "qwen_emb_size": cfg.model.text_embedder.qwen.emb_size,
            "qwen_max_length": cfg.model.text_embedder.qwen.max_length,
            "qwen_checkpoint": cfg.model.text_embedder.qwen.checkpoint_path.strip("/"),
            "clip_emb_size": cfg.model.text_embedder.clip.emb_size,
            "clip_max_length": cfg.model.text_embedder.clip.max_length,
            "clip_checkpoint": cfg.model.text_embedder.clip.checkpoint_path.strip("/"),
            "vae_checkpoint": cfg.model.vae.checkpoint_path,
            "vae_name": cfg.model.vae.name,
            "model_checkpoint": cfg.model.checkpoint_path,
        }
    else:
        # Fallback defaults
        is_10s = "10s" in variant
        return {
            "prompt": "A closeshot of beautiful blonde woman standing under the sun at the beach. Soft waves lapping at her feet and vibrant palm trees lining the distant coastline under a clear blue sky.",
            "width": 512,
            "height": 512,
            "duration": 5,
            "seed": -1,
            "num_steps": 50,
            "guidance_weight": 5.0,
            "expand_prompts": True,
            "use_offload": True,
            "use_magcache": False,
            "use_dit_int8_ao_quantization": False,
            "use_save_quantized_weights": False,
            "in_visual_dim": 16,
            "out_visual_dim": 16,
            "time_dim": 512,
            "model_dim": 1792,
            "ff_dim": 7168,
            "num_text_blocks": 2,
            "num_visual_blocks": 32,
            "patch_size": "[1, 2, 2]",
            "axes_dims": "[16, 24, 24]",
            "visual_cond": True,
            "in_text_dim": 3584,
            "in_text_dim2": 768,
            "attention_type": "nabla" if is_10s else "flash",
            "attention_causal": False,
            "attention_local": False,
            "attention_glob": False,
            "attention_window": 3,
            "nabla_P": 0.9,
            "nabla_wT": 11,
            "nabla_wW": 3,
            "nabla_wH": 3,
            "nabla_add_sta": True,
            "nabla_method": "topcdf",
            "qwen_emb_size": 3584,
            "qwen_max_length": 256,
            "qwen_checkpoint": "Qwen/Qwen2.5-VL-7B-Instruct",
            "clip_emb_size": 768,
            "clip_max_length": 77,
            "clip_checkpoint": "openai/clip-vit-large-patch14",
            "vae_checkpoint": "hunyuanvideo-community/HunyuanVideo",
            "vae_name": "hunyuan",
            "model_checkpoint": f"ai-forever/Kandinsky-5.0-T2V-Lite-{get_model_name_from_variant(variant)}",
        }


def get_model_name_from_variant(variant):
    """Convert variant name to model repository name"""
    variant_map = {
        "5s_sft": "sft-5s",
        "5s_pretrain": "pretrain-5s",
        "5s_nocfg": "nocfg-5s",
        "5s_distil": "distilled16steps-5s",
        "10s_sft": "sft-10s",
        "10s_pretrain": "pretrain-10s",
        "10s_nocfg": "nocfg-10s",
        "10s_distil": "distilled16steps-10s",
    }
    return variant_map.get(variant, "sft-5s")


def t2v_kd5_ui(generate_fn, shared: SharedUI, tabs, session):
    augmentations = shared.create_ext_augment_blocks("t2v_kd5")
    value = lambda name, def_value: get_value(shared.storage, block, name, def_value)

    # Load default configs from YAML files
    config_defaults = {}
    variants = [
        "5s_sft",
        "5s_pretrain",
        "5s_nocfg",
        "5s_distil",
        "10s_sft",
        "10s_pretrain",
        "10s_nocfg",
        "10s_distil",
    ]
    for variant in variants:
        config_defaults[variant] = load_config_defaults(variant)

    # Get initial variant and its defaults
    initial_variant = value("config_variant", "5s_sft")
    defaults = get_variant_defaults(config_defaults, initial_variant)

    with gr.Row() as t2v_kd5_block:
        t2v_kd5_block.elem_classes = ["t2v_kd5_block"]

        with gr.Column(scale=2) as t2v_kd5_params:
            augmentations["ui_before_prompt"]()

            # Variant selector
            with gr.Row():
                config_variant = gr.Radio(
                    choices=[
                        ("5s SFT", "5s_sft"),
                        ("5s Pretrain", "5s_pretrain"),
                        ("5s No CFG", "5s_nocfg"),
                        ("5s Distilled", "5s_distil"),
                        ("10s SFT", "10s_sft"),
                        ("10s Pretrain", "10s_pretrain"),
                        ("10s No CFG", "10s_nocfg"),
                        ("10s Distilled", "10s_distil"),
                    ],
                    value=initial_variant,
                    label="Model Variant",
                    info="Select which KD5 model variant to use. Settings are saved per variant when you press Generate.",
                )

            with gr.Row():
                prompt = gr.TextArea(
                    value=defaults["prompt"],
                    label="Prompt",
                    placeholder="",
                    lines=4,
                )

            augmentations["ui_before_params"]()

            with gr.Row():
                with gr.Column():
                    width = gr.Number(
                        value=defaults["width"],
                        label="Width",
                        precision=0,
                        minimum=128,
                        maximum=2048,
                        step=64,
                    )
                    height = gr.Number(
                        value=defaults["height"],
                        label="Height",
                        precision=0,
                        minimum=128,
                        maximum=2048,
                        step=64,
                    )
                with gr.Column():
                    duration = gr.Slider(
                        minimum=1,
                        maximum=20,
                        value=defaults["duration"],
                        step=1,
                        label="Duration (seconds)",
                    )
                    seed = gr.Number(value=defaults["seed"], label="Seed", precision=0)

            # Single configuration panel
            with gr.Accordion("MODEL CONFIGURATION", open=True):
                components = {}

                with gr.Row():
                    components["num_steps"] = gr.Slider(
                        minimum=1,
                        maximum=200,
                        value=defaults["num_steps"],
                        label="Number of Steps",
                        step=1,
                    )
                    components["guidance_weight"] = gr.Slider(
                        minimum=0.0,
                        maximum=20.0,
                        value=defaults["guidance_weight"],
                        label="Guidance Weight",
                        step=0.5,
                    )

                with gr.Row():
                    components["expand_prompts"] = gr.Checkbox(
                        value=defaults["expand_prompts"],
                        label="Expand Prompts (use Qwen to enhance)",
                    )

                with gr.Accordion("Optimization Options", open=True):
                    with gr.Row():
                        components["use_offload"] = gr.Checkbox(
                            value=defaults["use_offload"],
                            label="Use Offloading",
                        )
                        components["use_magcache"] = gr.Checkbox(
                            value=defaults["use_magcache"],
                            label="Use MagCache",
                        )
                        components["use_dit_int8_ao_quantization"] = gr.Checkbox(
                            value=defaults["use_dit_int8_ao_quantization"],
                            label="Use DiT INT8 Quantization",
                        )
                        components["use_save_quantized_weights"] = gr.Checkbox(
                            value=defaults["use_save_quantized_weights"],
                            label="Save Quantized Weights",
                        )

                with gr.Accordion("DiT Parameters", open=False):
                    with gr.Row():
                        components["in_visual_dim"] = gr.Number(
                            interactive=True,
                            label="Input Visual Dimension",
                            precision=0,
                            value=defaults["in_visual_dim"],
                        )
                        components["out_visual_dim"] = gr.Number(
                            interactive=True,
                            precision=0,
                            label="Output Visual Dimension",
                            value=defaults["out_visual_dim"],
                        )
                        components["time_dim"] = gr.Number(
                            interactive=True,
                            label="Time Dimension",
                            value=defaults["time_dim"],
                            precision=0,
                        )
                        components["model_dim"] = gr.Number(
                            precision=0,
                            interactive=True,
                            label="Model Dimension",
                            value=defaults["model_dim"],
                        )

                    with gr.Row():
                        components["ff_dim"] = gr.Number(
                            interactive=True,
                            precision=0,
                            label="Feed Forward Dimension",
                            value=defaults["ff_dim"],
                        )
                        components["num_text_blocks"] = gr.Number(
                            precision=0,
                            interactive=True,
                            label="Number of Text Blocks",
                            value=defaults["num_text_blocks"],
                        )
                        components["num_visual_blocks"] = gr.Number(
                            precision=0,
                            interactive=True,
                            label="Number of Visual Blocks",
                            value=defaults["num_visual_blocks"],
                        )

                    with gr.Row():
                        components["patch_size"] = gr.Textbox(
                            interactive=True,
                            max_lines=1,
                            label="Patch Size",
                            value=defaults["patch_size"],
                        )
                        components["axes_dims"] = gr.Textbox(
                            interactive=True,
                            max_lines=1,
                            label="Axes Dimensions",
                            value=defaults["axes_dims"],
                        )
                        components["visual_cond"] = gr.Checkbox(
                            value=defaults["visual_cond"],
                            label="Visual Conditioning",
                        )

                    with gr.Row():
                        components["in_text_dim"] = gr.Number(
                            interactive=True,
                            precision=0,
                            label="Input Text Dimension (Qwen)",
                            value=defaults["in_text_dim"],
                        )
                        components["in_text_dim2"] = gr.Number(
                            interactive=True,
                            precision=0,
                            label="Input Text Dimension 2 (CLIP)",
                            value=defaults["in_text_dim2"],
                        )

                with gr.Accordion("Attention Parameters", open=False):
                    with gr.Row():
                        components["attention_type"] = gr.Dropdown(
                            interactive=True,
                            label="Attention Type",
                            value=defaults["attention_type"],
                            choices=["flash", "nabla", "sdpa"],
                        )
                        components["attention_causal"] = gr.Checkbox(
                            value=defaults["attention_causal"],
                            label="Causal Attention",
                        )
                        components["attention_local"] = gr.Checkbox(
                            value=defaults["attention_local"],
                            label="Local Attention",
                        )
                        components["attention_glob"] = gr.Checkbox(
                            value=defaults["attention_glob"],
                            label="Global Attention",
                        )
                        components["attention_window"] = gr.Number(
                            interactive=True,
                            precision=0,
                            label="Attention Window",
                            value=defaults["attention_window"],
                        )

                # Nabla-specific parameters (visible for 10s models)
                with gr.Accordion(
                    "Nabla Attention Parameters (for 10s models)", open=False
                ):
                    with gr.Row():
                        components["nabla_P"] = gr.Number(
                            interactive=True,
                            label="P",
                            value=defaults["nabla_P"],
                        )
                        components["nabla_wT"] = gr.Number(
                            interactive=True,
                            precision=0,
                            label="wT",
                            value=defaults["nabla_wT"],
                        )
                        components["nabla_wW"] = gr.Number(
                            interactive=True,
                            precision=0,
                            label="wW",
                            value=defaults["nabla_wW"],
                        )
                        components["nabla_wH"] = gr.Number(
                            interactive=True,
                            precision=0,
                            label="wH",
                            value=defaults["nabla_wH"],
                        )
                    with gr.Row():
                        components["nabla_add_sta"] = gr.Checkbox(
                            value=defaults["nabla_add_sta"],
                            label="Add STA",
                        )
                        components["nabla_method"] = gr.Dropdown(
                            interactive=True,
                            label="Method",
                            value=defaults["nabla_method"],
                            choices=["topcdf", "top"],
                        )

                with gr.Accordion("Text Embedder Configuration", open=False):
                    with gr.Row():
                        components["qwen_emb_size"] = gr.Number(
                            precision=0,
                            interactive=True,
                            label="Qwen Embedding Size",
                            value=defaults["qwen_emb_size"],
                        )
                        components["qwen_max_length"] = gr.Number(
                            precision=0,
                            interactive=True,
                            label="Qwen Max Length",
                            value=defaults["qwen_max_length"],
                        )
                        components["qwen_checkpoint"] = gr.Textbox(
                            interactive=True,
                            max_lines=1,
                            label="Qwen Checkpoint Path",
                            value=defaults["qwen_checkpoint"],
                        )

                    with gr.Row():
                        components["clip_emb_size"] = gr.Number(
                            precision=0,
                            interactive=True,
                            label="CLIP Embedding Size",
                            value=defaults["clip_emb_size"],
                        )
                        components["clip_max_length"] = gr.Number(
                            precision=0,
                            interactive=True,
                            label="CLIP Max Length",
                            value=defaults["clip_max_length"],
                        )
                        components["clip_checkpoint"] = gr.Textbox(
                            interactive=True,
                            max_lines=1,
                            label="CLIP Checkpoint Path",
                            value=defaults["clip_checkpoint"],
                        )

                with gr.Accordion("VAE & Model Paths", open=False):
                    with gr.Row():
                        components["vae_checkpoint"] = gr.Textbox(
                            interactive=True,
                            max_lines=1,
                            label="VAE Checkpoint Path",
                            value=defaults["vae_checkpoint"],
                        )
                        components["vae_name"] = gr.Textbox(
                            interactive=True,
                            max_lines=1,
                            label="VAE Name",
                            value=defaults["vae_name"],
                        )
                    with gr.Row():
                        components["model_checkpoint"] = gr.Textbox(
                            interactive=True,
                            max_lines=1,
                            label="Model Checkpoint Path",
                            value=defaults["model_checkpoint"],
                        )

                # Reset button
                with gr.Row():
                    reset_config_btn = gr.Button(
                        "Reset current variant to defaults",
                        variant="secondary",
                        size="sm",
                    )

                # Setup reset functionality
                def reset_to_defaults(variant):
                    """Load defaults from YAML config for the selected variant"""
                    defaults = get_variant_defaults(config_defaults, variant)

                    return [
                        gr.update(value=defaults["prompt"]),
                        gr.update(value=defaults["width"]),
                        gr.update(value=defaults["height"]),
                        gr.update(value=defaults["duration"]),
                        gr.update(value=defaults["seed"]),
                        gr.update(value=defaults["num_steps"]),
                        gr.update(value=defaults["guidance_weight"]),
                        gr.update(value=defaults["expand_prompts"]),
                        gr.update(value=defaults["use_offload"]),
                        gr.update(value=defaults["use_magcache"]),
                        gr.update(value=defaults["in_visual_dim"]),
                        gr.update(value=defaults["out_visual_dim"]),
                        gr.update(value=defaults["time_dim"]),
                        gr.update(value=defaults["model_dim"]),
                        gr.update(value=defaults["ff_dim"]),
                        gr.update(value=defaults["num_text_blocks"]),
                        gr.update(value=defaults["num_visual_blocks"]),
                        gr.update(value=defaults["patch_size"]),
                        gr.update(value=defaults["axes_dims"]),
                        gr.update(value=defaults["visual_cond"]),
                        gr.update(value=defaults["in_text_dim"]),
                        gr.update(value=defaults["in_text_dim2"]),
                        gr.update(value=defaults["attention_type"]),
                        gr.update(value=defaults["attention_causal"]),
                        gr.update(value=defaults["attention_local"]),
                        gr.update(value=defaults["attention_glob"]),
                        gr.update(value=defaults["attention_window"]),
                        gr.update(value=defaults["nabla_P"]),
                        gr.update(value=defaults["nabla_wT"]),
                        gr.update(value=defaults["nabla_wW"]),
                        gr.update(value=defaults["nabla_wH"]),
                        gr.update(value=defaults["nabla_add_sta"]),
                        gr.update(value=defaults["nabla_method"]),
                        gr.update(value=defaults["qwen_emb_size"]),
                        gr.update(value=defaults["qwen_max_length"]),
                        gr.update(value=defaults["qwen_checkpoint"]),
                        gr.update(value=defaults["clip_emb_size"]),
                        gr.update(value=defaults["clip_max_length"]),
                        gr.update(value=defaults["clip_checkpoint"]),
                        gr.update(value=defaults["vae_checkpoint"]),
                        gr.update(value=defaults["vae_name"]),
                        gr.update(value=defaults["model_checkpoint"]),
                    ]

                reset_config_btn.click(
                    fn=reset_to_defaults,
                    inputs=[config_variant],
                    outputs=[
                        prompt,
                        width,
                        height,
                        duration,
                        seed,
                        components["num_steps"],
                        components["guidance_weight"],
                        components["expand_prompts"],
                        components["use_offload"],
                        components["use_magcache"],
                        components["use_dit_int8_ao_quantization"],
                        components["use_save_quantized_weights"],
                        components["in_visual_dim"],
                        components["out_visual_dim"],
                        components["time_dim"],
                        components["model_dim"],
                        components["ff_dim"],
                        components["num_text_blocks"],
                        components["num_visual_blocks"],
                        components["patch_size"],
                        components["axes_dims"],
                        components["visual_cond"],
                        components["in_text_dim"],
                        components["in_text_dim2"],
                        components["attention_type"],
                        components["attention_causal"],
                        components["attention_local"],
                        components["attention_glob"],
                        components["attention_window"],
                        components["nabla_P"],
                        components["nabla_wT"],
                        components["nabla_wW"],
                        components["nabla_wH"],
                        components["nabla_add_sta"],
                        components["nabla_method"],
                        components["qwen_emb_size"],
                        components["qwen_max_length"],
                        components["qwen_checkpoint"],
                        components["clip_emb_size"],
                        components["clip_max_length"],
                        components["clip_checkpoint"],
                        components["vae_checkpoint"],
                        components["vae_name"],
                        components["model_checkpoint"],
                    ],
                )

                # Setup variant switching - load saved/default params when user switches variants
                def load_variant_params(variant):
                    """Load parameters for the selected variant from storage or defaults"""
                    defaults = get_variant_defaults(config_defaults, variant)

                    # Try to load saved values, fall back to defaults
                    def get_saved(param_path, default_val):
                        return get_value(
                            shared.storage,
                            block,
                            f"configs.{variant}.{param_path}",
                            default_val,
                        )

                    return [
                        gr.update(value=get_saved("prompt", defaults["prompt"])),
                        gr.update(value=get_saved("width", defaults["width"])),
                        gr.update(value=get_saved("height", defaults["height"])),
                        gr.update(value=get_saved("duration", defaults["duration"])),
                        gr.update(value=get_saved("seed", defaults["seed"])),
                        gr.update(value=get_saved("num_steps", defaults["num_steps"])),
                        gr.update(
                            value=get_saved(
                                "guidance_weight", defaults["guidance_weight"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "expand_prompts", defaults["expand_prompts"]
                            )
                        ),
                        gr.update(
                            value=get_saved("use_offload", defaults["use_offload"])
                        ),
                        gr.update(
                            value=get_saved("use_magcache", defaults["use_magcache"])
                        ),
                        gr.update(
                            value=get_saved(
                                "use_dit_int8_ao_quantization",
                                defaults["use_dit_int8_ao_quantization"],
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "use_save_quantized_weights",
                                defaults["use_save_quantized_weights"],
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "dit_params.in_visual_dim", defaults["in_visual_dim"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "dit_params.out_visual_dim", defaults["out_visual_dim"]
                            )
                        ),
                        gr.update(
                            value=get_saved("dit_params.time_dim", defaults["time_dim"])
                        ),
                        gr.update(
                            value=get_saved(
                                "dit_params.model_dim", defaults["model_dim"]
                            )
                        ),
                        gr.update(
                            value=get_saved("dit_params.ff_dim", defaults["ff_dim"])
                        ),
                        gr.update(
                            value=get_saved(
                                "dit_params.num_text_blocks",
                                defaults["num_text_blocks"],
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "dit_params.num_visual_blocks",
                                defaults["num_visual_blocks"],
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "dit_params.patch_size", defaults["patch_size"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "dit_params.axes_dims", defaults["axes_dims"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "dit_params.visual_cond", defaults["visual_cond"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "dit_params.in_text_dim", defaults["in_text_dim"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "dit_params.in_text_dim2", defaults["in_text_dim2"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "attention.type", defaults["attention_type"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "attention.causal", defaults["attention_causal"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "attention.local", defaults["attention_local"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "attention.glob", defaults["attention_glob"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "attention.window", defaults["attention_window"]
                            )
                        ),
                        gr.update(value=get_saved("attention.P", defaults["nabla_P"])),
                        gr.update(
                            value=get_saved("attention.wT", defaults["nabla_wT"])
                        ),
                        gr.update(
                            value=get_saved("attention.wW", defaults["nabla_wW"])
                        ),
                        gr.update(
                            value=get_saved("attention.wH", defaults["nabla_wH"])
                        ),
                        gr.update(
                            value=get_saved(
                                "attention.add_sta", defaults["nabla_add_sta"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "attention.method", defaults["nabla_method"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "text_embedder.qwen.emb_size", defaults["qwen_emb_size"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "text_embedder.qwen.max_length",
                                defaults["qwen_max_length"],
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "text_embedder.qwen.checkpoint_path",
                                defaults["qwen_checkpoint"],
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "text_embedder.clip.emb_size", defaults["clip_emb_size"]
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "text_embedder.clip.max_length",
                                defaults["clip_max_length"],
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "text_embedder.clip.checkpoint_path",
                                defaults["clip_checkpoint"],
                            )
                        ),
                        gr.update(
                            value=get_saved(
                                "vae.checkpoint_path", defaults["vae_checkpoint"]
                            )
                        ),
                        gr.update(value=get_saved("vae.name", defaults["vae_name"])),
                        gr.update(
                            value=get_saved(
                                "checkpoint_path", defaults["model_checkpoint"]
                            )
                        ),
                    ]

                # When variant changes, load its parameters
                config_variant.change(
                    fn=load_variant_params,
                    inputs=[config_variant],
                    outputs=[
                        prompt,
                        width,
                        height,
                        duration,
                        seed,
                        components["num_steps"],
                        components["guidance_weight"],
                        components["expand_prompts"],
                        components["use_offload"],
                        components["use_magcache"],
                        components["use_dit_int8_ao_quantization"],
                        components["use_save_quantized_weights"],
                        components["in_visual_dim"],
                        components["out_visual_dim"],
                        components["time_dim"],
                        components["model_dim"],
                        components["ff_dim"],
                        components["num_text_blocks"],
                        components["num_visual_blocks"],
                        components["patch_size"],
                        components["axes_dims"],
                        components["visual_cond"],
                        components["in_text_dim"],
                        components["in_text_dim2"],
                        components["attention_type"],
                        components["attention_causal"],
                        components["attention_local"],
                        components["attention_glob"],
                        components["attention_window"],
                        components["nabla_P"],
                        components["nabla_wT"],
                        components["nabla_wW"],
                        components["nabla_wH"],
                        components["nabla_add_sta"],
                        components["nabla_method"],
                        components["qwen_emb_size"],
                        components["qwen_max_length"],
                        components["qwen_checkpoint"],
                        components["clip_emb_size"],
                        components["clip_max_length"],
                        components["clip_checkpoint"],
                        components["vae_checkpoint"],
                        components["vae_name"],
                        components["model_checkpoint"],
                    ],
                )

                with gr.Column():
                    with gr.Row():
                        reload_model = gr.Button(
                            "Force model reload",
                            variant="secondary",
                            elem_classes=["options-medium"],
                        )
                        reload_model.click(
                            lambda: shared._kubin.model.flush(), queue=False
                        ).then(
                            fn=None,
                            _js='_ => kubin.notify.success("Model reload forced")',
                        )

            t2v_kd5_params.elem_classes = ["block-params", "t2v_kd5_params"]

        with gr.Column(
            scale=1, elem_classes=["t2v-kd5-output-block", "clear-flex-grow"]
        ):
            augmentations["ui_before_generate"]()

            generate_t2v_kd5 = gr.Button("Generate", variant="primary")

            with gr.Column():
                t2v_kd5_output = gr.Video(
                    label="Video output",
                    elem_classes=["t2v-kd5-output-video"],
                    autoplay=True,
                    show_share_button=True,
                )

            augmentations["ui_after_generate"]()

            async def generate(
                session,
                text,
                variant,
                width,
                height,
                duration,
                seed,
                num_steps,
                guidance_weight,
                expand_prompts,
                use_offload,
                use_magcache,
                use_dit_int8_ao_quantization,
                use_save_quantized_weights,
                in_visual_dim,
                out_visual_dim,
                time_dim,
                model_dim,
                ff_dim,
                num_text_blocks,
                num_visual_blocks,
                patch_size,
                axes_dims,
                visual_cond,
                in_text_dim,
                in_text_dim2,
                attention_type,
                attention_causal,
                attention_local,
                attention_glob,
                attention_window,
                nabla_P,
                nabla_wT,
                nabla_wW,
                nabla_wH,
                nabla_add_sta,
                nabla_method,
                qwen_emb_size,
                qwen_max_length,
                qwen_checkpoint,
                clip_emb_size,
                clip_max_length,
                clip_checkpoint,
                vae_checkpoint,
                vae_name,
                model_checkpoint,
                *injections,
            ):
                text = generate_prompt_from_wildcard(text)

                while True:
                    # Build config for the selected variant
                    variant_config = {
                        "num_steps": num_steps,
                        "guidance_weight": guidance_weight,
                        "expand_prompts": expand_prompts,
                        "use_offload": use_offload,
                        "use_magcache": use_magcache,
                        "use_dit_int8_ao_quantization": use_dit_int8_ao_quantization,
                        "use_save_quantized_weights": use_save_quantized_weights,
                        "dit_params": {
                            "in_visual_dim": in_visual_dim,
                            "out_visual_dim": out_visual_dim,
                            "time_dim": time_dim,
                            "model_dim": model_dim,
                            "ff_dim": ff_dim,
                            "num_text_blocks": num_text_blocks,
                            "num_visual_blocks": num_visual_blocks,
                            "patch_size": eval(patch_size),
                            "axes_dims": eval(axes_dims),
                            "visual_cond": visual_cond,
                            "in_text_dim": in_text_dim,
                            "in_text_dim2": in_text_dim2,
                        },
                        "attention": {
                            "type": attention_type,
                            "causal": attention_causal,
                            "local": attention_local,
                            "glob": attention_glob,
                            "window": attention_window,
                            "P": nabla_P,
                            "wT": nabla_wT,
                            "wW": nabla_wW,
                            "wH": nabla_wH,
                            "add_sta": nabla_add_sta,
                            "method": nabla_method,
                        },
                        "text_embedder": {
                            "qwen": {
                                "emb_size": qwen_emb_size,
                                "max_length": qwen_max_length,
                                "checkpoint_path": qwen_checkpoint,
                            },
                            "clip": {
                                "emb_size": clip_emb_size,
                                "max_length": clip_max_length,
                                "checkpoint_path": clip_checkpoint,
                            },
                        },
                        "vae": {
                            "checkpoint_path": vae_checkpoint,
                            "name": vae_name,
                        },
                        "checkpoint_path": model_checkpoint,
                    }

                    params = {
                        ".session": session,
                        "config_variant": variant,
                        "pipeline_args": {
                            "config_name": variant,
                            "kd50_conf": {variant: variant_config},
                        },
                        "prompt": text,
                        "width": width,
                        "height": height,
                        "time_length": duration,
                        "seed": seed,
                        # Save variant-specific config and basic parameters
                        f"configs.{variant}": variant_config,
                        f"configs.{variant}.prompt": text,
                        f"configs.{variant}.width": width,
                        f"configs.{variant}.height": height,
                        f"configs.{variant}.duration": duration,
                        f"configs.{variant}.seed": seed,
                    }

                    shared.storage.save(block, params)

                    params = augmentations["exec"](params, injections)
                    try:
                        yield generate_fn(params)
                    except Exception as e:
                        import traceback

                        error_msg = f"Error in KD5 generation: {str(e)}\n\nFull traceback:\n{traceback.format_exc()}"
                        print(error_msg)
                        yield f"Generation failed: {error_msg}"

                    if not shared.check("LOOP_T2V_KD5", False):
                        break

            click_and_disable(
                element=generate_t2v_kd5,
                fn=generate,
                inputs=[
                    session,
                    prompt,
                    config_variant,
                    width,
                    height,
                    duration,
                    seed,
                    components["num_steps"],
                    components["guidance_weight"],
                    components["expand_prompts"],
                    components["use_offload"],
                    components["use_magcache"],
                    components["use_dit_int8_ao_quantization"],
                    components["use_save_quantized_weights"],
                    components["in_visual_dim"],
                    components["out_visual_dim"],
                    components["time_dim"],
                    components["model_dim"],
                    components["ff_dim"],
                    components["num_text_blocks"],
                    components["num_visual_blocks"],
                    components["patch_size"],
                    components["axes_dims"],
                    components["visual_cond"],
                    components["in_text_dim"],
                    components["in_text_dim2"],
                    components["attention_type"],
                    components["attention_causal"],
                    components["attention_local"],
                    components["attention_glob"],
                    components["attention_window"],
                    components["nabla_P"],
                    components["nabla_wT"],
                    components["nabla_wW"],
                    components["nabla_wH"],
                    components["nabla_add_sta"],
                    components["nabla_method"],
                    components["qwen_emb_size"],
                    components["qwen_max_length"],
                    components["qwen_checkpoint"],
                    components["clip_emb_size"],
                    components["clip_max_length"],
                    components["clip_checkpoint"],
                    components["vae_checkpoint"],
                    components["vae_name"],
                    components["model_checkpoint"],
                ]
                + augmentations["injections"],
                outputs=[t2v_kd5_output],
                js=[
                    "args => kubin.UI.taskStarted('Text To Video KD5')",
                    "args => kubin.UI.taskFinished('Text To Video KD5')",
                ],
            )

    return t2v_kd5_block
