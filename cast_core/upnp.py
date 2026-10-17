# -*- coding: utf-8 -*-
"""UPnP AVTransport / RenderingControl 控制点。
所有 SOAP 调用只依赖标准库。国产电视固件实现差异很大，
这里对错误做了宽松处理：失败会返回结构化错误而不是抛异常。
"""
from __future__ import annotations

import mimetypes
from xml.etree import ElementTree as ET

from .util import http_post, xml_escape

SOAP_ENV = "http://schemas.xmlsoap.org/soap/envelope/"

# 常见容器的 DLNA 能力签名
STREAMING_FLAG = "DLNA.ORG_OP=01"          # 不可 seek（直播流）
INTERACTIVE_FLAG = "DLNA.ORG_OP=01;DLNA.ORG_OP=10"  # 可 seek（本地文件）


def _envelope(service_type: str, action: str, args: dict) -> bytes:
    body = "".join(f"<{k}>{v}</{k}>" for k, v in args.items())
    xml = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<s:Envelope xmlns:s="{SOAP_ENV}" '
        's:encodingStyle="http://schemas.xmlsoap.org/soap/encoding/">'
        f'<s:Body><u:{action} xmlns:u="{service_type}">{body}</u:{action}></s:Body>'
        "</s:Envelope>"
    )
    return xml.encode("utf-8")


def call(service_type: str, control_url: str, action: str, args: dict, timeout: float = 8.0) -> dict:
    """执行一次 SOAP 调用。返回 {"ok": bool, "status": int, "data": {}, "raw": "", "error": ""}"""
    headers = {
        "Content-Type": 'text/xml; charset="utf-8"',
        "SOAPACTION": f'"{service_type}#{action}"',
        "Connection": "close",
    }
    status, raw = http_post(control_url, _envelope(service_type, action, args), headers, timeout)

    result = {"ok": False, "status": status, "data": {}, "raw": raw, "error": ""}
    if status == 0:
        result["error"] = raw
        return result
    if status >= 400:
        # 试图从 SOAP Fault 里捞出可读错误
        try:
            root = ET.fromstring(raw)
            for node in root.iter():
                if node.tag.endswith("errorDescription") and node.text:
                    result["error"] = node.text.strip()
                    return result
        except ET.ParseError:
            pass
        result["error"] = f"HTTP {status}"
        return result

    result["ok"] = True
    try:
        root = ET.fromstring(raw)
        for node in root.iter():
            tag = node.tag.split("}")[-1] if "}" in node.tag else node.tag
            if tag not in ("Envelope", "Body"):
                result["data"][tag] = (node.text or "").strip()
    except ET.ParseError:
        pass
    return result


def guess_mime(path_or_url: str) -> str:
    mime, _ = mimetypes.guess_type(path_or_url)
    fallback = {
        ".mkv": "video/x-matroska",
        ".ts": "video/mpeg",
        ".m2ts": "video/mpeg",
        ".rmvb": "video/vnd.rn-realvideo",
        ".flv": "video/x-flv",
        ".opus": "audio/ogg",
        ".m4a": "audio/mp4",
        ".heic": "image/heic",
    }
    if mime:
        return mime
    lower = path_or_url.lower()
    for ext, val in fallback.items():
        if lower.endswith(ext):
            return val
    return "video/mpeg"


def pick_dlna_class(mime: str) -> str:
    if mime.startswith("video/"):
        return "object.item.videoItem"
    if mime.startswith("audio/"):
        return "object.item.audioItem.musicTrack"
    if mime.startswith("image/"):
        return "object.item.imageItem.photo"
    return "object.item.videoItem"


def build_didl(item_id: str, title: str, url: str, mime: str, upnp_class: str | None = None,
               size: int | None = None, duration: str | None = None) -> str:
    """生成 DIDL-Lite 元数据。返回未转义的原始 XML，由调用方决定何时转义。"""
    upnp_class = upnp_class or pick_dlna_class(mime)
    size_attr = f' size="{size}"' if size else ""
    dur_attr = f' duration="{duration}"' if duration else ""
    return (
        '<DIDL-Lite xmlns="urn:schemas-upnp-org:metadata-1-0/DIDL-Lite/" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/" '
        'xmlns:upnp="urn:schemas-upnp-org:metadata-1-0/upnp/" '
        'xmlns:dlna="urn:schemas-dlna-org:metadata-1-0/">'
        f'<item id="{item_id}" parentID="0" restricted="1">'
        f"<upnp:class>{upnp_class}</upnp:class>"
        f"<dc:title>{xml_escape(title)}</dc:title>"
        f'<res protocolInfo="http-get:*:{mime}:*"{size_attr}{dur_attr}>{xml_escape(url)}</res>'
        "</item></DIDL-Lite>"
    )


class Renderer:
    """一台已发现的电视 / 投屏接收端。"""

    def __init__(self, info: dict):
        self.info = info
        self.name = info.get("friendly_name") or info.get("model_name") or info.get("ip") or "未命名设备"
        self.vendor = info.get("manufacturer") or info.get("model_name") or ""
        self.model = info.get("model_name") or ""
        self.ip = info.get("ip", "")
        self.services = info.get("services", {})
        self.last_error = ""
        # 一台电视上可能同时跑多个 DLNA 服务（比如康佳的乐播 + 极光TV），
        # 它们 IP 相同但端口不同，所以唯一标识必须用完整描述地址，不能用 IP。
        self.key = info.get("location") or f"{self.ip}:0"

    def reliability(self) -> int:
        """打分排优先级：同一台电视上多个接收端时，挑实测最能播的那个。

        康佳 LED55T60U 上实测：乐播 HappyCast 收 URI 后立刻 PLAYING；
        极光 TV DLNA 会把地址收下但不播，只能当备胎。
        """
        text = f"{self.name} {self.vendor} {self.model} {self.key}".lower()
        score = 0
        if "lebo" in text or "happycast" in text or "happycast" in self.key.lower():
            score += 100
        if "极光" in text or "qqlive" in text:
            score -= 50
        # 服务齐全度也算分，缺 AVTransport 的根本没法推
        if self.services.get("AVTransport"):
            score += 10
        if self.services.get("RenderingControl"):
            score += 2
        return score

    # ---------- 内部 ----------
    def _svc(self, alias: str) -> tuple[str, str] | None:
        s = self.services.get(alias)
        if not s:
            self.last_error = f"设备未提供 {alias} 服务"
            return None
        return s["service_type"], s["control_url"]

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "vendor": self.vendor,
            "model": self.model,
            "ip": self.ip,
            "location": self.info.get("location", ""),
            "device_type": self.info.get("device_type", ""),
            "services": sorted(self.services.keys()),
            "last_error": self.last_error,
        }

    # ---------- AVTransport ----------
    def set_uri(self, url: str, didl_xml: str) -> dict:
        svc = self._svc("AVTransport")
        if not svc:
            return {"ok": False, "error": self.last_error}
        return call(svc[0], svc[1], "SetAVTransportURI", {
            "InstanceID": "0",
            "CurrentURI": xml_escape(url),
            "CurrentURIMetaData": xml_escape(didl_xml),
        })

    def play(self, speed: str = "1", timeout: float = 8.0) -> dict:
        svc = self._svc("AVTransport")
        if not svc:
            return {"ok": False, "error": self.last_error}
        return call(svc[0], svc[1], "Play", {"InstanceID": "0", "Speed": speed}, timeout=timeout)

    def pause(self) -> dict:
        svc = self._svc("AVTransport")
        if not svc:
            return {"ok": False, "error": self.last_error}
        return call(svc[0], svc[1], "Pause", {"InstanceID": "0"})

    def stop(self) -> dict:
        svc = self._svc("AVTransport")
        if not svc:
            return {"ok": False, "error": self.last_error}
        return call(svc[0], svc[1], "Stop", {"InstanceID": "0"})

    def seek(self, target_seconds: int) -> dict:
        """target 既可以是秒数，也可以是 HH:MM:SS。统一用秒数构造。"""
        h, rem = divmod(int(target_seconds), 3600)
        m, s = divmod(rem, 60)
        hms = f"{h:02d}:{m:02d}:{s:02d}"
        svc = self._svc("AVTransport")
        if not svc:
            return {"ok": False, "error": self.last_error}
        return call(svc[0], svc[1], "Seek", {
            "InstanceID": "0",
            "Unit": "REL_TIME",
            "Target": hms,
        })

    def position_info(self) -> dict:
        svc = self._svc("AVTransport")
        if not svc:
            return {"ok": False, "error": self.last_error}
        return call(svc[0], svc[1], "GetPositionInfo", {"InstanceID": "0"}, timeout=4.0)

    def transport_info(self) -> dict:
        svc = self._svc("AVTransport")
        if not svc:
            return {"ok": False, "error": self.last_error}
        return call(svc[0], svc[1], "GetTransportInfo", {"InstanceID": "0"}, timeout=4.0)

    def next_track(self) -> dict:
        svc = self._svc("AVTransport")
        if not svc:
            return {"ok": False, "error": self.last_error}
        return call(svc[0], svc[1], "Next", {"InstanceID": "0"})

    def previous_track(self) -> dict:
        svc = self._svc("AVTransport")
        if not svc:
            return {"ok": False, "error": self.last_error}
        return call(svc[0], svc[1], "Previous", {"InstanceID": "0"})

    # ---------- RenderingControl ----------
    def set_volume(self, volume: int) -> dict:
        volume = max(0, min(100, int(volume)))
        svc = self._svc("RenderingControl")
        if not svc:
            return {"ok": False, "error": self.last_error}
        return call(svc[0], svc[1], "SetVolume", {
            "InstanceID": "0", "Channel": "Master", "DesiredVolume": str(volume),
        })

    def get_volume(self) -> dict:
        svc = self._svc("RenderingControl")
        if not svc:
            return {"ok": False, "error": self.last_error}
        return call(svc[0], svc[1], "GetVolume", {
            "InstanceID": "0", "Channel": "Master",
        }, timeout=4.0)

    def set_mute(self, muted: bool) -> dict:
        svc = self._svc("RenderingControl")
        if not svc:
            return {"ok": False, "error": self.last_error}
        return call(svc[0], svc[1], "SetMute", {
            "InstanceID": "0", "Channel": "Master", "DesiredMute": "1" if muted else "0",
        })

    # ---------- 组合动作 ----------
    def cast_media(self, url: str, title: str, mime: str | None = None,
                   size: int | None = None, duration: str | None = None,
                   upnp_class: str | None = None, autoplay: bool = True) -> dict:
        """推送一条媒体资源。"""
        mime = mime or guess_mime(url)
        didl = build_didl("konkacast-0", title, url, mime, upnp_class, size, duration)
        set_res = self.set_uri(url, didl)
        if not set_res["ok"]:
            # 部分老旧固件不认 MetaData，退化为只带 URL 重试一次
            bare = self.set_uri(url, "")
            if not bare["ok"]:
                return set_res
            set_res = bare
        if autoplay:
            play_res = self.play()
            if not play_res["ok"]:
                return {**play_res, "set_uri_ok": True}
        return set_res
