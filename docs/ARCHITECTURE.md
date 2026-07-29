# PrintOS — System Architecture

## Overview

PrintOS 是亚马逊来图定制（POD）业务的内部工具平台，覆盖：图片质检 → AI 修复 → 排版 → 订单自动化。

```
┌─────────────┐
│   用户浏览器  │  (美工 / 运营)
└──────┬──────┘
       │ HTTPS
       ▼
┌─────────────┐
│    Nginx     │  (443 反代 → 127.0.0.1:5051)
└──────┬──────┘
       │
       ▼
┌─────────────┐
│   Flask App  │  (Waitress WSGI, threads=12)
│   app.py     │  ← 纯路由层，不包含业务逻辑
└──────┬──────┘
       │
       ▼
┌─────────────────────────────────────────┐
│              modules/                    │
│  ┌─────────┐ ┌──────────┐ ┌──────────┐ │
│  │  auth   │ │ quality  │ │  repair  │ │
│  │ 登录/会话│ │ 图片质检  │ │ AI 修复  │ │
│  └─────────┘ └──────────┘ └──────────┘ │
│  ┌─────────┐                            │
│  │ orders  │                            │
│  │ 订单处理 │                            │
│  └─────────┘                            │
└─────────────────────────────────────────┘
```

## Tech Stack

| Layer | Technology |
|-------|-----------|
| Frontend | Vanilla HTML/CSS/JS (Jinja2 templates) |
| Backend | Python 3, Flask |
| WSGI Server | Waitress (production) |
| Image Processing | Pillow, OpenCV, rembg (U2Net) |
| ML Models | EDSR_x4 (super-resolution), u2net (background removal) |
| Excel Export | openpyxl |
| Auth | Flask session + environment variable password |
| Deployment | systemd, Nginx, Let's Encrypt |
| Version Control | Git → GitHub Private Repo |

## Directory Structure

```
printos/
├── backend/           # Flask 应用（当前 image-screener 代码）
│   ├── app.py         # 路由入口
│   ├── run.py         # 生产启动
│   ├── modules/       # 业务模块
│   │   ├── auth/      # 登录/会话
│   │   ├── quality/   # 图片质检
│   │   ├── repair/    # AI 修复引擎
│   │   └── orders/    # 订单处理
│   └── templates/     # Jinja2 模板
├── frontend/          # 未来独立前端（React/Vue）
├── docs/              # 文档
│   ├── ROADMAP.md
│   ├── TASK.md
│   ├── CHANGELOG.md
│   └── ARCHITECTURE.md
├── dataset/           # AI 训练数据
│   ├── gold/          # 100 组标准样本
│   ├── train/         # 训练集
│   └── test/          # 测试集
├── docker/            # Docker 配置（未来）
├── scripts/           # 运维脚本
├── nginx/             # Nginx 配置
└── tests/             # 单元测试
```

## API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | ✅ | 主页面（重定向到登录） |
| GET/POST | `/login` | ❌ | 登录页 |
| GET | `/logout` | ✅ | 退出 |
| POST | `/api/screen` | ✅ | 单张图片质检 |
| POST | `/api/repair` | ✅ | 单张图片修复 |
| POST | `/api/repair-batch` | ✅ | 批量修复 |
| POST | `/api/batch-orders` | ✅ | 解析订单 ZIP |
| POST | `/api/export-excel` | ✅ | 导出 Excel |
| GET | `/api/download/<id>` | ✅ | 下载修复后图片 |
| GET | `/outputs/<path>` | ✅ | 静态文件访问 |

## Quality Check Dimensions

| 维度 | 算法 | 阈值 |
|------|------|------|
| 分辨率 | DPI @ 30×30cm | ≥ 150 DPI |
| 清晰度 | Laplacian 方差 | ≥ 100 |
| 噪点 | 高频分量比率 | ≤ 0.15 |
| 对比度 | 像素标准差 | ≥ 30 |
| 颜色均匀度 | 网格亮度 CV | ≤ 0.20 |
| 边缘质量 | Sobel 梯度方向一致性 | ≥ 0.6 |
| 格式 | PNG 透明底检查 | 必须有 alpha 通道 |

## Repair Engine

### V1 (当前生效 — Pillow)
- Lanczos 超分 → MedianFilter 降噪 → UnsharpMask 锐化 → CLAHE 对比度
- **效果有限，即将下线**

### V2 (已编写，待部署 — OpenCV + rembg)
- EDSR x4 真实超分 → NL-Means 降噪 → DetailEnhance 锐化 → CLAHE
- rembg (U2Net) AI 去背景 → 自适应边缘平滑 → 透明底导出
- 需要服务器安装: `opencv-python-headless`, `rembg`, `onnxruntime`

## Development Workflow

```
GitHub (代码仓库)
    │
    ▼
WorkBuddy (Claw 开发)
    │
    ▼
Y同学 (架构设计 + Code Review)
    │
    ▼
腾讯云 (101.33.236.219)
    │
    ▼
美工测试
    │
    ▼
继续迭代
```

**铁律**: 本地开发 → Git 提交 → 推送 GitHub → 部署到腾讯云。**不在服务器上直接改代码。**

---

*最后更新: 2026-07-29*
