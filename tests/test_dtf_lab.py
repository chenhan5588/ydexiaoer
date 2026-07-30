import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parents[1] / "backend"))

from modules.dtf_lab import run_pipeline


def test_flat_background_becomes_transparent_and_keeps_colour():
    image = Image.new("RGB", (240, 160), "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 35, 200, 125), fill=(15, 190, 95))

    output, report = run_pipeline(image, target_long_edge=600)
    pixels = np.array(output)

    assert output.size == (600, 400)
    assert report["transparent"] is True
    assert pixels[0, 0, 3] == 0
    center = pixels[200, 300]
    assert center[1] > 170 and center[0] < 40


def test_complex_border_is_not_destructively_removed():
    y, x = np.mgrid[:120, :180]
    rgb = np.dstack(((x * 2) % 255, (y * 2) % 255, ((x + y) * 2) % 255)).astype(np.uint8)
    image = Image.fromarray(rgb)

    output, report = run_pipeline(image, target_long_edge=500)

    assert output.size == (500, 333)
    assert report["background_mode"] == "complex_review"
    assert report["status"] == "review"
    assert report["transparent"] is False
