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
  app.py              # Main Flask application (routes + logic)
  run.py              # Production startup (Waitress on :5051)
  image_repair_v2.py  # V2 repair engine (OpenCV + rembg) — WORK IN PROGRESS
  PROJECT.md          # This file — AI collaboration guide
  requirements.txt    # Python dependencies
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

## V2 Repair Engine (image_repair_v2.py — deploying next)

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

### Deployment Command (from local to server)

```bash
# Package and upload
tar czf screener.tar.gz -C /Users/dannychen/WorkBuddy/2026-07-06-10-52-55/image-screener \
  app.py run.py image_repair_v2.py templates/ requirements.txt

# Upload (need SSH access)
scp screener.tar.gz root@101.33.236.219:/opt/

# On server
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

## How Another AI Should Work On This

1. **Read this file first** — it explains everything
2. **Understand the domain**: Amazon POD, 30x30cm heat transfer, PNG transparent background required
3. **Critical files to modify**:
   - `app.py` — routes and V1 repair (being replaced)
   - `image_repair_v2.py` — the new repair engine (integrate into app.py)
   - `templates/index.html` — frontend UI
4. **Testing**: Run `python3 app.py` and use the test client
5. **Deployment**: Package via tar, scp to server, restart systemd

### Priority Tasks

1. **Integrate V2 repair engine into app.py** — replace all Pillow-only repair functions with OpenCV/rembg versions from `image_repair_v2.py`
2. **Add domain + HTTPS** — set up Nginx reverse proxy with Let's Encrypt
3. **Performance optimization** — V2 repair is CPU-heavy, consider parallel processing
4. **Add batch repair to order processing** — currently only screens, doesn't repair in batch mode

---

## User Preferences (from memory)

- Called: Y同学
- AI called: Claw (🦹)
- Style: direct, no fluff
- Exchange rates: Bank of China daily rate minus 2%
- Shipping: Yuntu clothing line +10% buffer, Europe +3 euro tariff
- Existing spreadsheets: FBM定价, 出款收支, 每周汇总
