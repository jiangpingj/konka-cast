# -*- coding: utf-8 -*-
"""投屏控制器：把设备发现、推送、镜像、播放控制串成一个状态机。"""
from __future__ import annotations

import ctypes
import os
import time

import sys

from . import ssdp
from .media_server import MediaServer
from .mirror import FfmpegInfo, MirrorSession, find_ffmpeg, is_audio, is_image, is_video
from .upnp import Renderer, guess_mime, pick_dlna_class
from .util import human_size, local_ip

if sys.platform == "win32":
    try:
        _user32 = ctypes.windll.user32
    except OSError:
        _user32 = None
else:
    _user32 = None


class Controller:
    def __init__(self, media_port: int = 8899, console_port: int = 8770):
        self.local_ip = local_ip()
        self.media_port = media_port
        self.console_port = console_port
        self.media = MediaServer(port=media_port)
        self.media.start()
        self.host_url = f"http://{self.local_ip}:{self.media.real_port}"

        # key = 描述地址(location)，不是 IP。
        # 同一台电视上可能同时跑多个 DLNA 服务，IP 相同端口不同，
        # 用 IP 当键会让它们互相覆盖，选中谁全看 SSDP 返回顺序。
        self.devices: dict[str, Renderer] = {}
        self.selected_key: str | None = None
        self.last_scan = 0.0

        self.ffmpeg_path = find_ffmpeg()
        self.ffmpeg_info = FfmpegInfo(self.ffmpeg_path)
        self.mirror = MirrorSession(self.ffmpeg_path or "ffmpeg", port=8900,
                                    host_ip=self.local_ip)
        self.notes: list[dict] = []

    # ---------- 工具 ----------
    def log(self, level: str, text: str):
        entry = {"t": time.strftime("%H:%M:%S"), "level": level, "text": text}
        self.notes.append(entry)
        if len(self.notes) > 300:
            self.notes.pop(0)
        return entry

    @property
    def selected_ip(self) -> str | None:
        """选中设备的 IP，给还按 IP 取值的旧代码用。"""
        dev = self.selected()
        return dev.ip if dev else None

    def selected(self) -> Renderer | None:
        return self.devices.get(self.selected_key) if self.selected_key else None

    def select(self, ident: str) -> bool:
        """选中一台设备。

        ident 可以是唯一标识 location（推荐），也可以是 IP。
        传 IP 且该 IP 上有多个接收端时，挑可靠性最高的那个。
        """
        if not ident:
            return False
        if ident in self.devices:
            self.selected_key = ident
            self.log("info", f"已选中 {self.devices[ident].name}")
            return True

        # 退化到 IP 匹配：同一 IP 上可能有多个接收端，按可靠性排序取最优
        cands = [k for k, d in self.devices.items() if d.ip == ident]
        if cands:
            cands.sort(key=lambda k: -self.devices[k].reliability())
            self.selected_key = cands[0]
            self.log("info", f"已选中 {self.devices[cands[0]].name}")
            return True
        return False

    # ---------- 发现 ----------
    def scan(self, timeout: float = 3.0) -> list[dict]:
        try:
            infos = ssdp.discover(timeout=timeout)
        except Exception as e:
            self.log("error", f"扫描失败：{e}")
            return []

        found: dict[str, Renderer] = {}
        for info in infos:
            dev = Renderer(info)
            # 用 location 去重，同一 IP 上的多个接收端都会被保留下来
            found[dev.key] = dev

        # SSDP 基于 UDP，电视偶尔会漏应答一轮（连续快速扫描时尤其明显）。
        # 直接拿本轮结果覆盖会把偶发丢包误判成设备离线，
        # 所以这里做合并：连续漏 3 轮才真的踢掉。
        miss = getattr(self, "_miss", {})
        for k in self.devices:
            miss[k] = 0 if k in found else miss.get(k, 0) + 1
        merged: dict[str, Renderer] = {}
        for k, dev in self.devices.items():
            if k in found:
                merged[k] = found[k]
            elif miss.get(k, 0) < 3:
                merged[k] = dev
        merged.update(found)
        self._miss = miss
        self.devices = merged

        lost = self.selected_key and self.selected_key not in found
        if self.selected_key and self.selected_key not in self.devices:
            self.log("warn", "原选中设备已离线")
            self.selected_key = None
        elif lost:
            self.log("warn", "原选中设备本轮没应答，暂时保留")
        if not self.selected_key and self.devices:
            # 按可靠性排序，挑最可能真的能播的那个，而不是碰运气按顺序取第一个
            best = sorted(self.devices.items(),
                          key=lambda kv: (-kv[1].reliability(), kv[0]))[0]
            self.selected_key = best[0]
            self.log("info", f"自动选中 {best[1].name}")

        self.last_scan = time.time()
        self.log("info", f"扫描完成，发现 {len(self.devices)} 台接收设备")
        return self.device_list()

    def device_list(self) -> list[dict]:
        out = []
        # 可靠性高的排前面，界面上用户第一眼看到的就是推荐的那个
        for key, dev in sorted(self.devices.items(),
                               key=lambda kv: (-kv[1].reliability(), kv[0])):
            d = dev.to_dict()
            d["selected"] = key == self.selected_key
            out.append(d)
        return out

    # ---------- 推送本地文件 ----------
    def cast_file(self, file_path: str, title: str | None = None,
                  subtitle: str | None = None) -> dict:
        dev = self.selected()
        if not dev:
            return {"ok": False, "error": "还没有选中任何设备"}
        if not os.path.isfile(file_path):
            return {"ok": False, "error": f"文件不存在：{file_path}"}

        url, fname = self.media.register(file_path, self.host_url)
        mime = guess_mime(file_path)
        title = title or os.path.splitext(fname)[0]

        kind = "photo" if is_image(file_path) else ("music" if is_audio(file_path) else "video")
        upnp_class = pick_dlna_class(mime)

        res = dev.cast_media(url, title, mime=mime, size=os.path.getsize(file_path),
                             upnp_class=upnp_class)
        if res.get("ok"):
            self.log("info", f"已推送「{title}」到 {dev.name}")
            return {"ok": True, "title": title, "url": url, "size": human_size(
                os.path.getsize(file_path)), "kind": kind}
        self.log("error", f"推送失败：{res.get('error') or '未知错误'}")
        return {"ok": False, "error": res.get("error") or f"HTTP {res.get('status')}",
                "raw": res.get("raw", "")[:400]}

    # ---------- 推送网络地址 ----------
    def cast_url(self, url: str, title: str | None = None) -> dict:
        dev = self.selected()
        if not dev:
            return {"ok": False, "error": "还没有选中任何设备"}
        if not url.startswith(("http://", "https://")):
            return {"ok": False, "error": "只支持 http/https 地址"}
        res = dev.cast_media(url, title or os.path.basename(url.split("?")[0]) or "网络视频",
                             mime=guess_mime(url))
        if res.get("ok"):
            self.log("info", f"已推送网络地址到 {dev.name}")
            return {"ok": True}
        return {"ok": False, "error": res.get("error") or f"HTTP {res.get('status')}"}

    # ---------- 屏幕镜像 ----------
    @staticmethod
    def screen_info() -> dict:
        info = {"primary": {"w": 1920, "h": 1080}, "virtual": {"w": 1920, "h": 1080},
                "monitors": 1}
        if _user32 is None:
            return info
        try:
            info["primary"] = {"w": _user32.GetSystemMetrics(0), "h": _user32.GetSystemMetrics(1)}
            info["virtual"] = {"w": _user32.GetSystemMetrics(78), "h": _user32.GetSystemMetrics(79)}
            info["monitors"] = max(1, _user32.GetSystemMetrics(80))
        except Exception:
            pass
        return info

    def start_mirror(self, **kwargs) -> dict:
        dev = self.selected()
        if not dev:
            return {"ok": False, "error": "还没有选中任何设备"}
        if not self.ffmpeg_path:
            return {"ok": False, "error": "未找到 ffmpeg，屏幕镜像需要它（可在控制台一键下载）"}

        encoder = kwargs.pop("encoder", "auto")
        if encoder == "auto":
            encoder = ("h264_nvenc" if self.ffmpeg_info.has_nvenc
                       else "h264_qsv" if self.ffmpeg_info.has_qsv
                       else "libx264")
        if encoder == "h264_nvenc" and not self.ffmpeg_info.has_nvenc:
            encoder = "libx264"

        res = self.mirror.start(encoder=encoder, **kwargs)
        if not res.get("ok"):
            self.log("error", f"镜像启动失败：{res.get('error')}")
            return res

        # 让电视去拉这条直播流
        cast_res = dev.cast_media(
            self.mirror.stream_url, "电脑屏幕",
            mime="video/mpeg", upnp_class="object.item.videoItem.videoBroadcast")
        if not cast_res.get("ok"):
            self.mirror.stop()
            err = cast_res.get("error") or f"HTTP {cast_res.get('status')}"
            self.log("error", f"电视拒绝接收镜像流：{err}")
            return {"ok": False, "error": f"电视拒绝播放：{err}"}

        self.log("info", f"屏幕镜像已启动（编码器 {encoder}）")
        return {"ok": True, "encoder": encoder, "url": self.mirror.stream_url}

    def stop_mirror(self) -> dict:
        self.mirror.stop()
        dev = self.selected()
        if dev:
            dev.stop()
        self.log("info", "屏幕镜像已停止")
        return {"ok": True}

    # ---------- 播放控制 ----------
    def _guard(self) -> Renderer | None:
        return self.selected()

    def control(self, action: str, value=None) -> dict:
        dev = self._guard()
        if not dev:
            return {"ok": False, "error": "还没有选中任何设备"}
        try:
            if action == "play":
                r = dev.play()
            elif action == "pause":
                r = dev.pause()
            elif action == "stop":
                r = dev.stop()
            elif action == "seek":
                r = dev.seek(int(value))
            elif action == "volume":
                r = dev.set_volume(int(value))
            elif action == "mute":
                r = dev.set_mute(bool(value))
            elif action == "next":
                r = dev.next_track()
            elif action == "prev":
                r = dev.previous_track()
            else:
                return {"ok": False, "error": f"不支持的动作：{action}"}
        except Exception as e:
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}

        if r.get("ok"):
            return {"ok": True}
        return {"ok": False, "error": r.get("error") or f"HTTP {r.get('status')}"}

    def status(self) -> dict:
        dev = self._guard()
        pos = {"ok": False}
        transport = {"ok": False}
        volume = {"ok": False}
        if dev:
            pos = dev.position_info()
            transport = dev.transport_info()
            volume = dev.get_volume()
        return {
            "local_ip": self.local_ip,
            "media_base": self.host_url,
            "selected": dev.to_dict() if dev else None,
            "devices": self.device_list(),
            "ffmpeg": self.ffmpeg_info.to_dict(),
            "mirror": {
                "running": self.mirror.running,
                "url": self.mirror.stream_url,
                "stderr_tail": self.mirror.stderr_tail[-10:],
            },
            "screen": self.screen_info(),
            "playback": {
                "ok": pos.get("ok", False),
                "track_duration": pos.get("data", {}).get("TrackDuration", "--:--:--"),
                "rel_time": pos.get("data", {}).get("RelTime", "--:--:--"),
                "abs_time": pos.get("data", {}).get("AbsTime", "--:--:--"),
                "state": transport.get("data", {}).get("CurrentTransportState", "UNKNOWN"),
                "track_uri": pos.get("data", {}).get("TrackURI", ""),
                "volume": volume.get("data", {}).get("CurrentVolume"),
            },
            "notes": self.notes[-40:],
        }

    # ---------- 本地目录浏览 ----------
    def list_dir(self, path: str | None) -> dict:
        if not path:
            path = os.path.expanduser("~")
        path = os.path.abspath(path)
        entries = []
        try:
            for name in sorted(os.listdir(path)):
                full = os.path.join(path, name)
                if os.path.isdir(full):
                    entries.append({"name": name, "path": full, "type": "dir"})
                elif is_video(full) or is_audio(full) or is_image(full):
                    entries.append({
                        "name": name, "path": full, "type": "file",
                        "size": human_size(os.path.getsize(full)),
                        "kind": ("photo" if is_image(full)
                                 else "music" if is_audio(full) else "video"),
                    })
        except PermissionError:
            return {"ok": False, "error": "没有权限访问该目录", "path": path}
        except FileNotFoundError:
            return {"ok": False, "error": "目录不存在", "path": path}

        parent = os.path.dirname(path)
        return {
            "ok": True, "path": path, "parent": parent if parent != path else None,
            "entries": entries,
        }

    def shutdown(self):
        try:
            self.mirror.stop()
        except Exception:
            pass
        try:
            self.media.stop()
        except Exception:
            pass
