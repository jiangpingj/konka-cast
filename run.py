# -*- coding: utf-8 -*-
"""KonkaCast 安全启动器。

和 main.py 干的事一样，但多了三件事：
  1. 启动前先做一轮环境自检，版本不够直接说人话
  2. 任何异常都捕获并写入 错误日志.txt
  3. 崩溃后窗口不关，等你按回车

报错排查时用它代替 main.py：
    python run.py
"""
from __future__ import annotations

import os
import sys
import traceback

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
LOG_PATH = os.path.join(ROOT, "错误日志.txt")

_MIN_VER = (3, 8)


def dump(title: str, exc: BaseException | None = None) -> None:
    """把错误信息同时打到屏幕和日志文件。"""
    buf = ["=" * 58, f"  {title}", "=" * 58, ""]
    if exc is not None:
        buf.append(f"{type(exc).__name__}: {exc}")
        buf.append("")
        buf.append(traceback.format_exc())
    text = "\n".join(buf)

    print()
    print(text)
    print()
    try:
        with open(LOG_PATH, "w", encoding="utf-8") as fh:
            fh.write(text)
        print(f"已写入日志文件: {LOG_PATH}")
    except Exception as write_err:                   # noqa: BLE001
        print(f"（日志写盘失败: {write_err}）")


def preflight() -> bool:
    """启动前检查，返回 False 表示不能继续。"""
    import platform
    v = sys.version_info
    print(f"Python {platform.python_version()}  ({sys.executable})")

    if v < _MIN_VER:
        print()
        print(f"版本过低：本项目需要 Python {_MIN_VER[0]}.{_MIN_VER[1]} 或更高，"
              f"当前是 {v[0]}.{v[1]}。")
        print()
        print("两个办法：")
        print("  1. 双击 启动投屏.bat（它会用自带的 Python 3.13 跑）")
        print("  2. 装一个新版 Python，并把 python 加进 PATH")
        return False

    # 逐个文件编译，语法问题在这里就暴露出来
    bad = []
    for root, _dirs, files in os.walk(ROOT):
        if "__pycache__" in root:
            continue
        for name in files:
            if not name.endswith(".py"):
                continue
            path = os.path.join(root, name)
            try:
                with open(path, encoding="utf-8") as fh:
                    compile(fh.read(), path, "exec")
            except SyntaxError as exc:
                bad.append((os.path.relpath(path, ROOT),
                            exc.lineno, exc.msg, exc.text))
    if bad:
        print()
        print(f"有 {len(bad)} 个文件在当前 Python 下无法解析：")
        for rel, lineno, msg, text in bad:
            print(f"  {rel}  第 {lineno} 行: {msg}")
            if text:
                print(f"      {text.rstrip()}")
        print()
        print("这就是报错根因 —— 你的 Python 版本不支持这些写法。")
        print("改用 启动投屏.bat，或者升级 Python。")
        return False

    return True


def reuse_if_running() -> bool:
    """已经有实例在跑就把用户导过去，返回 True 表示可以直接退出了。"""
    try:
        from cast_core.util import probe_running
        port = probe_running()
    except Exception:                                # noqa: BLE001
        return False
    if not port:
        return False

    url = f"http://127.0.0.1:{port}"
    print()
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
    else:
        print("  （--no-browser 模式，不自动打开浏览器）")
    _pause()
    return True


def main() -> int:
    if reuse_if_running():
        return 0

    if not preflight():
        return 1

    try:
        from cast_core import ConsoleServer, Controller
        from cast_core.util import local_ip
    except Exception as exc:                         # noqa: BLE001
        dump("模块导入失败", exc)
        print("依赖缺失。本项目零第三方库，出现导入失败通常是文件被改坏了。")
        _pause()
        return 1

    ctrl = None
    console = None
    try:
        import argparse
        import threading
        import time

        parser = argparse.ArgumentParser(description="KonkaCast 安全启动器")
        parser.add_argument("--port", type=int, default=8770)
        parser.add_argument("--media-port", type=int, default=8899)
        parser.add_argument("--no-browser", action="store_true")
        args = parser.parse_args()

        ctrl = Controller(media_port=args.media_port)
        console = ConsoleServer(ctrl, port=args.port)
        console.start(open_browser=not args.no_browser)
        threading.Thread(target=ctrl.scan, kwargs={"timeout": 3.5},
                         daemon=True).start()

        real = console.real_port
        print()
        print("=" * 56)
        print("  KonkaCast 已启动")
        print(f"  控制台   http://127.0.0.1:{real}")
        print(f"  媒体服务 http://{local_ip()}:{ctrl.media.real_port}")
        print(f"  本机 IP  {local_ip()}")
        ff = ctrl.ffmpeg_info
        print(f"  ffmpeg   {ff.version if ff.ok else '未安装（仅影响屏幕镜像）'}")
        print("=" * 56)
        print("  按 Ctrl+C 退出")

        while True:
            time.sleep(1)

    except KeyboardInterrupt:
        print("\n正在退出 ...")
        return 0
    except Exception as exc:                         # noqa: BLE001
        dump("运行时错误", exc)
        print("把上面这份 错误日志.txt 发给我，我照着改。")
        _pause()
        return 1
    finally:
        for obj in (console, ctrl):
            try:
                if obj is not None:
                    obj.shutdown() if hasattr(obj, "shutdown") else obj.stop()
            except Exception:                        # noqa: BLE001, S110
                pass
    return 0


def _pause() -> None:
    try:
        input("\n按回车键关闭 ...")
    except Exception:                                # noqa: BLE001, S110
        pass


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                                # noqa: BLE001
        dump("未捕获的崩溃")
        traceback.print_exc()
        _pause()
