#!/bin/bash
# === 服务器端一键部署脚本 ===
# 在服务器上运行: bash server-deploy.sh
set -e

APP_DIR="/opt/image-screener"
echo "=== PrintAI Studio 部署 ==="

# 1. 备份
echo "[1/5] 备份旧文件..."
cp $APP_DIR/app.py $APP_DIR/app.py.bak 2>/dev/null || true

# 2. 覆盖文件
echo "[2/5] 更新代码..."
cp app.py $APP_DIR/
cp run.py $APP_DIR/
cp image_repair_v2.py $APP_DIR/
cp requirements.txt $APP_DIR/
mkdir -p $APP_DIR/templates
cp templates/login.html $APP_DIR/templates/
cp templates/index.html $APP_DIR/templates/

# 3. 安装新依赖（Flask-Login）
echo "[3/5] 安装 Python 依赖..."
pip3 install flask-login 2>&1 | tail -3

# 4. 确保环境变量（默认密码 printai2024）
echo "[4/5] 配置环境变量..."
if ! grep -q "APP_PASSWORD" /etc/systemd/system/image-screener.service 2>/dev/null; then
    sed -i '/\[Service\]/a Environment=APP_PASSWORD=printai2024' /etc/systemd/system/image-screener.service
    systemctl daemon-reload
fi

# 5. 重启服务
echo "[5/5] 重启服务..."
systemctl restart image-screener

sleep 2
systemctl status image-screener --no-pager | head -10

echo ""
echo "=== 部署完成 ==="
echo "访问: http://101.33.236.219:5051"
echo "密码: printai2024"
echo "修改密码: 编辑 /etc/systemd/system/image-screener.service 中的 APP_PASSWORD 后重启"
