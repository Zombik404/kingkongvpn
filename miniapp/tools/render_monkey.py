"""Renders the swinging monkey (profile view, fur shading, banana in hand) as a transparent PNG.

Run from miniapp/:  python3 tools/render_monkey.py  → src/assets/monkey.png
Every body part is a tapered capsule shaded like a cylinder (light from the upper right) with
streaky fur noise along the limb; parts are composited far → near. The vine hand is at GRIP.
"""

import numpy as np
from PIL import Image, ImageFilter

from render_common import bezier

W, H = 640, 760
GRIP = (300, 60)  # where the hand holds the vine (image px before downscaling)
RNG = np.random.default_rng(5)
YY, XX = np.mgrid[0:H, 0:W].astype(np.float32)
LIGHT = np.array([0.5, -0.62, 0.6], dtype=np.float32)
LIGHT /= np.linalg.norm(LIGHT)

# streaky fur texture: noise smeared along the first axis
_t = RNG.random((512, 256)).astype(np.float32)
FUR = np.asarray(Image.fromarray(np.uint8(_t * 255)).filter(ImageFilter.BoxBlur(0)).resize((256, 512)), dtype=np.float32) / 255
FUR = np.asarray(Image.fromarray(np.uint8(FUR * 255)).resize((256, 40)).resize((256, 512), Image.BICUBIC), dtype=np.float32) / 255
EDGE = RNG.random(4096).astype(np.float32)

FUR_C = np.array([104, 70, 40], dtype=np.float32)
FUR_DARK = np.array([70, 46, 27], dtype=np.float32)
BELLY_C = np.array([186, 146, 98], dtype=np.float32)
SKIN_C = np.array([188, 140, 104], dtype=np.float32)
PAW_C = np.array([62, 44, 34], dtype=np.float32)

canvas = np.zeros((H, W, 4), dtype=np.float32)


def over(rgb: np.ndarray, alpha: np.ndarray):
    a = alpha[..., None]
    canvas[..., :3] = rgb * a + canvas[..., :3] * (1 - a)
    canvas[..., 3:] = a + canvas[..., 3:] * (1 - a)


def capsule(a, b, ra, rb, color, *, fur=0.5, dim=1.0, fringe=0.1, belly=None, gloss=0.0, seed=0):
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
    rim = np.clip(-nx * 0.9 - 0.2, 0, 1) ** 2 * 0.22  # faint cool back light on the left edge
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
    rgb = col * (shade * dim)[..., None] + np.array([70, 90, 80], dtype=np.float32)[None, None, :] * rim[..., None]
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


def render() -> Image.Image:
    # --- far side: the arm that holds the vine, the far leg (darker, in shadow)
    limb([(318, 268), (286, 168), (300, 70)], [27, 21, 15], FUR_DARK, dim=0.72, fur=0.6)
    capsule((300, 74), (300, 52), 15, 13, PAW_C, fur=0.15, dim=0.9, fringe=0.03)   # hand on the vine
    limb([(286, 468), (352, 540), (306, 612)], [31, 24, 16], FUR_DARK, dim=0.7, fur=0.6, seed=7)
    capsule((306, 612), (346, 634), 13, 9, PAW_C, fur=0.15, dim=0.8, fringe=0.03)
    # --- tail: long, curling at the tip
    tail = np.vstack([bezier((268, 468), (196, 510), (168, 628), (232, 676), n=16), bezier((232, 676), (292, 708), (322, 660), (286, 640), n=12)[1:]])
    tr = 13 - 7.5 * np.linspace(0, 1, len(tail))
    for i in range(len(tail) - 1):
        capsule(tail[i], tail[i + 1], tr[i], tr[i + 1], FUR_DARK, fur=0.5, dim=0.95, fringe=0.06, seed=20)
    # --- torso (light belly), near leg
    capsule((326, 286), (292, 452), 58, 53, FUR_C, fur=0.55, belly=BELLY_C, seed=3)
    limb([(302, 462), (386, 506), (350, 592)], [33, 25, 17], FUR_C, fur=0.6, seed=11)
    capsule((350, 592), (392, 614), 14, 10, PAW_C, fur=0.15, dim=0.95, fringe=0.03)
    # --- head: skull, ear, muzzle, face skin
    capsule((366, 230), (366, 230), 49, 49, FUR_C, fur=0.5, seed=5)
    blob(345, 232, 13, 15, SKIN_C * 0.8)                       # ear
    blob(347, 233, 7, 9, SKIN_C * 0.5)
    capsule((398, 250), (414, 256), 25, 21, SKIN_C, fur=0.08, fringe=0.02)   # muzzle
    blob(392, 232, 22, 20, SKIN_C * 0.96, alpha=0.95, soft=6)   # skin around the eye
    blob(388, 212, 26, 8, FUR_DARK * 0.8, alpha=0.9, soft=4)    # brow ridge
    blob(396, 228, 6.5, 5.5, (26, 16, 10))                      # eye
    blob(398, 226, 2, 2, (250, 245, 235), soft=1)               # catch light
    blob(431, 247, 3, 2.4, (60, 34, 24), soft=1.2)              # nostril
    for i, (x, y) in enumerate(bezier((434, 263), (424, 270), (410, 271), (398, 266), n=22)):  # mouth line
        blob(x, y, 2.2, 1.6, (70, 38, 28), alpha=0.9, soft=1.2)
    # --- banana, then the near arm and fingers wrapped around it
    ban = bezier((452, 334), (474, 322), (520, 292), (536, 236), n=40)
    kk = np.linspace(0, 1, len(ban))
    br = 4.5 + 12.5 * np.sin(np.pi * kk) ** 0.6
    for i in range(len(ban) - 1):
        tip = kk[i] < 0.05 or kk[i] > 0.95
        col = np.array([92, 64, 26]) if tip else np.array([246, 210, 64]) * (0.9 + 0.1 * np.sin(np.pi * kk[i]))
        capsule(ban[i], ban[i + 1], br[i], br[i + 1], col, fur=0.0, fringe=0.0, gloss=0.1)
    limb([(340, 292), (416, 366), (462, 322)], [28, 22, 16], FUR_C, fur=0.6, seed=15)
    capsule((462, 322), (470, 312), 15, 13, PAW_C, fur=0.15, fringe=0.03)
    for dx in (-7, 3, 13):  # fingers over the banana
        capsule((464 + dx, 328), (472 + dx, 306), 4.5, 4, PAW_C, fur=0.1, fringe=0.0, dim=1.1)
    img = Image.fromarray(np.uint8(np.clip(canvas, 0, [255, 255, 255, 1]) * [1, 1, 1, 255]), "RGBA")
    return img


if __name__ == "__main__":
    out = render().resize((W // 2, H // 2), Image.LANCZOS)
    out.save("src/assets/monkey.png", optimize=True)
    import os
    print("monkey.png", os.path.getsize("src/assets/monkey.png") // 1024, "KB", out.size)
    bg = Image.open("src/assets/jungle.jpg").convert("RGBA").crop((150, 500, 150 + W, 500 + H))
    big = render()
    bg.alpha_composite(big)
    bg.convert("RGB").save("/tmp/claude-0/-home-claude/2b2a5de2-dea3-534f-9e0c-71b51034fee2/scratchpad/miniapp-e2e/vh/monkey-preview.jpg", quality=88)
