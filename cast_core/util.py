# -*- coding: utf-8 -*-
"""通用小工具：本机 IP、HTTP GET、URL 编解码、实例探测。"""
from __future__ import annotations

import json
import socket
import urllib.request
from urllib.parse import quote, unquote

UA = "KonkaCast/1.0"
_cache: dict[str, str] = {}

# 控制台会尝试的端口范围（被占就 +1），探测时要把它们都问一遍
CONSOLE_PORT = 8770
CONSOLE_PORT_SPAN = 6


def probe_running(span: int = CONSOLE_PORT_SPAN, timeout: float = 0.8) -> int | None:
    """看看是不是已经有控制台实例在跑了，返回它的端口号，没有则返回 None。

    重复启动时靠这个把用户导回已存在的实例 —— 否则新实例会静默挪到下一个端口，
    用户以为「双击没反应」，其实是开了两个互不相干的控制台。
    """
    for offset in range(span):
        port = CONSOLE_PORT + offset
        try:
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/status",
                headers={"User-Agent": UA},
            )
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                data = json.loads(resp.read().decode("utf-8", "ignore"))
            # 简单校验一下确实是我们自己的服务，别把别人的 HTTP 服务认成自己
            if isinstance(data, dict) and "local_ip" in data:
                return port
        except Exception:                            # noqa: BLE001, S112
            continue
    return None


def _candidate_ips() -> list[str]:
    """枚举本机全部 IPv4（纯标准库），去重保序。"""
    ips: list[str] = []
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127.") and ip not in ips:
                ips.append(ip)
    except OSError:
        pass
    # UDP connect 兜底：不真发包，让内核挑默认出口
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.settimeout(0.2)
        s.connect(("223.5.5.5", 80))
        ip = s.getsockname()[0]
        s.close()
        if ip and ip not in ips:
            ips.append(ip)
    except OSError:
        pass
    return ips


def _ip_score(ip: str) -> int:
    """越小越优先。家庭路由器网段 192.168.* 最可能是投屏目标所在；
    10.* 常见于 VPN / 虚拟网卡 / CGNAT，排最后。"""
    if ip.startswith("192.168."):
        return 0
    parts = ip.split(".")
    if parts[0] == "172" and parts[1].isdigit() and 16 <= int(parts[1]) <= 31:
        return 1
    if parts[0] == "10":
        return 2
    return 3


def set_local_ip(ip: str) -> None:
    """手动指定投屏用的本机 IP（优先级最高）。"""
    _cache["ip"] = ip


def local_ip() -> str:
    """拿到用于访问同网段设备的本机 IPv4。取不到就回落 127.0.0.1。

    机器上可能有多个网卡（如远程/投屏软件带的虚拟网卡），默认路由
    出口未必和电视同网段。这里枚举全部 IPv4 按可能性打分挑选；
    也可用环境变量 KONKA_CAST_IP 强制指定。
    """
    if "ip" in _cache:
        return _cache["ip"]
    import os

    forced = os.environ.get("KONKA_CAST_IP", "").strip()
    if forced:
        _cache["ip"] = forced
        return forced
    ips = [i for i in _candidate_ips() if not i.startswith("169.254.")]
    ips.sort(key=_ip_score)
    ip = ips[0] if ips else ""
    if not ip or ip.startswith("127."):
        ip = "127.0.0.1"
    _cache["ip"] = ip
    return ip


def http_get_text(url: str, timeout: float = 4.0) -> str:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "ignore")
    except Exception:
        return ""


def http_post(url: str, data: bytes, headers: dict, timeout: float = 8.0) -> tuple[int, str]:
    """返回 (status_code, body_text)。异常时返回 (0, 错误信息)。"""
    try:
        req = urllib.request.Request(url, data=data, method="POST")
        req.add_header("User-Agent", UA)
        for k, v in headers.items():
            req.add_header(k, v)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        body = ""
        try:
            body = e.read().decode("utf-8", "ignore")
        except Exception:
            pass
        return e.code, body
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


def encode_url(url: str) -> str:
    return quote(url, safe=":/?#[]@!$&'()*+,;=%~-._")


def xml_escape(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def human_size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024.0
    return f"{n:.1f} TB"


def human_time(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


__all__ = [
    "local_ip", "http_get_text", "http_post", "encode_url", "xml_escape",
    "human_size", "human_time", "unquote",
]
