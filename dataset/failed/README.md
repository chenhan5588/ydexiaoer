# Failed Cases — AI 失败案例库

## 目的

记录 AI 自动修复**无法通过**或**需要人工介入**的案例。
AI 学会"什么不能做"比学会"怎么做"更重要。

## 目录结构

```
failed/
├── README.md               # 本文件
├── 001/                    # 失败案例编号
│   ├── input.png           # 客户原始来图
│   ├── ai_output.png       # AI 自动修复的结果
│   ├── final_manual.png    # 人工最终修复结果
│   ├── reason.txt          # 失败原因（纯文本说明）
│   └── metadata.json       # 结构化失败数据
└── ...
```

## metadata.json 格式

```json
{
  "fail_reason": "ai_removed_text",       // 失败原因代号
  "fail_detail": "AI 去背景时把文字也删除了",
  "severity": "critical",                 // critical / major / minor
  "expected_action": "keep_text",
  "ai_model": "V2-rule-based",
  "timestamp": "2026-07-30",
  "fix_by_human": "手动用 Photoshop 钢笔工具描边后重新导出",
  "human_time_minutes": 15
}
```

## 失败原因代号

| 代号 | 含义 |
|---|---|
| ai_removed_text | AI 误删了文字 |
| background_residue | 背景残留白边 |
| color_shift | 颜色偏差/变淡 |
| edge_jagged | 边缘锯齿/不平滑 |
| lost_detail | 丢失了细小细节 |
| over_smooth | 过度平滑导致模糊 |
| wrong_crop | 裁切错误，裁掉了主体 |
| watermark_fail | 水印去除不干净 |

## 使用方式

1. AI 跑一遍修复 → 输出 `ai_output.png`
2. 人工检查不通过 → 创建新目录 `dataset/failed/{编号}/`
3. 填入原始图、AI 结果、人工最终结果
4. 写 reason.txt 和 metadata.json
5. 未来用这些数据训练 AI 识别"不能做什么"

## 当前状态

- 案例数：0
- 待采集：新 AI 引擎上线后自动积累
