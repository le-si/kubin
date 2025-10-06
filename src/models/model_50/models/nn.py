# This source code is licensed under the Apache License found in the
# LICENSE file in the current directory's parent directory.
"""
The code has been adopted from Kandinsky-5
(https://github.com/ai-forever/Kandinsky-5/blob/main/kandinsky/models/nn.py)
"""


import math
import os

import torch
from torch import nn
from torch.nn.attention.flex_attention import flex_attention

from .utils import get_freqs, nablaT_v2
from ..enhance import compute_enhance_multiplier, is_enhance_enabled


def kd5_compile(*args, **kwargs):
    def decorator(fn):
        # Check for global disable
        if os.environ.get("KD5_DISABLE_COMPILE") == "1":
            return fn
        # Check for nabla-specific disable (default: disabled for nabla to prevent OOM)
        if fn.__name__ == "nabla" and os.environ.get("KD5_COMPILE_NABLA", "0") != "1":
            return fn
        # Check for VAE-specific disable (for VAE forward methods)
        # VAE methods are in vae.py and include: forward methods of HunyuanVideoUpsampleCausal3D, HunyuanVideoResnetBlockCausal3D
        if os.environ.get("KD5_DISABLE_COMPILE_VAE") == "1":
            # Identify VAE methods by their module
            module_name = fn.__module__ if hasattr(fn, '__module__') else ''
            if 'vae' in module_name.lower() or fn.__name__ in ['forward', 'decode', 'encode']:
                # More precise: check if function is defined in a VAE class
                if hasattr(fn, '__qualname__'):
                    qualname = fn.__qualname__
                    if any(vae_class in qualname for vae_class in [
                        'HunyuanVideo', 'AutoencoderKL', 'Encoder3D', 'Decoder3D',
                        'UpsampleCausal3D', 'ResnetBlockCausal3D'
                    ]):
                        return fn
        # Check for DiT-specific disable
        if os.environ.get("KD5_DISABLE_COMPILE_DIT") == "1":
            # DiT methods are everything NOT in VAE
            module_name = fn.__module__ if hasattr(fn, '__module__') else ''
            if 'vae' not in module_name.lower():
                if hasattr(fn, '__qualname__'):
                    qualname = fn.__qualname__
                    # If it's not a VAE class, it's likely DiT-related
                    if not any(vae_class in qualname for vae_class in [
                        'HunyuanVideo', 'AutoencoderKL', 'Encoder3D', 'Decoder3D',
                        'UpsampleCausal3D', 'ResnetBlockCausal3D'
                    ]):
                        return fn
        return torch.compile(*args, **kwargs)(fn)

    return decorator


if torch.cuda.get_device_capability()[0] >= 9:
    try:
        from flash_attn import flash_attn_func as FA

        print("✓ FlashAttention 2 found")
    except:
        FA = None

    try:
        from flash_attn_interface import flash_attn_func as FA  # type: ignore

        print("✓ FlashAttention 3 found (overriding FA2)")
    except:
        FA = FA
else:
    try:
        from flash_attn import flash_attn_func as FA

        print("✓ FlashAttention 2 found")
    except:
        FA = None

if FA is None:
    print("⚠️  Flash Attention not found - will use PyTorch SDPA fallback")
    print("   Install FlashAttention with: pip install flash-attn")

try:
    from sageattention import sageattn

    SAGE_ATTN = sageattn
except ImportError:
    SAGE_ATTN = None
    print("⚠️  Sage Attention not found - install with: pip install sageattention")


@kd5_compile()
@torch.autocast(device_type="cuda", dtype=torch.float32)
def apply_scale_shift_norm(norm, x, scale, shift):
    return (norm(x) * (scale + 1.0) + shift).to(torch.bfloat16)


@kd5_compile()
@torch.autocast(device_type="cuda", dtype=torch.float32)
def apply_gate_sum(x, out, gate):
    return (x + gate * out).to(torch.bfloat16)


@kd5_compile()
@torch.autocast(device_type="cuda", enabled=False)
def apply_rotary(x, rope):
    x_ = x.reshape(*x.shape[:-1], -1, 1, 2).to(torch.float32)
    x_out = (rope * x_).sum(dim=-1)
    return x_out.reshape(*x.shape).to(torch.bfloat16)


class TimeEmbeddings(nn.Module):
    def __init__(self, model_dim, time_dim, max_period=10000.0):
        super().__init__()
        assert model_dim % 2 == 0
        self.model_dim = model_dim
        self.max_period = max_period
        self.register_buffer(
            "freqs", get_freqs(model_dim // 2, max_period), persistent=False
        )
        self.in_layer = nn.Linear(model_dim, time_dim, bias=True)
        self.activation = nn.SiLU()
        self.out_layer = nn.Linear(time_dim, time_dim, bias=True)

    @torch.autocast(device_type="cuda", dtype=torch.float32)
    def forward(self, time):
        args = torch.outer(time, self.freqs.to(device=time.device))
        time_embed = torch.cat([torch.cos(args), torch.sin(args)], dim=-1)
        time_embed = self.out_layer(self.activation(self.in_layer(time_embed)))
        return time_embed


class TextEmbeddings(nn.Module):
    def __init__(self, text_dim, model_dim):
        super().__init__()
        self.in_layer = nn.Linear(text_dim, model_dim, bias=True)
        self.norm = nn.LayerNorm(model_dim, elementwise_affine=True)

    def forward(self, text_embed):
        text_embed = self.in_layer(text_embed)
        return self.norm(text_embed).type_as(text_embed)


class VisualEmbeddings(nn.Module):
    def __init__(self, visual_dim, model_dim, patch_size):
        super().__init__()
        self.patch_size = patch_size
        self.in_layer = nn.Linear(math.prod(patch_size) * visual_dim, model_dim)

    def forward(self, x):
        duration, height, width, dim = x.shape
        x = (
            x.view(
                duration // self.patch_size[0],
                self.patch_size[0],
                height // self.patch_size[1],
                self.patch_size[1],
                width // self.patch_size[2],
                self.patch_size[2],
                dim,
            )
            .permute(0, 2, 4, 1, 3, 5, 6)
            .flatten(3, 6)
        )
        return self.in_layer(x)


class RoPE1D(nn.Module):
    def __init__(self, dim, max_pos=1024, max_period=10000.0):
        super().__init__()
        self.max_period = max_period
        self.dim = dim
        self.max_pos = max_pos
        freq = get_freqs(dim // 2, max_period)
        pos = torch.arange(max_pos, dtype=freq.dtype)
        self.register_buffer(f"args", torch.outer(pos, freq), persistent=False)

    @torch.autocast(device_type="cuda", enabled=False)
    def forward(self, pos):
        args = self.args[pos]
        cosine = torch.cos(args)
        sine = torch.sin(args)
        rope = torch.stack([cosine, -sine, sine, cosine], dim=-1)
        rope = rope.view(*rope.shape[:-1], 2, 2)
        return rope.unsqueeze(-4)


class RoPE3D(nn.Module):
    def __init__(self, axes_dims, max_pos=(128, 128, 128), max_period=10000.0):
        super().__init__()
        self.axes_dims = axes_dims
        self.max_pos = max_pos
        self.max_period = max_period

        for i, (axes_dim, ax_max_pos) in enumerate(zip(axes_dims, max_pos)):
            freq = get_freqs(axes_dim // 2, max_period)
            pos = torch.arange(ax_max_pos, dtype=freq.dtype)
            self.register_buffer(f"args_{i}", torch.outer(pos, freq), persistent=False)

    @torch.autocast(device_type="cuda", enabled=False)
    def forward(self, shape, pos, scale_factor=(1.0, 1.0, 1.0)):
        duration, height, width = shape
        args_t = self.args_0[pos[0]] / scale_factor[0]
        args_h = self.args_1[pos[1]] / scale_factor[1]
        args_w = self.args_2[pos[2]] / scale_factor[2]

        args = torch.cat(
            [
                args_t.view(duration, 1, 1, -1).repeat(1, height, width, 1),
                args_h.view(1, height, 1, -1).repeat(duration, 1, width, 1),
                args_w.view(1, 1, width, -1).repeat(duration, height, 1, 1),
            ],
            dim=-1,
        )
        cosine = torch.cos(args)
        sine = torch.sin(args)
        rope = torch.stack([cosine, -sine, sine, cosine], dim=-1)
        rope = rope.view(*rope.shape[:-1], 2, 2)
        return rope.unsqueeze(-4)


class Modulation(nn.Module):
    def __init__(self, time_dim, model_dim, num_params):
        super().__init__()
        self.activation = nn.SiLU()
        self.out_layer = nn.Linear(time_dim, num_params * model_dim)
        self.out_layer.weight.data.zero_()
        self.out_layer.bias.data.zero_()

    @kd5_compile()
    @torch.autocast(device_type="cuda", dtype=torch.float32)
    def forward(self, x):
        return self.out_layer(self.activation(x))


class MultiheadSelfAttentionEnc(nn.Module):
    def __init__(self, num_channels, head_dim):
        super().__init__()
        assert num_channels % head_dim == 0
        self.num_heads = num_channels // head_dim

        self.to_query = nn.Linear(num_channels, num_channels, bias=True)
        self.to_key = nn.Linear(num_channels, num_channels, bias=True)
        self.to_value = nn.Linear(num_channels, num_channels, bias=True)
        self.query_norm = nn.RMSNorm(head_dim)
        self.key_norm = nn.RMSNorm(head_dim)

        self.out_layer = nn.Linear(num_channels, num_channels, bias=True)

    @kd5_compile()
    def get_qkv(self, x):
        query = self.to_query(x)
        key = self.to_key(x)
        value = self.to_value(x)

        shape = query.shape[:-1]
        query = query.reshape(*shape, self.num_heads, -1)
        key = key.reshape(*shape, self.num_heads, -1)
        value = value.reshape(*shape, self.num_heads, -1)

        return query, key, value

    @kd5_compile()
    def norm_qk(self, q, k):
        q = self.query_norm(q.float()).type_as(q)
        k = self.key_norm(k.float()).type_as(k)
        return q, k

    @kd5_compile()
    def scaled_dot_product_attention(self, query, key, value):
        attn_mode = os.environ.get("KD5_ATTENTION_MODE", "flash")

        if attn_mode == "sage" and SAGE_ATTN is not None:
            # Use Sage Attention (plug-and-play replacement)
            if not hasattr(self, "_sage_logged"):
                print(f"→ Using Sage Attention (mode={attn_mode})")
                self._sage_logged = True
            out = (
                SAGE_ATTN(
                    query.unsqueeze(0).transpose(1, 2),  # [B, heads, seq, dim]
                    key.unsqueeze(0).transpose(1, 2),
                    value.unsqueeze(0).transpose(1, 2),
                )
                .transpose(1, 2)[0]
                .flatten(-2, -1)
            )
        elif attn_mode == "flash" and FA is not None:
            if not hasattr(self, "_flash_logged"):
                print(f"→ Using Flash Attention (mode={attn_mode})")
                self._flash_logged = True
            out = FA(q=query.unsqueeze(0), k=key.unsqueeze(0), v=value.unsqueeze(0))[
                0
            ].flatten(-2, -1)
        else:
            # Use PyTorch native SDPA (fallback)
            if not hasattr(self, "_sdpa_logged"):
                if attn_mode == "sage" and SAGE_ATTN is None:
                    print(
                        f"⚠️  Sage Attention requested but not found - falling back to PyTorch SDPA"
                    )
                elif attn_mode == "flash" and FA is None:
                    print(
                        f"⚠️  Flash Attention requested but not found - falling back to PyTorch SDPA"
                    )
                else:
                    print(f"→ Using PyTorch SDPA (mode={attn_mode})")
                self._sdpa_logged = True
            out = (
                torch.nn.functional.scaled_dot_product_attention(
                    query.unsqueeze(0).transpose(1, 2),  # [B, heads, seq, dim]
                    key.unsqueeze(0).transpose(1, 2),
                    value.unsqueeze(0).transpose(1, 2),
                )
                .transpose(1, 2)[0]
                .flatten(-2, -1)
            )
        return out

    @kd5_compile()
    def out_l(self, x):
        return self.out_layer(x)

    def forward(self, x, rope):
        query, key, value = self.get_qkv(x)
        query, key = self.norm_qk(query, key)
        query = apply_rotary(query, rope).type_as(query)
        key = apply_rotary(key, rope).type_as(key)

        out = self.scaled_dot_product_attention(query, key, value)

        out = self.out_l(out)
        return out


class MultiheadSelfAttentionDec(nn.Module):
    def __init__(self, num_channels, head_dim):
        super().__init__()
        assert num_channels % head_dim == 0
        self.num_heads = num_channels // head_dim

        self.to_query = nn.Linear(num_channels, num_channels, bias=True)
        self.to_key = nn.Linear(num_channels, num_channels, bias=True)
        self.to_value = nn.Linear(num_channels, num_channels, bias=True)
        self.query_norm = nn.RMSNorm(head_dim)
        self.key_norm = nn.RMSNorm(head_dim)

        self.out_layer = nn.Linear(num_channels, num_channels, bias=True)

    @kd5_compile()
    def get_qkv(self, x):
        query = self.to_query(x)
        key = self.to_key(x)
        value = self.to_value(x)

        shape = query.shape[:-1]
        query = query.reshape(*shape, self.num_heads, -1)
        key = key.reshape(*shape, self.num_heads, -1)
        value = value.reshape(*shape, self.num_heads, -1)

        return query, key, value

    @kd5_compile()
    def norm_qk(self, q, k):
        q = self.query_norm(q.float()).type_as(q)
        k = self.key_norm(k.float()).type_as(k)
        return q, k

    @kd5_compile()
    def attention(self, query, key, value):
        attn_mode = os.environ.get("KD5_ATTENTION_MODE", "flash")

        if attn_mode == "sage" and SAGE_ATTN is not None:
            # Use Sage Attention (plug-and-play replacement)
            out = (
                SAGE_ATTN(
                    query.unsqueeze(0).transpose(1, 2),  # [B, heads, seq, dim]
                    key.unsqueeze(0).transpose(1, 2),
                    value.unsqueeze(0).transpose(1, 2),
                )
                .transpose(1, 2)[0]
                .flatten(-2, -1)
            )
        elif attn_mode == "flash" and FA is not None:
            out = FA(q=query.unsqueeze(0), k=key.unsqueeze(0), v=value.unsqueeze(0))[
                0
            ].flatten(-2, -1)
        else:
            out = (
                torch.nn.functional.scaled_dot_product_attention(
                    query.unsqueeze(0).transpose(1, 2),  # [B, heads, seq, dim]
                    key.unsqueeze(0).transpose(1, 2),
                    value.unsqueeze(0).transpose(1, 2),
                )
                .transpose(1, 2)[0]
                .flatten(-2, -1)
            )
        return out

    # NOTE: torch.compile disabled for nabla by default (see kd5_compile decorator)
    # This prevents FlexAttention from falling back to dense math_attention (OOM with 457GB allocation)
    # Set KD5_COMPILE_NABLA=1 to enable torch.compile for nabla (experimental, may cause OOM)
    @kd5_compile(mode="max-autotune-no-cudagraphs", dynamic=True)
    def nabla(self, query, key, value, sparse_params=None):
        print(f"\n{'='*80}")
        print(f"NABLA ATTENTION CALLED")
        print(f"Query shape (before): {query.shape}")
        print(f"Key shape (before): {key.shape}")
        print(f"Value shape (before): {value.shape}")

        query = query.unsqueeze(0).transpose(1, 2).contiguous()
        key = key.unsqueeze(0).transpose(1, 2).contiguous()
        value = value.unsqueeze(0).transpose(1, 2).contiguous()

        print(f"Query shape (after reshape): {query.shape}  [B, heads, seq, dim]")
        print(f"Key shape (after reshape): {key.shape}")
        print(f"Value shape (after reshape): {value.shape}")
        print(
            f"STA mask shape: {sparse_params['sta_mask'].shape if sparse_params and 'sta_mask' in sparse_params else 'MISSING'}"
        )
        print(
            f"Threshold P: {sparse_params.get('P', 'MISSING') if sparse_params else 'MISSING'}"
        )
        print(f"Sequence length S: {query.shape[2]}")
        print(f"S // 64 = {query.shape[2] // 64} (must be > 0 for nabla to work)")
        print(f"{'='*80}\n")

        block_mask = nablaT_v2(
            query,
            key,
            sparse_params["sta_mask"],
            thr=sparse_params["P"],
        )
        out = (
            flex_attention(query, key, value, block_mask=block_mask)
            .transpose(1, 2)
            .squeeze(0)
            .contiguous()
        )
        out = out.flatten(-2, -1)
        return out

    @kd5_compile()
    def out_l(self, x):
        return self.out_layer(x)

    def forward(self, x, rope, sparse_params=None):
        query, key, value = self.get_qkv(x)
        query, key = self.norm_qk(query, key)
        query = apply_rotary(query, rope).type_as(query)
        key = apply_rotary(key, rope).type_as(key)

        enhance_multiplier = None
        if is_enhance_enabled():
            enhance_multiplier = compute_enhance_multiplier(query, key)

        if sparse_params is not None:
            out = self.nabla(query, key, value, sparse_params=sparse_params)
        else:
            out = self.attention(query, key, value)

        out = self.out_l(out)

        if enhance_multiplier is not None:
            out = out * enhance_multiplier.to(out.dtype)

        return out


class MultiheadCrossAttention(nn.Module):
    def __init__(self, num_channels, head_dim):
        super().__init__()
        assert num_channels % head_dim == 0
        self.num_heads = num_channels // head_dim

        self.to_query = nn.Linear(num_channels, num_channels, bias=True)
        self.to_key = nn.Linear(num_channels, num_channels, bias=True)
        self.to_value = nn.Linear(num_channels, num_channels, bias=True)
        self.query_norm = nn.RMSNorm(head_dim)
        self.key_norm = nn.RMSNorm(head_dim)

        self.out_layer = nn.Linear(num_channels, num_channels, bias=True)

    @kd5_compile()
    def get_qkv(self, x, cond):
        query = self.to_query(x)
        key = self.to_key(cond)
        value = self.to_value(cond)

        shape, cond_shape = query.shape[:-1], key.shape[:-1]
        query = query.reshape(*shape, self.num_heads, -1)
        key = key.reshape(*cond_shape, self.num_heads, -1)
        value = value.reshape(*cond_shape, self.num_heads, -1)

        return query, key, value

    @kd5_compile()
    def norm_qk(self, q, k):
        q = self.query_norm(q.float()).type_as(q)
        k = self.key_norm(k.float()).type_as(k)
        return q, k

    @kd5_compile()
    def attention(self, query, key, value):
        attn_mode = os.environ.get("KD5_ATTENTION_MODE", "flash")

        if attn_mode == "sage" and SAGE_ATTN is not None:
            # Use Sage Attention (plug-and-play replacement)
            out = (
                SAGE_ATTN(
                    query.unsqueeze(0).transpose(1, 2),  # [B, heads, seq, dim]
                    key.unsqueeze(0).transpose(1, 2),
                    value.unsqueeze(0).transpose(1, 2),
                )
                .transpose(1, 2)[0]
                .flatten(-2, -1)
            )
        elif attn_mode == "flash" and FA is not None:
            out = FA(q=query.unsqueeze(0), k=key.unsqueeze(0), v=value.unsqueeze(0))[
                0
            ].flatten(-2, -1)
        else:
            out = (
                torch.nn.functional.scaled_dot_product_attention(
                    query.unsqueeze(0).transpose(1, 2),  # [B, heads, seq, dim]
                    key.unsqueeze(0).transpose(1, 2),
                    value.unsqueeze(0).transpose(1, 2),
                )
                .transpose(1, 2)[0]
                .flatten(-2, -1)
            )
        return out

    @kd5_compile()
    def out_l(self, x):
        return self.out_layer(x)

    def forward(self, x, cond):
        query, key, value = self.get_qkv(x, cond)
        query, key = self.norm_qk(query, key)

        out = self.attention(query, key, value)
        out = self.out_l(out)
        return out


class FeedForward(nn.Module):
    def __init__(self, dim, ff_dim):
        super().__init__()
        self.in_layer = nn.Linear(dim, ff_dim, bias=False)
        self.activation = nn.GELU()
        self.out_layer = nn.Linear(ff_dim, dim, bias=False)

    @kd5_compile()
    def forward(self, x):
        return self.out_layer(self.activation(self.in_layer(x)))


class OutLayer(nn.Module):
    def __init__(self, model_dim, time_dim, visual_dim, patch_size):
        super().__init__()
        self.patch_size = patch_size
        self.modulation = Modulation(time_dim, model_dim, 2)
        self.norm = nn.LayerNorm(model_dim, elementwise_affine=False)
        self.out_layer = nn.Linear(
            model_dim, math.prod(patch_size) * visual_dim, bias=True
        )

    def forward(self, visual_embed, text_embed, time_embed):
        shift, scale = torch.chunk(self.modulation(time_embed), 2, dim=-1)
        visual_embed = apply_scale_shift_norm(
            self.norm,
            visual_embed,
            scale[:, None, None],
            shift[:, None, None],
        ).type_as(visual_embed)
        x = self.out_layer(visual_embed)

        duration, height, width, _ = x.shape
        x = (
            x.view(
                duration,
                height,
                width,
                -1,
                self.patch_size[0],
                self.patch_size[1],
                self.patch_size[2],
            )
            .permute(0, 4, 1, 5, 2, 6, 3)
            .flatten(0, 1)
            .flatten(1, 2)
            .flatten(2, 3)
        )
        return x
