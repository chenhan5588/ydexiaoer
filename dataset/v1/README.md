# Dataset V1 — 修图标准样本集

> 📋 标注规范请参考 **[DATASET_GUIDE.md](../DATASET_GUIDE.md)** — 新增样本前必读

## 目录结构

```
dataset/v1/
├── README.md          # 本文件
├── 001/               # 样本 001
│   ├── input.png      # 客户原始来图 (before)
│   ├── output.png     # 美工修图标准 (after)
│   └── metadata.json  # 操作记录（问题/操作/难度/耗时）
├── 002/
│   ├── input.png
│   ├── output.png
│   └── metadata.json
├── ...
└── 012/
    ├── input.png
    ├── output.png
    └── metadata.json
```

**命名规范**：
- 目录：三位数字编号 `001` ~ `012`
- 文件：`input.*` = 原始图，`output.png` = 标准图
- input 格式可以是 jpg/png，output 统一 PNG
- 每样本必须包含 `metadata.json`（标注操作记录）

---

## 12 组样本概览

| ID | Input 尺寸 | Output 尺寸 | 类型 | 问题 | 操作 | 难度 | 耗时 |
|---|---|---|---|---|---|---|---|
| 001 | 5906×5906 | 2111×2276 | logo | 黑底/无透明 | 去背景+裁切 | 1 | 3min |
| 002 | 1024×1024 | 5906×5906 | logo | 低分辨率/黑底 | 放大+去背景 | 2 | 5min |
| 003 | 1206×985 | 5906×5906 | logo | 低分辨率/黑底 | 放大+去背景 | 2 | 5min |
| 004 | 1365×2048 | 5906×5906 | logo | 低分辨率/纹理背景 | 去背景+放大 | 2 | 5min |
| 005 | 8000×8000 | 5906×5906 | logo | 超大图/无透明 | 去背景+缩小 | 1 | 3min |
| 006 | 2767×3597 | 5906×5906 | 实物→重绘 | 摩尔纹/反光/低质 | 手工重绘+矢量化 | 4 | 30min |
| 007 | 1024×776 | 5906×5906 | 实物→重绘 | 反光/反射/歪斜 | 手工重绘+颜色校正 | 4 | 25min |
| 008 | 1254×1254 | 5906×5906 | logo | 低分辨率/复杂背景 | 去背景+放大+边缘平滑 | 2 | 8min |
| 009 | 1458×1625 | 5906×5906 | 实物→重绘 | 照片质量/非白背景 | 手工重绘+颜色增强 | 3 | 20min |
| 010 | 4320×9600 | 5906×5906 | 截图提取 | 水印/UI/文字叠层 | 裁切主体+去水印+去UI | 3 | 15min |
| 011 | 5906×4134 | 5906×5906 | logo | 黑底/无透明/方向 | 去背景+旋转+裁切 | 2 | 5min |
| 012 | 7400×3600 | 5906×5906 | logo | 超大图/复杂背景 | 去背景+缩小 | 2 | 5min |

---

## 四种变换类型

### A. 去背景 → 透明底（4 组：001, 005, 010, 011）
- Input：RGB/RGBA 带背景（纯色/纹理/深色）
- Output：RGBA 透明底，仅保留主体图案
- 关键操作：背景移除，Alpha 通道生成

### B. 放大 + 透明底（5 组：002, 003, 004, 008, 012）
- Input：小尺寸 RGB/RGBA（~1000-1500px）
- Output：5906×5906 RGBA 透明底
- 关键操作：超分辨率放大（2-5x）+ 去背景

### C. 实物照片 → 数字重绘（3 组：006, 007, 009）
- Input：JPG 实物照片（反光/摩尔纹/褶皱）
- Output���5906×5906 RGBA 干净数字图
- 关键操作：去摩尔纹 + 平滑 + 颜色归一化 + 放大

### D. 特殊变换
- **005**：8000×8000 → 5906×5906，超大图缩小 + 去背景
- **001**：5906×5906 → 2111×2276，仅去背景，尺寸缩小（保持原始比例）
- **010**：4320×9600 竖长图 → 5906×5906 正方形，需裁切/填充 + 去背景

---

## 输出标准

| 属性 | 标准 |
|---|---|
| 尺寸 | 目标 5906×5906px（30×30cm @ 500DPI） |
| 格式 | PNG，RGBA 透明底 |
| 背景 | 完全透明，无残留白边/黑边 |
| 颜色 | 保真，无色偏 |
| 边缘 | 平滑，无锯齿/坑洼 |

---

## 难度分布

| 难度 | 数量 | 样本 | AI 可自动？ |
|---|---|---|---|
| 1 (简单) | 2 | 001, 005 | ✅ |
| 2 (普通) | 6 | 002, 003, 004, 008, 011, 012 | ✅ 大部分 |
| 3 (困难) | 2 | 009, 010 | ⚠️ 部分 |
| 4 (极难) | 2 | 006, 007 | ❌ 需人工 |

---

## 使用方式

### 评估修��质量
```python
import json
from PIL import Image

pair_id = "001"

# 加载样本
input_img = Image.open(f"dataset/v1/{pair_id}/input.png")
output_img = Image.open(f"dataset/v1/{pair_id}/output.png")

# 加载标注
with open(f"dataset/v1/{pair_id}/metadata.json") as f:
    meta = json.load(f)
    print(f"类型: {meta['type']}, 难度: {meta['difficulty']}")

# 用修复引擎处理 input
repaired = repair_engine.process(input_img)

# 对比 repaired vs output（标准答案）
ssim_score = calculate_ssim(repaired, output_img)
```

### 扩展新样本
```bash
# 见 DATASET_GUIDE.md 完整流程
mkdir dataset/v1/013
cp customer_original.jpg dataset/v1/013/input.jpg
cp retoucher_final.png    dataset/v1/013/output.png
# 然后填写 metadata.json
```

---

## 统计

- 总样本：12 组
- 总大小：~185MB
- metadata：12 个 JSON 文件
- Input 尺寸范围：1024×776 ~ 8000×8000
- Output 尺寸：目标 5906×5906（001 例外：2111×2276）
- Input 格式：8 PNG + 4 JPG
- Output 格式：全部 PNG RGBA
- 总美工耗时：~129 分钟
