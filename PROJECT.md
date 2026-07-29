# PrintAI Studio — AI Collaboration Guide

## Project Overview

**What it does**: Internal tool for an Amazon print-on-demand (POD) business. Customers upload images for custom t-shirt printing via heat press machine. This tool:
1. Screens uploaded images for print quality (resolution, clarity, noise, contrast, color uniformity, edge quality, format)
2. AI-repairs images (super-resolution, denoising, sharpening, background removal)
3. Processes Amazon order ZIP files — extracts orders, matches customer images, repairs them, exports Excel reports

**Business context**: FBM (Fulfilled by Merchant), ~13 Amazon stores (US/UK/DE/FR/IT/ES). Print specs: 30x30cm, 300 DPI, PNG transparent background.

**Owner**: Y同学 (Claw)

---

## Tech Stack

| Layer | Technology |
|---|---|
| Backend | Python 3.9+ / Flask |
| Image Processing | Pillow, OpenCV (cv2), rembg |
| Excel Export | openpyxl |
| Production Server | Waitress (WSGI) |
| Frontend | Vanilla HTML/CSS/JS (no framework) |
| Auth | Flask session cookies |
| OS | Ubuntu 22.04 on Tencent Cloud |

---

## File Structure

```
image-screener/
  app.py              # Flask routing ONLY — no business logic
  run.py              # Production startup (Waitress on :5051)
  PROJECT.md          # This file — AI collaboration guide
  requirements.txt    # Python dependencies
  server-deploy.sh    # Server-side one-click deploy script

  modules/            # All business logic organized by domain
    auth/
      __init__.py     # login_required decorator
    quality/
      __init__.py     # analyze_image(), check_edge_quality(), check_color_uniformity()
    repair/
      __init__.py     # V1 repair (PIL-based): repair_image(), repair_upscale(), etc.
      engine_v2.py    # V2 repair (OpenCV + rembg) — WORK IN PROGRESS
    orders/
      __init__.py     # process_order_zip(), ZIP extraction, JSON parsing
      exporter.py     # Excel export (openpyxl)

  templates/
    login.html        # Login page (password-based)
    index.html        # Main UI (2 tabs: Image QC + Order Batch)
  uploads/            # Temp upload directory (auto-cleaned after 7 days)
  outputs/            # Repaired images + generated Excel files
  models/             # Downloaded ML models (EDSR_x4.pb, u2net.onnx)
```

---

## API Endpoints

All protected by `@login_required`. Unauthenticated requests → 302 redirect (page) or 401 JSON (API).

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Main app (index.html) |
| GET/POST | `/login` | Login page / password verification |
| GET | `/logout` | Clear session → redirect to login |
| GET | `/outputs/<filename>` | Serve generated files |
| POST | `/api/screen` | Upload images → quality analysis |
| POST | `/api/repair` | Upload image → AI repair (current PIL-based) |
| POST | `/api/repair-batch` | Upload multiple images → batch repair |
| GET | `/api/download/<file_id>` | Download repaired image |
| POST | `/api/batch-orders` | Upload Amazon ZIP → parse orders + images |
| POST | `/api/export-excel` | Export order data to Excel with embedded images |

### Auth Config

- Password: environment variable `APP_PASSWORD` (default: `printai2024`)
- Secret key: environment variable `FLASK_SECRET_KEY`
- Session: cookie-based, permanent

---

## Current V1 Repair Engine (app.py — needs replacement)

The repair functions in `app.py` use only Pillow filters:

| Function | Algorithm | Issue |
|---|---|---|
| `repair_upscale` | Lanczos resize | Just interpolation, no new detail |
| `repair_denoise` | MedianFilter(3) + GaussianBlur(0.6) | Very weak |
| `repair_sharpen` | UnsharpMask (radius=1.5) | Conservative |
| `repair_contrast` | ImageEnhance.Contrast (adaptive factor) | OK but basic |
| `repair_color_uniformity` | Global histogram equalization | Washes out colors |
| `repair_edge_smooth` | Downscale 80% then upscale | DESTRUCTIVE — reduces quality! |
| `repair_remove_background` | Brightness threshold (>200) | Crude, leaves white edges |

## Development Workflow

```
Y同学 (提需求) ──→ GPT (出设计文档/API/架构) ──→ Claw/WorkBuddy (写代码)
                                                       │
                                              GPT (Review 代码)
                                                       │
                                              Y同学 (部署到腾讯云)
```

**Code organization rule**: All code MUST go under `modules/<domain>/`. NEVER create flat files like `repair.py`, `upload.py`, `detect.py` in the root.

---

## V2 Repair Engine (modules/repair/engine_v2.py — deploying next)

| Function | Algorithm | Technology |
|---|---|---|
| `repair_super_resolution` | EDSR x4 neural network | OpenCV DNN superres |
| `repair_denoise` | Non-local Means + Bilateral | cv2.fastNlMeansDenoisingColored |
| `repair_contrast` | CLAHE in LAB colorspace | cv2.createCLAHE |
| `repair_sharpen` | detailEnhance + Unsharp Mask | cv2.detailEnhance |
| `repair_color_uniformity` | LAB channel normalization (30% blend) | cv2.normalize |
| `repair_edge_smooth` | Edge-preserving filter + morphological | cv2.edgePreservingFilter |
| `repair_remove_background` | U2Net AI model | rembg |

---

## Server Info

```
IP: 101.33.236.219
OS: Ubuntu 22.04
App path: /opt/image-screener/
Service: systemctl (image-screener.service)
Port: 5051 (open in Tencent Cloud security group)
Python: system python3
Packages: flask, waitress, pillow, openpyxl
```

### Deployment Command

```bash
# Single command from local — packages + uploads + deploys
bash deploy.sh

# Or manually:
tar czf screener.tar.gz app.py run.py modules/ templates/ requirements.txt
scp screener.tar.gz root@101.33.236.219:/opt/
ssh root@101.33.236.219 "
  cd /opt && tar xzf screener.tar.gz -C image-screener/
  pip3 install -r /opt/image-screener/requirements.txt
  systemctl restart image-screener
"
```

### systemd Service File

```
[Unit]
Description=PrintAI Image Screener
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/image-screener
Environment="APP_PASSWORD=printai2024"
Environment="FLASK_SECRET_KEY=changeme-in-production"
ExecStart=/usr/bin/python3 /opt/image-screener/run.py
Restart=always

[Install]
WantedBy=multi-user.target
```

---

## Email System (agent-mail connector)

The `agent-mail` MCP is connected. It can send/receive emails. Useful for:
- Sending repair results to team members
- Automated notifications

---

## How GPT Should Work On This

1. **Read this file first** — it explains everything
2. **Understand the domain**: Amazon POD, 30x30cm heat transfer, PNG transparent background required
3. **Code lives in `modules/`** — never add flat files. New feature = new sub-directory under modules/
4. **`app.py` is routing only** — no business logic goes there
5. **Critical files to modify**:
   - `modules/repair/engine_v2.py` — the V2 repair engine
   - `modules/repair/__init__.py` — V1 repair (being replaced by V2)
   - `modules/quality/__init__.py` — image analysis and scoring
   - `modules/orders/__init__.py` — ZIP parsing and order processing
   - `templates/index.html` — frontend UI
6. **Testing**: `python3 -c "from app import app; ..."` 
7. **Deployment**: `bash server-deploy.sh` on the server after scp

### Priority Tasks

1. **Integrate V2 repair into repair route** — use `modules/repair/engine_v2.py` in `app.py`'s `/api/repair` and `/api/repair-batch`
2. **Add domain + HTTPS** — Nginx + Let's Encrypt
3. **Improve V2 engine robustness** — graceful fallback when OpenCV/rembg models fail
4. **Add progress tracking for batch repair** — WebSocket or polling for long-running repairs

---

## User Preferences (from memory)

- Called: Y同学
- AI called: Claw (🦹)
- Style: direct, no fluff
- Exchange rates: Bank of China daily rate minus 2%
- Shipping: Yuntu clothing line +10% buffer, Europe +3 euro tariff
- Existing spreadsheets: FBM定价, 出款收支, 每周汇总
