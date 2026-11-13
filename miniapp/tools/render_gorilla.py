"""Renders the app's own jungle king — a big gorilla in a gold crown, swinging on a liana with a
banana in hand — as a transparent PNG (profile view, fur shading). An original design.

Run from miniapp/:  python3 tools/render_gorilla.py  → src/assets/gorilla.png
Every body part is a tapered capsule shaded like a cylinder (light from the upper right) with
streaky fur noise along the limb; parts are composited far → near. The vine hand is at GRIP.
"""

import numpy as np
from PIL import Image, ImageFilter

from render_common import bezier

W, H = 780, 860
GRIP = (360, 62)  # where the hand holds the vine (image px before downscaling)
RNG = np.random.default_rng(5)
YY, XX = np.mgrid[0:H, 0:W].astype(np.float32)
LIGHT = np.array([0.5, -0.62, 0.6], dtype=np.float32)
LIGHT /= np.linalg.norm(LIGHT)

# streaky fur texture: noise smeared along the first axis
_t = RNG.random((512, 256)).astype(np.float32)
FUR = np.asarray(Image.fromarray(np.uint8(_t * 255)).filter(ImageFilter.BoxBlur(0)).resize((256, 512)), dtype=np.float32) / 255
FUR = np.asarray(Image.fromarray(np.uint8(FUR * 255)).resize((256, 40)).resize((256, 512), Image.BICUBIC), dtype=np.float32) / 255
EDGE = RNG.random(4096).astype(np.float32)

FUR_C = np.array([70, 70, 80], dtype=np.float32)       # black-blue fur (reads dark once shaded)
FUR_DARK = np.array([50, 50, 58], dtype=np.float32)
CHEST_C = np.array([88, 84, 88], dtype=np.float32)     # bare leathery chest
SILVER_C = np.array([176, 178, 186], dtype=np.float32)  # silverback saddle
SKIN_C = np.array([66, 62, 66], dtype=np.float32)      # face, hands, feet
PAW_C = np.array([52, 48, 52], dtype=np.float32)

canvas = np.zeros((H, W, 4), dtype=np.float32)


def over(rgb: np.ndarray, alpha: np.ndarray):
    a = alpha[..., None]
    canvas[..., :3] = rgb * a + canvas[..., :3] * (1 - a)
    canvas[..., 3:] = a + canvas[..., 3:] * (1 - a)


def capsule(a, b, ra, rb, color, *, fur=0.5, dim=1.0, fringe=0.08, belly=None, back=None, gloss=0.0, seed=0):
    """A tapered capsule from a to b. Returns (alpha, t, v) so callers can add details."""
    a = np.asarray(a, dtype=np.float32); b = np.asarray(b, dtype=np.float32)
    ab = b - a
    ln2 = max(float(ab @ ab), 1e-3)
    ln = ln2 ** 0.5
    t = np.clip(((XX - a[0]) * ab[0] + (YY - a[1]) * ab[1]) / ln2, 0, 1)
    cx, cy = a[0] + t * ab[0], a[1] + t * ab[1]
    dx, dy = XX - cx, YY - cy
    d = np.hypot(dx, dy)
    r = ra + t * (rb - ra)
    u = t * ln
    ang = np.arctan2(dy, dx)
    e = EDGE[(np.int32(u * 1.3 + ang * 23) + seed * 131) % 4096]
    r_eff = r * (1 + fringe * (e - 0.5) * 2)
    alpha = np.clip((r_eff - d) / 1.6, 0, 1)
    if not alpha.any():
        return alpha, t, d / np.maximum(r, 1)
    nx, ny = dx / np.maximum(r, 1), dy / np.maximum(r, 1)
    nz = np.sqrt(np.clip(1 - nx * nx - ny * ny, 0, 1))
    lam = np.clip(nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2], 0, 1)
    shade = 0.34 + 0.86 * lam
    rim = np.clip(-nx * 0.9 - 0.15, 0, 1) ** 2 * 0.4  # green back light from the forest, left edge
    if ln > 1:  # fur streaks follow the limb; on a sphere they radiate
        across = (dx * ab[1] - dy * ab[0]) / ln
        fu = FUR[np.int32(u * 1.1 + seed * 37) % 512, np.int32(across * 2.2 + 300) % 256]
    else:
        fu = FUR[np.int32(d * 2.0 + seed * 37) % 512, np.int32(ang * 40 + 300) % 256]
    shade = shade * (1 - fur * 0.5 + fur * fu)
    col = np.asarray(color, dtype=np.float32)[None, None, :] * np.ones((H, W, 1), dtype=np.float32)
    if belly is not None:  # lighter fur where the surface faces the front (+x) and down
        k = np.clip((nx * 0.9 + ny * 0.25 - 0.1) * 1.6, 0, 1)[..., None]
        col = col * (1 - k) + belly[None, None, :] * k
    if back is not None:  # silver saddle: the lower back, facing away from the front
        k = (np.clip((-nx * 0.9 - 0.05) * 1.8, 0, 1) * np.clip((t - 0.3) * 2.6, 0, 1))[..., None]
        col = col * (1 - k) + back[None, None, :] * k
    rgb = col * (shade * dim)[..., None] + np.array([120, 170, 120], dtype=np.float32)[None, None, :] * rim[..., None]
    if gloss:
        rgb += 255 * gloss * (lam[..., None] ** 14)
    over(np.clip(rgb, 0, 255), alpha)
    return alpha, t, d / np.maximum(r, 1)


def limb(points, radii, color, **kw):
    for i in range(len(points) - 1):
        capsule(points[i], points[i + 1], radii[i], radii[i + 1], color, seed=i + kw.pop("seed", 0), **kw)


def blob(cx, cy, rx, ry, color, alpha=1.0, soft=2.0):
    d = np.hypot((XX - cx) / rx, (YY - cy) / ry)
    a = np.clip((1 - d) * min(rx, ry) / soft, 0, 1) * alpha
    over(np.asarray(color, dtype=np.float32)[None, None, :] * np.ones((H, W, 1), dtype=np.float32), a)


def crown() -> Image.Image:
    """Gold crown drawn flat (supersampled), then tilted onto the head."""
    from PIL import ImageDraw
    s = 4
    w, h = 190 * s, 130 * s
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    gold, hi, sh = (236, 186, 52, 255), (255, 236, 150, 255), (150, 104, 24, 255)
    base_y, top = 104 * s, 30 * s
    pts = [(14 * s, base_y)]
    xs = np.linspace(14 * s, 176 * s, 11)
    for i, x in enumerate(xs):
        pts.append((x, (top if i % 2 else top + 44 * s) if 0 < i < 10 else top + 18 * s))
    pts += [(176 * s, base_y)]
    d.polygon(pts, fill=gold)
    d.polygon([pts[0], pts[1], (pts[1][0] + 26 * s, base_y)], fill=sh)                    # shaded left side
    for i in range(1, 10, 2):                                                             # balls on the points
        x, y = xs[i], top
        d.ellipse([x - 9 * s, y - 14 * s, x + 9 * s, y + 4 * s], fill=hi, outline=sh, width=s)
        d.line([(x, y + 6 * s), (x - 3 * s, base_y - 26 * s)], fill=hi, width=2 * s)      # facet highlight
    d.rectangle([14 * s, base_y - 24 * s, 176 * s, base_y], fill=gold, outline=sh, width=s)
    d.rectangle([14 * s, base_y - 24 * s, 176 * s, base_y - 19 * s], fill=hi)
    d.rectangle([14 * s, base_y - 5 * s, 176 * s, base_y], fill=sh)
    for i, col in enumerate([(214, 40, 56), (40, 170, 96), (214, 40, 56), (60, 120, 220), (214, 40, 56)]):  # gems
        x = (36 + i * 30) * s
        d.ellipse([x - 8 * s, base_y - 20 * s, x + 8 * s, base_y - 6 * s], fill=col + (255,), outline=sh, width=s)
        d.ellipse([x - 4 * s, base_y - 18 * s, x, base_y - 14 * s], fill=(255, 255, 255, 190))
    return im.resize((190, 130), Image.LANCZOS)


def render() -> Image.Image:
    # --- far side (in shadow): the arm on the liana and the far leg
    limb([(396, 304), (346, 188), (360, 78)], [50, 42, 31], FUR_DARK, dim=0.74, fur=0.6)
    capsule((360, 86), (360, 56), 30, 25, PAW_C, fur=0.1, dim=0.9, fringe=0.02)      # hand on the liana
    limb([(338, 582), (432, 672), (382, 760)], [54, 42, 30], FUR_DARK, dim=0.7, fur=0.6, seed=7)
    capsule((382, 760), (436, 786), 24, 16, PAW_C, fur=0.1, dim=0.8, fringe=0.02)
    # --- torso: huge chest, silver saddle on the back, bare chest in front
    capsule((402, 332), (352, 560), 108, 88, FUR_C, fur=0.6, belly=CHEST_C, back=SILVER_C, seed=3)
    # --- near leg (short and thick)
    limb([(362, 578), (470, 642), (432, 742)], [58, 45, 32], FUR_C, fur=0.6, seed=11)
    capsule((432, 742), (490, 770), 25, 17, PAW_C, fur=0.1, dim=0.95, fringe=0.02)
    # --- head: cone-shaped skull with a crest, heavy brow, broad muzzle
    capsule((482, 262), (462, 186), 74, 50, FUR_C, fur=0.55, seed=5)
    blob(436, 276, 12, 16, SKIN_C * 0.9)                                   # ear
    capsule((526, 318), (544, 324), 46, 38, SKIN_C, fur=0.05, fringe=0.02)   # jaw
    capsule((530, 284), (558, 290), 44, 34, SKIN_C * 1.1, fur=0.05, fringe=0.02)  # muzzle
    capsule((496, 242), (566, 250), 17, 13, SKIN_C * 0.85, fur=0.1, fringe=0.03)  # brow ridge
    blob(538, 266, 10, 8, (14, 10, 10))                                    # eye socket
    blob(539, 266, 5.6, 5, (158, 100, 36))                                 # amber iris
    blob(540, 266, 2.6, 2.6, (10, 8, 8), soft=1)
    blob(541.8, 264.2, 1.5, 1.5, (255, 250, 240), soft=0.8)                # catch light
    blob(584, 286, 8, 6, (16, 12, 12), soft=1.5)                           # nostril
    for x, y in bezier((594, 318), (572, 332), (546, 336), (518, 326), n=36):   # mouth line
        blob(x, y, 2.8, 2.0, (18, 12, 12), alpha=0.95, soft=1.2)
    # --- crown, sitting on the crest and tilted with the head
    cr = crown().resize((166, 114), Image.LANCZOS).rotate(12, resample=Image.BICUBIC, expand=True)
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    layer.paste(cr, (462 - cr.width // 2 + 4, 158 - cr.height + 40), cr)
    la = np.asarray(layer, dtype=np.float32)
    over(la[..., :3], la[..., 3] / 255)
    # --- banana, then the near arm and the fingers around it
    ban = bezier((598, 420), (634, 400), (696, 352), (712, 276), n=44)
    kk = np.linspace(0, 1, len(ban))
    br = 6 + 16 * np.sin(np.pi * kk) ** 0.6
    for i in range(len(ban) - 1):
        tip = kk[i] < 0.05 or kk[i] > 0.95
        col = np.array([96, 68, 28]) if tip else np.array([248, 212, 66]) * (0.9 + 0.1 * np.sin(np.pi * kk[i]))
        capsule(ban[i], ban[i + 1], br[i], br[i + 1], col, fur=0.0, fringe=0.0, gloss=0.1)
    limb([(408, 372), (540, 474), (616, 396)], [54, 44, 33], FUR_C, fur=0.6, seed=15)
    capsule((616, 396), (630, 380), 30, 26, PAW_C, fur=0.1, fringe=0.02)
    for dx in (-12, 2, 16):
        capsule((618 + dx, 414), (632 + dx, 378), 7.5, 6.5, PAW_C * 1.15, fur=0.05, fringe=0.0)
    return Image.fromarray(np.uint8(np.clip(canvas, 0, [255, 255, 255, 1]) * [1, 1, 1, 255]), "RGBA")


if __name__ == "__main__":
    import os
    big = render()
    out = big.resize((W // 2, H // 2), Image.LANCZOS)
    out.save("src/assets/gorilla.png", optimize=True)
    print("gorilla.png", os.path.getsize("src/assets/gorilla.png") // 1024, "KB", out.size)
    if os.environ.get("PREVIEW"):
        bg = Image.open("src/assets/jungle.jpg").convert("RGBA").resize((1080, 2340)).crop((150, 500, 150 + W, 500 + H))
        bg.alpha_composite(big)
        bg.convert("RGB").save(os.environ["PREVIEW"], quality=88)
