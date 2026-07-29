"""Order processing module — ZIP parsing, JSON extraction, image matching.

Core flow:
    process_order_zip(zip_path, mabang_order_id)
        -> extract_nested_zip() -> find_order_json() -> find_images_in_order()
        -> analyze + repair customer images in parallel
        -> return order dict with snapshots and analyzed customer images
"""

import os
import json
import re
import uuid
import zipfile
import tempfile
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from PIL import Image

from modules.quality import analyze_image
from modules.repair import repair_image


# Shared thread pool for parallel image processing
_io_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="order-img")


# ---------------------------------------------------------------------------
# ZIP extraction
# ---------------------------------------------------------------------------

def extract_nested_zip(zip_path, extract_to):
    """Recursively extract nested zip files."""
    extracted = []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        zf.extractall(extract_to)
        for name in zf.namelist():
            full_path = os.path.join(extract_to, name)
            if name.lower().endswith('.zip') and os.path.isfile(full_path):
                sub_dir = os.path.join(extract_to, f"_nested_{uuid.uuid4().hex[:8]}")
                os.makedirs(sub_dir, exist_ok=True)
                extracted.extend(extract_nested_zip(full_path, sub_dir))
    extracted.append(extract_to)
    return extracted


def find_files(root_dir, extensions):
    """Find all files with given extensions under root_dir."""
    results = []
    for dirpath, _, filenames in os.walk(root_dir):
        for fn in filenames:
            if any(fn.lower().endswith(ext) for ext in extensions):
                results.append(os.path.join(dirpath, fn))
    return results


# ---------------------------------------------------------------------------
# Size extraction
# ---------------------------------------------------------------------------

def parse_size_from_title(title):
    """Extract size from Amazon product title, e.g. '..., Schwarz, M' -> 'M'."""
    if not title:
        return ""
    patterns = [
        r',\s*([XSML]|XL|XXL|XXXL|2XL|3XL|4XL|5XL)\s*$',
        r',\s*(\d{2,3}[cm]?\s*(?:/\s*\d{2,3}[cm]?)?)\s*$',
        r'-([XSML]|XL|XXL|XXXL|2XL|3XL|4XL|5XL)\s*$',
    ]
    for pat in patterns:
        m = re.search(pat, title, re.IGNORECASE)
        if m:
            return m.group(1).strip()
    return ""


def parse_size_from_sku(sku_or_filename):
    """Extract size from SKU like '1946VEST4-Black-M'."""
    if not sku_or_filename:
        return ""
    parts = sku_or_filename.replace('_', '-').split('-')
    for p in parts:
        p_upper = p.strip().upper()
        if p_upper in ('XS', 'S', 'M', 'L', 'XL', 'XXL', 'XXXL', '2XL', '3XL', '4XL', '5XL'):
            return p.strip()
    return ""


# ---------------------------------------------------------------------------
# JSON + image discovery
# ---------------------------------------------------------------------------

def find_order_json(root_dir):
    """Find the order JSON file in extracted directory."""
    json_files = find_files(root_dir, ['.json'])
    for jf in json_files:
        try:
            with open(jf, 'r', encoding='utf-8') as f:
                data = json.load(f)
            if 'orderId' in data or 'customizationData' in data:
                return jf, data
        except Exception:
            continue
    return None, None


def find_images_in_order(root_dir, order_data):
    """Find snapshot (effect image) and customer upload images from order data."""
    all_images = find_files(root_dir, ['.jpg', '.jpeg', '.png'])
    snapshots = []
    customer_images = []

    if not order_data:
        return snapshots, customer_images

    def _find_all(node, surface_label=""):
        """Recursively find all ImageCustomization nodes in the JSON tree."""
        if isinstance(node, dict):
            if node.get('type') == 'PreviewContainerCustomization':
                surface_label = node.get('label', '')

            snap = node.get('snapshot', {})
            if isinstance(snap, dict) and snap.get('imageName'):
                snap_name = snap['imageName']
                for img_path in all_images:
                    if snap_name.lower() in img_path.lower():
                        snapshots.append(img_path)
                        break

            if node.get('type') == 'ImageCustomization':
                img_info = node.get('image', {})
                img_name = img_info.get('imageName')
                if img_name:
                    for img_path in all_images:
                        if img_name.lower() in img_path.lower():
                            customer_images.append({
                                'path': img_path,
                                'buyer_filename': img_info.get('buyerFilename', ''),
                                'surface': surface_label,
                            })
                            break

            for v in node.values():
                _find_all(v, surface_label)
        elif isinstance(node, list):
            for item in node:
                _find_all(item, surface_label)

    try:
        _find_all(order_data)
    except Exception as e:
        print(f"Error finding images: {e}")

    return snapshots, customer_images


# ---------------------------------------------------------------------------
# Main order processing
# ---------------------------------------------------------------------------

def process_order_zip(zip_path, mabang_order_id, output_dir, do_repair=True):
    """Process a single order ZIP file.

    Args:
        zip_path: Path to the order ZIP file.
        mabang_order_id: Malang order ID (from filename).
        output_dir: Path to outputs directory for saving images.
        do_repair: Whether to run repair on problematic images.

    Returns:
        dict with order data, or {"error": ...} on failure.
    """
    temp_dir = tempfile.mkdtemp(prefix="order_")
    try:
        extract_nested_zip(zip_path, temp_dir)

        json_path, order_data = find_order_json(temp_dir)
        if not order_data:
            return {"error": "无法解析订单数据", "mabang_order_id": mabang_order_id}

        order_id = order_data.get('orderId', '')
        asin = order_data.get('asin', '')
        title = order_data.get('title', '')
        quantity = order_data.get('quantity', 1)
        size = parse_size_from_title(title) or parse_size_from_sku(mabang_order_id)

        snapshots, customer_images = find_images_in_order(temp_dir, order_data)

        # Save snapshots
        saved_snapshots = []
        for snap_path in snapshots:
            try:
                snap_img = Image.open(snap_path)
                snap_fid = uuid.uuid4().hex[:12]
                snap_save = output_dir / f"snapshot_{snap_fid}_{os.path.basename(snap_path)}"
                if snap_img.mode == 'RGBA':
                    snap_img.convert('RGB').save(snap_save, 'JPEG', quality=90)
                else:
                    snap_img.save(snap_save, 'JPEG', quality=90)
                saved_snapshots.append(str(snap_save))
            except Exception as e:
                print(f"Failed to save snapshot {snap_path}: {e}")
                saved_snapshots.append(snap_path)

        # Process images in parallel
        analyzed_images = []

        def _process_one_image(ci):
            try:
                img = Image.open(ci['path'])
                if img.mode not in ('RGB', 'RGBA'):
                    img = img.convert('RGBA')

                analysis = analyze_image(img, os.path.basename(ci['path']), fast_mode=True)
                analysis['surface'] = ci['surface']
                analysis['buyer_filename'] = ci['buyer_filename']

                orig_fid = uuid.uuid4().hex[:12]
                orig_save_path = output_dir / f"orig_{orig_fid}_{os.path.basename(ci['path'])}"
                img.save(orig_save_path, format='PNG')
                analysis['saved_original_path'] = str(orig_save_path)

                if do_repair and analysis['verdict'] != 'pass':
                    try:
                        repaired, fixes = repair_image(img, analysis['scores'], analysis['issues'])
                        fid = uuid.uuid4().hex[:12]
                        repaired_path = output_dir / f"repaired_{fid}.png"
                        repaired.save(repaired_path, format='PNG')
                        analysis['repaired_path'] = str(repaired_path)
                        analysis['applied_fixes'] = fixes

                        re_check = analyze_image(repaired, f"repaired_{os.path.basename(ci['path'])}", fast_mode=True)
                        analysis['repaired_score'] = re_check['quality_score']
                        analysis['repaired_verdict'] = re_check['verdict_label']
                    except Exception as e:
                        analysis['repair_error'] = str(e)

                return analysis
            except Exception as e:
                return {
                    'filename': os.path.basename(ci['path']),
                    'error': str(e),
                    'surface': ci.get('surface', ''),
                    'buyer_filename': ci.get('buyer_filename', ''),
                }

        if customer_images:
            futures = [_io_pool.submit(_process_one_image, ci) for ci in customer_images]
            for future in as_completed(futures):
                analyzed_images.append(future.result())

        return {
            "mabang_order_id": mabang_order_id,
            "order_id": order_id,
            "asin": asin,
            "title": title,
            "size": size,
            "quantity": quantity,
            "snapshot_paths": saved_snapshots,
            "customer_images": analyzed_images,
        }
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
