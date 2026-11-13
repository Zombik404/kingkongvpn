"""Generates the decorative jungle artwork (static SVG assets) for the Mini App.

Run from miniapp/:  python3 tools/jungle.py   → src/assets/jungle.svg, src/assets/sprig.svg
The drawing is deterministic (fixed seed), so rebuilding gives the same files.
"""

import math
import random

random.seed(7)
BACK, MID, FRONT, RIB, TRUNK = "#06170c", "#0b2815", "#113a1f", "#1b5a30", "#0a1d10"


def leaf(x, y, ang, length, width, fill, rib=RIB, veins=4):
    p = (f"M0,0 C{length * .25:.1f},{-width:.1f} {length * .7:.1f},{-width * .9:.1f} {length:.1f},0 "
         f"C{length * .7:.1f},{width * .9:.1f} {length * .25:.1f},{width:.1f} 0,0Z")
    v = "".join(
        f"M{length * t:.1f},0 L{length * (t + .12):.1f},{-width * .55 * (1 - t):.1f} "
        f"M{length * t:.1f},0 L{length * (t + .12):.1f},{width * .55 * (1 - t):.1f} "
        for t in [0.2 + i * 0.55 / max(1, veins - 1) for i in range(veins)])
    return (f'<g transform="translate({x:.1f},{y:.1f}) rotate({ang:.1f})"><path d="{p}" fill="{fill}"/>'
            f'<path d="M0,0 L{length * .95:.1f},0 {v}" stroke="{rib}" stroke-width="1" fill="none"/></g>')


def frond(x, y, ang, length, fill, droop=0.35, leaflets=13, lw=3.0):
    """A feather palm frond: a drooping rachis with leaflets on both sides (drawn as strokes)."""
    out = [f'<g transform="translate({x:.1f},{y:.1f}) rotate({ang:.1f})" stroke="{fill}" stroke-linecap="round" fill="none">']
    cx, cy = length * 0.55, -length * droop * 0.2
    ex, ey = length, length * droop
    out.append(f'<path d="M0,0 Q{cx:.1f},{cy:.1f} {ex:.1f},{ey:.1f}" stroke-width="3"/>')
    d = []
    for i in range(1, leaflets + 1):
        t = i / (leaflets + 1)
        px = 2 * (1 - t) * t * cx + t * t * ex
        py = 2 * (1 - t) * t * cy + t * t * ey
        tx = 2 * (1 - t) * cx + 2 * t * (ex - cx)
        ty = 2 * (1 - t) * cy + 2 * t * (ey - cy)
        a = math.atan2(ty, tx)
        ll = length * 0.34 * math.sin(math.pi * (0.15 + 0.85 * t)) + 6
        for side in (-1, 1):
            b = a + side * math.radians(62)
            d.append(f"M{px:.1f},{py:.1f} L{px + ll * math.cos(b):.1f},{py + ll * math.sin(b) + ll * 0.25:.1f}")
    out.append(f'<path d="{" ".join(d)}" stroke-width="{lw}"/></g>')
    return "".join(out)


def palm(x, base_y, height, lean, fill, crown=9, frond_len=120):
    top_x, top_y = x + lean, base_y - height
    mx = x + lean * 0.2
    out = [f'<path d="M{x},{base_y} Q{mx:.1f},{base_y - height * .55:.1f} {top_x:.1f},{top_y:.1f}" stroke="{TRUNK}" stroke-width="15" fill="none" stroke-linecap="round"/>',
           f'<path d="M{x},{base_y} Q{mx:.1f},{base_y - height * .55:.1f} {top_x:.1f},{top_y:.1f}" stroke="{fill}" stroke-width="15" fill="none" stroke-dasharray="2 12" opacity=".7"/>']
    for i in range(crown):
        ang = -200 + i * (220 / (crown - 1)) + random.uniform(-6, 6)
        out.append(frond(top_x, top_y, ang, frond_len * random.uniform(0.85, 1.1), fill, droop=0.3 + 0.25 * abs(math.cos(math.radians(ang)))))
    out.append(f'<circle cx="{top_x:.1f}" cy="{top_y + 4:.1f}" r="7" fill="{TRUNK}"/><circle cx="{top_x - 9:.1f}" cy="{top_y + 9:.1f}" r="6" fill="{TRUNK}"/>')
    return "".join(out)


def monstera(x, y, ang, size, fill, rib=RIB):
    """Split-leaf shape in polar form: a heart with notches cut in from the edge."""
    pts = []
    for i in range(0, 361, 4):
        th = math.radians(i)
        heart = 1 - 0.28 * math.cos(th) + 0.1 * math.cos(2 * th)
        notch = max(0.0, math.sin(th * 4.5)) ** 3 * 0.62 if 30 < i < 330 else 0
        r = size * heart * (1 - notch)
        pts.append(f"{r * math.cos(th):.1f},{r * math.sin(th):.1f}")
    veins = "".join(f"M{-size * .1:.1f},0 L{size * .8 * math.cos(math.radians(a)):.1f},{size * .8 * math.sin(math.radians(a)):.1f} " for a in (-140, -100, -60, 60, 100, 140))
    return (f'<g transform="translate({x:.1f},{y:.1f}) rotate({ang:.1f})"><polygon points="{" ".join(pts)}" fill="{fill}"/>'
            f'<path d="M{size * 1.1:.1f},0 L{-size * .9:.1f},0 {veins}" stroke="{rib}" stroke-width="1.2" fill="none"/></g>')


def vine(x, length, color, leaves_fill, amp=9, period=42):
    pts = " ".join(f"{x + math.sin(y / period) * amp:.1f},{y}" for y in range(-10, length, 8))
    out = [f'<polyline points="{pts}" stroke="{color}" stroke-width="3" fill="none" stroke-linecap="round"/>']
    for i, y in enumerate(range(26, length - 8, 34)):
        px = x + math.sin(y / period) * amp
        out.append(leaf(px, y, 30 if i % 2 else 150, 24, 8, leaves_fill, veins=2))
    return "".join(out)


def fern(x, y, n, spread, length, fill):
    return "".join(leaf(x, y, -90 - spread / 2 + i * spread / (n - 1), length * random.uniform(0.8, 1.15), length * 0.13, fill, veins=3) for i in range(n))


def backdrop():
    w, hgt = 400, 900
    p = []
    # far layer: tall palms
    p.append(palm(40, 930, 620, 60, BACK, frond_len=150))
    p.append(palm(372, 940, 720, -70, BACK, frond_len=160))
    p.append(palm(215, 950, 480, 25, BACK, crown=8, frond_len=120))
    # hanging vines from the canopy
    for vx, vl in ((28, 330), (88, 210), (150, 120), (252, 150), (318, 260), (376, 360)):
        p.append(vine(vx, vl, "#0e3019", MID))
    # canopy: big leaves coming in from the top corners
    p.append(monstera(18, 26, 35, 62, MID))
    p.append(monstera(388, 20, 150, 66, FRONT))
    p.append(monstera(110, -14, 80, 44, FRONT))
    p.append(monstera(300, -10, 100, 46, MID))
    p.append(frond(-10, 120, 20, 190, FRONT))
    p.append(frond(410, 150, 160, 180, MID))
    # mid layer
    p.append(palm(-6, 760, 330, 70, MID, crown=8, frond_len=130))
    p.append(palm(408, 800, 300, -66, MID, crown=8, frond_len=125))
    p.append(monstera(22, 470, -20, 58, MID))
    p.append(monstera(386, 520, 200, 60, FRONT))
    # undergrowth at the bottom
    for fx in (10, 90, 180, 270, 350, 410):
        p.append(fern(fx, 915, 7, 130, random.uniform(90, 140), random.choice([MID, FRONT])))
    p.append(monstera(60, 880, -70, 54, FRONT))
    p.append(monstera(340, 885, -110, 58, MID))
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {hgt}" preserveAspectRatio="xMidYMin slice">{"".join(p)}</svg>'


def sprig():
    p = ['<path d="M4,30 Q30,24 70,6" stroke="#1b5a30" stroke-width="2.5" fill="none" stroke-linecap="round"/>']
    for x, y, a, ln in ((14, 28, -70, 20), (26, 25, 40, 18), (38, 21, -75, 22), (50, 16, 35, 18), (62, 10, -60, 18), (70, 6, -15, 20)):
        p.append(leaf(x, y, a, ln, ln * 0.3, "#1f6b38", rib="#0c2a16", veins=2))
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 92 44">{"".join(p)}</svg>'


if __name__ == "__main__":
    for name, svg in (("jungle", backdrop()), ("sprig", sprig())):
        with open(f"src/assets/{name}.svg", "w") as f:
            f.write(svg)
        print(name, len(svg) // 1024, "KB")
