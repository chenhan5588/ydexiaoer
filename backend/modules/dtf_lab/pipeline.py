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
