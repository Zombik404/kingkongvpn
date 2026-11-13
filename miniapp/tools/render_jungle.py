"""Renders the jungle backdrop and the foreground plants as raster art (no photos needed).

Run from miniapp/:  python3 tools/render_jungle.py
  → src/assets/jungle.jpg  (backdrop: misty rainforest with depth, light shafts, soft foreground)
  → src/assets/vine.png    (a liana with leaves, transparent — sways at the screen edges)
  → src/assets/wreath.png  (ring of leaves around the hub, transparent)
Deterministic (fixed seed).
"""

import math

import numpy as np
from PIL import Image, ImageDraw

from render_common import RNG, bezier, blur, noise, paste_leaf, stroke

W, H = 720, 1560
SUN = np.array([W * 0.74, -H * 0.06])


def light_map() -> np.ndarray:
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    d = np.hypot(xx - SUN[0], yy - SUN[1])
    return np.exp(-(d / (H * 0.62)) ** 1.6)


def tint(base, light: float, jitter: float = 0.12):
    """Leaf colour: yellower and brighter in the light, bluer and darker in shade."""
    r, g, b = base
    k = 0.45 + 1.0 * light + RNG.uniform(-jitter, jitter)
    return (r * k * (0.9 + 0.5 * light), g * k, b * k * (1.05 - 0.45 * light))


def foliage(layer, lm, n, region, sizes, base, kinds=("long", "broad"), cluster=7):
    """Clusters of leaves: each cluster fans out from a twig, like real branches do."""
    x0, y0, x1, y1 = region
    for _ in range(n):
        cx, cy = RNG.uniform(x0, x1), RNG.uniform(y0, y1)
        main = RNG.uniform(0, 360)
        kind = kinds[RNG.integers(len(kinds))]
        for _ in range(cluster):
            x, y = cx + RNG.normal(0, sizes[1] * 0.28), cy + RNG.normal(0, sizes[1] * 0.28)
            lx, ly = int(np.clip(x, 0, W - 1)), int(np.clip(y, 0, H - 1))
            paste_leaf(layer, kind, x, y, RNG.uniform(*sizes), main + RNG.normal(0, 38), tint(base, float(lm[ly, lx])))


def frond(layer, lm, x, y, angle, length, base, leaflets=26):
    """Palm frond: a drooping rachis with narrow leaflets on both sides."""
    a = math.radians(angle)
    p3 = (x + length * math.cos(a), y + length * math.sin(a) + length * 0.28)
    pts = bezier((x, y), (x + length * 0.4 * math.cos(a), y + length * 0.4 * math.sin(a) - length * 0.1),
                 (x + length * 0.8 * math.cos(a), y + length * 0.8 * math.sin(a)), p3, n=leaflets + 2)
    stroke(layer, pts, 4, (40, 70, 30, 255), taper=0.3)
    for i in range(1, leaflets + 1):
        px, py = pts[i]
        tx, ty = pts[i + 1] - pts[i - 1]
        ang = math.degrees(math.atan2(ty, tx))
        ll = length * 0.42 * math.sin(math.pi * (0.12 + 0.88 * i / (leaflets + 1))) + 10
        light = float(lm[int(np.clip(py, 0, H - 1)), int(np.clip(px, 0, W - 1))])
        for side in (-1, 1):
            paste_leaf(layer, "blade", px, py, ll * RNG.uniform(0.85, 1.1), ang + side * RNG.uniform(48, 66) + 14, tint(base, light, 0.08))


def backdrop() -> Image.Image:
    lm = light_map()
    yy, xx = np.mgrid[0:H, 0:W].astype(np.float32)
    # --- air: dark forest floor fading up into sunlit haze
    haze = np.array([118, 150, 104], dtype=np.float32)
    deep = np.array([3, 10, 7], dtype=np.float32)
    k = (0.08 + 0.62 * lm) * (0.75 + 0.25 * noise(H, W, 180))
    img = deep[None, None] * (1 - k[..., None]) + haze[None, None] * k[..., None]
    canvas = Image.fromarray(np.uint8(np.clip(img, 0, 255))).convert("RGBA")

    def far_colour(depth):  # atmospheric perspective: distant things take the haze colour
        c = haze * (0.30 + 0.25 * depth) + deep * 0.6
        return tuple(int(v) for v in c) + (255,)

    # --- far trunks, soft and pale
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(11):
        x = RNG.uniform(-20, W + 20); wdt = RNG.uniform(10, 30); lean = RNG.uniform(-40, 40)
        d.polygon([(x, -10), (x + wdt, -10), (x + wdt * 1.25 + lean, H), (x - wdt * 0.25 + lean, H)], fill=far_colour(RNG.uniform(0.3, 1)))
    foliage(layer, lm * 0.5 + 0.25, 70, (0, -20, W, H * 0.5), (14, 26), (70, 100, 62), cluster=9)
    canvas.alpha_composite(blur(layer, 7))

    # --- light shafts through the canopy
    rays = Image.new("L", (W, H), 0)
    dr = ImageDraw.Draw(rays)
    for _ in range(12):
        a = math.radians(RNG.uniform(96, 152)); spread = math.radians(RNG.uniform(1.2, 4.2)); ln = H * 1.3
        p1 = (SUN[0] + ln * math.cos(a - spread), SUN[1] + ln * math.sin(a - spread))
        p2 = (SUN[0] + ln * math.cos(a + spread), SUN[1] + ln * math.sin(a + spread))
        dr.polygon([tuple(SUN), p1, p2], fill=int(RNG.uniform(60, 130)))
    ray = np.asarray(blur(rays, 16), dtype=np.float32) / 255 * (0.6 + 0.4 * noise(H, W, 60)) * np.clip(1.25 - yy / H, 0, 1)
    arr = np.asarray(canvas, dtype=np.float32)
    arr[..., :3] = 255 - (255 - arr[..., :3]) * (1 - ray[..., None] * np.array([0.85, 0.95, 0.62])[None, None])
    canvas = Image.fromarray(np.uint8(np.clip(arr, 0, 255)), "RGBA")

    # --- mid trunks with lianas
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    trunks = [(-30, 70, 30), (W - 70, 84, -34), (W * 0.2, 34, 12)]
    for x, wdt, lean in trunks:
        for i in range(int(wdt)):  # bark: vertical strips with cylinder shading
            t = i / wdt
            sh = 0.35 + 0.9 * math.sin(math.pi * (0.15 + 0.7 * t)) * (0.55 + 0.45 * t)
            c = (int(26 * sh), int(40 * sh), int(24 * sh), 255)
            d.line([(x + i, -10), (x + i + lean, H)], fill=c, width=2)
    for _ in range(9):  # hanging lianas
        x = RNG.uniform(0, W); ln = RNG.uniform(H * 0.25, H * 0.8); sway = RNG.uniform(-80, 80)
        pts = bezier((x, -10), (x + sway * 0.3, ln * 0.3), (x + sway, ln * 0.7), (x + sway * 0.6, ln))
        stroke(layer, pts, RNG.uniform(3, 7), (38, 52, 26, 255), taper=0.5)
    for _ in range(4):  # looping lianas between trees
        xa, xb = RNG.uniform(-40, W * 0.4), RNG.uniform(W * 0.6, W + 40); ya, yb = RNG.uniform(0, H * 0.3), RNG.uniform(0, H * 0.3)
        sag = RNG.uniform(120, 320)
        pts = bezier((xa, ya), (xa + (xb - xa) * 0.3, ya + sag), (xa + (xb - xa) * 0.7, yb + sag), (xb, yb))
        stroke(layer, pts, RNG.uniform(4, 8), (34, 46, 24, 255))
    canvas.alpha_composite(blur(layer, 1.6))

    # --- mid foliage: canopy on top, bushes at the sides, leaving a clearing in the middle
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    foliage(layer, lm, 110, (0, -30, W, H * 0.13), (26, 52), (58, 118, 44), cluster=10)
    foliage(layer, lm, 120, (-30, H * 0.08, W * 0.17, H * 0.95), (28, 60), (50, 110, 42), cluster=10)
    foliage(layer, lm, 120, (W * 0.83, H * 0.08, W + 30, H * 0.95), (28, 60), (50, 110, 42), cluster=10)
    for x, y, ang, ln in ((W * 0.18, H * 0.2, 20, 300), (W * 0.84, H * 0.26, 165, 320), (W * 0.1, H * 0.52, -10, 280), (W * 0.92, H * 0.6, 190, 300)):
        frond(layer, lm, x, y, ang, ln, (56, 122, 46))
    canvas.alpha_composite(blur(layer, 1.1))

    # --- undergrowth: ferns and broad leaves at the bottom
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for x in np.linspace(-20, W + 20, 9):
        for ang in np.linspace(-150, -30, 6):
            frond(layer, lm + 0.12, x + RNG.uniform(-20, 20), H + 10, ang + RNG.uniform(-8, 8), RNG.uniform(170, 300), (44, 104, 40), leaflets=18)
    foliage(layer, lm + 0.1, 30, (0, H * 0.9, W, H), (50, 100), (46, 108, 42), kinds=("broad",), cluster=5)
    canvas.alpha_composite(blur(layer, 0.8))

    # --- near foreground: big out-of-focus leaves (depth of field)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    for x, y, ang, ln, kind in ((-30, 60, 30, 330, "broad"), (W + 30, 30, 150, 360, "broad"), (-40, H * 0.42, -25, 300, "long"),
                                (W + 40, H * 0.5, 205, 320, "long"), (W * 0.1, H + 30, -70, 360, "broad"), (W * 0.9, H + 30, -110, 380, "broad")):
        paste_leaf(layer, kind, x, y, ln, ang, (16, 44, 22))
    canvas.alpha_composite(blur(layer, 9))

    # --- bokeh highlights where light breaks through
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    for _ in range(46):
        x, y = RNG.normal(SUN[0] - 60, W * 0.3), abs(RNG.normal(0, H * 0.2))
        r = RNG.uniform(5, 20)
        d.ellipse([x - r, y - r, x + r, y + r], fill=(215, 240, 170, int(RNG.uniform(14, 44))))
    canvas.alpha_composite(blur(layer, 2.2))

    # --- grade: darken for legible UI, vignette, film grain
    arr = np.asarray(canvas.convert("RGB"), dtype=np.float32) / 255
    arr = arr ** 1.12 * 0.86
    vig = 1 - 0.5 * np.clip(np.hypot((xx - W / 2) / (W * 0.75), (yy - H * 0.38) / (H * 0.75)), 0, 1) ** 2
    arr *= vig[..., None]
    arr += RNG.normal(0, 0.012, arr.shape[:2])[..., None]
    return Image.fromarray(np.uint8(np.clip(arr, 0, 1) * 255))


def vine_strip() -> Image.Image:
    w, h = 150, 1400
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    ys = np.arange(-10, h + 10, 6, dtype=np.float32)
    pts = np.stack([w / 2 + np.sin(ys / 62) * 14 + np.sin(ys / 23) * 3, ys], axis=1)
    stroke(layer, pts, 9, (62, 84, 40, 255), taper=0.55)
    for i in range(8, len(pts) - 4, 7):
        x, y = pts[i]
        side = 1 if (i // 7) % 2 else -1
        light = 0.75 - 0.45 * y / h
        for k in range(RNG.integers(1, 3)):
            paste_leaf(layer, "long" if k else "broad", x, y, RNG.uniform(38, 62), 90 - side * RNG.uniform(48, 80) + k * 18 * side,
                       (60 * (0.6 + light), 128 * (0.6 + light), 46 * (0.6 + light)))
    return layer


def wreath_ring() -> Image.Image:
    s = 720
    layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    c, r = s / 2, s * 0.4
    ang = np.linspace(0, 2 * np.pi, 180)
    stroke(layer, np.stack([c + r * np.cos(ang), c + r * np.sin(ang)], axis=1), 7, (58, 80, 38, 255))
    n = 54
    for i in range(n):
        a = i / n * 2 * math.pi + RNG.normal(0, 0.02)
        x, y = c + r * math.cos(a), c + r * math.sin(a)
        deg = math.degrees(a) + 90 + (38 if i % 2 else 142) + RNG.normal(0, 8)
        light = 0.55 + 0.4 * (0.5 - 0.5 * math.sin(a))  # lit from above
        paste_leaf(layer, "long" if i % 3 else "broad", x, y, RNG.uniform(46, 66), deg, (58 * (0.5 + light), 126 * (0.5 + light), 44 * (0.5 + light)))
    return layer


if __name__ == "__main__":
    backdrop().save("src/assets/jungle.jpg", quality=72, optimize=True, progressive=True)
    vine_strip().resize((75, 700), Image.LANCZOS).save("src/assets/vine.png", optimize=True)
    wreath_ring().resize((480, 480), Image.LANCZOS).save("src/assets/wreath.png", optimize=True)
    import os
    for f in ("jungle.jpg", "vine.png", "wreath.png"):
        print(f, os.path.getsize(f"src/assets/{f}") // 1024, "KB")
