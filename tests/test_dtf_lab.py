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
    assert report["status"] == "manual"
    assert report["transparent"] is False


def test_uniform_subject_is_never_deleted_as_background():
    image = Image.new("RGB", (180, 120), (20, 180, 90))

    output, report = run_pipeline(image, target_long_edge=500)

    assert report["status"] == "manual"
    assert report["background_mode"] == "subject_loss_guard"
    assert np.asarray(output.getchannel("A")).min() == 255


def test_flat_document_preserves_enclosed_white_and_removes_paper():
    image = Image.new("RGB", (320, 200), (225, 226, 229))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((20, 15, 145, 150), radius=12, fill=(25, 25, 28))
    draw.rectangle((55, 45, 95, 110), fill="white")
    draw.text((175, 55), "CONTACT", fill=(20, 20, 20))

    output, report = run_pipeline(image, target_long_edge=640)
    pixels = np.asarray(output)

    assert output.size == (640, 640)
    assert report["background_mode"] == "flat_document_recovery"
    assert pixels[0, 0, 3] == 0
    assert pixels[150, 150, :3].mean() > 235  # enclosed white remains visible


def test_colourful_mascot_is_not_flattened_into_a_silhouette():
    image = Image.new("RGB", (320, 240), "white")
    draw = ImageDraw.Draw(image)
    draw.ellipse((35, 25, 185, 210), fill=(15, 90, 190))
    draw.ellipse((75, 55, 145, 130), fill=(245, 175, 30))
    draw.rectangle((190, 70, 295, 160), fill=(20, 20, 25))

    output, report = run_pipeline(image, target_long_edge=640)
    pixels = np.asarray(output)

    assert report["background_mode"] != "flat_document_recovery"
    blue_pixels = (
        (pixels[..., 2] > pixels[..., 0] + 50)
        & (pixels[..., 2] > pixels[..., 1] + 30)
    )
    yellow_pixels = (
        (pixels[..., 0] > 200)
        & (pixels[..., 1] > 120)
        & (pixels[..., 2] < 80)
    )
    assert blue_pixels.any()
    assert yellow_pixels.any()
