"""Image quality analysis - screening & scoring against heat-transfer standards.

The central function is `analyze_image()`, which examines:
- Resolution (DPI at 30x30cm @ 300dpi)
- Sharpness (Laplacian variance)
- Noise level
- Contrast
- Color uniformity (grid-based CV)
- Edge quality / jaggedness
- Format (PNG transparent background requirement)
"""

import io
import math
import base64
import statistics
import random
from pathlib import Path
from PIL import Image, ImageFilter, ImageStat, ImageOps

# ---------------------------------------------------------------------------
# Print standard constants
# ---------------------------------------------------------------------------
PRINT_DPI = 300
CM_TO_INCH = 1 / 2.54
DEFAULT_PRINT_CM = 30


# ---------------------------------------------------------------------------
# Edge quality analysis
# ---------------------------------------------------------------------------

def check_edge_quality(gray_img):
    """Check if edges are clean/smooth vs jagged/fragmented.

    Uses local gradient consistency: at each edge pixel, compare the
    gradient direction with its neighbors. Clean edges have consistent
    local directions; jagged edges have rapidly changing directions.
    """
    w, h = gray_img.size
    sample_size = min(w, 1200)
    if w > sample_size:
        gray_img = gray_img.resize((sample_size, int(h * sample_size / w)), Image.LANCZOS)

    # Sobel-like edge detection
    kx = ImageFilter.Kernel((3, 3), [-1, 0, 1, -2, 0, 2, -1, 0, 1], scale=4, offset=128)
    ky = ImageFilter.Kernel((3, 3), [-1, -2, -1, 0, 0, 0, 1, 2, 1], scale=4, offset=128)

    gx = gray_img.filter(kx)
    gy = gray_img.filter(ky)

    w2, h2 = gray_img.size
    pixels_gx = list(gx.getdata())
    pixels_gy = list(gy.getdata())

    magnitudes = []
    edge_pixels = []
    edge_mask = [False] * (w2 * h2)

    for y in range(1, h2 - 1):
        for x in range(1, w2 - 1):
            idx = y * w2 + x
            dx = pixels_gx[idx] - 128
            dy = pixels_gy[idx] - 128
            mag = math.sqrt(dx * dx + dy * dy)
            magnitudes.append(mag)
            if mag > 12:
                dir_val = math.atan2(dy, dx)
                edge_pixels.append((y, x, dir_val))
                edge_mask[idx] = True

    if len(edge_pixels) < 50:
        return 0.0, "pass", "边缘柔和，无明显锯齿"

    sample_size_edges = min(500, len(edge_pixels))
    sampled = random.sample(edge_pixels, sample_size_edges)

    consistency_scores = []
    window = 3

    for cy, cx, main_dir in sampled:
        same_dir = 0
        total_neighbors = 0
        for dy in range(-window, window + 1):
            for dx in range(-window, window + 1):
                if dy == 0 and dx == 0:
                    continue
                ny, nx = cy + dy, cx + dx
                if 0 <= ny < h2 and 0 <= nx < w2:
                    nidx = ny * w2 + nx
                    if edge_mask[nidx]:
                        total_neighbors += 1
                        ndx = pixels_gx[nidx] - 128
                        ndy = pixels_gy[nidx] - 128
                        if ndx != 0 or ndy != 0:
                            ndir = math.atan2(ndy, ndx)
                            diff = abs(ndir - main_dir)
                            if diff > math.pi:
                                diff = 2 * math.pi - diff
                            if diff < math.pi / 4:
                                same_dir += 1

        if total_neighbors >= 2:
            ratio = same_dir / total_neighbors
            consistency_scores.append(ratio)

    if not consistency_scores:
        return 0.0, "pass", "无法评估边缘"

    avg_consistency = statistics.mean(consistency_scores)
    jaggedness = 1.0 - avg_consistency

    if avg_consistency >= 0.6:
        return round(jaggedness, 3), "pass", "边缘清晰平滑"
    elif avg_consistency >= 0.35:
        return round(jaggedness, 3), "warn", "边缘存在轻微锯齿，建议描边检查"
    else:
        return round(jaggedness, 3), "fail", "边缘锯齿严重，需要修整"


# ---------------------------------------------------------------------------
# Color uniformity analysis
# ---------------------------------------------------------------------------

def check_color_uniformity(rgb_img):
    """Check if colors are uniform and even across the image.

    Splits the image into a grid of patches and measures the standard
    deviation of brightness between patches. Low variance = uniform color,
    high variance = blotchy/uneven color.
    """
    w, h = rgb_img.size

    grid = 6
    patch_w = max(w // grid, 10)
    patch_h = max(h // grid, 10)

    patch_brightness = []
    for gy in range(grid):
        for gx in range(grid):
            x1 = gx * patch_w
            y1 = gy * patch_h
            x2 = min(x1 + patch_w, w)
            y2 = min(y1 + patch_h, h)
            if x2 - x1 < 5 or y2 - y1 < 5:
                continue
            patch = rgb_img.crop((x1, y1, x2, y2))
            stat = ImageStat.Stat(patch)
            avg = sum(stat.mean) / 3
            patch_brightness.append(avg)

    if len(patch_brightness) < 9:
        return 0.0, "pass", ""

    mean_brightness = statistics.mean(patch_brightness)
    if mean_brightness < 0.5:
        return 0.0, "pass", ""

    std_brightness = statistics.stdev(patch_brightness)
    cv = std_brightness / mean_brightness

    if cv < 0.06:
        return round(cv, 4), "pass", "颜色均匀"
    elif cv < 0.15:
        return round(cv, 4), "warn", "颜色轻微不均匀，建议检查"
    else:
        return round(cv, 4), "fail", "颜色不均匀，有坑洼或色差"


# ---------------------------------------------------------------------------
# Main analysis function
# ---------------------------------------------------------------------------

def analyze_image(img: Image.Image, filename: str, fast_mode: bool = False) -> dict:
    """Analyze image quality against t-shirt heat transfer standards.

    Args:
        img: PIL Image object.
        filename: Original filename (for format detection).
        fast_mode: Skip preview generation and heavy edge analysis for batch processing.

    Returns:
        dict with scores, issues, verdict, quality_score, and metadata.
    """
    w, h = img.size

    # ---- Basic info ----
    total_pixels = w * h
    megapixels = round(total_pixels / 1_000_000, 2)
    mode = img.mode
    has_alpha = mode == "RGBA"

    ext = Path(filename).suffix.lower()
    is_png = ext == ".png"

    # ---- 1. Resolution ----
    eff_dpi = min(
        round(w / (DEFAULT_PRINT_CM * CM_TO_INCH)),
        round(h / (DEFAULT_PRINT_CM * CM_TO_INCH)),
    )

    # ---- 2. Sharpness (Laplacian variance) ----
    gray = img.convert("L")
    sample_w = min(w, 800)
    sample_h = int(h * sample_w / w) if w > 0 else sample_w
    gray_small = gray.resize((sample_w, sample_h), Image.LANCZOS)

    laplacian = gray_small.filter(ImageFilter.Kernel(
        (3, 3), [-1, -1, -1, -1, 8, -1, -1, -1, -1], scale=1, offset=0
    ))
    stat = ImageStat.Stat(laplacian)
    sharpness = stat.var[0]

    # ---- 3. Noise estimation ----
    blurred = gray_small.filter(ImageFilter.GaussianBlur(radius=2))
    diff_total = 0
    pixels = gray_small.width * gray_small.height
    for orig, blur in zip(gray_small.getdata(), blurred.getdata()):
        diff_total += abs(orig - blur)
    noise_level = diff_total / pixels

    # ---- 4. Contrast ----
    contrast_stat = ImageStat.Stat(gray_small)
    contrast = contrast_stat.stddev[0] if contrast_stat.stddev else 0

    # ---- 5. Color uniformity ----
    if mode in ("RGB", "RGBA"):
        rgb = img.convert("RGB")
        color_cv, color_grade, color_msg = check_color_uniformity(rgb)
    else:
        color_cv, color_grade, color_msg = 0.0, "pass", ""

    # ---- 6. Edge quality (skip in fast mode) ----
    if fast_mode:
        edge_cv, edge_grade, edge_msg = 0.0, "pass", ""
    else:
        edge_cv, edge_grade, edge_msg = check_edge_quality(gray)

    # ---- Scoring ----
    scores = {}
    issues = []

    # Resolution
    if eff_dpi >= 300:
        scores["resolution"] = "pass"
    elif eff_dpi >= 200:
        scores["resolution"] = "warn"
        issues.append(f"分辨率偏低 ({eff_dpi}dpi), 建议至少 300dpi (30cm需3543px)")
    else:
        scores["resolution"] = "fail"
        issues.append(f"分辨率严重不足 ({eff_dpi}dpi), 需要客户提供更高清图 (30cm需3543px)")

    # Sharpness
    if sharpness >= 200:
        scores["sharpness"] = "pass"
    elif sharpness >= 80:
        scores["sharpness"] = "warn"
        issues.append("图片轻微模糊, 锐化后可改善")
    else:
        scores["sharpness"] = "fail"
        issues.append("图片严重模糊, 不建议使用")

    # Noise
    if noise_level <= 8:
        scores["noise"] = "pass"
    elif noise_level <= 18:
        scores["noise"] = "warn"
        issues.append("图片有噪点, 降噪后可改善")
    else:
        scores["noise"] = "fail"
        issues.append("噪点严重, 烫画效果差")

    # Contrast
    if contrast >= 35:
        scores["contrast"] = "pass"
    elif contrast >= 20:
        scores["contrast"] = "warn"
        issues.append("对比度偏低, 烫画可能发灰")
    else:
        scores["contrast"] = "fail"
        issues.append("对比度过低, 印刷不清晰")

    # Color uniformity
    scores["color_uniformity"] = color_grade
    if color_grade == "warn":
        issues.append(f"颜色轻微不均匀 ({color_cv:.3f}), 建议检查色差")
    elif color_grade == "fail":
        issues.append(f"颜色不均匀 ({color_cv:.3f}), 存在坑洼或色块差异")

    # Edge quality
    scores["edge_quality"] = edge_grade
    if edge_grade == "warn":
        issues.append(f"边缘有锯齿 ({edge_cv:.2f}), 建议描边检查")
    elif edge_grade == "fail":
        issues.append(f"边缘锯齿严重 ({edge_cv:.2f}), 需要修整")

    # Format check
    if not is_png:
        scores["format"] = "warn"
        issues.append("建议转换为 PNG 透明底格式")
    elif has_alpha:
        scores["format"] = "pass"
    else:
        scores["format"] = "warn"
        issues.append("PNG 格式正确，但缺少透明底，建议抠图后使用")

    if not has_alpha and not is_png:
        scores["format"] = "fail"
        issues.append("格式不符合要求：需要 PNG 透明底 (30x30cm, 300dpi)")

    # ---- Overall verdict ----
    fails = sum(1 for v in scores.values() if v == "fail")
    warns = sum(1 for v in scores.values() if v == "warn")

    if fails >= 2:
        verdict = "reject"
        verdict_label = "不可用"
    elif fails >= 1 or warns >= 3:
        verdict = "fix"
        verdict_label = "需修改"
    else:
        verdict = "pass"
        verdict_label = "可直接用"

    # Overall quality score 0-100
    quality_score = 100
    quality_score -= fails * 25
    quality_score -= warns * 10
    if megapixels < 1:
        quality_score -= 15
    if eff_dpi < 150:
        quality_score -= 20
    elif eff_dpi < 300:
        quality_score -= 10
    quality_score = max(0, min(100, quality_score))

    result = {
        "filename": filename,
        "width": w,
        "height": h,
        "megapixels": megapixels,
        "eff_dpi": eff_dpi,
        "sharpness": round(sharpness, 1),
        "noise_level": round(noise_level, 1),
        "contrast": round(contrast, 1),
        "color_uniformity": color_cv,
        "edge_quality": edge_cv,
        "mode": mode,
        "has_alpha": has_alpha,
        "is_png": is_png,
        "scores": scores,
        "issues": issues,
        "verdict": verdict,
        "verdict_label": verdict_label,
        "quality_score": quality_score,
        "fast_mode": fast_mode,
    }

    # Generate base64 preview for non-fast mode
    if not fast_mode:
        preview = img.copy()
        max_side = 400
        if max(preview.size) > max_side:
            preview.thumbnail((max_side, max_side), Image.LANCZOS)
        buf = io.BytesIO()
        if preview.mode == "RGBA":
            bg = Image.new("RGB", preview.size, (255, 255, 255))
            bg.paste(preview, mask=preview.split()[3])
            preview = bg
        preview.save(buf, format="JPEG", quality=75)
        buf.seek(0)
        preview_b64 = base64.b64encode(buf.read()).decode()
        result["preview"] = f"data:image/jpeg;base64,{preview_b64}"

    return result
