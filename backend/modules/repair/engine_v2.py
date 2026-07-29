"""
PrintAI Studio V2 — Real Image Repair Engine
==============================================
Replaces the weak PIL-filter-based "repair" with:
- OpenCV DNN Super Resolution (EDSR x4)
- CLAHE adaptive contrast (LAB colorspace)
- Non-local Means denoising
- Detail enhancement + bilateral edge smoothing
- rembg AI background removal (U2Net)
- Morphological edge refinement
"""

import os
import cv2
import numpy as np
from PIL import Image
from pathlib import Path

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
PRINT_CM = 30
PRINT_DPI = 300
CM_TO_INCH = 1 / 2.54
TARGET_PX = int(PRINT_CM * CM_TO_INCH * PRINT_DPI)  # ~3543px

# Model download paths
MODEL_DIR = Path(__file__).parent / "models"
EDSR_MODEL_PATH = MODEL_DIR / "EDSR_x4.pb"

# ---------------------------------------------------------------------------
# Model Management
# ---------------------------------------------------------------------------

_sr_model = None


def _get_sr_model():
    """Load OpenCV DNN super-resolution model (EDSR x4)."""
    global _sr_model
    if _sr_model is not None:
        return _sr_model

    MODEL_DIR.mkdir(exist_ok=True)

    if not EDSR_MODEL_PATH.exists():
        print(f"[SR] Downloading EDSR_x4 model (~38MB)...")
        import urllib.request
        url = "https://github.com/Saafke/EDSR_Tensorflow/raw/master/models/EDSR_x4.pb"
        urllib.request.urlretrieve(url, str(EDSR_MODEL_PATH))
        print(f"[SR] Model saved to {EDSR_MODEL_PATH}")

    sr = cv2.dnn_superres.DnnSuperResImpl_create()
    sr.readModel(str(EDSR_MODEL_PATH))
    sr.setModel("edsr", 4)
    sr.setPreferableBackend(cv2.dnn.DNN_BACKEND_OPENCV)
    sr.setPreferableTarget(cv2.dnn.DNN_TARGET_CPU)
    _sr_model = sr
    print("[SR] EDSR x4 model loaded.")
    return _sr_model


# ---------------------------------------------------------------------------
# Core Repair Functions
# ---------------------------------------------------------------------------

def repair_super_resolution(pil_img):
    """
    Real AI super-resolution using EDSR x4 neural network.
    Adds genuine detail, not just interpolation.
    Falls back to Lanczos if model is unavailable.
    """
    img = np.array(pil_img.convert("RGB"))
    h, w = img.shape[:2]

    # Determine how much upscaling is needed
    max_dim = max(w, h)
    if max_dim >= TARGET_PX:
        # Already big enough, no upscale needed
        return pil_img, "skip"

    # How many times do we need to scale?
    target_scale = TARGET_PX / max_dim

    try:
        sr = _get_sr_model()
        # EDSR x4: do 4x super resolution
        img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        # If target scale > 4, do SR + Lanczos
        # If target scale <= 4, do SR only
        interim = cv2.dnn_superres.DnnSuperResImpl_create()

        # Split: do 4x EDSR first
        result = sr.upsample(img_bgr)

        # If we need more than 4x, do Lanczos on top
        if target_scale > 4:
            new_h = int(h * target_scale)
            new_w = int(w * target_scale)
            result = cv2.resize(result, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)
        elif target_scale > 0.9:  # Close enough to 4x
            pass  # EDSR 4x is sufficient
        else:
            # Target is less than 4x — downscale from 4x result to exact target
            new_h = int(h * target_scale)
            new_w = int(w * target_scale)
            result = cv2.resize(result, (new_w, new_h), interpolation=cv2.INTER_LANCZOS4)

        result_rgb = cv2.cvtColor(result, cv2.COLOR_BGR2RGB)
        result_pil = Image.fromarray(result_rgb)
        return result_pil, "edsr_4x"

    except Exception as e:
        print(f"[SR] EDSR failed: {e}, falling back to Lanczos")
        new_w = int(w * target_scale)
        new_h = int(h * target_scale)
        return pil_img.resize((new_w, new_h), Image.LANCZOS), "lanczos_fallback"


def repair_denoise(pil_img, strength="medium"):
    """
    Proper denoising with OpenCV's Non-local Means + Bilateral filter.
    Strength: 'light' | 'medium' | 'strong'
    """
    params = {
        "light":  (3, 21, 7, 21),
        "medium": (7, 35, 11, 35),
        "strong": (10, 49, 15, 49),
    }
    h, templateWindowSize, searchWindowSize, d = params.get(strength, params["medium"])

    img = np.array(pil_img.convert("RGB"))
    img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    # Non-local Means denoising
    denoised = cv2.fastNlMeansDenoisingColored(
        img_bgr, None, h, h, templateWindowSize, searchWindowSize
    )

    # Bilateral filter for edge preservation
    denoised = cv2.bilateralFilter(denoised, d, 75, 75)

    result = cv2.cvtColor(denoised, cv2.COLOR_BGR2RGB)
    return Image.fromarray(result)


def repair_contrast(pil_img):
    """
    CLAHE (Contrast Limited Adaptive Histogram Equalization) in LAB colorspace.
    Much better than global histogram equalization — preserves colors,
    only enhances lightness channel locally.
    """
    img = np.array(pil_img.convert("RGB"))
    img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    # Convert to LAB
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)
    l, a, b = cv2.split(lab)

    # CLAHE on L channel — clip limit 2.0, tile grid 8x8
    clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l_eq = clahe.apply(l)

    # Merge back
    lab_eq = cv2.merge([l_eq, a, b])
    bgr_eq = cv2.cvtColor(lab_eq, cv2.COLOR_LAB2BGR)

    result = cv2.cvtColor(bgr_eq, cv2.COLOR_BGR2RGB)
    return Image.fromarray(result)


def repair_sharpen(pil_img):
    """
    Multi-stage sharpening:
    1. detailEnhance() — OpenCV's texture enhancement
    2. Subtle Unsharp Mask for fine detail
    """
    img = np.array(pil_img.convert("RGB"))
    img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

    # Stage 1: Detail enhancement
    enhanced = cv2.detailEnhance(img_bgr, sigma_s=10, sigma_r=0.15)

    # Stage 2: Light Unsharp Mask
    gaussian = cv2.GaussianBlur(enhanced, (0, 0), 1.0)
    sharpened = cv2.addWeighted(enhanced, 1.5, gaussian, -0.5, 0)

    result = cv2.cvtColor(sharpened, cv2.COLOR_BGR2RGB)
    return Image.fromarray(result)


def repair_remove_background(pil_img):
    """
    AI background removal using rembg (U2Net).
    Produces clean transparent PNG.
    Falls back to improved threshold-based removal if rembg fails.
    """
    try:
        from rembg import remove
        img = np.array(pil_img.convert("RGB"))
        img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)

        result_bgr = remove(img_bgr, alpha_matting=True,
                            alpha_matting_foreground_threshold=240,
                            alpha_matting_background_threshold=10,
                            alpha_matting_erode_size=10)
        result_rgba = cv2.cvtColor(result_bgr, cv2.COLOR_BGRA2RGBA)
        return Image.fromarray(result_rgba)

    except Exception as e:
        print(f"[BG] rembg failed: {e}, using improved fallback")
        return _fallback_bg_removal(pil_img)


def _fallback_bg_removal(pil_img):
    """Improved background removal: adaptive threshold + edge feathering + morphological cleanup."""
    img = np.array(pil_img.convert("RGBA"))

    # Convert to grayscale
    gray = cv2.cvtColor(img[..., :3], cv2.COLOR_RGB2GRAY)

    # Adaptive threshold for better background detection
    thresh = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 21, 5
    )

    # Morphological cleanup: close small gaps, open to remove noise
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5))
    mask = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    # Edge feathering with Gaussian blur
    mask = cv2.GaussianBlur(mask, (7, 7), 3)

    # Apply mask to alpha channel
    img[..., 3] = mask
    return Image.fromarray(img)


def repair_edge_smooth(pil_img):
    """
    Edge smoothing using morphological operations.
    NON-destructive: uses guided-style smoothing instead of resize.
    """
    if pil_img.mode == "RGBA":
        rgb = np.array(pil_img.convert("RGB"))
        alpha = np.array(pil_img.split()[3])
    else:
        rgb = np.array(pil_img.convert("RGB"))
        alpha = None

    img_bgr = cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    # Edge-preserving smoothing
    smoothed = cv2.edgePreservingFilter(img_bgr, flags=1, sigma_s=60, sigma_r=0.4)

    if alpha is not None:
        # Also smooth the alpha channel edges
        kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
        alpha_smooth = cv2.morphologyEx(alpha, cv2.MORPH_CLOSE, kernel)
        alpha_smooth = cv2.GaussianBlur(alpha_smooth, (3, 3), 0.5)

        result_rgb = cv2.cvtColor(smoothed, cv2.COLOR_BGR2RGB)
        result_rgba = np.dstack([result_rgb, alpha_smooth])
        return Image.fromarray(result_rgba)
    else:
        result_rgb = cv2.cvtColor(smoothed, cv2.COLOR_BGR2RGB)
        return Image.fromarray(result_rgb)


def repair_color_uniformity(pil_img):
    """
    Color uniformity using LAB-based saturation correction + subtle white balance.
    """
    img = np.array(pil_img.convert("RGB"))
    img_bgr = cv2.cvtColor(img, cv2.COLOR_RGB2BGR)
    lab = cv2.cvtColor(img_bgr, cv2.COLOR_BGR2LAB)

    l, a, b = cv2.split(lab)

    # Normalize a and b channels (remove color casts)
    a_norm = cv2.normalize(a, None, 0, 255, cv2.NORM_MINMAX)
    b_norm = cv2.normalize(b, None, 0, 255, cv2.NORM_MINMAX)

    # Blend: 70% original, 30% normalized (subtle correction)
    a_blend = cv2.addWeighted(a, 0.7, a_norm, 0.3, 0)
    b_blend = cv2.addWeighted(b, 0.7, b_norm, 0.3, 0)

    lab_corrected = cv2.merge([l, a_blend, b_blend])
    bgr_corrected = cv2.cvtColor(lab_corrected, cv2.COLOR_LAB2BGR)

    result = cv2.cvtColor(bgr_corrected, cv2.COLOR_BGR2RGB)
    return Image.fromarray(result)


# ---------------------------------------------------------------------------
# Full Pipeline
# ---------------------------------------------------------------------------

def full_repair(pil_img, options=None):
    """
    Complete repair pipeline. Returns repaired PIL Image and step log.

    options dict keys (all default True):
        super_resolution: bool
        denoise: bool
        contrast: bool
        sharpen: bool
        remove_background: bool
        edge_smooth: bool
        color_uniformity: bool
    """
    if options is None:
        options = {}

    steps = {}
    img = pil_img.copy()

    # 1. Super Resolution (MUST be first — adds real detail)
    if options.get("super_resolution", True):
        img, sr_method = repair_super_resolution(img)
        steps["super_resolution"] = sr_method

    # 2. Denoise
    if options.get("denoise", True):
        img = repair_denoise(img, "light")
        steps["denoise"] = "nl_means+bilateral"

    # 3. Contrast enhancement
    if options.get("contrast", True):
        img = repair_contrast(img)
        steps["contrast"] = "clahe_lab"

    # 4. Color uniformity
    if options.get("color_uniformity", True):
        img = repair_color_uniformity(img)
        steps["color_uniformity"] = "lab_balance"

    # 5. Sharpen + Detail
    if options.get("sharpen", True):
        img = repair_sharpen(img)
        steps["sharpen"] = "detail_enhance+usm"

    # 6. Edge smoothing
    if options.get("edge_smooth", True):
        img = repair_edge_smooth(img)
        steps["edge_smooth"] = "morphological+epf"

    # 7. Background removal (MUST be last — produces RGBA)
    if options.get("remove_background", True):
        img = repair_remove_background(img)
        steps["remove_background"] = "rembg_u2net"

    return img, steps


# ---------------------------------------------------------------------------
# Standalone test
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    import sys
    import time

    if len(sys.argv) < 2:
        print("Usage: python image_repair_v2.py <input_image> [output_image]")
        sys.exit(1)

    input_path = sys.argv[1]
    output_path = sys.argv[2] if len(sys.argv) > 2 else "repaired.png"

    print(f"Loading: {input_path}")
    img = Image.open(input_path).convert("RGB")
    print(f"Original: {img.size}")

    start = time.time()
    repaired, steps = full_repair(img)
    elapsed = time.time() - start

    repaired.save(output_path, "PNG")
    print(f"\nDone in {elapsed:.1f}s")
    print(f"Output: {output_path} ({repaired.size})")
    print(f"Steps applied: {steps}")
