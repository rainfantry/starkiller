"""
Generate DayBoard launcher icon PNGs for all mipmap densities.
Requires Pillow: pip install pillow
"""

import os
import math

try:
    from PIL import Image, ImageDraw
except ImportError:
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "pip", "install", "pillow"], check=True)
    from PIL import Image, ImageDraw

SIZES = {
    "mipmap-mdpi":    48,
    "mipmap-hdpi":    72,
    "mipmap-xhdpi":   96,
    "mipmap-xxhdpi":  144,
    "mipmap-xxxhdpi": 192,
}

RES = "client/app/src/main/res"

BG      = (21, 101, 192)       # #1565C0
CYAN    = (0, 229, 255)        # #00E5FF
PURPLE  = (124, 77, 255)       # #7C4DFF
GREEN   = (0, 200, 83)         # #00C853
LIGHT   = (227, 242, 253)      # #E3F2FD
WHITE   = (255, 255, 255)
DARK    = (13, 71, 161)        # #0D47A1


def round_rect(draw, xy, radius, fill):
    x0, y0, x1, y1 = xy
    r = radius
    draw.rectangle([x0 + r, y0, x1 - r, y1], fill=fill)
    draw.rectangle([x0, y0 + r, x1, y1 - r], fill=fill)
    draw.ellipse([x0, y0, x0 + 2*r, y0 + 2*r], fill=fill)
    draw.ellipse([x1 - 2*r, y0, x1, y0 + 2*r], fill=fill)
    draw.ellipse([x0, y1 - 2*r, x0 + 2*r, y1], fill=fill)
    draw.ellipse([x1 - 2*r, y1 - 2*r, x1, y1], fill=fill)


def make_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # Background circle
    round_rect(draw, (0, 0, size, size), size // 6, BG)

    pad  = size // 8
    gap  = size // 16
    half = (size - 2 * pad - gap) // 2

    # Tile positions
    tl = (pad, pad, pad + half, pad + half)
    tr = (pad + half + gap, pad, size - pad, pad + half)
    bl = (pad, pad + half + gap, pad + half, size - pad)
    br = (pad + half + gap, pad + half + gap, size - pad, size - pad)

    r = size // 20

    # Top-left: cyan with mini bar chart
    round_rect(draw, tl, r, CYAN)
    bx, by = tl[0] + size//32, tl[3] - size//24
    bw = size // 32
    bars = [size//14, size//10, size//12, size//8]
    for i, h in enumerate(bars):
        x = bx + i * (bw + size // 48)
        draw.rectangle([x, by - h, x + bw, by], fill=DARK)

    # Top-right: purple with checkmark
    round_rect(draw, tr, r, PURPLE)
    cx = (tr[0] + tr[2]) // 2
    cy = (tr[1] + tr[3]) // 2
    ck = size // 14
    pts = [
        (cx - ck, cy),
        (cx - ck // 3, cy + ck * 2 // 3),
        (cx + ck, cy - ck * 2 // 3),
    ]
    draw.line(pts, fill=WHITE, width=max(2, size // 24))

    # Bottom-left: light blue with calendar dots
    round_rect(draw, bl, r, LIGHT)
    dot_r = max(2, size // 40)
    rows, cols = 2, 3
    dx = (bl[2] - bl[0] - 2 * dot_r * cols) // (cols + 1)
    dy = (bl[3] - bl[1] - 2 * dot_r * rows) // (rows + 1)
    for row in range(rows):
        for col in range(cols):
            x = bl[0] + dx + col * (2 * dot_r + dx) + dot_r
            y = bl[1] + dy + row * (2 * dot_r + dy) + dot_r
            c = CYAN if (row + col) % 2 == 0 else DARK
            draw.ellipse([x - dot_r, y - dot_r, x + dot_r, y + dot_r], fill=c)

    # Bottom-right: green with ring
    round_rect(draw, br, r, GREEN)
    cr_x = (br[0] + br[2]) // 2
    cr_y = (br[1] + br[3]) // 2
    ring_r = half // 3
    ring_w = max(2, size // 32)
    draw.ellipse(
        [cr_x - ring_r, cr_y - ring_r, cr_x + ring_r, cr_y + ring_r],
        outline=WHITE, width=ring_w,
    )
    # Arc fill (270 deg sweep from top)
    draw.arc(
        [cr_x - ring_r, cr_y - ring_r, cr_x + ring_r, cr_y + ring_r],
        start=-90, end=180, fill=DARK, width=ring_w,
    )

    return img


base = os.path.dirname(os.path.abspath(__file__))

for folder, size in SIZES.items():
    out_dir = os.path.join(base, RES, folder)
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "ic_launcher.png")
    icon = make_icon(size)
    icon.save(path)
    print(f"[+] {folder}/ic_launcher.png ({size}x{size})")

print("[+] Done.")
