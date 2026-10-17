# -*- coding: utf-8 -*-
"""UPnP 原始响应诊断。
看不出电视在哪台机子上时跑这个：它会把所有应答 SSDP 的设备都列出来，
能分清是「电视没响应」还是「本机多播被防火墙挡了」。
"""
from __future__ import annotations

import os
import socket
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cast_core import ssdp  # noqa: E402
from cast_core.util import local_ip  # noqa: E402


def main():
    ip = local_ip()
    print(f"本机 IP        : {ip}")
    print(f"多播地址       : {ssdp.SSDP_ADDR}:{ssdp.SSDP_PORT}")
    print()

    print("原始 UDP 探测 ...")
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.settimeout(4)
        sock.bind((ip, 0))
        sock.sendto(ssdp._build_search("ssdp:all", mx=3),
                    (ssdp.SSDP_ADDR, ssdp.SSDP_PORT))
        import time
        count = 0
        end = time.time() + 4
        while time.time() < end:
            try:
                data, addr = sock.recvfrom(65535)
            except socket.timeout:
                continue
            count += 1
            headers = ssdp._parse_headers(data.decode("utf-8", "ignore"))
            print(f"  来自 {addr[0]:<15} LOCATION={headers.get('location', '?')}")
            print(f"    SERVER={headers.get('server', '?')}")
            print(f"    ST={headers.get('st') or headers.get('nt') or '?'}")
        print(f"\n总共收到 {count} 条 SSDP 响应")
        if count == 0:
            print("  一条都没有 → 大概率是 Windows 防火墙挡了 UDP 1900，")
            print("  或者本机/HUB 不支持多播。请检查防火墙入站规则。")
    except OSError as e:
        print(f"  多播失败：{e}")
    finally:
        sock.close()

    print("\n" + "=" * 60)
    print("发现的渲染器（解析过 UPnP 描述的）")
    print("=" * 60)
    infos = ssdp.discover(timeout=3.5)
    if not infos:
        print("  没有解析出可用渲染器")
    for i in infos:
        print(f"\n  名称     : {i['friendly_name']}")
        print(f"  厂商/型号: {i['manufacturer']} / {i['model_name']}")
        print(f"  类型     : {i['device_type']}")
        print(f"  IP       : {i['ip']}")
        print(f"  描述地址 : {i['location']}")
        for alias, svc in i["services"].items():
            print(f"    {alias:<18} {svc['control_url']}")

    print("\n" + "=" * 60)
    print("局域网全部 UPnP 设备（含非渲染器）")
    print("=" * 60)
    raw = ssdp.quick_scan(timeout=3.0)
    for d in raw["devices"]:
        if d.get("error"):
            print(f"  {d['location']}  → {d['error']}")
            continue
        print(f"  {d['friendlyName'] or '(无名称)':<24} {d['manufacturer'] or '':<16} {d['deviceType']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
