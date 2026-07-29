#!/bin/bash
# PrintAI Studio — Deploy to Tencent Cloud
# Usage: ./deploy.sh

set -e

SERVER="root@101.33.236.219"
APP_DIR="/opt/image-screener"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "=== PrintAI Studio Deploy ==="
echo "Server: $SERVER"
echo ""

# 1. Package
echo "[1/4] Packaging..."
cd "$LOCAL_DIR"
tar czf /tmp/screener-deploy.tar.gz \
  app.py run.py image_repair_v2.py \
  templates/ requirements.txt PROJECT.md \
  2>/dev/null
echo "      Package: /tmp/screener-deploy.tar.gz ($(du -h /tmp/screener-deploy.tar.gz | cut -f1))"

# 2. Upload
echo "[2/4] Uploading to server..."
scp /tmp/screener-deploy.tar.gz "$SERVER:/tmp/" 2>/dev/null || {
  echo "      SSH failed. Transfer manually:"
  echo "      scp /tmp/screener-deploy.tar.gz $SERVER:/tmp/"
  exit 1
}

# 3. Extract & install
echo "[3/4] Installing on server..."
ssh "$SERVER" << 'REMOTE_EOF'
  set -e
  cd /tmp
  tar xzf screener-deploy.tar.gz -C /opt/image-screener/

  # Install dependencies
  pip3 install flask waitress pillow openpyxl 2>/dev/null

  # V2 deps (optional — install only if models are available)
  pip3 install opencv-python-headless rembg onnxruntime 2>/dev/null || echo "      [warn] opencv/rembg install failed (may need system deps)"

  # Restart service
  systemctl restart image-screener 2>/dev/null || echo "      [warn] systemctl not available, start manually"
  echo "      Deployed!"
REMOTE_EOF

# 4. Verify
echo "[4/4] Verifying..."
sleep 2
curl -s -o /dev/null -w "      HTTP %{http_code}" "http://101.33.236.219:5051/login" 2>/dev/null || echo "      Cannot reach server"

echo ""
echo "=== Done ==="
echo "Login: http://101.33.236.219:5051/login"
echo "Password: printai2024 (change via APP_PASSWORD env)"
