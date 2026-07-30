"""
PrintAI Studio — Flask Application (Routing Layer)
====================================================
This file contains ONLY Flask routes. All business logic lives in modules/.

modules/auth/       — login_required decorator
modules/quality/    — analyze_image, edge/color checks
modules/repair/     — V1 repair (PIL), V2 engine (OpenCV + rembg)
modules/orders/     — ZIP parsing, parallel processing, Excel export
"""

import os
import io
import json
import uuid
import base64
import zipfile
import tempfile
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from flask import Flask, request, jsonify, render_template, send_file, session, redirect, url_for
from PIL import Image

# ---- Module imports ----
from modules.auth import login_required
from modules.quality import analyze_image
from modules.repair import repair_image
from modules.dtf_lab import run_pipeline as run_dtf_pipeline
from modules.orders import (
    extract_nested_zip, find_files, find_order_json, find_images_in_order,
    parse_size_from_title, parse_size_from_sku,
    process_order_zip,
)
from modules.orders.exporter import export_excel_file

# ---- App setup ----
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "printai-studio-secret-2024")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "printai2024")

BASE_DIR = Path(__file__).parent
UPLOAD_DIR = BASE_DIR / "uploads"
OUTPUT_DIR = BASE_DIR / "outputs"
UPLOAD_DIR.mkdir(exist_ok=True)
OUTPUT_DIR.mkdir(exist_ok=True)

CM_TO_INCH = 1 / 2.54
DEFAULT_PRINT_CM = 30

# Shared IO thread pool
_io_pool = ThreadPoolExecutor(max_workers=4, thread_name_prefix="img")

# ===========================================================================
# Pages
# ===========================================================================


@app.route("/")
@login_required
def index():
    return render_template("index.html")


@app.route("/lab")
def dtf_lab():
    """DTF lab page. Production access is protected by Nginx basic auth."""
    return render_template("lab.html")


@app.route("/login", methods=["GET", "POST"])
def login_page():
    error = None
    if request.method == "POST":
        if request.form.get("password") == APP_PASSWORD:
            session["logged_in"] = True
            session.permanent = True
            return redirect(url_for("index"))
        error = "密码错误，请重试"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login_page"))


@app.route("/outputs/<path:filename>")
@login_required
def serve_output(filename):
    return send_file(OUTPUT_DIR / filename)


# ===========================================================================
# API — Image Screening
# ===========================================================================


@app.route("/api/screen", methods=["POST"])
@login_required
def screen():
    files = request.files.getlist("images")
    if not files:
        return jsonify({"error": "请上传图片"}), 400

    target_w = float(request.form.get("printWidth", DEFAULT_PRINT_CM))
    target_h = float(request.form.get("printHeight", DEFAULT_PRINT_CM))

    results = []
    for f in files:
        if f.filename == "":
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"):
            results.append({"filename": f.filename, "error": f"不支持的格式: {ext}"})
            continue

        try:
            img = Image.open(f.stream)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")
            result = analyze_image(img, f.filename)

            eff_dpi_w = round(result["width"] / (target_w * CM_TO_INCH))
            eff_dpi_h = round(result["height"] / (target_h * CM_TO_INCH))
            result["eff_dpi"] = min(eff_dpi_w, eff_dpi_h)
            result["eff_dpi_w"] = eff_dpi_w
            result["eff_dpi_h"] = eff_dpi_h
            result["print_width_cm"] = target_w
            result["print_height_cm"] = target_h

            # Re-score resolution for target size
            if result["eff_dpi"] >= 300:
                result["scores"]["resolution"] = "pass"
            elif result["eff_dpi"] >= 200:
                result["scores"]["resolution"] = "warn"
            else:
                result["scores"]["resolution"] = "fail"

            # Recalculate verdict
            fails = sum(1 for v in result["scores"].values() if v == "fail")
            warns = sum(1 for v in result["scores"].values() if v == "warn")
            if fails >= 2:
                result["verdict"] = "reject"
                result["verdict_label"] = "不可用"
            elif fails >= 1 or warns >= 3:
                result["verdict"] = "fix"
                result["verdict_label"] = "需修改"
            else:
                result["verdict"] = "pass"
                result["verdict_label"] = "可直接用"

            quality_score = 100 - fails * 25 - warns * 10
            if result["megapixels"] < 1:
                quality_score -= 15
            if result["eff_dpi"] < 150:
                quality_score -= 20
            elif result["eff_dpi"] < 300:
                quality_score -= 10
            result["quality_score"] = max(0, min(100, quality_score))

            results.append(result)
        except Exception as e:
            results.append({"filename": f.filename, "error": f"读取失败: {str(e)}"})

    pass_count = sum(1 for r in results if r.get("verdict") == "pass")
    fix_count = sum(1 for r in results if r.get("verdict") == "fix")
    reject_count = sum(1 for r in results if r.get("verdict") == "reject")
    error_count = sum(1 for r in results if "error" in r)

    return jsonify({
        "results": results,
        "summary": {
            "total": len(results),
            "pass": pass_count,
            "fix": fix_count,
            "reject": reject_count,
            "error": error_count,
        },
        "print_size": f"{target_w}x{target_h}cm",
    })


# ===========================================================================
# API — AI Repair
# ===========================================================================


def _parse_image_from_request(required=True):
    """Parse uploaded image from request. Returns (img, error_response)."""
    file = request.files.get("image")
    if not file or file.filename == "":
        if required:
            return None, (jsonify({"error": "请上传图片"}), 400)
        return None, None
    ext = Path(file.filename).suffix.lower()
    if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"):
        return None, (jsonify({"error": f"不支持的格式: {ext}"}), 400)
    try:
        img = Image.open(file.stream)
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        return img, None
    except Exception as e:
        return None, (jsonify({"error": f"读取失败: {str(e)}"}), 400)


def _save_preview(img, filename, fmt="PNG"):
    """Generate and return base64-encoded preview thumbnail."""
    preview_img = img.copy()
    max_side = 400
    if max(preview_img.size) > max_side:
        preview_img.thumbnail((max_side, max_side), Image.LANCZOS)
    buf = io.BytesIO()
    preview_img.save(buf, format=fmt)
    buf.seek(0)
    preview_b64 = base64.b64encode(buf.read()).decode()
    return f"data:image/{fmt.lower()};base64,{preview_b64}"


@app.route("/api/dtf-lab", methods=["POST"])
def dtf_lab_repair():
    """Conservative single-image DTF prototype; never claims text reconstruction."""
    img, err = _parse_image_from_request()
    if err:
        return err

    try:
        file_id = uuid.uuid4().hex[:12]
        original_path = UPLOAD_DIR / f"dtf_original_{file_id}.png"
        img.convert("RGBA").save(original_path, format="PNG")
        output, report = run_dtf_pipeline(img)
        output_path = OUTPUT_DIR / f"dtf_{file_id}.png"
        output.save(output_path, format="PNG", dpi=(300, 300))
        report_path = OUTPUT_DIR / f"dtf_{file_id}.json"
        report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                               encoding="utf-8")
        return jsonify({
            "file_id": file_id,
            "preview": _save_preview(output, "preview.png"),
            "download_url": f"/api/dtf-download/{file_id}",
            "report": report,
        })
    except Exception as exc:
        app.logger.exception("DTF lab processing failed")
        return jsonify({"error": f"处理失败: {exc}"}), 500


@app.route("/api/dtf-download/<file_id>")
def dtf_download(file_id):
    path = OUTPUT_DIR / f"dtf_{file_id}.png"
    if not path.exists():
        return jsonify({"error": "文件不存在或已过期"}), 404
    return send_file(path, mimetype="image/png", as_attachment=True,
                     download_name=f"dtf_ready_{file_id}.png")


@app.route("/api/repair", methods=["POST"])
@login_required
def repair():
    """AI repair endpoint: accepts image, returns fixed image + preview."""
    img, err = _parse_image_from_request()
    if err:
        return err

    analysis = analyze_image(img, img.filename or "upload.png")
    repaired, applied_fixes = repair_image(img, analysis["scores"], analysis["issues"])

    preview = _save_preview(repaired, "preview.png")

    file_id = uuid.uuid4().hex[:12]
    output_path = OUTPUT_DIR / f"repaired_{file_id}.png"
    repaired.save(output_path, format="PNG")

    repaired_check = analyze_image(repaired, f"repaired_{Path(img.filename or 'image').stem}.png")

    return jsonify({
        "filename": img.filename or "upload",
        "repaired_filename": f"repaired_{Path(img.filename or 'image').stem}.png",
        "file_id": file_id,
        "preview": preview,
        "applied_fixes": applied_fixes,
        "original_score": analysis["quality_score"],
        "repaired_score": repaired_check["quality_score"],
        "original_verdict": analysis["verdict_label"],
        "repaired_verdict": repaired_check["verdict_label"],
        "repaired_issues": repaired_check["issues"],
        "download_url": f"/api/download/{file_id}",
    })


@app.route("/api/repair-batch", methods=["POST"])
@login_required
def repair_batch():
    """Batch repair: accepts multiple images, returns all repaired results."""
    files = request.files.getlist("images")
    if not files:
        return jsonify({"error": "请上传图片"}), 400

    results = []
    for f in files:
        if f.filename == "":
            continue
        ext = Path(f.filename).suffix.lower()
        if ext not in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tiff", ".tif"):
            results.append({"filename": f.filename, "error": f"不支持的格式: {ext}"})
            continue

        try:
            img = Image.open(f.stream)
            if img.mode not in ("RGB", "RGBA"):
                img = img.convert("RGBA")

            analysis = analyze_image(img, f.filename)
            repaired, applied_fixes = repair_image(img, analysis["scores"], analysis["issues"])

            file_id = uuid.uuid4().hex[:12]
            output_path = OUTPUT_DIR / f"repaired_{file_id}.png"
            repaired.save(output_path, format="PNG")

            preview = _save_preview(repaired, "preview.png")

            results.append({
                "filename": f.filename,
                "repaired_filename": f"repaired_{Path(f.filename).stem}.png",
                "file_id": file_id,
                "preview": preview,
                "applied_fixes": applied_fixes,
                "original_score": analysis["quality_score"],
                "download_url": f"/api/download/{file_id}",
            })
        except Exception as e:
            results.append({"filename": f.filename, "error": f"修复失败: {str(e)}"})

    return jsonify({"results": results})


@app.route("/api/download/<file_id>")
@login_required
def download_fixed(file_id):
    """Download a repaired image by its file_id."""
    path = OUTPUT_DIR / f"repaired_{file_id}.png"
    if not path.exists():
        return jsonify({"error": "文件不存在或已过期"}), 404
    return send_file(path, mimetype="image/png", as_attachment=True,
                     download_name=f"repaired_{file_id}.png")


# ===========================================================================
# API — Batch Orders
# ===========================================================================


@app.route("/api/batch-orders", methods=["POST"])
@login_required
def batch_orders():
    """Upload order ZIP files, parse and analyze all.

    Two-phase approach:
    1. Extract all ZIPs and parse order data
    2. Flatten all images across orders into a single parallel processing pool
    """
    files = request.files.getlist("zips")
    if not files:
        return jsonify({"error": "请上传 ZIP 文件"}), 400

    do_repair = request.form.get("repair", "true").lower() == "true"

    # Phase 1: Extract all ZIPs, collect metadata
    orders_meta = []

    for f in files:
        if f.filename == "" or not f.filename.lower().endswith('.zip'):
            continue

        mabang_id = Path(f.filename).stem
        temp_zip = tempfile.NamedTemporaryFile(suffix='.zip', delete=False)
        f.save(temp_zip.name)
        temp_zip.close()

        try:
            temp_dir = tempfile.mkdtemp(prefix="order_")
            extract_nested_zip(temp_zip.name, temp_dir)

            json_path, order_data = find_order_json(temp_dir)
            if not order_data:
                orders_meta.append({
                    "mabang_id": mabang_id, "error": "无法解析订单数据",
                    "temp_dir": temp_dir, "temp_zip": temp_zip.name,
                })
                continue

            order_id = order_data.get('orderId', '')
            asin = order_data.get('asin', '')
            title = order_data.get('title', '')
            quantity = order_data.get('quantity', 1)
            size = parse_size_from_title(title) or parse_size_from_sku(mabang_id)

            snapshots, customer_images = find_images_in_order(temp_dir, order_data)

            orders_meta.append({
                "mabang_id": mabang_id, "order_id": order_id, "asin": asin,
                "title": title, "size": size, "quantity": quantity,
                "snapshots": snapshots, "customer_images": customer_images,
                "temp_dir": temp_dir, "temp_zip": temp_zip.name, "error": None,
            })
        except Exception as e:
            orders_meta.append({
                "mabang_id": mabang_id, "error": str(e),
                "temp_dir": None, "temp_zip": temp_zip.name,
            })

    # Phase 2: Flatten all images, process in parallel
    flat_tasks = []
    for idx, meta in enumerate(orders_meta):
        if meta.get("error"):
            continue
        for ci in meta.get("customer_images", []):
            flat_tasks.append((ci, idx))

    image_results = {}

    def _process_flat(ci, meta_idx):
        try:
            img = Image.open(ci['path'])
            if img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGBA')

            analysis = analyze_image(img, os.path.basename(ci['path']), fast_mode=True)
            analysis['surface'] = ci['surface']
            analysis['buyer_filename'] = ci['buyer_filename']

            orig_fid = uuid.uuid4().hex[:12]
            orig_save_path = OUTPUT_DIR / f"orig_{orig_fid}_{os.path.basename(ci['path'])}"
            img.save(orig_save_path, format='PNG')
            analysis['saved_original_path'] = str(orig_save_path)

            if do_repair and analysis['verdict'] != 'pass':
                try:
                    repaired, fixes = repair_image(img, analysis['scores'], analysis['issues'])
                    fid = uuid.uuid4().hex[:12]
                    repaired_path = OUTPUT_DIR / f"repaired_{fid}.png"
                    repaired.save(repaired_path, format='PNG')
                    analysis['repaired_path'] = str(repaired_path)
                    analysis['applied_fixes'] = fixes

                    re_check = analyze_image(repaired,
                        f"repaired_{os.path.basename(ci['path'])}", fast_mode=True)
                    analysis['repaired_score'] = re_check['quality_score']
                    analysis['repaired_verdict'] = re_check['verdict_label']
                except Exception as e:
                    analysis['repair_error'] = str(e)

            return meta_idx, analysis
        except Exception as e:
            return meta_idx, {
                'filename': os.path.basename(ci['path']),
                'error': str(e),
                'surface': ci.get('surface', ''),
                'buyer_filename': ci.get('buyer_filename', ''),
            }

    if flat_tasks:
        futures = [_io_pool.submit(_process_flat, ci, idx) for ci, idx in flat_tasks]
        for future in as_completed(futures):
            meta_idx, result = future.result()
            image_results.setdefault(meta_idx, []).append(result)

    # Phase 3: Assemble results
    results = []
    errors = []

    for meta in orders_meta:
        if meta.get("error"):
            errors.append({"filename": meta["mabang_id"], "error": meta["error"]})
            if meta.get("temp_dir"):
                shutil.rmtree(meta["temp_dir"], ignore_errors=True)
            if meta.get("temp_zip"):
                os.unlink(meta["temp_zip"])
            continue

        saved_snapshots = []
        for snap_path in meta.get("snapshots", []):
            try:
                snap_img = Image.open(snap_path)
                snap_fid = uuid.uuid4().hex[:12]
                snap_save = OUTPUT_DIR / f"snapshot_{snap_fid}_{os.path.basename(snap_path)}"
                if snap_img.mode == 'RGBA':
                    snap_img.convert('RGB').save(snap_save, 'JPEG', quality=90)
                else:
                    snap_img.save(snap_save, 'JPEG', quality=90)
                saved_snapshots.append(str(snap_save))
            except Exception as e:
                saved_snapshots.append(snap_path)

        results.append({
            "mabang_order_id": meta["mabang_id"],
            "order_id": meta["order_id"],
            "asin": meta["asin"],
            "title": meta["title"],
            "size": meta["size"],
            "quantity": meta["quantity"],
            "snapshot_paths": saved_snapshots,
            "customer_images": image_results.get(orders_meta.index(meta), []),
        })

        if meta.get("temp_dir"):
            shutil.rmtree(meta["temp_dir"], ignore_errors=True)
        if meta.get("temp_zip"):
            os.unlink(meta["temp_zip"])

    return jsonify({
        "orders": results,
        "errors": errors,
        "total": len(files),
        "success": len(results),
        "failed": len(errors),
    })


# ===========================================================================
# API — Excel Export
# ===========================================================================


@app.route("/api/export-excel", methods=["POST"])
@login_required
def export_excel():
    """Generate Excel from parsed order data."""
    data = request.get_json()
    if not data or 'orders' not in data:
        return jsonify({"error": "缺少订单数据"}), 400

    buf = export_excel_file(data['orders'])
    return send_file(
        buf,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name=f"订单汇总_{uuid.uuid4().hex[:8]}.xlsx"
    )


# ===========================================================================
# Main
# ===========================================================================

if __name__ == "__main__":
    app.run(debug=True, port=5051)
