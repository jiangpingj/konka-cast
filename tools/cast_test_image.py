# -*- coding: utf-8 -*-
"""针对本机那两台 DLNA 渲染器做一次真截面验证：
推送一张本地生成的 PNG 图片到电视，并读取 Err 状态。

不需要 ffmpeg —— 这条链路本来就不经过编码。
"""
from __future__ import annotations

import os
import struct
import sys
import tempfile
import time
import zlib

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cast_core import ssdp  # noqa: E402
from cast_core.media_server import MediaServer  # noqa: E402
from cast_core.upnp import Renderer  # noqa: E402
from cast_core.util import local_ip  # noqa: E402


def write_png(path: str, w: int = 1280, h: int = 720) -> str:
    """纯标准库画一张测试图：蓝白渐变 + 中心色块。"""
    rows = bytearray()
    for y in range(h):
        rows.append(0)  # filter type = None
        for x in range(w):
            if (x // 40 + y // 40) % 2 == 0:
                r, g, b = 30, 90, 200
            else:
                r = int(30 + 200 * x / w)
                g = int(90 + 120 * y / h)
                b = int(200 - 60 * x / w)
            cx = abs(x - w // 2)
            cy = abs(y - h // 2)
            if cx < 180 and cy < 90:
                r, g, b = 255, 255, 255
            rows += bytes((r, g, b))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(rows), 6))
    png += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)
    return path


def main():
    ip = local_ip()
    print(f"本机 IP: {ip}")

    png = write_png(os.path.join(tempfile.gettempdir(), "konkacast-test.png"))
    print(f"测试图: {png} ({os.path.getsize(png) / 1024:.0f} KB)")

    ms = MediaServer(port=8899)
    ms.start()
    url, fname = ms.register(png, f"http://{ip}:{ms.real_port}")
    print(f"服务地址: {url}")

    # 确认 Range 请求正常
    import urllib.request
    req = urllib.request.Request(url, headers={"Range": "bytes=0-1023"})
    try:
        with urllib.request.urlopen(req, timeout=5) as r:
            print(f"Range 自检: HTTP {r.status}  {r.headers.get('Content-Range')}")
            print(f"   accept-ranges={r.headers.get('Accept-Ranges')}  "
                  f"dlna-op={r.headers.get('contentFeatures.dlna.org')}")
    except Exception as e:
        print(f"Range 自检失败: {e}")

    infos = ssdp.discover(timeout=3.5)
    print(f"\n发现 {len(infos)} 台渲染器")
    for i in infos:
        r = Renderer(i)
        print(f"\n---- {r.name} ({r.ip}) ----")
        res = r.cast_media(url, "KonkaCast 测试图", mime="image/png",
                           size=os.path.getsize(png))
        if not res.get("ok"):
            print(f"  推送失败 {res.get('error')} HTTP={res.get('status')}")
            continue
        time.sleep(2.5)
        pos = r.position_info()
        tinfo = r.transport_info()
        print(f"  运输状态: {tinfo.get('data', {}).get('CurrentTransportState')}")
        print(f"  当前 URI: {pos.get('data', {}).get('TrackURI', '?')[:70]}")
        if r.name.startswith("LED55") or "极光" in r.name:
            print("  → 图片已投递，请看电视画面（约 8 秒后自动停止）")
        time.sleep(8)
        r.stop()

    ms.stop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
