"""Renders the "hidden in the jungle" overgrowth that covers the screen edges while the VPN is on.

Run from miniapp/:  python3 tools/render_overgrowth.py
  → src/assets/og-corner-top.png, og-corner-bottom.png  (leaf clusters growing from a corner)
  → src/assets/og-edge.png                                (a leafy liana along the left edge)
  → src/assets/og-leaf.png                                (a single leaf, for falling leaves)
All anchored at the top-left; CSS mirrors them for the other corners/edges. Deterministic.
"""

import math
import os

import numpy as np
from PIL import Image

from render_common import RNG, bezier, paste_leaf, stroke

STEM = (52, 66, 30, 255)


def leaf_colour(light: float, depth: float):
    """Natural greens: lighter/yellower toward the tips in light, darker and bluer in depth."""
    k = (0.55 + 0.75 * light) * (0.55 + 0.45 * depth)
    return (64 * k * (0.9 + 0.35 * light), 138 * k, 52 * k * (1.1 - 0.4 * light))


def corner(size: int, seed: int, stems: int, spread=(4, 86)) -> Image.Image:
    rng = np.random.default_rng(seed)
    S = size * 2
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    plan = []
    for i in range(stems):
        a = math.radians(spread[0] + (spread[1] - spread[0]) * (i + rng.uniform(0.15, 0.85)) / stems)
        ln = S * rng.uniform(0.48, 0.9)
        bend = rng.uniform(-0.25, 0.25)
        p0 = (rng.uniform(-10, 10), rng.uniform(-10, 10))
        p3 = (ln * math.cos(a), ln * math.sin(a))
        p1 = (p3[0] * 0.35 - p3[1] * bend, p3[1] * 0.35 + p3[0] * bend)
        p2 = (p3[0] * 0.7 - p3[1] * bend * 0.6, p3[1] * 0.7 + p3[0] * bend * 0.6)
        plan.append((bezier(p0, p1, p2, p3, n=40), ln))
    for depth in (0.45, 1.0):  # a darker back layer of leaves, then the front layer
        for pts, ln in plan:
            if depth == 1.0:
                stroke(img, pts, 9 * (ln / S + 0.4), STEM, taper=0.35)
            for j in range(4, len(pts) - 1, 3 if depth == 1.0 else 4):
                t = j / len(pts)
                x, y = pts[j]
                tx, ty = pts[min(j + 1, len(pts) - 1)] - pts[j - 1]
                base = math.degrees(math.atan2(ty, tx))
                big = 1 - 0.45 * t
                for side in (-1, 1):
                    if rng.random() < (0.35 if depth < 1 else 0.15):
                        continue
                    ang = base + side * rng.uniform(35, 72) + rng.normal(0, 6) + (rng.uniform(-30, 30) if depth < 1 else 0)
                    kind = "broad" if (t < 0.6 and rng.random() < 0.7) else "long"
                    ll = S * rng.uniform(0.17, 0.3) * big * (1.15 if depth < 1 else 1)
                    paste_leaf(img, kind, x, y, ll, ang, leaf_colour(0.35 + 0.6 * t, depth))
            if depth == 1.0:  # leaves at the tip
                x, y = pts[-1]
                tx, ty = pts[-1] - pts[-3]
                base = math.degrees(math.atan2(ty, tx))
                for d in (-28, 0, 28):
                    paste_leaf(img, "long", x, y, S * rng.uniform(0.09, 0.13), base + d, leaf_colour(0.95, 1.0))
    return img.resize((size, size), Image.LANCZOS)


def edge(width: int, height: int) -> Image.Image:
    W, H = width * 2, height * 2
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ys = np.arange(-20, H + 20, 8, dtype=np.float32)
    pts = np.stack([26 + 14 * np.sin(ys / 120) + 5 * np.sin(ys / 37), ys], axis=1)
    for depth in (0.5, 1.0):
        if depth == 1.0:
            stroke(img, pts, 11, STEM, taper=1.0)
        step = 5 if depth == 1.0 else 7
        for j in range(2, len(pts) - 1, step):
            x, y = pts[j]
            light = 0.9 - 0.5 * y / H
            n = RNG.integers(1, 3)
            for k in range(n):
                ang = RNG.uniform(-70, 70) + (RNG.uniform(-25, 25) if depth < 1 else 0)
                kind = "broad" if RNG.random() < 0.35 else "long"
                ll = RNG.uniform(70, 150) * (1.15 if depth < 1 else 1)
                paste_leaf(img, kind, x + RNG.uniform(-6, 6), y + RNG.uniform(-10, 10), ll, ang, leaf_colour(light, depth))
    return img.resize((width, height), Image.LANCZOS)


def single_leaf() -> Image.Image:
    img = Image.new("RGBA", (260, 260), (0, 0, 0, 0))
    paste_leaf(img, "broad", 20, 130, 220, 0, leaf_colour(0.8, 1.0))
    return img.crop((10, 50, 250, 210)).resize((120, 80), Image.LANCZOS)


if __name__ == "__main__":
    out = {
        "og-corner-top.png": corner(300, 21, 7, (6, 84)),
        "og-corner-bottom.png": corner(340, 33, 8, (2, 88)),
        "og-edge.png": edge(120, 900),
        "og-leaf.png": single_leaf(),
    }
    for name, im in out.items():
        im.save(f"src/assets/{name}", optimize=True)
        print(name, im.size, os.path.getsize(f"src/assets/{name}") // 1024, "KB")
