#!/bin/bash
# === 服务器端一键部署脚本 ===
# 在服务器上运行: bash server-deploy.sh
set -e

APP_DIR="/opt/image-screener"
echo "=== PrintAI Studio 部署 ==="

# 1. 备份
echo "[1/6] 备份旧文件..."
cp $APP_DIR/app.py $APP_DIR/app.py.bak 2>/dev/null || true

# 2. 覆盖文件
echo "[2/6] 更新代码..."
cp app.py $APP_DIR/
cp run.py $APP_DIR/
cp requirements.txt $APP_DIR/

# 3. 覆盖 modules/
echo "[3/6] 更新模块..."
mkdir -p $APP_DIR/modules/auth $APP_DIR/modules/quality $APP_DIR/modules/repair $APP_DIR/modules/orders
cp modules/__init__.py $APP_DIR/modules/
cp modules/auth/__init__.py $APP_DIR/modules/auth/
cp modules/quality/__init__.py $APP_DIR/modules/quality/
cp modules/repair/__init__.py $APP_DIR/modules/repair/
cp modules/repair/engine_v2.py $APP_DIR/modules/repair/
cp modules/orders/__init__.py $APP_DIR/modules/orders/
cp modules/orders/exporter.py $APP_DIR/modules/orders/

# 4. 覆盖模板
echo "[4/6] 更新模板..."
mkdir -p $APP_DIR/templates
cp templates/login.html $APP_DIR/templates/
cp templates/index.html $APP_DIR/templates/

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
