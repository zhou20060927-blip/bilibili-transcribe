#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
B 站视频字幕探测脚本
用途：批量探测多P视频每集是否有语音字幕（AI字幕/CC字幕），输出有/无字幕清单。
配合 Web Clipper + 转录脚本分工：
  - 有字幕的集 → 浏览器 Web Clipper 抓取（快、准）
  - 无字幕的集 → transcribe.py 转录
用法：
  python check_subs.py --series BV号 [--cookie "SESSDATA=xxx"] [--p 1-40]
"""
import argparse
import json
import re
import sys
import urllib.request
import urllib.parse
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"


def http_get(url: str, cookie: str = "") -> tuple[int, str]:
    """GET 请求，返回 (状态码, 文本)。cookie 可选。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": "https://www.bilibili.com/"})
    if cookie:
        req.add_header("Cookie", cookie)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return r.status, r.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode("utf-8", errors="replace")
    except Exception as e:
        return 0, str(e)


def get_cid_and_meta(bvid: str, p: int, cookie: str = "") -> tuple:
    """从视频页 HTML 提取 cid + 标题。返回 (cid, title) 或 (None, None)。"""
    url = f"https://www.bilibili.com/video/{bvid}?p={p}"
    status, html = http_get(url, cookie)
    if status != 200 or not html:
        print(f"    页面获取失败 status={status}")
        return None, None

    # cid 在 __INITIAL_STATE__ 里，格式 "cid":123456
    m = re.search(r'"cid":\s*(\d+)', html)
    cid = m.group(1) if m else None

    # 标题
    tm = re.search(r"<title>([^<]+)</title>", html)
    title = tm.group(1).strip() if tm else None

    if not cid:
        # 再试 __INITIAL_STATE__ JSON 提取（万一被转义）
        m2 = re.search(r'"cid":(\d+)', html)
        cid = m2.group(1) if m2 else None
    return cid, title


def check_subtitle(cid: str, bvid: str, cookie: str = "") -> dict:
    """调 B 站 player/v2 API 查字幕。返回 {"has_sub": bool, "subs": [...], "ai_sub": bool}"""
    url = f"https://api.bilibili.com/x/player/wbi/v2?bvid={bvid}&cid={cid}"
    status, text = http_get(url, cookie)
    if status != 200:
        return {"has_sub": False, "subs": [], "ai_sub": False, "error": f"http_{status}"}
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return {"has_sub": False, "subs": [], "ai_sub": False, "error": "json_parse_fail"}

    result = data.get("data") or {}
    subtitle = result.get("subtitle") or {}
    subs = subtitle.get("subtitles") or []
    has_sub = len(subs) > 0
    # 是否 AI 字幕
    ai_sub = any("ai" in str(s.get("ai_status")) for s in subs)
    info = []
    for s in subs:
        info.append({
            "lan": s.get("lan"),
            "lan_doc": s.get("lan_doc"),
            "ai_status": s.get("ai_status"),
        })
    return {"has_sub": has_sub, "subs": info, "ai_sub": ai_sub}


def main():
    ap = argparse.ArgumentParser(description="B站多P视频字幕探测")
    ap.add_argument("--series", required=True, help="BV号")
    ap.add_argument("--cookie", default="", help="B站登录 Cookie（含 SESSDATA 等）")
    ap.add_argument("--p", default=None, help="探测范围，如 1-40 或 3 或 5-")
    args = ap.parse_args()

    bvid = args.series.strip()
    # 先拿总集数（flat-playlist）
    import subprocess
    import os
    py = Path(sys.executable)
    cmd = [str(py), "-m", "yt_dlp", "-J", "--flat-playlist", "--no-warnings", f"https://www.bilibili.com/video/{bvid}"]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    total = 0
    if r.returncode == 0:
        try:
            d = json.loads(r.stdout)
            total = len(d.get("entries") or [])
        except json.JSONDecodeError:
            total = 0
    if total == 0:
        print("无法获取系列集数，退出")
        sys.exit(1)
    print(f"系列 {bvid} 共 {total} 集")

    # 解析范围
    start, end = 1, total
    if args.p:
        m = re.match(r"^(\d+)?\s*-\s*(\d+)?$", args.p.strip())
        if m:
            start = int(m.group(1)) if m.group(1) else 1
            end = int(m.group(2)) if m.group(2) else total
    end = min(end, total)

    print(f"探测第 {start}~{end} 集...\n")
    has_sub_eps = []   # (p, title)
    no_sub_eps = []    # (p, title)
    fail_eps = []      # (p, reason)

    for p in range(start, end + 1):
        cid, title = get_cid_and_meta(bvid, p, args.cookie)
        if not cid:
            fail_eps.append((p, "no_cid"))
            print(f"  p{p:02d}  无法获取 cid")
            continue
        res = check_subtitle(cid, bvid, args.cookie)
        # 精简标题（去掉超长前缀）
        short_title = re.sub(r"^【[^】]*】", "", title or "").strip()
        if res.get("has_sub"):
            has_sub_eps.append((p, short_title, res))
            lan = ",".join(s.get("lan_doc") or s.get("lan") or "?" for s in res.get("subs", []))
            ai = "AI" if res.get("ai_sub") else "CC"
            print(f"  p{p:02d}  ✅ 有字幕 [{ai}] {lan}  {short_title}")
        else:
            no_sub_eps.append((p, short_title))
            print(f"  p{p:02d}  ❌ 无字幕  {short_title}")

    # 汇总
    print(f"\n===== 汇总 =====")
    print(f"有字幕（用 Web Clipper）: {len(has_sub_eps)} 集")
    for p, t, _ in has_sub_eps:
        print(f"  p{p:02d}: {t}")
    print(f"\n无字幕（用脚本转录）: {len(no_sub_eps)} 集")
    for p, t in no_sub_eps:
        print(f"  p{p:02d}: {t}")
    if fail_eps:
        print(f"\n获取失败: {len(fail_eps)} 集")
        for p, r in fail_eps:
            print(f"  p{p:02d}: {r}")

    # 生成可直接用的命令提示
    if no_sub_eps:
        ps = f"{no_sub_eps[0][0]}-{no_sub_eps[-1][0]}"
        print(f"\n转录命令建议: transcribe.py --series {bvid} --p {ps} --series-name \"<系列名>\"")
    print("\n探测完成。")


if __name__ == "__main__":
    main()
