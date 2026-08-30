"""Generate static/favicon.ico without external dependencies.

Draws a white "KB" monogram (5x7 bitmap font, scaled per size) on a black
rounded square at 16/32/48px, encodes each as an RGBA PNG by hand, and wraps
them in an ICO container.
"""
from pathlib import Path
import struct
import zlib

BACKGROUND = (0x00, 0x00, 0x00, 255)
WHITE = (0xFF, 0xFF, 0xFF, 255)
TRANSPARENT = (0, 0, 0, 0)

SIZES = [16, 32, 48]

# Normalized (0..1) background geometry: rounded square.
BG = (0.03, 0.03, 0.97, 0.97, 0.28)

# 5x7 bitmap font glyphs.
GLYPH_K = [
    "#...#",
    "#..#.",
    "#.#..",
    "##...",
    "#.#..",
    "#..#.",
    "#...#",
]
GLYPH_B = [
    "###..",
    "#..#.",
    "#..#.",
    "###..",
    "#..#.",
    "#..#.",
    "###..",
]
LETTERS = [GLYPH_K, GLYPH_B]
GAP = 1  # columns between letters


def inside_round_rect(px, py, x0, y0, x1, y1, r):
    if px < x0 or px > x1 or py < y0 or py > y1:
        return False
    cx = min(max(px, x0 + r), x1 - r)
    cy = min(max(py, y0 + r), y1 - r)
    return (px - cx) ** 2 + (py - cy) ** 2 <= r * r


def pixel_color(n, px, py):
    """Return RGBA for pixel (px, py) in an n x n image."""
    x, y = (px + 0.5) / n, (py + 0.5) / n
    if not inside_round_rect(x, y, *BG):
        return TRANSPARENT
    color = BACKGROUND
    # "KB" monogram: 11 columns x 7 rows of glyph cells, scaled per size.
    scale = max(1, n // 12)
    glyph_w = 5
    block_w = (glyph_w * 2 + GAP) * scale
    block_h = 7 * scale
    x0 = (n - block_w) // 2
    y0 = (n - block_h) // 2
    for li, glyph in enumerate(LETTERS):
        cell_x0 = x0 + li * (glyph_w + GAP) * scale
        for gy, row in enumerate(glyph):
            for gx, ch in enumerate(row):
                if ch != "#":
                    continue
                if (
                    cell_x0 + gx * scale <= px < cell_x0 + (gx + 1) * scale
                    and y0 + gy * scale <= py < y0 + (gy + 1) * scale
                ):
                    color = WHITE
    return color


def write_png(size):
    """Encode the icon at `size` as an RGBA PNG (no external deps)."""
    rows = []
    for py in range(size):
        row = b""
        for px in range(size):
            row += bytes(pixel_color(size, px, py))
        rows.append(row)

    def chunk(typ, data):
        c = struct.pack(">I", len(data)) + typ + data
        return c + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)  # filter 0 per scanline
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", ihdr)
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def build_ico():
    """Wrap PNGs of each size in an ICO container."""
    pngs = {s: write_png(s) for s in SIZES}
    header = struct.pack("<HHH", 0, 1, len(SIZES))
    entries = b""
    offset = 6 + 16 * len(SIZES)
    for s in SIZES:
        data = pngs[s]
        entries += struct.pack(
            "<BBBBHHII", s & 0xFF, s & 0xFF, 0, 0, 1, 32, len(data), offset
        )
        offset += len(data)
    return header + entries + b"".join(pngs[s] for s in SIZES)


if __name__ == "__main__":
    out = Path(__file__).resolve().parent / "static" / "favicon.ico"
    out.write_bytes(build_ico())
    print(f"wrote {out} ({out.stat().st_size} bytes)")
