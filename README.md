# B站视频转写 → Obsidian Clippings

把哔哩哔哩视频转成带时间戳的 Markdown，自动存入 Obsidian 的 `Clippings\` 目录。

**混合策略**：有 AI 字幕的视频秒级抓字幕（100% 准确、零 GPU）；无字幕的视频用 faster-whisper + GPU 本地转录。支持单条、多条、整个多P系列批量处理。

## 功能特性

- 🎯 **字幕优先**：复用浏览器登录态抓取 B 站 AI 自动字幕（秒级、准确）
- 🔉 **转录兜底**：无字幕视频用 faster-whisper + NVIDIA GPU 本地离线转录（隐私、免费）
- 📦 **批量**：多条链接、整个多P系列、指定 P 范围/列表
- 📝 **统一格式**：frontmatter + 时间戳 + bilibili iframe，对齐 Obsidian Clippings 风格

## 依赖

- Python 3.10+
- `faster-whisper`（转录）、`yt-dlp`（抓音频）、`playwright`（驱动 Edge 抓字幕）
- ffmpeg（音频解码，项目内自带）
- NVIDIA GPU 可选（转录加速，CPU 也可用）

安装：
```bash
pip install -r requirements.txt
```

## 怎么用

**方式一（最简单）**：双击 `run.bat`，粘贴 B站链接，回车，等它转完。自动落到 `Clippings\`。

**方式二（命令行）**：
```bash
python transcribe.py "https://www.bilibili.com/video/BVxxxxx/" --out "D:\obsidian\Clippings"
```

## 混合策略：字幕优先，转录兜底

B 站很多视频有 **AI 自动字幕**（需登录态才能抓取）。抓字幕比 whisper 转录快得多（秒级、100% 准确、零 GPU）。脚本支持「有字幕抓字幕、无字幕转录」分工。

**① 探测系列字幕清单**（区分哪些集有字幕/无字幕）
```bash
venv\Scripts\python.exe detect_subs_via_edge.py
```
（需要 Edge 里 B 站已登录；会短暂弹出 Edge 窗口复用登录态，探测结果存 subs_result.json）

**② 批量抓取字幕 → Markdown**（有字幕的集）
```bash
venv\Scripts\python.exe fetch_subs_series.py --series BV1xqdrBeETc --series-name "计算机基础课程"
```

**③ 转录无字幕的集**
```bash
venv\Scripts\python.exe transcribe.py --series BV1xqdrBeETc --p "3,5,8" --series-name "计算机基础课程"
```
（`--p` 支持范围 `3-6`、单集 `4`、列表 `3,5,8`）

> 实测：BV1xqdrBeETc（计算机基础课程，40 集）31 集有 AI 字幕（秒级抓取）、9 集无字幕（GPU 转录）。

## 批量转写（三种模式）

**① 多个独立链接**：一次传多个链接，挨个转
```bash
venv\Scripts\python.exe transcribe.py "链接A" "链接B" "链接C"
```

**② 整个多P系列**：给一个 BV 号，自动转全部 P 集，每集自动命名
```bash
venv\Scripts\python.exe transcribe.py --series BV1xqdrBeETc --series-name "计算机基础课程"
```

**③ 指定 P 范围**：只转某几集（补缺/跳过已转的）
```bash
# 只转第 4~6 集
venv\Scripts\python.exe transcribe.py --series BV1xqdrBeETc --p 4-6 --series-name "计算机基础课程"
# 只转第 4 集
venv\Scripts\python.exe transcribe.py --series BV1xqdrBeETc --p 4-4 --series-name "计算机基础课程"
# 从第 5 集转到末尾
venv\Scripts\python.exe transcribe.py --series BV1xqdrBeETc --p 5- --series-name "计算机基础课程"
```

> 系列模式文件名自动生成：`系列名 p04 子标题.md`（如 `计算机基础课程 p04 4-组成原理-计算机指令介绍.md`）

**参数**：
| 参数 | 默认 | 说明 |
|---|---|---|
| 链接（位置参数） | — | 一个或多个 B站视频 URL |
| `--series` | — | 多P系列 BV 号，自动转全部 P |
| `--p` | — | 与 `--series` 配合：`3-6`（范围）`4`（单集）`4-`（到末尾） |
| `--series-name` | 标题截断 | 系列短名，用于文件名前缀 |
| `--out` | `D:\obsidian\Clippings` | 输出目录 |
| `--model` | `medium` | 模型档位：`small`（快/一般）`medium`（推荐/中文好）`large-v3`（最准/慢） |
| `--short-name` | — | 自定义文件名（仅单条链接时有效） |

## 工作流程（三段）

```
B站链接
 ① yt-dlp 抓音频(m4a) + 元信息（标题/UP主/日期/简介）
 ② faster-whisper GPU 转写（RTX 4060，medium 模型）
 ③ 生成 Clippings 风格 Markdown（frontmatter + [mm:ss] 时间戳 + bilibili iframe）
```

## 关键点

- **模型**：`D:\AI\Reasonix\models\faster-whisper-medium\`（~1.5GB，一次下载以后复用）。换档位时首次会自动去 HuggingFace 下载（走 hf-mirror 镜像 + 代理 127.0.0.1:7897，模型存 D 盘不占 C 盘）。
- **GPU**：优先用 NVIDIA 显卡，失败自动回退 CPU。转写速度：1 小时视频 GPU 约 5~15 分钟。
- **依赖**：项目内自带 ffmpeg（`ffmpeg\`）和 nvidia cublas DLL（`venv\`），无需系统级安装。

## 文件结构

```
bilibili-transcribe/
├── transcribe.py      # 主脚本：抓取 + 转写 + 排版
├── run.bat            # 双击运行（粘贴链接即可）
├── ffmpeg/            # 自带 ffmpeg + ffprobe（yt-dlp 转换用）
└── venv/              # Python 虚拟环境（含 faster-whisper、nvidia cublas）
```

## 生成笔记格式（对齐 Clippings 现有风格）

```markdown
---
title: "视频标题"
source: "B站链接"
author: "UP主"
published: 2026-08-01
created: 2026-08-27
description: "简介（前200字）"
tags:
  - "clippings"
---

<iframe ... bvid=xxx ...></iframe>

## Transcript

**00:00** · 第一句
**00:03** · 第二句
...
```

> 转写稿保持原始流水文本（不预分节），便于交给 ingest 流程提取概念、建概念页。
