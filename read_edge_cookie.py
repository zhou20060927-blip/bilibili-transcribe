#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
读取 Edge 浏览器 Cookie 数据库，解密 B 站 Cookie（本机当前用户 DPAPI）。
用法：python read_edge_cookie.py [--out bili_cookies.txt]
依赖：pip install pycryptodome
"""
import argparse
import base64
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from pathlib import Path

if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

COOKIES_DB = Path(os.path.expanduser(r"~/AppData/Local/Microsoft/Edge/User Data/Default/Network/Cookies"))
LOCAL_STATE = Path(os.path.expanduser(r"~/AppData/Local/Microsoft/Edge/User Data/Local State"))


def decrypt_with_dpapi(encrypted: bytes) -> bytes:
    """用 Windows DPAPI 解密（当前用户）。"""
    import ctypes
    import ctypes.wintypes as wt

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wt.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]

    def blob_from_bytes(data: bytes) -> DATA_BLOB:
        buf = ctypes.create_string_buffer(data, len(data))
        return DATA_BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char)))

    def blob_to_bytes(blob: DATA_BLOB) -> bytes:
        return ctypes.string_at(blob.pbData, blob.cbData)

    crypt32 = ctypes.windll.crypt32
    crypt32.CryptUnprotectData.argtypes = [ctypes.POINTER(DATA_BLOB), wt.LPWSTR, ctypes.POINTER(DATA_BLOB), wt.LPVOID, ctypes.POINTER(DATA_BLOB), wt.DWORD, ctypes.POINTER(DATA_BLOB)]
    crypt32.CryptUnprotectData.restype = ctypes.c_bool

    in_blob = blob_from_bytes(encrypted)
    out_blob = DATA_BLOB()
    ok = crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0, ctypes.byref(out_blob))
    if not ok:
        return b""
    return blob_to_bytes(out_blob)


def get_v10_key() -> bytes:
    """新版 Edge/Chrome v10 加密：Local State 里的 AES key（DPAPI 加密），需先解密。"""
    if not LOCAL_STATE.exists():
        return b""
    state = json.loads(LOCAL_STATE.read_text(encoding="utf-8"))
    enc_key = state.get("os_crypt", {}).get("encrypted_key")
    if not enc_key:
        return b""
    enc = base64.b64decode(enc_key)
    assert enc[:5] == b"DPAPI", "key 非 DPAPI"
    return decrypt_with_dpapi(enc[5:])


def decrypt_cookie(value: bytes, key: bytes) -> str:
    """解密 Cookie 值：v10 用 AES-GCM（key 里带 v10 前缀），老版用 DPAPI。"""
    if value[:3] == b"v10":
        try:
            from Crypto.Cipher import AES
            nonce = value[3:15]
            ciphertext = value[15:-16]
            tag = value[-16:]
            cipher = AES.new(key, AES.MODE_GCM, nonce=nonce)
            return cipher.decrypt_and_verify(ciphertext, tag).decode("utf-8")
        except Exception:
            return ""
    # 老版直接 DPAPI
    return decrypt_with_dpapi(value).decode("utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser(description="读取 Edge Cookie 并输出 B 站 Cookie 串")
    ap.add_argument("--out", default="bili_cookies.txt")
    args = ap.parse_args()

    if not COOKIES_DB.exists():
        print("Cookie 数据库不存在:", COOKIES_DB)
        sys.exit(1)

    # 复制数据库（避免占用锁）
    tmp = Path(tempfile.gettempdir()) / "edge_cookies_copy.db"
    try:
        shutil.copy2(COOKIES_DB, tmp)
    except Exception as e:
        print("复制 Cookie 库失败（Edge 可能仍占用）:", e)
        sys.exit(1)

    v10_key = get_v10_key()
    print("v10 AES key:", "已获取" if v10_key else "未获取（可能用老版 DPAPI）")

    conn = sqlite3.connect(str(tmp))
    cur = conn.cursor()
    cur.execute("SELECT host_key, name, path, encrypted_value, expires_utc FROM cookies WHERE host_key LIKE '%bilibili%'")
    rows = cur.fetchall()
    conn.close()
    tmp.unlink(missing_ok=True)

    print(f"B站 Cookie 数: {len(rows)}")
    cookie_parts = []
    important = ["SESSDATA", "bili_jct", "DedeUserID", "DedeUserID__ckMd5"]
    found = {}
    for host, name, path, enc_val, expires in rows:
        val = decrypt_cookie(enc_val, v10_key)
        if not val:
            continue
        cookie_parts.append(f"{name}={val}")
        if name in important:
            found[name] = val[:30] + ("..." if len(val) > 30 else "")
    print("关键 Cookie:")
    for k in important:
        print(f"  {k}: {found.get(k, '未找到')}")

    if "SESSDATA" not in found:
        print("\n⚠️ 未找到 SESSDATA（可能 Edge 里 B 站未登录）")
        # 仍保存已拿到的
    cookie_str = "; ".join(cookie_parts)
    out = Path(args.out)
    out.write_text(cookie_str, encoding="utf-8")
    print(f"\n已保存 {len(cookie_parts)} 个 Cookie 到 {out}")
    print("是否含 SESSDATA:", "是（已登录）" if "SESSDATA" in cookie_str else "否")


if __name__ == "__main__":
    main()
