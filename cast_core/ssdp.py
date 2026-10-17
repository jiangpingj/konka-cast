# -*- coding: utf-8 -*-
"""SSDP / UPnP 设备发现层。
只用标准库实现，负责：
  1. 局域网多播 M-SEARCH 找出所有可用设备描述地址
  2. 拉取设备描述 XML，解析出 AVTransport / RenderingControl 控制点
"""
from __future__ import annotations

import socket
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urljoin, urlparse
from xml.etree import ElementTree as ET

from .util import http_get_text, local_ip

SSDP_ADDR = "239.255.255.250"
SSDP_PORT = 1900

# 单次 M-SEARCH 里把这几个 ST 全发一遍，宣称自己是 MediaRenderer 但
# 只响应 ssdp:all 的老电视也能被捞出来
SEARCH_TARGETS = [
    "ssdp:all",
    "upnp:rootdevice",
    "urn:schemas-upnp-org:device:MediaRenderer:1",
    "urn:schemas-upnp-org:device:MediaRenderer:2",
    "urn:schemas-upnp-org:service:AVTransport:1",
    "urn:schemas-upnp-org:service:AVTransport:2",
    "urn:schemas-upnp-org:service:RenderingControl:1",
    "urn:dial-multiscreen-org:service:dial:1",
]

NS_DEVICE = "urn:schemas-upnp-org:device-1-0"
NS_SERVICE = "urn:schemas-upnp-org:service-1-0"

# 注意：设备描述文档里 <serviceList>/<service> 继承的是默认命名空间
# device-1-0，而不是 service-1-0（后者只出现在 SCPD 文档里）。
# 这里两个前缀都指向 device-1-0，避免踩到这个经典坑。
NS = {"d": NS_DEVICE, "s": NS_DEVICE}

WANTED_SERVICES = {
    "urn:schemas-upnp-org:service:AVTransport:1": "AVTransport",
    "urn:schemas-upnp-org:service:AVTransport:2": "AVTransport",
    "urn:schemas-upnp-org:service:RenderingControl:1": "RenderingControl",
    "urn:schemas-upnp-org:service:RenderingControl:2": "RenderingControl",
    "urn:schemas-upnp-org:service:ConnectionManager:1": "ConnectionManager",
}


def _build_search(st: str, mx: int = 2) -> bytes:
    return (
        f"M-SEARCH * HTTP/1.1\r\n"
        f"HOST: {SSDP_ADDR}:{SSDP_PORT}\r\n"
        f'MAN: "ssdp:discover"\r\n'
        f"MX: {mx}\r\n"
        f"ST: {st}\r\n"
        f"USER-AGENT: KonkaCast/1.0 UPnP/1.1 DLNADOC/1.50\r\n"
        f"\r\n"
    ).encode("ascii")


def _parse_headers(raw: str) -> dict:
    headers = {}
    for line in raw.split("\r\n")[1:]:
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        headers[k.strip().lower()] = v.strip()
    return headers


def msearch(timeout: float = 3.0, bind_ip: str | None = None) -> set[str]:
    """多播 M-SEARCH，返回去重后的 LOCATION 集合。

    所有 ST 共用同一个 socket，一次收完——比起逐个 ST 轮询快一个数量级。
    """
    if bind_ip is None:
        bind_ip = local_ip()

    locations: set[str] = set()
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((bind_ip, 0))
        except OSError:
            sock.bind(("", 0))
    except OSError:
        return locations

    dest = (SSDP_ADDR, SSDP_PORT)
    try:
        for st in SEARCH_TARGETS:
            try:
                sock.sendto(_build_search(st, mx=min(3, max(1, int(timeout)))), dest)
            except OSError:
                continue

        deadline = time.time() + timeout
        while True:
            remaining = deadline - time.time()
            if remaining <= 0:
                break
            sock.settimeout(min(remaining, 0.6))
            try:
                data, _addr = sock.recvfrom(65535)
            except (socket.timeout, OSError):
                continue
            headers = _parse_headers(data.decode("utf-8", "ignore"))
            loc = headers.get("location")
            if loc:
                locations.add(loc)
    finally:
        sock.close()

    return locations


def _walk(node: ET.Element) -> list[ET.Element]:
    """返回该 device 及其所有内嵌 device。"""
    out = [node]
    for emb in node.findall("d:deviceList/d:device", NS):
        out.extend(_walk(emb))
    return out


def describe(location: str) -> dict | None:
    """拉取设备描述 XML 抽取渲染能力。返回 None 表示不是可用渲染器。"""
    xml = http_get_text(location, timeout=4.0)
    if not xml:
        return None
    try:
        root = ET.fromstring(xml)
    except ET.ParseError:
        return None

    # base URL：优先 URLBase（很多国产固件靠它补口书写得不规范）
    urlbase = root.findtext("d:URLBase", namespaces=NS) or ""
    if urlbase:
        base_url = urlbase.rstrip("/")
    else:
        parts = location.split("/")
        base_url = f"{parts[0]}//{parts[2]}"

    info = {
        "location": location,
        "base_url": base_url,
        "device_type": "",
        "friendly_name": "",
        "manufacturer": "",
        "model_name": "",
        "model_number": "",
        "serial": "",
        "udn": "",
        "ip": urlparse(location).hostname or "",
        "services": {},
    }

    top_devices = root.findall("d:device", NS) or [root]
    for top in top_devices:
        for dev in _walk(top):
            for key, tag in (
                ("device_type", "deviceType"),
                ("friendly_name", "friendlyName"),
                ("manufacturer", "manufacturer"),
                ("model_name", "modelName"),
                ("model_number", "modelNumber"),
                ("serial", "serialNumber"),
                ("udn", "UDN"),
            ):
                if not info[key]:
                    info[key] = dev.findtext(f"d:{tag}", "", NS) or ""

            for svc in dev.findall("d:serviceList/s:service", NS):
                stype = svc.findtext("s:serviceType", "", NS) or ""
                alias = WANTED_SERVICES.get(stype)
                if not alias:
                    continue
                ctrl = svc.findtext("s:controlURL", "", NS) or ""
                evt = svc.findtext("s:eventSubURL", "", NS) or ""
                scpd = svc.findtext("s:SCPDURL", "", NS) or ""
                candidate = {
                    "service_type": stype,
                    "control_url": urljoin(base_url + "/", ctrl.lstrip("/")),
                    "event_url": urljoin(base_url + "/", evt.lstrip("/")),
                    "scpd_url": urljoin(base_url + "/", scpd.lstrip("/")),
                }
                old = info["services"].get(alias)
                # 同一服务存在多版本时保留高版本
                if old and old["service_type"] >= stype:
                    continue
                info["services"][alias] = candidate

    if "AVTransport" not in info["services"]:
        return None
    return info


def discover(timeout: float = 3.0) -> list[dict]:
    """完整发现流程，返回渲染器信息列表。"""
    locations = msearch(timeout=timeout)
    if not locations:
        return []

    devices: list[dict] = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        for result in pool.map(describe, list(locations)):
            if result:
                devices.append(result)

    # 同一设备可能有多个 LOCATION，按 IP+UDN 去重
    seen: dict[str, dict] = {}
    for d in devices:
        key = f'{d["ip"]}|{d["udn"]}'
        old = seen.get(key)
        if old is None or len(d["services"]) > len(old["services"]):
            seen[key] = d
    return list(seen.values())


def quick_scan(timeout: float = 3.0) -> dict:
    """给诊断用：返回全部发现到的 UPnP 设备（含非渲染器），便于排查。"""
    locations = msearch(timeout=timeout)
    raw = []
    for loc in sorted(locations):
        xml = http_get_text(loc, timeout=4.0)
        if not xml:
            raw.append({"location": loc, "error": "描述拉取失败"})
            continue
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as e:
            raw.append({"location": loc, "error": f"XML 解析失败 {e}"})
            continue
        dev = root.find("d:device", NS)
        node = dev if dev is not None else root
        raw.append({
            "location": loc,
            "friendlyName": node.findtext("d:friendlyName", "", NS),
            "manufacturer": node.findtext("d:manufacturer", "", NS),
            "deviceType": node.findtext("d:deviceType", "", NS),
            "services": sorted({s.findtext("s:serviceType", "", NS)
                                for s in node.findall("d:serviceList/s:service", NS)}),
        })
    return {"count": len(raw), "devices": raw}
