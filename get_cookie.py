#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
用 Playwright 驱动用户 Edge（复用登录态）访问 B 站，提取 Cookie 供字幕探测用。
注意：仅读取浏览器已有的登录态，不修改浏览器数据。
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


async def main():
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        # 用 persistent context 复用 Edge 默认用户数据（登录态）
        user_data = os.path.expanduser(r"~/AppData/Local/Microsoft/Edge/User Data")
        ctx = await p.chromium.launch_persistent_context(
            user_data,
            channel="msedge",
            headless=False,
            executable_path=EDGE_PATH,
            args=[
                "--profile-directory=Default",
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
            ],
        )
        page = ctx.pages[0] if ctx.pages else await ctx.new_page()

        # 访问 B 站触发登录态加载
        await page.goto("https://www.bilibili.com", wait_until="domcontentloaded", timeout=30000)
        await page.wait_for_timeout(3000)

        # 拿 Cookie
        cookies = await ctx.cookies()
        bili_cookies = [c for c in cookies if "bilibili" in c.get("domain", "")]
        print("=== B站 Cookie 获取 ===")
        print(f"B站相关 Cookie 数: {len(bili_cookies)}")
        important = ["SESSDATA", "bili_jct", "DedeUserID", "buvid3"]
        found = {k: "有" for k in important if any(c["name"] == k for c in bili_cookies)}
        print("关键 Cookie:", found if found else "无")
        # 只打印关键 Cookie 值（SESSDATA 等）
        for c in bili_cookies:
            if c["name"] in important:
                print(f"  {c['name']} = {c['value'][:40]}{'...' if len(c['value'])>40 else ''}")

        # 组装完整 Cookie 串
        cookie_str = "; ".join(f"{c['name']}={c['value']}" for c in bili_cookies)
        out = Path(__file__).resolve().parent / "bili_cookies.txt"
        out.write_text(cookie_str, encoding="utf-8")
        print(f"\nCookie 已存: {out} ({len(cookie_str)} 字符)")
        print("登录状态:", "已登录" if "SESSDATA" in cookie_str else "未登录")

        await ctx.close()


if __name__ == "__main__":
    asyncio.run(main())
