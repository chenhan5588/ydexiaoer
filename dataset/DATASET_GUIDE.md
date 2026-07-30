# DATASET_GUIDE.md — PrintOS 数据标注规范

> 本指南面向美工和标注人员。按此规范新增样本，AI 就能持续学习你的操作经验。
> 版本：V1.0 | 更新：2026-07-30

---

## 1. 目录结构总览

```
dataset/
├── v1/                        # 标准样本库（当前使用）
│   ├── README.md              # 样本统计 + 变换分类说明
│   ├── 001/                   # 每个样本一个目录，三位数编号
│   │   ├── input.png          # 客户原始来图
│   │   ├── output.png         # 美工修复后的标准图
│   │   └── metadata.json      # 操作记录（关键！）
│   └── ...
├── failed/                    # AI 失败案例库（持续积累）
│   ├── README.md
│   └── 001/
│       ├── input.png          # 原始来图
│       ├── ai_output.png      # AI 自动修复的结果
│       ├── final_manual.png   # 人工最终修复结果
│       ├── reason.txt         # 失败原因说明
│       └── metadata.json
├── benchmark/
│   └── test_cases.json        # 自动化测试用例
├── gold/                      # 旧版目录（迁移中，不再新增）
├── train/                     # 训练集（预留）
└── test/                      # 测试集（预留）
```

---

## 2. 新增样本流程

### 步骤 1：找到下一个编号

```bash
# 查看当前最大编号
ls dataset/v1/ | tail -1
# 如果是 012，下一个就是 013
```

### 步骤 2：准备文件

```
013/
├── input.png       # 客户原始图（不改名，保留原格式）
└── output.png      # 美工修好的标准图（强制 PNG 透明底）
```

**命名规则**：
- `input.*` — 必须叫 `input`，扩展名保留原格式（`.png` / `.jpg` / `.jpeg`）
- `output.png` — 必须叫 `output`，**强制 PNG 格式**

### 步骤 3：填写 metadata.json

复制模板：

```json
{
  "type": "",
  "problem": [],
  "human_action": [],
  "difficulty": 0,
  "print_info": {
    "method": "DTF",
    "target_size_cm": 30,
    "material": "cotton"
  },
  "time_minutes": 0,
  "notes": ""
}
```

按照下面的字段说明填写（见第 3 节）。

### 步骤 4：提交

```bash
git add dataset/v1/013/
git commit -m "dataset/v1: 新增样本 013 — [简述]"
git push origin main
```

---

## 3. metadata.json 字段说明

### 3.1 type — 图片类型（必填）

| 值 | 含义 | 典型特征 |
|---|---|---|
| `logo` | 品牌 Logo | 文字/图形组合，纯色背景 |
| `photo_to_digital` | 实物照片转数字 | 有摩尔纹、反光、拍摄角度 |
| `screenshot_extract` | 截图提取主体 | 带水印、UI 元素、手机状态栏 |
| `illustration` | 插画/手绘 | 线条复杂，颜色丰富 |
| `text_only` | 纯文字 | 只有文字，无图形 |
| `pattern` | 连续图案 | 需要无缝拼接 |

### 3.2 problem — 原始图问题列表

**可多选**，下面是最常见的标签：

| 标签 | 含义 |
|---|---|
| `low_resolution` | 分辨率不足（< 5906px 任一维度） |
| `dark_background` | 深色/黑色背景 |
| `textured_background` | 纹理/渐变背景 |
| `complex_background` | 复杂场景背景 |
| `no_transparency` | 没有透明通道 |
| `moire_pattern` | 摩尔纹 |
| `glare` | 反光 |
| `reflection` | 反射 |
| `warped_photo` | 拍摄角度歪斜 |
| `low_quality_photo` | 照片画质差 |
| `watermark` | 带水印 |
| `screenshot_ui` | 截图带 UI 元素 |
| `text_overlay` | 文字叠层 |
| `oversized` | 图片过大（> 8000px） |
| `jagged_edge` | 边缘锯齿 |
| `color_shift` | 颜色偏差 |
| `blurry` | 模糊 |
| `noise` | 噪点 |
| `orientation_fix` | 方向需要修正 |

### 3.3 human_action — 美工操作记录

**按操作先后顺序列出**：

| 标签 | 含义 | 工具 |
|---|---|---|
| `remove_background` | 去除背景 | PS 魔棒/钢笔/通道 |
| `upscale_to_5906` | 放大到 5906px | PS 图像大小 / AI 放大 |
| `downscale_to_5906` | 缩小到 5906px | PS 图像大小 |
| `auto_crop` | 自动裁切多余空白 | PS 裁切工具 |
| `crop_subject` | 手动裁出主体 | PS 裁切工具 |
| `edge_smooth` | 边缘平滑 | PS 羽化/平滑 |
| `remove_watermark` | 去除水印 | PS 修补工具 |
| `remove_ui_elements` | 去除 UI 元素 | PS 修补工具 |
| `manual_redraw` | 手工重绘 | PS / Illustrator |
| `vectorize` | 转矢量 | Illustrator 描摹 |
| `color_correction` | 颜色校正 | PS 色阶/曲线 |
| `color_enhance` | 颜色增强 | PS 饱和度/自然饱和度 |
| `denoise` | 降噪 | PS 降噪滤镜 |
| `sharpen` | 锐化 | PS 锐化/USM |
| `rotate_correct` | 旋转修正 | PS 自由变换 |
| `find_font` | 查找匹配字体 | WhatFont / 字体库 |

### 3.4 difficulty — 难度等级

| 值 | 含义 | 判断标准 | AI 能自动通过？ |
|---|---|---|---|
| `1` | 简单 | 纯色背景 Logo，去背景即完成 | ✅ 是 |
| `2` | 普通 | 需放大 + 去背景 + 边缘修正 | ✅ 大部分 |
| `3` | 困难 | 截图提取 / 复杂照片转数字 | ⚠️ 部分 |
| `4` | 极难 | 实物照片重绘 / 严重损坏 | ❌ 需人工 |

### 3.5 print_info — 打印信息（固定值）

目前所有样本统一：
```json
{
  "method": "DTF",
  "target_size_cm": 30,
  "material": "cotton"
}
```

未来如果扩展其他打印方式（丝印、热转印），再补充。

### 3.6 time_minutes — 人工耗时（估算）

记录美工实际修这张图花了多少分钟。这是重要的成本数据。

### 3.7 notes — 备注

自由文字，记录任何额外的注意事项。例如：
- "客户要求保留右下角签名"
- "这张文字需要重新找字体 Wingdings"
- "主体和背景颜色太接近，钢笔工具很难描"

---

## 4. 标注示例

### 示例 1：简单 Logo

```json
{
  "type": "logo",
  "problem": ["dark_background", "no_transparency"],
  "human_action": ["remove_background", "auto_crop"],
  "difficulty": 1,
  "print_info": {"method": "DTF", "target_size_cm": 30, "material": "cotton"},
  "time_minutes": 3,
  "notes": "纯黑底白字，一键去底完成"
}
```

### 示例 2：低分辨率放大

```json
{
  "type": "logo",
  "problem": ["low_resolution", "dark_background", "jagged_edge"],
  "human_action": ["upscale_to_5906", "remove_background", "edge_smooth"],
  "difficulty": 2,
  "print_info": {"method": "DTF", "target_size_cm": 30, "material": "cotton"},
  "time_minutes": 8,
  "notes": "1206px 放大到 5906px，放大后边缘有锯齿，需要手动羽化"
}
```

### 示例 3：实物照片重绘

```json
{
  "type": "photo_to_digital",
  "problem": ["moire_pattern", "glare", "low_quality_photo", "color_shift"],
  "human_action": ["manual_redraw", "vectorize", "remove_background", "color_enhance"],
  "difficulty": 4,
  "print_info": {"method": "DTF", "target_size_cm": 30, "material": "cotton"},
  "time_minutes": 30,
  "notes": "客户拍的 T 恤实物照片，摩尔纹严重，颜色偏暗。用 Illustrator 手动描摹重绘"
}
```

### 示例 4：截图提取

```json
{
  "type": "screenshot_extract",
  "problem": ["watermark", "screenshot_ui", "text_overlay"],
  "human_action": ["crop_subject", "remove_watermark", "remove_ui_elements"],
  "difficulty": 3,
  "print_info": {"method": "DTF", "target_size_cm": 30, "material": "cotton"},
  "time_minutes": 15,
  "notes": "Facebook 截图，有 itstrendbuzz 水印和手机状态栏。先裁出主体区域，再用修补工具去掉水和 UI"
}
```

---

## 5. 失败案例标注（failed/ 目录）

当 AI 自动修复的结果**不通过人工审核**时，记录到这里。

### 失败案例 metadata.json

```json
{
  "fail_reason": "background_residue",
  "fail_detail": "AI 去背景后在文字边缘留下了一圈白边，约 2px 宽",
  "severity": "major",
  "expected_action": "remove_background_clean",
  "ai_model": "V2-rule-based",
  "timestamp": "2026-07-30",
  "fix_by_human": "用 Photoshop 钢笔工具重新描边，导出时勾选'消除锯齿'",
  "human_time_minutes": 10
}
```

### reason.txt

纯文本，写清楚：输入图的问题 → AI 做了什么 → 哪里不对 → 人工怎么修的。

---

## 6. 质量标准速查

### 合格输出图标准

| 标准 | 要求 |
|---|---|
| 格式 | PNG |
| 色彩模式 | RGBA（带透明通道） |
| 尺寸 | 5906 × 5906 px（或不超过此范围） |
| 分辨率 | 300 DPI @ 30×30cm |
| 背景 | 完全透明，无白边 |
| 边缘 | 平滑无锯齿 |
| 水印 | 完全去除 |

### 常见返工原因

- ❌ 透明底有白边残留
- ❌ 边缘锯齿明显
- ❌ 放大后文字变模糊
- ❌ 颜色与原图偏差大
- ❌ 裁切时裁掉了主体

---

## 7. 数据统计

维护一个计数器，方便追踪数据量增长：

```
当前 V1 样本数：12
失败案例数：0
总美工耗时：~129 分钟
```

---

## 8. 附录：标签速查卡

### problem 常用标签

```
low_resolution    dark_background    textured_background
complex_background  no_transparency  moire_pattern
glare             reflection        warped_photo
low_quality_photo watermark         screenshot_ui
text_overlay      oversized         jagged_edge
color_shift       blurry            noise
orientation_fix
```

### human_action 常用标签

```
remove_background   upscale_to_5906    downscale_to_5906
auto_crop           crop_subject       edge_smooth
remove_watermark    remove_ui_elements  manual_redraw
vectorize           color_correction   color_enhance
denoise             sharpen            rotate_correct
find_font
```

### type 选项

```
logo    photo_to_digital    screenshot_extract
illustration    text_only    pattern
```

---

> **记住**：这个目录是 PrintOS 最核心的资产。每次标注花 2 分钟，未来 AI 能为你省下 20 分钟。
