# -*- coding: utf-8 -*-
"""直接运行即可：python main.py    可选参数 --port 8770"""
from __future__ import annotations

import argparse
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cast_core import Controller, ConsoleServer  # noqa: E402
from cast_core.util import local_ip  # noqa: E402


def _reuse_if_running() -> bool:
    """已经有一个实例在跑，就把用户导过去而不是再开一个。"""
    try:
        from cast_core.util import probe_running
        port = probe_running()
    except Exception:                                # noqa: BLE001
        return False
    if not port:
        return False
    url = f"http://127.0.0.1:{port}"
    print("=" * 56)
    print(f"  控制台已经在运行了：{url}")
    print("  没有重复启动，直接帮你把窗口打开。")
    print("  要彻底重启，先关掉原来那个黑窗口。")
    print("=" * 56)
    if "--no-browser" not in sys.argv:
        try:
            import webbrowser
            webbrowser.open(url)
        except Exception:                            # noqa: BLE001, S110
            pass
    return True


def main():
    if _reuse_if_running():
        return

    parser = argparse.ArgumentParser(description="KonkaCast 电视投屏控制台")
    parser.add_argument("--port", type=int, default=8770, help="控制台端口")
    parser.add_argument("--media-port", type=int, default=8899, help="媒体服务端口")
    parser.add_argument("--no-browser", action="store_true", help="不自动打开浏览器")
    args = parser.parse_args()

    ctrl = Controller(media_port=args.media_port)
    console = ConsoleServer(ctrl, port=args.port)
    console.start(open_browser=not args.no_browser)

    # 先扫一轮，用户打开页面时设备列表就已经有内容了
    threading.Thread(target=ctrl.scan, kwargs={"timeout": 3.5}, daemon=True).start()

    real = console.real_port
    print("=" * 56)
    print("  KonkaCast 已启动")
    print(f"  控制台   http://127.0.0.1:{real}")
    print(f"  媒体服务 http://{local_ip()}:{ctrl.media.real_port}")
    print(f"  本机 IP  {local_ip()}")
    ff = ctrl.ffmpeg_info
    if ff.ok:
        print(f"  ffmpeg   {ff.version}"
              f"{'  [NVENC 可用]' if ff.has_nvenc else ''}")
    else:
        print("  ffmpeg   未安装（控制台里可一键下载）")
    print("=" * 56)
    print("  按 Ctrl+C 退出")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n正在退出...")
        ctrl.shutdown()
        console.stop()


if __name__ == "__main__":
    main()
