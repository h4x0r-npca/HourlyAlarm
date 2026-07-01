#!/usr/bin/env python3
import math
import struct
from pathlib import Path

from PIL import Image, ImageDraw


ROOT = Path(__file__).resolve().parents[1]
ASSETS_DIR = ROOT / "assets"
ICONSET_DIR = ASSETS_DIR / "HourlyAlarm.iconset"
ICNS_PATH = ASSETS_DIR / "HourlyAlarm.icns"
ICNS_ENTRIES = [
    ("icon_16x16.png", "icp4"),
    ("icon_32x32.png", "icp5"),
    ("icon_32x32@2x.png", "icp6"),
    ("icon_128x128.png", "ic07"),
    ("icon_256x256.png", "ic08"),
    ("icon_512x512.png", "ic09"),
    ("icon_512x512@2x.png", "ic10"),
    ("icon_16x16@2x.png", "ic11"),
    ("icon_32x32@2x.png", "ic12"),
    ("icon_128x128@2x.png", "ic13"),
    ("icon_256x256@2x.png", "ic14"),
]


def make_clock_icon(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    margin = max(8, size // 16)
    stroke = max(4, size // 28)
    center = size // 2
    radius = (size // 2) - margin

    d.ellipse(
        (center - radius, center - radius, center + radius, center + radius),
        fill=(255, 255, 255, 255),
        outline=(24, 24, 24, 255),
        width=stroke,
    )

    for angle, width_ratio in [(0, 0.9), (90, 0.65), (180, 0.9), (270, 0.65)]:
        r1 = size * 0.36
        r2 = size * 0.44
        x1 = center + r1 * math.cos(math.radians(angle))
        y1 = center + r1 * math.sin(math.radians(angle))
        x2 = center + r2 * math.cos(math.radians(angle))
        y2 = center + r2 * math.sin(math.radians(angle))
        d.line((x1, y1, x2, y2), fill=(24, 24, 24, 255), width=max(3, int(stroke * width_ratio)))

    d.line((center, center, center, center - size * 0.18), fill=(24, 24, 24, 255), width=max(6, size // 16))
    d.line((center, center, center + size * 0.21, center), fill=(24, 24, 24, 255), width=max(5, size // 20))
    dot = max(5, size // 28)
    d.ellipse((center - dot, center - dot, center + dot, center + dot), fill=(24, 24, 24, 255))
    return img


def write_icns():
    blocks = []
    for filename, icon_type in ICNS_ENTRIES:
        data = (ICONSET_DIR / filename).read_bytes()
        blocks.append(icon_type.encode("ascii") + struct.pack(">I", len(data) + 8) + data)

    payload = b"".join(blocks)
    ICNS_PATH.write_bytes(b"icns" + struct.pack(">I", len(payload) + 8) + payload)


def main():
    ASSETS_DIR.mkdir(exist_ok=True)
    ICONSET_DIR.mkdir(exist_ok=True)

    base = make_clock_icon(1024)
    sizes = [
        ("icon_16x16.png", 16),
        ("icon_16x16@2x.png", 32),
        ("icon_32x32.png", 32),
        ("icon_32x32@2x.png", 64),
        ("icon_128x128.png", 128),
        ("icon_128x128@2x.png", 256),
        ("icon_256x256.png", 256),
        ("icon_256x256@2x.png", 512),
        ("icon_512x512.png", 512),
        ("icon_512x512@2x.png", 1024),
    ]
    for filename, size in sizes:
        base.resize((size, size), Image.LANCZOS).save(ICONSET_DIR / filename)

    write_icns()
    print(ICNS_PATH)


if __name__ == "__main__":
    main()
