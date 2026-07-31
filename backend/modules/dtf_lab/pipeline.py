"""Conservative DTF production-PNG pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import shutil
import subprocess
import tempfile
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps

TARGET_LONG_EDGE = 5000
OUTPUT_DPI = 300


@dataclass
class LabReport:
    status: str
    status_label: str
    width: int
    height: int
    dpi: int
    transparent: bool
    background_mode: str
    edge_score: int
    text_risk: str
    review_reasons: list[str]
    steps: list[str]


def _border_pixels(rgb: np.ndarray) -> np.ndarray:
    return np.concatenate((rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]), axis=0)


def _flat_border_background(rgb: np.ndarray) -> tuple[bool, np.ndarray, float]:
    border = _border_pixels(rgb).astype(np.float32)
    median = np.median(border, axis=0)
    distances = np.linalg.norm(border - median, axis=1)
    uniformity = float(np.percentile(distances, 90))
    return uniformity <= 28.0, median, uniformity


def _connected_background_alpha(rgb: np.ndarray, background: np.ndarray) -> np.ndarray:
    """Remove only background-like pixels connected to the image border."""
    lab = cv2.cvtColor(rgb, cv2.COLOR_RGB2LAB).astype(np.float32)
    bg_lab = cv2.cvtColor(
        np.uint8([[background.clip(0, 255)]]), cv2.COLOR_RGB2LAB
    )[0, 0].astype(np.float32)
    distance = np.linalg.norm(lab - bg_lab, axis=2)

    likely_bg = (distance < 18).astype(np.uint8)
    h, w = likely_bg.shape
    flood_source = likely_bg.copy()
    mask = np.zeros((h + 2, w + 2), np.uint8)
    for point in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)):
        if flood_source[point[1], point[0]]:
            cv2.floodFill(flood_source, mask, point, 2)
    connected = flood_source == 2

    # A short transition produces antialiased edges without a broad grey halo.
    alpha = np.full((h, w), 255, np.uint8)
    alpha[connected] = 0
    transition = connected & (distance >= 8)
    alpha[transition] = np.clip((distance[transition] - 8) / 10 * 255, 0, 255)
    return alpha


def _clean_alpha(alpha: np.ndarray) -> np.ndarray:
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    cleaned = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, kernel)
    # Keep edge transition narrow; wide feathering is visible on dark garments.
    return cv2.GaussianBlur(cleaned, (3, 3), 0.45)


def _looks_like_flat_document(rgb: np.ndarray) -> bool:
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    border = _border_pixels(rgb)
    border_lightness = float(np.median(cv2.cvtColor(
        border.reshape(-1, 1, 3), cv2.COLOR_RGB2GRAY
    )))
    dark_ratio = float(np.mean(hsv[..., 2] < 105))
    colourful_ratio = float(np.mean((hsv[..., 1] > 85) & (hsv[..., 2] > 55)))
    # Colour-rich artwork/mascots on white are not documents. Flattening them
    # destroys shading and character details.
    return (
        border_lightness > 175
        and dark_ratio > 0.025
        and colourful_ratio < 0.12
    )


def _soft_region(mask: np.ndarray, sigma: float = 0.9) -> np.ndarray:
    """Return a clean sub-pixel coverage mask, not a blurred image."""
    binary = mask.astype(np.uint8) * 255
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    binary = cv2.morphologyEx(binary, cv2.MORPH_OPEN, kernel)
    return cv2.GaussianBlur(binary, (0, 0), sigma).astype(np.float32) / 255.0


def _deskew_from_logo_panel(rgb: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    contours, _ = cv2.findContours(
        (gray < 105).astype(np.uint8) * 255,
        cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE,
    )
    if not contours:
        return rgb
    largest = max(contours, key=cv2.contourArea)
    if cv2.contourArea(largest) < gray.size * 0.08:
        return rgb
    (_, _), (rw, rh), angle = cv2.minAreaRect(largest)
    correction = angle + 90 if rw >= rh and angle < -45 else angle
    if abs(correction) < 0.15 or abs(correction) > 5:
        return rgb
    h, w = gray.shape
    border = np.median(_border_pixels(rgb), axis=0).tolist()
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), correction, 1.0)
    return cv2.warpAffine(
        rgb, matrix, (w, h), flags=cv2.INTER_CUBIC,
        borderMode=cv2.BORDER_CONSTANT, borderValue=border,
    )


def _render_confirmed_small_text(
    yellow: np.ndarray, panel: np.ndarray, text: str
) -> tuple[np.ndarray, np.ndarray]:
    """Replace damaged small yellow subtitle with confirmed, editable text."""
    ys, xs = np.where(panel)
    if not len(xs):
        return yellow, np.zeros_like(yellow)
    top, bottom = int(ys.min()), int(ys.max())
    subtitle_zone = yellow & (np.indices(yellow.shape)[0] > top + (bottom - top) * 0.68)
    points = cv2.findNonZero(subtitle_zone.astype(np.uint8))
    if points is None:
        return yellow, np.zeros_like(yellow)
    x, y, w, h = cv2.boundingRect(points)
    erase = cv2.dilate(
        subtitle_zone.astype(np.uint8),
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
    ).astype(bool)

    mask = Image.new("L", (yellow.shape[1], yellow.shape[0]), 0)
    draw = ImageDraw.Draw(mask)
    font_path = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    font = ImageFont.truetype(font_path, max(8, int(h * 1.05)))
    widths = [draw.textlength(char, font=font) for char in text]
    base_width = sum(widths)
    spacing = max(0.0, (w - base_width) / max(1, len(text) - 1))
    cursor = x + max(0, (w - (base_width + spacing * (len(text) - 1))) / 2)
    bbox = draw.textbbox((0, 0), text, font=font)
    baseline_y = y + (h - (bbox[3] - bbox[1])) / 2 - bbox[1]
    for char, char_width in zip(text, widths):
        draw.text((cursor, baseline_y), char, font=font, fill=255)
        cursor += char_width + spacing
    rendered = np.asarray(mask) > 0
    result = yellow.copy()
    result[erase] = False
    result |= rendered
    return result, erase


def _recover_flat_document(
    rgb: np.ndarray, confirmed_small_text: str | None = None
) -> tuple[np.ndarray, np.ndarray]:
    """Recover photographed/scanned flat artwork without inventing text.

    Removes only border-connected paper, flattens the largest dark logo panel,
    and turns photographed black ink into clean neutral ink.
    """
    rgb = _deskew_from_logo_panel(rgb)
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    h, w = gray.shape

    # Paper varies because of lighting. Treat bright, low-saturation pixels as
    # candidates, then retain only the component connected to the border.
    paper_candidate = ((gray > 168) & (hsv[..., 1] < 72)).astype(np.uint8)
    paper_candidate = cv2.morphologyEx(
        paper_candidate, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8)
    )
    count, labels, _, _ = cv2.connectedComponentsWithStats(paper_candidate, 8)
    border_labels = np.unique(np.concatenate((
        labels[0], labels[-1], labels[:, 0], labels[:, -1]
    )))
    paper = np.isin(labels, border_labels[border_labels != 0])

    alpha = np.full((h, w), 255, np.uint8)
    alpha[paper] = 0
    alpha = _clean_alpha(alpha)

    cleaned = rgb.copy().astype(np.float32)
    dark = (gray < 125).astype(np.uint8) * 255
    contours, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    panel_mask = np.zeros((h, w), np.uint8)
    if contours:
        largest = max(contours, key=cv2.contourArea)
        if cv2.contourArea(largest) > h * w * 0.08:
            # A logo panel can contain white shapes connected to the paper
            # through a small opening. Its convex hull defines the panel area
            # without deleting those white design elements.
            hull = cv2.convexHull(largest)
            cv2.drawContours(panel_mask, [hull], -1, 255, -1)
            panel_mask = cv2.morphologyEx(
                panel_mask, cv2.MORPH_CLOSE, np.ones((9, 9), np.uint8)
            )

    panel = panel_mask > 0
    yellow = panel & (hsv[..., 0] >= 12) & (hsv[..., 0] <= 42) & (hsv[..., 1] > 70)
    white = panel & (gray > 145) & ~yellow
    black = panel & ~yellow & ~white
    if confirmed_small_text:
        yellow, erased_text = _render_confirmed_small_text(
            yellow, panel, confirmed_small_text
        )
        black |= erased_text
        black &= ~yellow
    cleaned[black] = (18, 18, 18)
    cleaned[white] = (250, 250, 250)
    if np.any(yellow):
        yellow_colour = np.median(rgb[yellow], axis=0).astype(np.uint8)
        cleaned[yellow] = yellow_colour
    # Re-render internal colour boundaries from sub-pixel region masks.
    white_cover = _soft_region(white)
    panel_cover = _soft_region(panel, sigma=1.0)
    base = np.zeros_like(cleaned) + np.array((18, 18, 18), np.float32)
    base = base * (1 - white_cover[..., None]) + 250 * white_cover[..., None]
    if np.any(yellow):
        # Keep the source shape intact here. Potrace performs the final
        # sub-pixel smoothing; pre-blurring small subtitles destroys glyphs.
        base[yellow] = yellow_colour.astype(np.float32)
    cleaned[panel] = base[panel]
    alpha = np.maximum(alpha, np.round(panel_cover * 255).astype(np.uint8))

    # Outside the logo panel, dark photographed ink should be neutral black.
    local_ink = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY_INV, 51, 13,
    )
    ink_seed = ((local_ink > 0) & (hsv[..., 1] < 105) & ~panel).astype(np.uint8)
    ink_seed = cv2.morphologyEx(
        ink_seed, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink_seed, 8)
    ink = np.zeros((h, w), dtype=bool)
    for component in range(1, count):
        cw = stats[component, cv2.CC_STAT_WIDTH]
        ch = stats[component, cv2.CC_STAT_HEIGHT]
        cx = stats[component, cv2.CC_STAT_LEFT] + cw / 2
        cy = stats[component, cv2.CC_STAT_TOP] + ch / 2
        is_page_rule = cw > w * 0.4 and ch < max(6, h * 0.018)
        is_border_artifact = (
            (cx < w * 0.025 or cx > w * 0.975 or cy > h * 0.965)
            and stats[component, cv2.CC_STAT_AREA] < h * w * 0.002
        )
        if (
            stats[component, cv2.CC_STAT_AREA] >= 10
            and not is_page_rule
            and not is_border_artifact
        ):
            ink |= labels == component
    ink &= ~panel
    cleaned[ink] = (12, 12, 12)
    # Rebuild opacity from the ink mask so JPEG-grey stroke edges do not
    # disappear into the removed paper.
    ink_alpha = np.round(_soft_region(ink, sigma=0.7) * 255).astype(np.uint8)
    alpha[~panel] = ink_alpha[~panel]
    return np.clip(cleaned, 0, 255).astype(np.uint8), alpha


def _edge_score(alpha: np.ndarray) -> int:
    edge = cv2.Canny(alpha, 40, 120)
    count = int(np.count_nonzero(edge))
    if count < 20:
        return 70
    contours, _ = cv2.findContours(edge, cv2.RETR_LIST, cv2.CHAIN_APPROX_NONE)
    if not contours:
        return 55
    total = sum(cv2.arcLength(c, False) for c in contours)
    simplified = sum(
        cv2.arcLength(cv2.approxPolyDP(c, 1.2, False), False) for c in contours
    )
    ratio = simplified / max(total, 1.0)
    return int(np.clip(45 + ratio * 55, 0, 100))


def _text_risk(rgb: np.ndarray) -> str:
    """Cheap, deterministic warning until the text reconstruction module exists."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    edges = cv2.Canny(gray, 80, 180)
    components, _, stats, _ = cv2.connectedComponentsWithStats(edges, 8)
    h, w = gray.shape
    small = 0
    for i in range(1, components):
        _, _, cw, ch, area = stats[i]
        if 3 <= area <= max(20, (h * w) // 3000) and ch < h * 0.12 and cw < w * 0.25:
            small += 1
    return "high" if small >= 18 else "medium" if small >= 7 else "low"


def _resize_rgba(rgba: np.ndarray, target: int) -> np.ndarray:
    h, w = rgba.shape[:2]
    scale = target / max(h, w)
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    interpolation = cv2.INTER_LANCZOS4 if scale > 1 else cv2.INTER_AREA
    return cv2.resize(rgba, size, interpolation=interpolation)


def _place_document_on_square(rgba: np.ndarray, target: int) -> np.ndarray:
    alpha = rgba[..., 3]
    points = cv2.findNonZero((alpha > 8).astype(np.uint8))
    if points is None:
        return cv2.resize(rgba, (target, target), interpolation=cv2.INTER_LANCZOS4)
    x, y, w, h = cv2.boundingRect(points)
    artwork = rgba[y:y + h, x:x + w]
    usable_w = int(target * 0.91)
    usable_h = int(target * 0.72)
    scale = min(usable_w / w, usable_h / h)
    size = (max(1, round(w * scale)), max(1, round(h * scale)))
    artwork = cv2.resize(
        artwork, size,
        interpolation=cv2.INTER_LANCZOS4 if scale > 1 else cv2.INTER_AREA,
    )
    canvas = np.zeros((target, target, 4), np.uint8)
    left = (target - artwork.shape[1]) // 2
    top = int(target * 0.04)
    canvas[top:top + artwork.shape[0], left:left + artwork.shape[1]] = artwork
    return canvas


def _trace_layer(
    mask: np.ndarray, width: int, height: int, *,
    turdsize: int = 8, alphamax: float = 1.0, tolerance: float = 0.18,
) -> np.ndarray:
    """Potrace a bitmap mask and render its Bezier paths at production size."""
    with tempfile.TemporaryDirectory(prefix="printos_trace_") as temp_dir:
        bitmap = f"{temp_dir}/layer.pbm"
        svg = f"{temp_dir}/layer.svg"
        png = f"{temp_dir}/layer.png"
        # Potrace traces black pixels.
        Image.fromarray(np.where(mask, 0, 255).astype(np.uint8)).convert("1").save(bitmap)
        subprocess.run([
            "potrace", bitmap, "--svg", "--output", svg,
            "--turdsize", str(turdsize), "--alphamax", str(alphamax),
            "--opttolerance", str(tolerance),
        ], check=True, capture_output=True, timeout=30)
        subprocess.run([
            "rsvg-convert", svg, "--width", str(width), "--height", str(height),
            "--output", png,
        ], check=True, capture_output=True, timeout=30)
        rendered = Image.open(png).convert("RGBA")
        if rendered.size != (width, height):
            rendered = rendered.resize((width, height), Image.Resampling.LANCZOS)
        return np.asarray(rendered)[..., 3]


def _vector_render_document(
    rgb: np.ndarray, alpha: np.ndarray, target: int
) -> np.ndarray | None:
    """Trace colour-separated artwork layers, then rasterise them at high DPI."""
    if not shutil.which("potrace") or not shutil.which("rsvg-convert"):
        return None

    h, w = alpha.shape
    render_w = target
    render_h = max(1, round(target * h / w))
    hsv = cv2.cvtColor(rgb, cv2.COLOR_RGB2HSV)
    visible = alpha > 70
    yellow = visible & (hsv[..., 0] >= 10) & (hsv[..., 0] <= 45) & (hsv[..., 1] > 65)
    white = visible & ~yellow & (cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY) > 180)
    black = visible & ~yellow & ~white

    black_alpha = _trace_layer(black, render_w, render_h)
    white_alpha = _trace_layer(white, render_w, render_h)
    # Yellow often contains a small subtitle. Preserve accents, counters and
    # narrow strokes instead of applying the large-logo simplification.
    yellow_alpha = _trace_layer(
        yellow, render_w, render_h,
        turdsize=1, alphamax=0.35, tolerance=0.025,
    )
    artwork = np.zeros((render_h, render_w, 4), np.uint8)

    def composite(colour: tuple[int, int, int], layer_alpha: np.ndarray) -> None:
        source = Image.new("RGBA", (render_w, render_h), (*colour, 0))
        source.putalpha(Image.fromarray(layer_alpha))
        base = Image.fromarray(artwork)
        artwork[:] = np.asarray(Image.alpha_composite(base, source))

    composite((12, 12, 12), black_alpha)
    composite((250, 250, 250), white_alpha)
    yellow_colour = (
        tuple(np.median(rgb[yellow], axis=0).astype(int))
        if np.any(yellow) else (232, 174, 29)
    )
    composite(yellow_colour, yellow_alpha)
    return _place_document_on_square(artwork, target)


def _render_traced_layers(
    layers: list[tuple[np.ndarray, tuple[int, int, int]]], target: int
) -> np.ndarray | None:
    """Trace selected design-colour masks and place them on a square canvas."""
    can_trace = bool(shutil.which("potrace") and shutil.which("rsvg-convert"))
    visible = np.zeros_like(layers[0][0], dtype=bool)
    for mask, _ in layers:
        visible |= mask
    points = cv2.findNonZero(visible.astype(np.uint8))
    if points is None:
        return None
    x, y, w, h = cv2.boundingRect(points)
    padding = max(4, round(max(w, h) * 0.015))
    x0, y0 = max(0, x - padding), max(0, y - padding)
    x1 = min(visible.shape[1], x + w + padding)
    y1 = min(visible.shape[0], y + h + padding)
    render_w = target
    render_h = max(1, round(target * (y1 - y0) / (x1 - x0)))
    artwork = np.zeros((render_h, render_w, 4), np.uint8)
    for mask, colour in layers:
        cropped = mask[y0:y1, x0:x1]
        if can_trace:
            layer_alpha = _trace_layer(
                cropped, render_w, render_h,
                turdsize=2, alphamax=0.65, tolerance=0.06,
            )
        else:
            # Deterministic local fallback used by tests and CPU-only installs.
            # Supersampling keeps the same narrow antialiasing behaviour as the
            # SVG renderer without blurring the interior of small lettering.
            layer_alpha = cv2.resize(
                cropped.astype(np.uint8) * 255,
                (render_w, render_h),
                interpolation=cv2.INTER_CUBIC,
            )
            layer_alpha = cv2.GaussianBlur(layer_alpha, (3, 3), 0.42)
        source = Image.new("RGBA", (render_w, render_h), (*colour, 0))
        source.putalpha(Image.fromarray(layer_alpha))
        artwork[:] = np.asarray(
            Image.alpha_composite(Image.fromarray(artwork), source)
        )
    return _place_document_on_square(artwork, target)


def _recover_line_art(
    rgb: np.ndarray, target: int, feedback: set[str] | None = None
) -> np.ndarray | None:
    """Turn a user-selected photographed drawing into smooth transparent ink."""
    gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    # Remove slow lighting/paper variation first. Pencil/ink strokes remain as
    # local dark valleys, while paper fibres and camera shading mostly vanish.
    gray = cv2.bilateralFilter(gray, 7, 28, 28)
    background = cv2.GaussianBlur(gray, (0, 0), 15)
    darkness = cv2.subtract(background, gray)
    positive = darkness[darkness > 0]
    if positive.size == 0:
        return None
    otsu, _ = cv2.threshold(
        darkness, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    threshold = max(10, min(34, int(otsu)))
    ink = (darkness >= threshold).astype(np.uint8) * 255
    ink = cv2.morphologyEx(
        ink, cv2.MORPH_CLOSE,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)),
    )
    count, labels, stats, _ = cv2.connectedComponentsWithStats(ink, 8)
    keep = np.zeros_like(ink, dtype=bool)
    feedback = feedback or set()
    area_divisor = 220000 if "preserve_detail" in feedback else 120000
    minimum_area = max(8 if "preserve_detail" in feedback else 14,
                       ink.size // area_divisor)
    for component in range(1, count):
        area = stats[component, cv2.CC_STAT_AREA]
        cw = stats[component, cv2.CC_STAT_WIDTH]
        ch = stats[component, cv2.CC_STAT_HEIGHT]
        # Preserve long thin calligraphy strokes, but reject isolated paper
        # grain and compression speckles.
        if area >= minimum_area or max(cw, ch) >= max(gray.shape) * 0.025:
            keep |= labels == component
    shape_kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    if "remove_noise" in feedback:
        keep = cv2.morphologyEx(
            keep.astype(np.uint8), cv2.MORPH_OPEN, shape_kernel
        ).astype(bool)
    if "smooth_edges" in feedback:
        keep = cv2.medianBlur(keep.astype(np.uint8) * 255, 5) > 127
    if "thicken_lines" in feedback:
        keep = cv2.dilate(keep.astype(np.uint8), shape_kernel).astype(bool)
    elif "thin_lines" in feedback:
        keep = cv2.erode(keep.astype(np.uint8), shape_kernel).astype(bool)
    return _render_traced_layers([(keep, (18, 18, 18))], target)


def _recover_embroidery(
    rgb: np.ndarray, target: int, feedback: set[str] | None = None
) -> np.ndarray | None:
    """Flatten selected embroidery colours while suppressing cloth texture."""
    smooth = cv2.bilateralFilter(rgb, 9, 55, 55)
    hsv = cv2.cvtColor(smooth, cv2.COLOR_RGB2HSV)
    gray = cv2.cvtColor(smooth, cv2.COLOR_RGB2GRAY)
    white = (hsv[..., 1] < 68) & (gray > 168)
    # Embroidery thread is normally substantially brighter and more saturated
    # than the surrounding cloth. Conservative thresholds avoid tracing the
    # knitted fabric as part of the production artwork.
    vivid = (hsv[..., 1] > 92) & (hsv[..., 2] > 112)
    green = vivid & (hsv[..., 0] >= 34) & (hsv[..., 0] < 65)
    cyan = vivid & (hsv[..., 0] >= 65) & (hsv[..., 0] <= 105)
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))

    feedback = feedback or set()

    def tidy(mask: np.ndarray, *, stronger: bool = False) -> np.ndarray:
        if stronger:
            mask = cv2.medianBlur(mask.astype(np.uint8) * 255, 5) > 127
        cleaned = cv2.morphologyEx(mask.astype(np.uint8), cv2.MORPH_CLOSE, kernel)
        cleaned = cv2.morphologyEx(cleaned, cv2.MORPH_OPEN, kernel)
        if "smooth_edges" in feedback or "remove_noise" in feedback:
            cleaned = cv2.medianBlur(cleaned * 255, 7) > 127
            cleaned = cleaned.astype(np.uint8)
        if "thicken_lines" in feedback:
            cleaned = cv2.dilate(cleaned, kernel, iterations=1)
        elif "thin_lines" in feedback:
            cleaned = cv2.erode(cleaned, kernel, iterations=1)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(cleaned, 8)
        result = np.zeros_like(cleaned, dtype=bool)
        if "preserve_detail" in feedback:
            divisor = 90000
        else:
            divisor = 18000 if "remove_noise" in feedback else 40000
        minimum_area = max(30, cleaned.size // divisor)
        for component in range(1, count):
            area = stats[component, cv2.CC_STAT_AREA]
            cw = stats[component, cv2.CC_STAT_WIDTH]
            ch = stats[component, cv2.CC_STAT_HEIGHT]
            if area >= minimum_area or max(cw, ch) >= max(cleaned.shape) * 0.035:
                result |= labels == component
        return result

    white, green, cyan = tidy(white, stronger=True), tidy(green), tidy(cyan)
    layers: list[tuple[np.ndarray, tuple[int, int, int]]] = []
    if np.any(green):
        layers.append((green, tuple(np.median(rgb[green], axis=0).astype(int))))
    if np.any(cyan):
        layers.append((cyan, tuple(np.median(rgb[cyan], axis=0).astype(int))))
    if np.any(white):
        layers.append((white, (245, 245, 242)))
    if not layers:
        return None
    return _render_traced_layers(layers, target)


def run_pipeline(
    image: Image.Image, target_long_edge: int = TARGET_LONG_EDGE,
    confirmed_small_text: str | None = None,
    recovery_mode: str = "auto",
    feedback_flags: set[str] | None = None,
) -> tuple[Image.Image, dict[str, Any]]:
    """Return a transparent, colour-preserving PNG candidate and honest report."""
    original = ImageOps.exif_transpose(image).convert("RGBA")
    rgba = np.array(original)
    rgb = rgba[..., :3]
    original_alpha = rgba[..., 3]
    steps: list[str] = ["analyze"]
    reasons: list[str] = []

    already_transparent = bool(np.any(original_alpha < 250))
    flat, background, uniformity = _flat_border_background(rgb)

    specialised_candidate = None
    if recovery_mode == "line_art":
        specialised_candidate = _recover_line_art(
            rgb, target_long_edge, feedback_flags
        )
        background_mode = "line_art_recovery"
        steps.extend(["extract_line_art", "potrace_bezier_rerender"])
        alpha = original_alpha
    elif recovery_mode == "embroidery":
        specialised_candidate = _recover_embroidery(
            rgb, target_long_edge, feedback_flags
        )
        background_mode = "embroidery_recovery"
        steps.extend(["suppress_fabric_texture", "separate_thread_colours",
                      "potrace_bezier_rerender"])
        alpha = original_alpha
    elif already_transparent:
        alpha = original_alpha
        background_mode = "existing_alpha"
        steps.append("preserve_existing_alpha")
    elif _looks_like_flat_document(rgb):
        rgb, alpha = _recover_flat_document(rgb, confirmed_small_text)
        background_mode = "flat_document_recovery"
        steps.extend(["remove_connected_paper", "flatten_logo_colours", "clean_ink"])
        if confirmed_small_text:
            steps.append("rebuild_confirmed_small_text")
    elif flat:
        alpha = _connected_background_alpha(rgb, background)
        removed_ratio = float(np.mean(alpha < 16))
        if removed_ratio > 0.94:
            # A nearly uniform design can look like its own background. Never
            # return an empty PNG and call it a successful repair.
            alpha = original_alpha
            background_mode = "subject_loss_guard"
            reasons.append("自动去底会删除几乎全部主体，已停止处理")
            steps.append("stop_subject_loss")
        else:
            background_mode = "flat_border"
            steps.append("remove_connected_flat_background")
    else:
        alpha = original_alpha
        background_mode = "complex_review"
        reasons.append(f"背景不够单一（边缘色差 {uniformity:.1f}），未自动强制抠除")

    alpha = _clean_alpha(alpha)
    candidate = np.dstack((rgb, alpha))

    if specialised_candidate is not None:
        candidate = specialised_candidate
    elif background_mode == "flat_document_recovery":
        vector_candidate = _vector_render_document(rgb, alpha, target_long_edge)
        if vector_candidate is not None:
            candidate = vector_candidate
            steps.append("potrace_bezier_rerender")
        else:
            candidate = _place_document_on_square(candidate, target_long_edge)
    else:
        candidate = _resize_rgba(candidate, target_long_edge)
    edge_score = _edge_score(candidate[..., 3])
    text_risk = _text_risk(rgb)
    if edge_score < 82:
        reasons.append(f"边缘评分 {edge_score}，需要美工放大检查")
    if text_risk != "low":
        reasons.append("检测到小文字/密集细节风险，必须核对文字，不自动重编")
    steps.extend(["resize_preserve_aspect", "export_rgba_png"])
    output = Image.fromarray(candidate)
    output.info["dpi"] = (OUTPUT_DPI, OUTPUT_DPI)

    requires_rebuild = (
        background_mode in ("complex_review", "subject_loss_guard")
        or specialised_candidate is None
        and recovery_mode in ("line_art", "embroidery")
    )
    status = "manual" if requires_rebuild else "pass" if not reasons else "review"
    labels = {
        "pass": "可进入生产测试",
        "review": "需要美工复核",
        "manual": "需要设计重建",
    }
    report = LabReport(
        status=status,
        status_label=labels[status],
        width=output.width,
        height=output.height,
        dpi=OUTPUT_DPI,
        transparent=bool(np.any(candidate[..., 3] < 250)),
        background_mode=background_mode,
        edge_score=edge_score,
        text_risk=text_risk,
        review_reasons=reasons,
        steps=steps,
    )
    return output, asdict(report)
