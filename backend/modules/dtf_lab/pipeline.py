"""Conservative DTF production-PNG pipeline."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

import cv2
import numpy as np
from PIL import Image

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
    return border_lightness > 175 and dark_ratio > 0.025


def _recover_flat_document(rgb: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Recover photographed/scanned flat artwork without inventing text.

    Removes only border-connected paper, flattens the largest dark logo panel,
    and turns photographed black ink into clean neutral ink.
    """
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

    cleaned = rgb.copy()
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
    cleaned[black] = (18, 18, 18)
    cleaned[white] = (250, 250, 250)
    if np.any(yellow):
        yellow_colour = np.median(rgb[yellow], axis=0).astype(np.uint8)
        cleaned[yellow] = yellow_colour
    alpha[panel] = 255

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
        is_page_rule = cw > w * 0.4 and ch < max(6, h * 0.018)
        if stats[component, cv2.CC_STAT_AREA] >= 10 and not is_page_rule:
            ink |= labels == component
    ink &= ~panel
    cleaned[ink] = (12, 12, 12)
    # Rebuild opacity from the ink mask so JPEG-grey stroke edges do not
    # disappear into the removed paper.
    ink_alpha = cv2.GaussianBlur(ink.astype(np.uint8) * 255, (3, 3), 0.45)
    alpha[~panel] = ink_alpha[~panel]
    return cleaned, alpha


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


def run_pipeline(image: Image.Image, target_long_edge: int = TARGET_LONG_EDGE) -> tuple[Image.Image, dict[str, Any]]:
    """Return a transparent, colour-preserving PNG candidate and honest report."""
    original = image.convert("RGBA")
    rgba = np.array(original)
    rgb = rgba[..., :3]
    original_alpha = rgba[..., 3]
    steps: list[str] = ["analyze"]
    reasons: list[str] = []

    already_transparent = bool(np.any(original_alpha < 250))
    flat, background, uniformity = _flat_border_background(rgb)

    if already_transparent:
        alpha = original_alpha
        background_mode = "existing_alpha"
        steps.append("preserve_existing_alpha")
    elif _looks_like_flat_document(rgb):
        rgb, alpha = _recover_flat_document(rgb)
        background_mode = "flat_document_recovery"
        steps.extend(["remove_connected_paper", "flatten_logo_colours", "clean_ink"])
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
    edge_score = _edge_score(alpha)
    text_risk = _text_risk(rgb)

    if edge_score < 82:
        reasons.append(f"边缘评分 {edge_score}，需要美工放大检查")
    if text_risk != "low":
        reasons.append("检测到小文字/密集细节风险，必须核对文字，不自动重编")

    if background_mode == "flat_document_recovery":
        candidate = _place_document_on_square(candidate, target_long_edge)
    else:
        candidate = _resize_rgba(candidate, target_long_edge)
    steps.extend(["resize_preserve_aspect", "export_rgba_png"])
    output = Image.fromarray(candidate)
    output.info["dpi"] = (OUTPUT_DPI, OUTPUT_DPI)

    requires_rebuild = background_mode in ("complex_review", "subject_loss_guard")
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
