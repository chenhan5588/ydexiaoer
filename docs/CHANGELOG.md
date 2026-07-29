# PrintOS — Changelog

## [2026-07-29] 模块化重构

### 变更
- `app.py` 拆分为纯路由层，业务逻辑移入 `modules/`
- 新增 `modules/auth/` — login_required 装饰器
- 新增 `modules/quality/` — analyze_image, 边缘检测, 颜色均匀度检测
- 新增 `modules/repair/` — V1 Pillow 修复 + V2 OpenCV 引擎
- 新增 `modules/orders/` — ZIP 解析, 订单处理, Excel 导出

### 新增
- 登录页 (`templates/login.html`)，密码环境变量控制
- V2 修复引擎 (`modules/repair/engine_v2.py`) — OpenCV 超分 + CLAHE + rembg
- `PROJECT.md` — AI 协作文档

### 修复
- 修复引擎放大算法优化：填满短边式 → 避免 2100 万像素
- 并行处理：ThreadPoolExecutor(4) → 分析 ~6s/2图（3.7x 提速）

---

## [2026-07-28] V1.0 初始版本

### 新增
- Flask 应用 `app.py`，图片质检 + 修复 API
- `templates/index.html` — 双 Tab 界面（图片质检 / 订单批量处理）
- 质检维度：分辨率、清晰度、噪点、对比度、颜色均匀度、边缘质量
- V1 修复：Lanczos 放大、中值滤波、UnsharpMask、直方图均衡
- 订单 ZIP 自动解析（嵌套解压、JSON 订单信息、效果图/来图匹配）
- Excel 导出（openpyxl，嵌入图片）
- 生产部署：Waitress + systemd（image-screener 服务）
- 开机自动清理 7 天旧文件

---

*约定格式: [YYYY-MM-DD] 变更类型 → 具体内容*
