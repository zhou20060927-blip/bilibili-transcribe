#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
B 站系列字幕批量抓取 → Clippings 风格 Markdown
用 Edge 登录态访问字幕接口，下载 AI 字幕 JSON，转成统一命名的 Markdown 落库。
用法：python fetch_subs_series.py --series BV号 --series-name "系列名" [--out DIR]
"""
import os
import asyncio
import json
import re
import sys
from datetime import datetime
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

EDGE_PATH = r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
USER_DATA = os.path.expanduser(r"~/AppData/Local/Microsoft/Edge/User Data")
CLIPPINGS = Path("D:/obsidian/Clippings")


def sanitize_filename(name: str, max_len: int = 80) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '', name)
    name = re.sub(r'\s+', ' ', name).strip().rstrip('.')
    return name[:max_len]


def fmt_ts(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m:02d}:{s:02d}"


def build_md(title, author, published, description, bvid, page, url, subs_body):
    """subs_body: [{from, to, content}]"""
    iframe = (
        f'<iframe width="560" height="315" src="https://player.bilibili.com/player.html?bvid={bvid}'
        f'&amp;page={page}&amp;high_quality=1&amp;danmaku=0" title="Bilibili video player" '
        f'frameborder="0" allowfullscreen=""></iframe>'
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
    if description:
        d = re.sub(r"\s+", " ", description)[:200]
        lines.append(f'description: "{d}"')
    lines.append("tags:")
    lines.append('  - "clippings"')
    lines.append("---")
    lines.append("")
    lines.append(iframe)
    lines.append("")
    lines.append("## Transcript")
    lines.append("")
    for seg in subs_body:
        text = seg.get("content", "").strip()
        if text:
            lines.append(f"**{fmt_ts(seg['from'])}** · {text}")
            lines.append("")
    lines.append("")
    return "\n".join(lines)


async def main():
    # 简单参数解析
    args = sys.argv[1:]
    bvid = None
    series_name = None
    out_dir = CLIPPINGS
    i = 0
    while i < len(args):
        if args[i] == "--series":
            bvid = args[i + 1]; i += 2
        elif args[i] == "--series-name":
            series_name = args[i + 1]; i += 2
        elif args[i] == "--out":
            out_dir = Path(args[i + 1]); i += 2
        else:
            i += 1
    if not bvid:
        print("需要 --series BV号")
        return

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            USER_DATA, channel="msedge", headless=False,
            executable_path=EDGE_PATH,
            args=["--profile-directory=Default", "--no-first-run"],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        await page.goto("https://www.bilibili.com", wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(3000)

        # 拿全部 cid + 标题
        view = await page.evaluate(f"""async () => {{
            const r = await fetch('https://api.bilibili.com/x/web-interface/view?bvid={bvid}', {{credentials:'include'}});
            return await r.json();
        }}""")
        data = view.get("data") or {}
        pages = data.get("pages") or []
        author = (data.get("owner") or {}).get("name", "")
        published = data.get("pubdate")
        if published:
            published = datetime.fromtimestamp(published).strftime("%Y-%m-%d")
        description = data.get("desc") or ""
        print(f"系列共 {len(pages)} 集, UP主: {author}")

        out_dir.mkdir(parents=True, exist_ok=True)
        done, skipped, failed = 0, 0, 0

        for pg in pages:
            p, cid, part = pg.get("page"), pg.get("cid"), pg.get("part") or ""
            # 精简标题：取 part 里 '数字-' 之后（如 "1-组成原理-软硬件概念" → "1-组成原理-软硬件概念" 保留即可）
            sub = re.sub(r"^\d+\s*-\s*", "", part)
            fname = sanitize_filename(f"{series_name} p{p:02d} {sub}", 80) + ".md"
            out_path = out_dir / fname
            if out_path.exists():
                print(f"  p{p:02d} 跳过（已存在）")
                skipped += 1
                continue

            # 查字幕
            res = await page.evaluate(f"""async () => {{
                const r = await fetch('https://api.bilibili.com/x/player/wbi/v2?bvid={bvid}&cid={cid}', {{credentials:'include'}});
                const j = await r.json();
                const subs = ((j.data||{{}}).subtitle||{{}}).subtitles||[];
                return {{code:j.code, subs: subs}};
            }}""")
            subs = res.get("subs") or []
            if not subs:
                print(f"  p{p:02d} 无字幕（应走转录）")
                skipped += 1
                continue

            # 取第一个中文字幕
            sub_url = subs[0].get("subtitle_url") or ""
            if sub_url.startswith("//"):
                sub_url = "https:" + sub_url
            resp = await ctx.request.get(sub_url, headers={
                "Referer": "https://www.bilibili.com/",
                "User-Agent": "Mozilla/5.0",
            })
            if resp.status != 200:
                print(f"  p{p:02d} 字幕下载失败 HTTP{resp.status}")
                failed += 1
                continue
            content = await resp.text()
            try:
                sub_json = json.loads(content)
            except json.JSONDecodeError:
                print(f"  p{p:02d} 字幕 JSON 解析失败")
                failed += 1
                continue
            body = sub_json.get("body") or []
            if not body:
                print(f"  p{p:02d} 字幕内容为空")
                failed += 1
                continue

            title = f"{series_name} p{p:02d} {sub}"
            url = f"https://www.bilibili.com/video/{bvid}?p={p}"
            md = build_md(title, author, published, description, bvid, p, url, body)
            out_path.write_text(md, encoding="utf-8")
            print(f"  p{p:02d} ✅ 字幕→{fname}（{len(body)} 条）")
            done += 1
            await page.wait_for_timeout(150)

        print(f"\n完成: 新抓 {done} 集, 跳过 {skipped} 集, 失败 {failed} 集")
        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
