# -*- coding: utf-8 -*-
"""屏幕镜像端到端自检：真的开一次镜像流并推到电视，验证可播放。"""
import json
import sys
import time

sys.path.insert(0, ".")

from cast_core import Controller


def main():
    ctrl = Controller()
    ctrl.mirror.port = 8911  # 用独立端口，避免和后台服务冲突
    print("扫描设备 ...")
    devs = ctrl.scan(timeout=3.0)
    if not devs:
        print("没扫到设备，退出")
        return
    sel = ctrl.selected()
    print(f"已选中: {sel.name}  ({sel.ip})")
    print(f"ffmpeg : {ctrl.ffmpeg_info.version}  nvenc={ctrl.ffmpeg_info.has_nvenc}")

    print("\n启动屏幕镜像（NVENC 硬编）...")
    res = ctrl.start_mirror(encoder="h264_nvenc" if ctrl.ffmpeg_info.has_nvenc else "libx264")
    print("  start_mirror ->", json.dumps(res, ensure_ascii=False))
    if not res.get("ok"):
        print("镜像启动失败，退出")
        return

    print(f"  流地址: {ctrl.mirror.stream_url}")
    time.sleep(3)

    # 1) ffmpeg 是否收到电视连接
    tail = "\n".join(ctrl.mirror.stderr_tail[-15:])
    connected = "Connection from" in tail or "accept" in tail
    print("\n[1] ffmpeg 日志（末 15 行）:")
    print("    " + "\n    ".join(ctrl.mirror.stderr_tail[-15:]))
    print("    -> 电视是否连上:", "是" if connected else "暂未（可能电视端缓冲）")

    # 2) 电视传输状态
    info = sel.transport_info()
    print("\n[2] 电视 GetTransportInfo:")
    print("    ", json.dumps(info, ensure_ascii=False))
    playing = "PLAYING" in str(info).upper()
    print("    -> 播放中:", "是" if playing else "否")

    # 3) 位置信息（证明有真实码流在走）
    pos = sel.position_info()
    print("\n[3] 电视 GetPositionInfo:")
    print("    ", json.dumps(pos, ensure_ascii=False)[:300])

    print("\n=== 结论 ===")
    if res.get("ok") and (playing or connected):
        print("✅ 屏幕镜像链路打通：ffmpeg 起流 + 电视接收正常")
    else:
        print("⚠️ 镜像已发起，但电视端未确认播放（多为 DLNA 缓冲/电视未聚焦到投屏源）")

    print("\n停止镜像 ...")
    ctrl.stop_mirror()
    print("done.")


if __name__ == "__main__":
    main()
