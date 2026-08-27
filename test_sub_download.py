#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
验证：登录态下能否下载 B 站字幕 JSON 内容。测 p01。
"""
import os
import asyncio
import json
import sys
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

EDGE_PATH = r"C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe"
USER_DATA = os.path.expanduser(r"~/AppData/Local/Microsoft/Edge/User Data")
BVID = "BV1xqdrBeETc"


async def main():
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

        # p01 的 cid
        view = await page.evaluate(f"""async () => {{
            const r = await fetch('https://api.bilibili.com/x/web-interface/view?bvid={BVID}', {{credentials:'include'}});
            return await r.json();
        }}""")
        pages = (view.get("data") or {}).get("pages") or []
        p1 = pages[0]
        cid = p1["cid"]
        print("p01 cid:", cid)

        # 查字幕
        res = await page.evaluate(f"""async () => {{
            const r = await fetch('https://api.bilibili.com/x/player/wbi/v2?bvid={BVID}&cid={cid}', {{credentials:'include'}});
            const j = await r.json();
            const subs = ((j.data||{{}}).subtitle||{{}}).subtitles||[];
            return {{code:j.code, subs: subs}};
        }}""")
        print("code:", res.get("code"))
        subs = res.get("subs") or []
        print("字幕条数:", len(subs))
        for s in subs:
            print("  lan:", s.get("lan"), "| doc:", s.get("lan_doc"), "| ai_status:", s.get("ai_status"))
            print("  url:", s.get("subtitle_url"))

        # 下载第一个字幕 JSON 内容（用 APIRequestContext 避免 CORS）
        if subs:
            sub_url = subs[0].get("subtitle_url")
            if sub_url:
                if sub_url.startswith("//"):
                    sub_url = "https:" + sub_url
                # 用 APIRequestContext（带 Cookie，不受页面 CORS 限制）
                resp = await ctx.request.get(sub_url, headers={
                    "Referer": "https://www.bilibili.com/",
                    "User-Agent": "Mozilla/5.0",
                })
                print("\n下载状态:", resp.status)
                content = await resp.text()
                print("=== 字幕 JSON 内容（前 500 字符）===")
                print(content[:500])
                Path("sub_sample.json").write_text(content, encoding="utf-8")
                print("\n已保存 sub_sample.json，长度:", len(content))

        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
