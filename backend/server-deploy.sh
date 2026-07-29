#!/bin/bash
# === 服务器端一键部署脚本 ===
# 在服务器上运行: bash server-deploy.sh
# 前提: deploy-update.tar.gz 已解压到 /tmp/
set -e

APP_DIR="/opt/image-screener"
SRC_DIR="/tmp/backend"  # tarball 解压后 backend/ 在 /tmp/backend/

echo "=== PrintAI Studio 部署 ==="

# 1. 备份
echo "[1/6] 备份旧文件..."
cp $APP_DIR/app.py $APP_DIR/app.py.bak 2>/dev/null || true

# 2. 覆盖文件
echo "[2/6] 更新代码..."
cp $SRC_DIR/app.py $APP_DIR/
cp $SRC_DIR/run.py $APP_DIR/
cp $SRC_DIR/requirements.txt $APP_DIR/

# 3. 覆盖 modules/
echo "[3/6] 更新模块..."
mkdir -p $APP_DIR/modules/auth $APP_DIR/modules/quality $APP_DIR/modules/repair $APP_DIR/modules/orders
cp $SRC_DIR/modules/__init__.py $APP_DIR/modules/ 2>/dev/null || true
cp $SRC_DIR/modules/auth/__init__.py $APP_DIR/modules/auth/ 2>/dev/null || true
cp $SRC_DIR/modules/quality/__init__.py $APP_DIR/modules/quality/ 2>/dev/null || true
cp $SRC_DIR/modules/repair/__init__.py $APP_DIR/modules/repair/ 2>/dev/null || true
cp $SRC_DIR/modules/repair/engine_v2.py $APP_DIR/modules/repair/ 2>/dev/null || true
cp $SRC_DIR/modules/orders/__init__.py $APP_DIR/modules/orders/ 2>/dev/null || true
cp $SRC_DIR/modules/orders/exporter.py $APP_DIR/modules/orders/ 2>/dev/null || true

# 4. 覆盖模板
echo "[4/6] 更新模板..."
mkdir -p $APP_DIR/templates
cp $SRC_DIR/templates/login.html $APP_DIR/templates/
cp $SRC_DIR/templates/index.html $APP_DIR/templates/

# 5. 安装依赖
echo "[5/6] 安装 Python 依赖..."
pip3 install flask-login 2>&1 | tail -3

# 6. 重启服务
echo "[6/6] 重启服务..."
systemctl restart image-screener

sleep 2
systemctl status image-screener --no-pager | head -10

echo ""
echo "=== 部署完成 ==="
echo "访问: http://101.33.236.219:5051"
echo "密码: printai2024"
echo "修改密码: 编辑 /etc/systemd/system/image-screener.service 中的 APP_PASSWORD 后重启"
