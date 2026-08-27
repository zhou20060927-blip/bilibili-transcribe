#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Playwright 驱动 Edge Default profile（复用登录态），访问 B 站字幕接口。
Edge 必须已关闭（避免 profile 锁）。
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


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        ctx = await p.chromium.launch_persistent_context(
            USER_DATA,
            channel="msedge",
            headless=False,
            executable_path=EDGE_PATH,
            args=[
                "--profile-directory=Default",
                "--no-first-run",
                "--disable-blink-features=AutomationControlled",
            ],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()
        # 先访问 B 站首页确认登录态
        await page.goto("https://www.bilibili.com", wait_until="domcontentloaded", timeout=40000)
        await page.wait_for_timeout(4000)

        # 检测登录态：通过接口
        nav = await page.evaluate("""async () => {
            const r = await fetch('https://api.bilibili.com/x/web-interface/nav', {credentials:'include'});
            return await r.json();
        }""")
        print("nav.isLogin:", nav.get("data", {}).get("isLogin"))
        print("nav.userName:", nav.get("data", {}).get("uname"))

        if not nav.get("data", {}).get("isLogin"):
            print("⚠️ 未登录，无法探测字幕")
            await ctx.close()
            return

        # 已登录：探测 40 集字幕（view API 拿 cid → player API 查字幕）
        bvid = "BV1xqdrBeETc"
        view = await page.evaluate(f"""async () => {{
            const r = await fetch('https://api.bilibili.com/x/web-interface/view?bvid={bvid}', {{credentials:'include'}});
            return await r.json();
        }}""")
        pages = (view.get("data") or {}).get("pages") or []
        print(f"总集数: {len(pages)}")

        has_list, no_list = [], []
        for pg in pages:
            p, cid, part = pg.get("page"), pg.get("cid"), pg.get("part") or ""
            res = await page.evaluate(f"""async () => {{
                const r = await fetch('https://api.bilibili.com/x/player/wbi/v2?bvid={bvid}&cid={cid}', {{credentials:'include'}});
                const j = await r.json();
                const subs = ((j.data||{{}}).subtitle||{{}}).subtitles||[];
                return {{code: j.code, subs: subs.map(s=>({{lan:s.lan, lan_doc:s.lan_doc, ai:s.ai_status}}))}};
            }}""")
            if res.get("subs"):
                has_list.append((p, part, res["subs"]))
                print(f"  p{p:02d}  ✅ 有字幕  {part}")
            else:
                no_list.append((p, part))
                print(f"  p{p:02d}  ❌ 无字幕  {part}")
            await page.wait_for_timeout(200)

        print(f"\n===== 汇总 =====\n有字幕: {len(has_list)} 集\n无字幕: {len(no_list)} 集")
        # 保存结果
        out = Path(__file__).resolve().parent / "subs_result.json"
        out.write_text(json.dumps({"has": has_list, "no": no_list}, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"结果已存: {out}")

        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
