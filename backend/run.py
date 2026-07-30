"""图片质检工具 - 生产环境启动"""
import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# 清理旧文件
for d in ['uploads', 'outputs']:
    path = os.path.join(os.path.dirname(__file__), d)
    if os.path.exists(path):
        now = time.time()
        for f in os.listdir(path):
            fp = os.path.join(path, f)
            if os.path.isfile(fp) and now - os.path.getmtime(fp) > 7 * 86400:
                os.remove(fp)

# PIL 预热：加载并丢弃以触发惰性初始化
from PIL import Image, ImageFilter
_warm = Image.new('RGB', (100, 100))
_warm.filter(ImageFilter.GaussianBlur(radius=1))
del _warm

from waitress import serve
from app import app

port = int(os.environ.get("PORT", "5051"))
print(f"PrintAI Studio 已启动: http://0.0.0.0:{port}")
serve(app, host='0.0.0.0', port=port, threads=8, channel_timeout=300)
