# -*- coding: utf-8 -*-
"""端到端自检：发现 -> 控制 -> 推送播放 -> 停止。
不需要 ffmpeg，生成一个 WAV 测试音即可验证整条链路。
"""
from __future__ import annotations

import math
import os
import struct
import sys
import tempfile
import time
import wave

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cast_core import ssdp  # noqa: E402
from cast_core.media_server import MediaServer  # noqa: E402
from cast_core.upnp import Renderer  # noqa: E402
from cast_core.util import local_ip  # noqa: E402


def make_test_wav(path: str, duration: float = 6.0):
    sr = 44100
    frames = bytearray()
    n = int(sr * duration)
    for i in range(n):
        t = i / sr
        step = int(t / 1.2) % 6
        freq = 392.0 * (2 ** (step / 12))  # 五声音阶，听起来像舒缓提示音
        env = min(1.0, t * 3, (duration - t) * 3, 1.0)
        v = 0.16 * env * (0.6 * math.sin(2 * math.pi * freq * t)
                          + 0.25 * math.sin(4 * math.pi * freq * t))
        s = max(-32768, min(32767, int(v * 32767)))
        frames += struct.pack("<hh", s, s)
    with wave.open(path, "wb") as w:
        w.setnchannels(2)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(bytes(frames))
    return path


def main():
    ip = local_ip()
    print(f"本机 IP: {ip}\n")

    print("[1/4] 扫描设备 ...")
    infos = ssdp.discover(timeout=3.5)
    if not infos:
        print("没有发现任何渲染器，自检中止")
        return 1
    renderers = [Renderer(i) for i in infos]
    for idx, r in enumerate(renderers):
        print(f"  [{idx}] {r.name}  ({r.ip})  AVTransport={r.services['AVTransport']['control_url']}")

    print("\n[2/4] 生成测试音频 ...")
    wav = make_test_wav(os.path.join(tempfile.gettempdir(), "konkacast-test.wav"))
    print(f"  {wav}  ({os.path.getsize(wav) / 1024:.0f} KB)")

    print("\n[3/4] 启动本地媒体服务 ...")
    ms = MediaServer(port=8899)
    ms.start()
    host = f"http://{ip}:{ms.real_port}"
    url, fname = ms.register(wav, host)
    print(f"  服务地址: {url}")

    print("\n[4/4] 逐个设备推送并播放")
    for r in renderers:
        print(f"\n  ---- {r.name} ----")
        info = r.transport_info()
        print(f"   运输状态   : {info.get('data', {}).get('CurrentTransportState', '?')}")
        vol = r.get_volume()
        print(f"   当前音量   : {vol.get('data', {}).get('CurrentVolume', '不支持')}")

        res = r.cast_media(url, "KonkaCast 测试音", mime="audio/wav",
                           size=os.path.getsize(wav))
        if not res.get("ok"):
            print(f"   推送失败   : {res.get('error')} HTTP={res.get('status')}")
            continue
        print("   推送成功   : SetAVTransportURI + Play 均返回 OK")
        time.sleep(2.0)
        pos = r.position_info()
        tinfo = r.transport_info()
        print(f"   播放状态   : {tinfo.get('data', {}).get('CurrentTransportState')}")
        print(f"   播放位置   : {pos.get('data', {}).get('RelTime', '?')}"
              f" / {pos.get('data', {}).get('TrackDuration', '?')}")
        r.stop()
        print("   已停止播放")

    ms.stop()
    print("\n自检结束。上方若显示 PLAYING / 位置在走，说明协议链路完全打通。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
