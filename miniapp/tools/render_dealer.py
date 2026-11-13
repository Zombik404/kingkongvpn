"""Renders the blackjack dealer — the app's own jungle king (crowned gorilla, bow tie), facing
the player from behind the table — as a set of transparent WebP frames:

    idle, blink, eat1, eat2 (banana between rounds), happy (dealer wins), sad (player wins)

Run from miniapp/:  python3 tools/render_dealer.py  → src/assets/dealer-*.webp
Uses the capsule/fur renderer from render_gorilla.py. An original design.
"""

import os

import numpy as np
from PIL import Image, ImageDraw

import render_gorilla as g
from render_common import bezier

CROP = (70, 40, 710, 700)  # the bust inside the 780×860 working canvas
OUT_W = 320


def reset() -> None:
    g.canvas[:] = 0


def paste(img: Image.Image, x: int, y: int) -> None:
    layer = Image.new("RGBA", (g.W, g.H), (0, 0, 0, 0))
    layer.paste(img, (x, y), img)
    la = np.asarray(layer, dtype=np.float32)
    g.over(la[..., :3], la[..., 3] / 255)


def bow_tie() -> Image.Image:
    s = 4
    im = Image.new("RGBA", (150 * s, 70 * s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    red, dark, hi = (196, 34, 48, 255), (120, 14, 26, 255), (236, 90, 100, 255)
    d.polygon([(6 * s, 6 * s), (70 * s, 30 * s), (6 * s, 64 * s)], fill=red, outline=dark)
    d.polygon([(144 * s, 6 * s), (80 * s, 30 * s), (144 * s, 64 * s)], fill=red, outline=dark)
    d.polygon([(10 * s, 12 * s), (52 * s, 28 * s), (10 * s, 30 * s)], fill=hi)
    d.polygon([(140 * s, 12 * s), (98 * s, 28 * s), (140 * s, 30 * s)], fill=hi)
    d.rounded_rectangle([60 * s, 16 * s, 90 * s, 54 * s], radius=8 * s, fill=dark)
    return im.resize((150, 70), Image.LANCZOS)


def banana(p0, p1, p2, p3, bitten: bool = False) -> None:
    pts = bezier(p0, p1, p2, p3, n=40)
    kk = np.linspace(0, 1, len(pts))
    rad = 6 + 15 * np.sin(np.pi * kk) ** 0.6
    end = 0.7 if bitten else 1.0
    for i in range(len(pts) - 1):
        if kk[i] > end:
            break
        tip = kk[i] < 0.05 or (not bitten and kk[i] > 0.95)
        col = np.array([96, 68, 28]) if tip else np.array([248, 212, 66]) * (0.9 + 0.1 * np.sin(np.pi * kk[i]))
        if bitten and kk[i] > end - 0.06:
            col = np.array([250, 240, 200])  # the bitten end: pale flesh
        g.capsule(pts[i], pts[i + 1], rad[i], rad[i + 1], col, fur=0.0, fringe=0.0, gloss=0.1)


def frame(kind: str) -> Image.Image:
    reset()
    F, D, S, P = g.FUR_C, g.FUR_DARK, g.SKIN_C, g.PAW_C
    up = kind == "happy"
    # --- body: shoulders, chest, resting arms
    g.capsule((250, 590), (530, 590), 150, 150, F, fur=0.6, fringe=0.035, seed=2)
    g.capsule((390, 560), (390, 800), 170, 170, F, fur=0.6, fringe=0.035, seed=4)
    g.blob(390, 690, 104, 130, g.CHEST_C * 0.9, alpha=0.92, soft=34)
    if not up:
        g.limb([(205, 575), (170, 720), (190, 850)], [78, 66, 58], D, dim=0.9, fur=0.6, seed=6)
    if kind in ("idle", "blink", "sad"):
        g.limb([(575, 575), (610, 720), (590, 850)], [78, 66, 58], D, dim=0.9, fur=0.6, seed=8)
    # --- head
    g.capsule((390, 330), (390, 232), 124, 86, F, fur=0.55, seed=5)
    for ex in (262, 518):
        g.blob(ex, 338, 22, 30, S * 0.95)
        g.blob(ex, 340, 11, 17, S * 0.6)
    g.blob(390, 352, 96, 104, S, alpha=0.97, soft=12)                       # face
    g.capsule((318, 300), (462, 300), 21, 21, S * 0.82, fur=0.1, fringe=0.03)  # brow ridge
    brow = {"sad": 10, "happy": -6}.get(kind, 0)
    for sx, sign in ((346, -1), (434, 1)):                                    # eyebrows
        for x, y in bezier((sx - 26, 292 - sign * brow), (sx - 8, 284), (sx + 8, 284), (sx + 26, 292 + sign * brow), n=20):
            g.blob(x, y, 5, 3.4, D * 0.5, soft=1.5)
    for ex in (346, 434):
        if kind == "blink" or kind == "happy":
            for x, y in bezier((ex - 15, 332), (ex - 6, 326 if kind == "happy" else 338), (ex + 6, 326 if kind == "happy" else 338), (ex + 15, 332), n=18):
                g.blob(x, y, 3, 2.2, (16, 12, 12), soft=1.2)
        else:
            dy = 6 if kind == "sad" else 0
            g.blob(ex, 332, 19, 14, (14, 10, 10))
            g.blob(ex, 332 + dy * 0.4, 11.5, 10, (176, 112, 38))
            g.blob(ex, 332 + dy * 0.4, 5.2, 5.2, (10, 8, 8), soft=1)
            g.blob(ex + 3.5, 328.5 + dy * 0.4, 2.4, 2.4, (255, 250, 240), soft=0.8)
            if kind == "sad":
                g.blob(ex, 322, 17, 6, S * 0.82, soft=2)                      # heavy eyelids
    g.capsule((390, 400), (390, 426), 66, 60, S * 1.1, fur=0.05, fringe=0.02)  # muzzle
    for nx in (369, 411):
        g.blob(nx, 388, 11, 7, (16, 12, 12), soft=1.6)
    if kind == "happy":                                                       # wide grin with teeth
        g.blob(390, 446, 50, 22, (24, 10, 12), soft=2)
        g.blob(390, 438, 42, 9, (245, 240, 228), soft=1.5)
        for tx in range(356, 430, 14):
            g.blob(tx, 438, 0.9, 8, (190, 180, 168), soft=0.8)
    elif kind == "eat2":                                                      # open mouth
        g.blob(390, 448, 26, 20, (24, 10, 12), soft=2)
    elif kind == "sad":
        for x, y in bezier((340, 458), (366, 440), (414, 440), (440, 458), n=30):
            g.blob(x, y, 3.2, 2.4, (18, 12, 12), soft=1.2)
    else:
        for x, y in bezier((338, 440), (366, 458), (414, 458), (442, 440), n=30):
            g.blob(x, y, 3.2, 2.4, (18, 12, 12), soft=1.2)
    # --- crown and bow tie
    cr = g.crown()
    paste(cr, 390 - cr.width // 2, 232 - 86 - cr.height + 62)
    paste(bow_tie(), 390 - 75, 500)
    # --- arms in action
    if kind in ("eat1", "eat2"):
        near = kind == "eat2"
        hand = (470, 452) if near else (520, 500)
        g.limb([(575, 575), (650, 650), (hand[0] + 34, hand[1] + 30)], [78, 62, 46], F, fur=0.6, seed=8)
        tip = (hand[0] - 78, hand[1] - 44) if near else (hand[0] - 70, hand[1] - 110)
        banana((hand[0] + 6, hand[1] + 16), (hand[0] - 20, hand[1] + 6), (tip[0] + 26, tip[1] + 26), tip, bitten=near)
        g.capsule((hand[0] + 34, hand[1] + 30), (hand[0] + 8, hand[1] + 10), 40, 34, P, fur=0.1, fringe=0.02)
        for dx in (-14, 2, 18):
            g.capsule((hand[0] + dx, hand[1] + 26), (hand[0] + dx + 12, hand[1] - 8), 9, 8, P * 1.15, fur=0.05, fringe=0.0)
    if up:                                                                    # both fists in the air
        for sx, sign in ((205, -1), (575, 1)):
            g.limb([(sx, 575), (sx + sign * 96, 470), (sx + sign * 84, 330)], [78, 62, 48], F, fur=0.6, seed=9)
            g.capsule((sx + sign * 84, 330), (sx + sign * 82, 296), 44, 40, P, fur=0.1, fringe=0.02)
    img = Image.fromarray(np.uint8(np.clip(g.canvas, 0, [255, 255, 255, 1]) * [1, 1, 1, 255]), "RGBA")
    return img.crop(CROP)


if __name__ == "__main__":
    sheet = []
    for kind in ("idle", "blink", "eat1", "eat2", "happy", "sad"):
        im = frame(kind)
        out = im.resize((OUT_W, OUT_W * im.height // im.width), Image.LANCZOS)
        out.save(f"src/assets/dealer-{kind}.webp", quality=84, method=6)
        sheet.append(out)
        print(kind, out.size, os.path.getsize(f"src/assets/dealer-{kind}.webp") // 1024, "KB")
    if os.environ.get("PREVIEW"):
        w = sum(s.width for s in sheet)
        prev = Image.new("RGBA", (w, sheet[0].height), (10, 26, 15, 255))
        x = 0
        for s in sheet:
            prev.alpha_composite(s, (x, 0))
            x += s.width
        prev.convert("RGB").save(os.environ["PREVIEW"], quality=88)
