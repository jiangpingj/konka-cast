# -*- coding: utf-8 -*-
"""环境自检 —— 报错时第一个跑这个。

它会依次检查：
  1. Python 版本够不够（本项目要求 3.8+）
  2. 代码里有没有用到当前版本不支持的语法
  3. 每个模块能不能正常导入
  4. 网络 / SSDP 多播能不能通
  5. 端口有没有被占

任何一步失败都会打印出具体原因。最后把完整报告写到 错误日志.txt。
"""
from __future__ import annotations

import os
import platform
import socket
import sys
import traceback

# 这个脚本放在 tools/ 里，要往上退一级才是项目根，否则 import cast_core 会失败
_HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(_HERE)
sys.path.insert(0, ROOT)

LOG_PATH = os.path.join(ROOT, "错误日志.txt")
_lines: list[str] = []


def say(msg: str = "") -> None:
    print(msg)
    _lines.append(msg)


def head(title: str) -> None:
    say()
    say("=" * 58)
    say(f"  {title}")
    say("=" * 58)


def check_python() -> bool:
    head("1 / Python 版本")
    v = sys.version_info
    say(f"  可执行文件 : {sys.executable}")
    say(f"  版本       : {platform.python_version()}  ({platform.architecture()[0]})")
    say(f"  系统       : {platform.platform()}")

    ok = v >= (3, 8)
    if ok:
        say("  结论       : 版本满足要求（需要 3.8+）")
        if v < (3, 10):
            say("  注意       : 低于 3.10，类型注解走延迟求值，功能不受影响")
    else:
        say("  结论       : 版本过低！本项目需要 Python 3.8 或更高")
        say("  处理办法   : 升级 Python，或者用目录下的 启动投屏.bat（自带 3.13）")
    return ok


# (语法特性, 最低版本, 用于探测的源码)
_FEATURES = [
    ("海象运算符 :=", (3, 8), "x := 1"),
    ("仅位置参数 /", (3, 8), "def f(a, /): pass"),
    ("字典合并 |", (3, 9), "{'a': 1} | {'b': 2}"),
    ("内置泛型 list[str]", (3, 9), "x: list = [1]\nx: list[str] = []"),
    ("removeprefix", (3, 9), "'a'.removeprefix('a')"),
    ("match 语句", (3, 10), "match 1:\n    case _: pass"),
    ("联合类型 X | Y", (3, 10), "x: int | None = None"),
    ("zip(strict=)", (3, 10), "zip([1], [2], strict=True)"),
    ("except*", (3, 11), "try:\n    pass\nexcept* ValueError:\n    pass"),
    ("泛型函数语法", (3, 12), "def f[T](x: T) -> T: return x"),
]


def check_syntax() -> None:
    head("2 / 语法兼容性扫描")
    v = sys.version_info
    blocked = []
    for name, need, snippet in _FEATURES:
        if v >= need:
            continue
        try:
            compile(snippet, "<probe>", "exec")
            say(f"  {name:<20} 需要 {need[0]}.{need[1]}  当前版本可能不支持 ← 风险")
            blocked.append(name)
        except SyntaxError:
            say(f"  {name:<20} 需要 {need[0]}.{need[1]}  当前不支持")
            blocked.append(name)
        except Exception:
            say(f"  {name:<20} 需要 {need[0]}.{need[1]}  当前不支持")
            blocked.append(name)

    if not blocked:
        say("  结论: 当前版本支持全部需要的语法")
        return

    say()
    say(f"  !! 有 {len(blocked)} 项语法在当前版本不可用，逐个文件检查实际影响 ...")
    hits = scan_project()
    if hits:
        say()
        say("  以下文件在当前 Python 下无法解析，这就是报错根因：")
        for path, err in hits:
            say(f"    {path}")
            say(f"      {err}")
    else:
        say("  不过项目源码本身没有踩到这些语法，可以继续往下查。")


def scan_project() -> list[tuple[str, str]]:
    """编译项目里每个 .py，返回失败清单。"""
    hits: list[tuple[str, str]] = []
    targets = []
    for rel in ("cast_core", "tools", "."):
        d = os.path.join(ROOT, rel) if rel != "." else ROOT
        if not os.path.isdir(d):
            continue
        for name in sorted(os.listdir(d)):
            if name.endswith(".py"):
                targets.append(os.path.join(d, name))
    for path in targets:
        try:
            with open(path, encoding="utf-8") as fh:
                compile(fh.read(), path, "exec")
        except SyntaxError as exc:
            hits.append((os.path.relpath(path, ROOT),
                         f"第 {exc.lineno} 行: {exc.msg}"))
        except Exception as exc:                     # noqa: BLE001
            hits.append((os.path.relpath(path, ROOT), f"{type(exc).__name__}: {exc}"))
    return hits


def check_imports() -> bool:
    head("3 / 模块导入")
    mods = [
        "cast_core",
        "cast_core.util",
        "cast_core.ssdp",
        "cast_core.upnp",
        "cast_core.media_server",
        "cast_core.mirror",
        "cast_core.ffmpeg_fetch",
        "cast_core.uploads",
        "cast_core.controller",
        "cast_core.console",
    ]
    bad = []
    for m in mods:
        try:
            __import__(m)
            say(f"  OK    {m}")
        except Exception as exc:                     # noqa: BLE001
            say(f"  失败  {m}  ->  {type(exc).__name__}: {exc}")
            bad.append((m, traceback.format_exc()))
    if bad:
        say()
        say("  导入失败的完整堆栈：")
        for m, tb in bad:
            say(f"  ---- {m} ----")
            for line in tb.strip().splitlines():
                say(f"    {line}")
        return False
    say("  结论: 全部模块导入正常")
    return True


def check_controller() -> bool:
    head("4 / 核心对象构造")
    try:
        from cast_core import Controller
        ctrl = Controller()
        say(f"  本机 IP    : {ctrl.local_ip}")
        say(f"  媒体服务   : {ctrl.host_url}")
        say(f"  ffmpeg     : {ctrl.ffmpeg_path or '未安装'}")
        ctrl.shutdown()
        say("  结论: Controller 构造与释放正常")
        return True
    except Exception:                                # noqa: BLE001
        say("  构造失败：")
        for line in traceback.format_exc().strip().splitlines():
            say(f"    {line}")
        return False


def check_network() -> None:
    head("5 / 网络与端口")
    try:
        from cast_core.util import local_ip
        ip = local_ip()
        say(f"  本机 LAN IP: {ip}")
    except Exception as exc:                        # noqa: BLE001
        say(f"  取不到本机 IP: {exc}")
        return

    for port in (8770, 8899):
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(0.6)
        try:
            s.bind(("127.0.0.1" if port == 8770 else "", port))
            say(f"  端口 {port:<5}  空闲")
        except OSError:
            say(f"  端口 {port:<5}  被占用（服务可能已经在跑，不算错误）")
        finally:
            s.close()

    try:
        from cast_core import ssdp
        infos = ssdp.discover(timeout=3.0)
        say(f"  SSDP 扫描  : 发现 {len(infos)} 台渲染器")
        for i in infos:
            say(f"    - {i['friendly_name']}  ({i['ip']})")
        if not infos:
            say("    → 一台都没有。通常是 Windows 防火墙挡了 UDP 1900 出站/入站。")
    except Exception:                                # noqa: BLE001
        say("  SSDP 扫描失败：")
        for line in traceback.format_exc().strip().splitlines():
            say(f"    {line}")


def save_log() -> None:
    try:
        with open(LOG_PATH, "w", encoding="utf-8") as fh:
            fh.write("\n".join(_lines))
        print()
        print(f"完整报告已写入: {LOG_PATH}")
    except Exception as exc:                        # noqa: BLE001
        print(f"（报告落盘失败: {exc}）")


def main() -> int:
    say()
    say("  KonkaCast 环境自检")
    ok = True
    try:
        ok &= check_python()
        check_syntax()
        ok &= check_imports()
        ok &= check_controller()
        check_network()
    except Exception:                                # noqa: BLE001
        say()
        say("自检脚本自身崩了，原始堆栈如下：")
        for line in traceback.format_exc().strip().splitlines():
            say(f"  {line}")
        ok = False

    head("结论")
    if ok:
        say("  环境没问题。如果 main.py 仍然报错，请把 错误日志.txt 发出来。")
    else:
        say("  发现问题，按上面的提示处理，或者把 错误日志.txt 发出来。")
    save_log()
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                                # noqa: BLE001
        traceback.print_exc()
        try:
            with open(LOG_PATH, "w", encoding="utf-8") as fh:
                fh.write(traceback.format_exc())
            print(f"\n崩溃堆栈已写入: {LOG_PATH}")
        except Exception:                            # noqa: BLE001
            pass
    print()
    input("按回车键关闭 ...")
