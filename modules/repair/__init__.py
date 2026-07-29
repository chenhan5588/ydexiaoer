"""Image repair module — V1 (PIL-based) repair functions.

These are the simpler PIL-filter-based repairs used in the current production.
For the advanced OpenCV-based V2 engine, see engine_v2.py.
"""

from PIL import Image, ImageFilter, ImageStat, ImageOps, ImageEnhance
from modules.quality import CM_TO_INCH


def repair_upscale(img: Image.Image, target_dpi: int = 300, target_cm: int = 30) -> Image.Image:
    """Upscale image to target DPI for print size using Lanczos resampling.

    Fits within target dimensions (maintains aspect ratio, smaller dimension hits target).
    """
    target_px = int(target_cm * CM_TO_INCH * target_dpi)
    w, h = img.size
    scale = target_px / max(w, h)
    if scale <= 1.0:
        return img
    new_w, new_h = int(w * scale), int(h * scale)
    return img.resize((new_w, new_h), Image.LANCZOS)


def repair_denoise(img: Image.Image) -> Image.Image:
    """Reduce noise using bilateral-like approach: median + subtle gaussian."""
    img = img.filter(ImageFilter.MedianFilter(size=3))
    img = img.filter(ImageFilter.GaussianBlur(radius=0.6))
    return img


def repair_sharpen(img: Image.Image) -> Image.Image:
    """Apply unsharp mask to improve clarity without over-sharpening."""
    return img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=120, threshold=3))


def repair_contrast(img: Image.Image) -> Image.Image:
    """Auto-enhance contrast for better print vibrancy."""
    enhancer = ImageEnhance.Contrast(img)
    gray = img.convert("L")
    stat = ImageStat.Stat(gray)
    current_std = stat.stddev[0] if stat.stddev else 35
    factor = max(1.0, min(2.0, 70 / max(current_std, 1)))
    return enhancer.enhance(factor)


def repair_color_uniformity(img: Image.Image) -> Image.Image:
    """Improve color uniformity via histogram equalization."""
    if img.mode == "RGBA":
        rgb = img.convert("RGB")
        alpha = img.getchannel("A")
    else:
        rgb = img.convert("RGB")
        alpha = None

    r, g, b = rgb.split()
    r = ImageOps.equalize(r)
    g = ImageOps.equalize(g)
    b = ImageOps.equalize(b)
    equalized = Image.merge("RGB", (r, g, b))
    result = Image.blend(rgb, equalized, alpha=0.7)

    if alpha:
        result = result.convert("RGBA")
        result.putalpha(alpha)

    return result


def repair_remove_background(img: Image.Image) -> Image.Image:
    """Remove light/white background and create transparent PNG.

    Uses threshold-based approach: pixels close to white become transparent.
    """
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA")

    if img.mode == "RGBA":
        r, g, b, a = img.split()
        rgb = Image.merge("RGB", (r, g, b))
    else:
        rgb = img.convert("RGB")
        a = Image.new("L", img.size, 255)

    pixels_rgb = list(rgb.getdata())
    pixels_a = list(a.getdata()) if a else [255] * len(pixels_rgb)

    new_alpha = []
    threshold = 200
    for i, (r_val, g_val, b_val) in enumerate(pixels_rgb):
        brightness = (r_val + g_val + b_val) / 3
        if brightness > threshold:
            opacity = max(0, int(255 * (brightness - threshold) / 55))
            new_alpha.append(min(pixels_a[i], opacity))
        else:
            new_alpha.append(pixels_a[i])

    result = rgb.convert("RGBA")
    alpha_channel = Image.new("L", img.size)
    alpha_channel.putdata(new_alpha)
    result.putalpha(alpha_channel)

    return result


def repair_edge_smooth(img: Image.Image) -> Image.Image:
    """Smooth jagged edges using anti-aliasing.

    Downscale slightly then upscale back with Lanczos for natural edge smoothing.
    """
    w, h = img.size
    small_w, small_h = int(w * 0.8), int(h * 0.8)
    small = img.resize((small_w, small_h), Image.LANCZOS)
    small = small.filter(ImageFilter.GaussianBlur(radius=0.5))
    result = small.resize((w, h), Image.LANCZOS)

    if img.mode == "RGBA":
        alpha = img.getchannel("A")
        result = result.convert("RGBA")
        result.putalpha(alpha)

    return result


def repair_image(img: Image.Image, scores: dict, issues: list) -> tuple:
    """Apply all relevant repairs based on detection results.

    Returns:
        (repaired_image: Image.Image, applied_fixes: list[str])
    """
    applied = []
    repaired = img.copy()

    fix_map = [
        ("denoise", scores.get("noise"), repair_denoise, "AI降噪"),
        ("sharpen", scores.get("sharpness"), repair_sharpen, "智能锐化"),
        ("contrast", scores.get("contrast"), repair_contrast, "对比度增强"),
        ("upscale", scores.get("resolution"), lambda i: repair_upscale(i), "超分辨率放大至300dpi"),
        ("color", scores.get("color_uniformity"), repair_color_uniformity, "颜色均匀化"),
        ("edge", scores.get("edge_quality"), repair_edge_smooth, "边缘平滑"),
        ("background", scores.get("format"), repair_remove_background, "去背景→透明底PNG"),
    ]

    for key, grade, fix_fn, label in fix_map:
        if grade and grade in ("warn", "fail"):
            try:
                repaired = fix_fn(repaired)
                applied.append(label)
            except Exception as e:
                print(f"Repair {label} failed: {e}")

    if repaired.mode not in ("RGB", "RGBA"):
        repaired = repaired.convert("RGBA")

    return repaired, applied
