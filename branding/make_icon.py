"""Draws the Stembase mark (logo T1e: a straight line, a gap, then black, blue and orange bars) as SVG files and as the
1024 px app icon. Run:  python branding/make_icon.py   then   cd ui && npx tauri icon ../branding/icon-1024.png"""
import os
from PIL import Image, ImageDraw

HERE = os.path.dirname(os.path.abspath(__file__))
BLACK, BLUE, ORANGE, CREAM, WHITE = "#111111", "#2563EB", "#EA580C", "#FAF7F0", "#F4F4F5"
# The mark on an 80 x 64 grid: (x1, y1, x2, y2, colour role). Stroke 5, round ends.
LINES = [(4, 32, 28, 32, "ink"),
         (38, 22, 38, 42, "ink"), (46, 14, 46, 50, "ink"),
         (54, 18, 54, 46, "blue"), (62, 26, 62, 38, "blue"),
         (70, 20, 70, 44, "orange"), (78, 28, 78, 36, "orange")]
STROKE = 5


def svg(ink):
    col = {"ink": ink, "blue": BLUE, "orange": ORANGE}
    paths = "".join(f'<path d="M{a} {b}L{c} {d}" stroke="{col[r]}"/>' for a, b, c, d, r in LINES)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 82 64" fill="none" stroke-width="{STROKE}" '
            f'stroke-linecap="round">{paths}</svg>\n')


def icon(size=1024):
    """Cream rounded tile with the mark centred: stays visible on dark taskbars, docks and panels."""
    S = 4   # draw large, then shrink for smooth edges
    W = size * S
    img = Image.new("RGBA", (W, W), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(W * 0.04)
    d.rounded_rectangle([pad, pad, W - pad, W - pad], radius=int(W * 0.22), fill=CREAM)
    # The mark with its round ends spans x 1.5..80.5 and y 11.5..52.5 (79 x 41 units): centre that box.
    k = (W * 0.70) / 79
    ox = (W - 79 * k) / 2 - 1.5 * k
    oy = (W - 41 * k) / 2 - 11.5 * k
    col = {"ink": BLACK, "blue": BLUE, "orange": ORANGE}
    sw = 6.2 * k                    # a little bolder than the logo so it still reads at 16 px
    r = sw / 2
    for a, b, c, e, role in LINES:
        p = [(ox + a * k, oy + b * k), (ox + c * k, oy + e * k)]
        d.line(p, fill=col[role], width=int(sw))
        for x, y in p: d.ellipse([x - r, y - r, x + r, y + r], fill=col[role])
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    open(os.path.join(HERE, "stembase-mark.svg"), "w").write(svg(BLACK))        # for light backgrounds
    open(os.path.join(HERE, "stembase-mark-dark.svg"), "w").write(svg(WHITE))   # for dark backgrounds (the app)
    icon().save(os.path.join(HERE, "icon-1024.png"))
    print("wrote stembase-mark.svg, stembase-mark-dark.svg, icon-1024.png")
