"""Shared helpers for the procedurally rendered jungle artwork (numpy + Pillow)."""

import math

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

RNG = np.random.default_rng(11)


def leaf_tile(kind: str, size: int = 160) -> tuple[np.ndarray, np.ndarray]:
    """One leaf pointing +x: returns (shade HxW float 0..~1.4, alpha HxW float 0..1)."""
    ss = 3
    w, h = size * ss, int(size * 0.62) * ss
    xs = np.linspace(0, 1, w)[None, :]
    ys = np.linspace(-1, 1, h)[:, None]
    if kind == "long":  # lanceolate
        half = 0.42 * np.sin(np.pi * xs ** 0.75) ** 1.25
    elif kind == "broad":  # heart-ish broad leaf
        half = 0.78 * np.sin(np.pi * xs ** 0.62) ** 0.85 * (1 - 0.25 * xs)
    else:  # "blade": narrow palm leaflet
        half = 0.2 * np.sin(np.pi * xs ** 0.8) ** 0.9
    bend = 0.18 * np.sin(np.pi * xs) * (1 if kind != "blade" else 0.5)
    v = (ys - bend) / np.maximum(half, 1e-3)
    alpha = np.clip((1 - np.abs(v)) * half * h / 2.2, 0, 1)
    alpha = np.where(half > 0.004, alpha, 0)
    # shading: darker underside half, glossy band, midrib, side veins, darker tip/base
    shade = 0.78 + 0.22 * (v > 0)
    shade = shade * (0.82 + 0.5 * np.exp(-((v - 0.42) / 0.3) ** 2))
    shade = shade * (0.75 + 0.35 * np.sin(np.pi * xs) ** 0.6)
    midrib = np.exp(-(v / 0.07) ** 2)
    shade = shade + 0.3 * midrib
    veins = np.sin((xs * 16 - np.abs(v) * 2.4) * np.pi) ** 10 * (np.abs(v) < 0.92)
    shade = shade + 0.1 * veins
    img_s = Image.fromarray(np.uint8(np.clip(shade / 1.6, 0, 1) * 255)).resize((size, h // ss), Image.LANCZOS)
    img_a = Image.fromarray(np.uint8(alpha * 255)).resize((size, h // ss), Image.LANCZOS)
    return np.asarray(img_s, dtype=np.float32) / 255 * 1.6, np.asarray(img_a, dtype=np.float32) / 255


TILES = {k: leaf_tile(k) for k in ("long", "broad", "blade")}


def paste_leaf(layer: Image.Image, kind: str, x: float, y: float, length: float, angle: float, color, alpha: float = 1.0):
    """Paste one shaded leaf whose stem starts at (x, y) pointing along `angle` (degrees)."""
    shade, a = TILES[kind]
    th, tw = shade.shape
    scale = length / tw
    nw, nh = max(2, int(tw * scale)), max(2, int(th * scale))
    rgb = np.clip(shade[..., None] * np.asarray(color, dtype=np.float32)[None, None, :], 0, 255)
    tile = Image.fromarray(np.dstack([rgb, a[..., None] * 255 * alpha]).astype(np.uint8), "RGBA").resize((nw, nh), Image.BILINEAR)
    # put the stem end at the centre of a square canvas so rotation keeps it fixed
    canvas = Image.new("RGBA", (2 * nw + 2, 2 * nw + 2), (0, 0, 0, 0))
    canvas.paste(tile, (nw + 1, nw + 1 - nh // 2))
    rot = canvas.rotate(-angle, resample=Image.BILINEAR)
    _safe_composite(layer, rot, int(x - nw - 1), int(y - nw - 1))


def _safe_composite(layer: Image.Image, img: Image.Image, x: int, y: int):
    """alpha_composite that tolerates images hanging over the canvas edge."""
    x0, y0 = max(0, x), max(0, y)
    x1, y1 = min(layer.width, x + img.width), min(layer.height, y + img.height)
    if x1 <= x0 or y1 <= y0:
        return
    layer.alpha_composite(img.crop((x0 - x, y0 - y, x1 - x, y1 - y)), (x0, y0))


def bezier(p0, p1, p2, p3, n=60):
    t = np.linspace(0, 1, n)[:, None]
    p0, p1, p2, p3 = (np.asarray(p, dtype=np.float32) for p in (p0, p1, p2, p3))
    return (1 - t) ** 3 * p0 + 3 * (1 - t) ** 2 * t * p1 + 3 * (1 - t) * t ** 2 * p2 + t ** 3 * p3


def stroke(layer: Image.Image, pts, width: float, color, taper: float = 1.0):
    """A rounded stroke with cylinder-like shading (dark edge, lighter core)."""
    d = ImageDraw.Draw(layer)
    n = len(pts)
    for wmul, cmul in ((1.0, 0.55), (0.62, 0.85), (0.28, 1.15)):
        for i in range(n - 1):
            w = max(1, width * wmul * (1 - (1 - taper) * i / n))
            c = tuple(int(min(255, v * cmul)) for v in color[:3]) + (color[3] if len(color) > 3 else 255,)
            d.line([tuple(pts[i]), tuple(pts[i + 1])], fill=c, width=int(round(w)))


def blur(img: Image.Image, r: float) -> Image.Image:
    return img.filter(ImageFilter.GaussianBlur(r)) if r > 0 else img


def noise(h: int, w: int, scale: float) -> np.ndarray:
    """Smooth value noise 0..1."""
    small = RNG.random((max(2, int(h / scale)), max(2, int(w / scale)))).astype(np.float32)
    return np.asarray(Image.fromarray(np.uint8(small * 255)).resize((w, h), Image.BICUBIC), dtype=np.float32) / 255
