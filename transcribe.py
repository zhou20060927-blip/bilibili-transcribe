#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
B 站视频 → 音频 → Whisper 转写 → Clippings 风格 Markdown
工作流：yt-dlp 抓音频 → faster-whisper(GPU) 转写 → 生成带时间戳的 Markdown
用法：
  python transcribe.py <B站视频URL> [--out DIR] [--model medium]
"""
import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path

# Windows 控制台默认 GBK，无法打印 emoji/特殊字符，强制 UTF-8 输出
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# 用项目内自带的 ffmpeg（含 ffmpeg.exe + ffprobe.exe），yt-dlp 转换和 faster-whisper 解码都需要
FFMPEG_DIR = str(Path(__file__).resolve().parent / "ffmpeg" / "ffmpeg-9.0.1-essentials_build" / "bin")
os.environ["PATH"] = FFMPEG_DIR + os.pathsep + os.environ["PATH"]
FFMPEG_LOCATION = os.path.join(FFMPEG_DIR, "ffmpeg.exe")

# 把 nvidia pip 包的 CUDA 运行库（cublas64_12.dll 等）加进 PATH，供 ctranslate2 GPU 推理加载
NVIDIA_BIN_DIR = str(Path(__file__).resolve().parent / "venv" / "Lib" / "site-packages" / "nvidia" / "cublas" / "bin")
if os.path.isdir(NVIDIA_BIN_DIR):
    os.environ["PATH"] = NVIDIA_BIN_DIR + os.pathsep + os.environ["PATH"]

WORK_DIR = Path(__file__).resolve().parent
CLIPPINGS_DIR = Path("D:/obsidian/Clippings")

# 本机代理（模型下载走代理更稳；抓 B 站直连即可）。仅在代理可用时设置，否则退回直连
if not (os.environ.get("HTTPS_PROXY") or os.environ.get("HTTP_PROXY")):
    import socket
    try:
        s = socket.create_connection(("127.0.0.1", 7897), timeout=2)
        s.close()
        os.environ["HTTPS_PROXY"] = "http://127.0.0.1:7897"
        os.environ["HTTP_PROXY"] = "http://127.0.0.1:7897"
        os.environ["ALL_PROXY"] = "http://127.0.0.1:7897"
        print("    检测到代理 127.0.0.1:7897，模型下载走代理")
    except OSError:
        print("    未检测到代理，直连")

# 模型缓存固定到 D 盘（用户要求模型放 D:\AI，不占 C 盘）
MODELS_DIR = Path("D:/AI/Reasonix/models")
MODELS_DIR.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(MODELS_DIR))

# 国内下载 HuggingFace 模型：用 hf-mirror 镜像 + 关闭 Xet（镜像不支持 Xet 协议）
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

def sanitize_filename(name: str, max_len: int = 80) -> str:
    """清理非法文件名字符（Windows）"""
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip().rstrip('.')
    return name[:max_len]

def fetch_audio(url: str, workdir: Path):
    """用 yt-dlp 抓取音频 + 元信息。返回 (音频路径, 元信息 dict)。"""
    outtmpl = str(workdir / "audio.%(ext)s")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-f", "bestaudio/best",
        "-x", "--audio-format", "m4a",
        "--audio-quality", "0",
        "--ffmpeg-location", FFMPEG_LOCATION,
        "-o", outtmpl,
        "--no-playlist",
        "--write-info-json",
        "--no-warnings",
        "--no-progress",
        url,
    ]
    print("[1/3] 抓取音频...")
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("yt-dlp stderr:", r.stderr[-3000:])
        raise RuntimeError("yt-dlp 抓取失败")

    audio = None
    info = None
    for p in workdir.glob("audio.*"):
        if p.suffix.lower() in (".m4a", ".mp3", ".wav", ".opus", ".webm", ".aac"):
            audio = p
    info_json = workdir / "audio.info.json"
    if info_json.exists():
        info = json.loads(info_json.read_text(encoding="utf-8"))

    if not audio:
        raise RuntimeError("未找到抓取到的音频文件")
    if not info:
        raise RuntimeError("未找到元信息文件")
    return audio, info

def fmt_ts(seconds: float) -> str:
    """秒 → mm:ss"""
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"

def transcribe(audio: Path, model_size: str, workdir: Path):
    """faster-whisper GPU 转写，返回带时间戳的段落列表。"""
    from faster_whisper import WhisperModel

    # 优先用本地模型目录（已下载到 D:\AI\Reasonix\models\faster-whisper-medium）
    local_model = MODELS_DIR / f"faster-whisper-{model_size}"
    if model_size == "large-v3":
        local_model = MODELS_DIR / "faster-whisper-large-v3"
    if local_model.is_dir() and (local_model / "model.bin").exists():
        model_path = str(local_model)
        print(f"[2/3] 加载本地模型 {model_path}...")
    else:
        model_path = model_size
        print(f"[2/3] 加载模型 {model_size}（将下载到 {MODELS_DIR}）...")

    # GPU 优先，失败回退 CPU
    try:
        model = WhisperModel(model_path, device="cuda", compute_type="float16")
        print("    使用 GPU 推理")
    except Exception as e:
        print(f"    GPU 不可用({e})，回退 CPU int8")
        model = WhisperModel(model_path, device="cpu", compute_type="int8")

    print("    转写中...")
    segments, info = model.transcribe(
        str(audio),
        language="zh",
        vad_filter=True,
        beam_size=5,
    )
    out = []
    for seg in segments:
        out.append({
            "start": seg.start,
            "end": seg.end,
            "text": seg.text.strip(),
        })
    return out, info

def build_markdown(meta: dict, segments: list, url: str) -> str:
    """生成 Clippings 风格 Markdown"""
    title = meta.get("title", "B站视频")
    author = meta.get("uploader") or meta.get("channel") or "未知UP主"
    published = ""
    if meta.get("upload_date"):
        try:
            published = datetime.strptime(str(meta["upload_date"]), "%Y%m%d").strftime("%Y-%m-%d")
        except ValueError:
            published = ""
    description = (meta.get("description") or "").strip()
    desc_short = re.sub(r"\s+", " ", description)[:200]

    bvid = meta.get("bvid") or meta.get("id") or ""
    # 多P视频：id 带 _pN 后缀（如 BV1xqdrBeETc_p3），提取出纯 BV 号和集数 page
    page_match = re.search(r"_p(\d+)$", bvid)
    page = page_match.group(1) if page_match else "1"
    bvid = re.sub(r"_p\d+$", "", bvid)
    iframe = ""
    if bvid:
        iframe = (
            f'<iframe width="560" height="315" src="https://player.bilibili.com/player.html?bvid={bvid}'
            f'&amp;page={page}&amp;high_quality=1&amp;danmaku=0" title="Bilibili video player" '
            f'frameborder="0" allowfullscreen=""></iframe>\n\n'
        )

    lines = [
        "---",
        f'title: "{title}"',
        f'source: "{url}"',
        f"author: \"{author}\"",
    ]
    if published:
        lines.append(f'published: {published}')
    lines.append(f'created: {datetime.now().strftime("%Y-%m-%d")}')
    if desc_short:
        lines.append(f'description: "{desc_short}"')
    lines.append("tags:")
    lines.append('  - "clippings"')
    lines.append("---")
    lines.append("")
    if iframe:
        lines.append(iframe.rstrip())
    lines.append("## Transcript")
    lines.append("")
    for seg in segments:
        lines.append(f"**{fmt_ts(seg['start'])}** · {seg['text']}")
        lines.append("")
    lines.append("")
    return "\n".join(lines)

def main():
    ap = argparse.ArgumentParser(description="B站视频 → Markdown 转写（支持单条/多条/多P系列批量）")
    ap.add_argument("urls", nargs="*", help="一个或多个B站视频链接（可选；系列模式用 --series）")
    ap.add_argument("--out", default=str(CLIPPINGS_DIR), help="输出目录（默认 D:/obsidian/Clippings）")
    ap.add_argument("--model", default="medium", help="Whisper 模型（small/medium/large-v3）")
    ap.add_argument("--short-name", default=None, help="自定义文件名（不含扩展名），仅单条时有效")
    ap.add_argument("--series", default=None, help="多P系列BV号（如 BV1xqdrBeETc），自动转全部P；可用 --p 限定范围")
    ap.add_argument("--series-name", default=None, help="系列短名（用于文件名前缀），不填则用标题截断")
    ap.add_argument("--p", default=None, help="与 --series 配合，转指定集范围，如 3-6 或 4 或 4-")
    args = ap.parse_args()

    if args.series:
        run_series(args)
    elif args.urls:
        run_links(args)
    else:
        ap.print_usage()
        print("错误: 请提供视频链接（位置参数）或 --series BV号")
        sys.exit(2)


def run_links(args):
    """多条独立链接批量转写"""
    if len(args.urls) > 1 and args.short_name:
        print("警告: --short-name 仅对单条链接有效，多条时忽略。")
    for i, url in enumerate(args.urls, 1):
        print(f"\n===== [{i}/{len(args.urls)}] {url} =====")
        try:
            process_one(url, args, short_name=args.short_name if len(args.urls) == 1 else None)
        except Exception as e:
            print(f"✗ 第{i}条失败: {e}")
            if len(args.urls) == 1:
                raise
            continue


def run_series(args):
    """多P系列批量转写。--series 传 BV 号，--p 限定集范围。"""
    import urllib.request

    bvid = args.series.strip()
    if not re.match(r"^BV[\w]+$", bvid):
        print("--series 需要 BV 号（如 BV1xqdrBeETc）")
        sys.exit(1)

    # 解析 P 选择：支持 3-6（范围）/ 4（单集）/ 4-（到末尾）/ 3,5,8（列表）
    pages_to_do = None  # None = 全部
    if args.p:
        p_str = args.p.strip()
        if "," in p_str:
            # 逗号列表
            pages_to_do = []
            for tok in p_str.split(","):
                tok = tok.strip()
                if not tok.isdigit():
                    print(f"--p 列表元素非法: {tok}")
                    sys.exit(1)
                pages_to_do.append(int(tok))
        else:
            m = re.match(r"^(\d+)?\s*-\s*(\d+)?$", p_str)
            if not m:
                print("--p 格式错误，应为 3-6 / 4 / 4- / 3,5,8")
                sys.exit(1)
            start = int(m.group(1)) if m.group(1) else 1
            end = int(m.group(2)) if m.group(2) else 10**6
            if start > end:
                print("P 范围无效")
                sys.exit(1)
            pages_to_do = list(range(start, end + 1))

    # 先拿系列信息：用 yt-dlp 扁平列出整个播放列表（不下载），确定总集数
    print("获取系列信息...")
    cmd = [
        sys.executable, "-m", "yt_dlp",
        "-J",
        "--flat-playlist",
        "--no-warnings",
        f"https://www.bilibili.com/video/{bvid}",
    ]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode != 0:
        print("获取系列信息失败:", r.stderr[-2000:])
        sys.exit(1)
    try:
        info = json.loads(r.stdout)
    except json.JSONDecodeError:
        print("解析系列信息失败")
        sys.exit(1)

    entries = info.get("entries") or []
    total = len(entries)
    if total == 0:
        print("未获取到系列集数，请确认 BV 号是否正确")
        sys.exit(1)

    if args.series_name:
        series_prefix = sanitize_filename(args.series_name, 30)
    else:
        first_title = entries[0].get("title") if entries[0] and entries[0].get("title") else (info.get("title") or bvid)
        series_prefix = sanitize_filename(first_title, 30)
    print(f"系列: {series_prefix}（共 {total} 集）")

    # 确定要处理的集
    if pages_to_do is None:
        pages_to_do = list(range(1, total + 1))
    else:
        # 越界集过滤（仅提示）
        valid = []
        for pp in pages_to_do:
            if 1 <= pp <= total:
                valid.append(pp)
            else:
                print(f"  提示: 第 {pp} 集超出范围(1-{total})，跳过")
        pages_to_do = valid
    if not pages_to_do:
        print("没有需要转写的集")
        sys.exit(1)
    print(f"将转写 {len(pages_to_do)} 集: p{' '.join(f'{p}' for p in pages_to_do)}")

    # 逐集处理
    total_to_do = len(pages_to_do)
    for idx, p in enumerate(pages_to_do, 1):
        url = f"https://www.bilibili.com/video/{bvid}?p={p}"
        print(f"\n===== 第 {p} 集 [{idx}/{total_to_do}] =====")
        try:
            with tempfile.TemporaryDirectory(prefix="bili_tx_", dir=WORK_DIR) as td:
                workdir = Path(td)
                audio, meta = fetch_audio(url, workdir)
                segments, info2 = transcribe(audio, args.model, workdir)
                md = build_markdown(meta, segments, url)

                # 文件名：系列名 + p集号 + 子标题
                title = meta.get("title", "")
                # 子标题：取 title 里 pNN 之后的部分，如 "3-组成原理-冯诺依曼计算机的特点"
                sub = ""
                pm = re.search(r"p\d+\s+(.+)$", title)
                if pm:
                    sub = pm.group(1).strip()
                short_name = f"{series_prefix} p{p:02d}"
                if sub:
                    short_name += f" {sub}"
                fname = sanitize_filename(short_name, 80) + ".md"

                out_dir = Path(args.out)
                out_dir.mkdir(parents=True, exist_ok=True)
                out_path = out_dir / fname
                out_path.write_text(md, encoding="utf-8")
                print(f"[3/3] 完成 → {out_path}")
                print(f"      时长 {info2.duration:.0f}s · 段落 {len(segments)}")
        except Exception as e:
            print(f"✗ 第 {p} 集失败: {e}")
            continue

    print(f"\n系列转写结束，共处理 {total_to_do} 集。")


def process_one(url, args, short_name=None):
    """单条视频转写并落盘"""
    with tempfile.TemporaryDirectory(prefix="bili_tx_", dir=WORK_DIR) as td:
        workdir = Path(td)
        audio, meta = fetch_audio(url, workdir)
        segments, info = transcribe(audio, args.model, workdir)
        md = build_markdown(meta, segments, url)

        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        if short_name:
            fname = sanitize_filename(short_name) + ".md"
        else:
            fname = sanitize_filename(meta.get("title", "B站视频")) + ".md"
        out_path = out_dir / fname
        out_path.write_text(md, encoding="utf-8")

        print(f"[3/3] 完成 → {out_path}")
        print(f"      时长 {info.duration:.0f}s · 段落 {len(segments)} · 模型 {args.model}")
        print(f"      语音时长: {sum(s['end']-s['start'] for s in segments):.0f}s")

if __name__ == "__main__":
    main()
