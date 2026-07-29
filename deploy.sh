#!/bin/bash
# Local -> Server sync script
set -e
SERVER="root@101.33.236.219"
APP_DIR="/opt/image-screener"
echo "=== PrintAI Studio Deploy ==="

# Package files
tar czf /tmp/printai-deploy.tar.gz \
  app.py run.py requirements.txt \
  modules/ templates/ PROJECT.md \
  --exclude="__pycache__" --exclude="*.pyc"

# Upload
scp /tmp/printai-deploy.tar.gz $SERVER:/tmp/

# Deploy on server
ssh $SERVER "cd /tmp && tar xzf printai-deploy.tar.gz && bash server-deploy.sh"

echo "Done."
