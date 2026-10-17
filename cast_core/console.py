# -*- coding: utf-8 -*-
"""本地控制台服务：REST API + 静态前端。启动后浏览器自动打开操作界面。"""
from __future__ import annotations

import json
import mimetypes
import os
import socket
import sys
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")


class _ConsoleHandler(BaseHTTPRequestHandler):
    controller = None  # type: ignore  由 ConsoleServer 注入
    server_name = "KonkaCast/1.0"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass

    # ---------- helpers ----------
    def _json(self, data: dict, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {}
        raw = self.rfile.read(length)
        if not raw:
            return {}
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def _serve_static(self, rel_path: str):
        if rel_path in ("", "/"):
            rel_path = "index.html"
        rel_path = rel_path.lstrip("/")
        full = os.path.abspath(os.path.join(WEB_DIR, rel_path))
        if not full.startswith(os.path.abspath(WEB_DIR)) or not os.path.isfile(full):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        mime, _ = mimetypes.guess_type(full)
        if mime is None:
            mime = "application/octet-stream"
        if mime.startswith("text/") or mime in ("application/javascript", "application/json"):
            mime += "; charset=utf-8"
        with open(full, "rb") as fh:
            data = fh.read()
        self.send_response(200)
        self.send_header("Content-Type", mime)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(data)
            except OSError:
                pass

    # ---------- routes ----------
    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path
        ctrl = self.controller

        if path.startswith("/api/"):
            api = path[5:]
            try:
                if api == "status":
                    return self._json(ctrl.status())
                if api == "devices":
                    return self._json({"devices": ctrl.device_list()})
                if api == "browse":
                    qs = parse_qs(parsed.query)
                    target = unquote(qs.get("path", [""])[0]) or None
                    return self._json(ctrl.list_dir(target))
                if api == "ffmpeg":
                    return self._json(ctrl.ffmpeg_info.to_dict())
                return self._json({"ok": False, "error": f"未知接口 {api}"}, 404)
            except Exception as e:
                return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

        self._serve_static(path)

    def do_POST(self):
        path = urlparse(self.path).path
        ctrl = self.controller

        if not path.startswith("/api/"):
            return self._json({"ok": False, "error": "not found"}, 404)

        api = path[5:]
        # 上传是二进制 body，必须抢在 JSON 解析之前处理
        if api == "upload":
            return self._json(self._handle_upload(self.path))

        payload = self._body()
        try:
            if api == "scan":
                devices = ctrl.scan(timeout=float(payload.get("timeout", 3.0)))
                return self._json({"ok": True, "devices": devices})
            if api == "select":
                # 优先用唯一标识 key(location)，老前端只传 ip 也能用
                ident = payload.get("key") or payload.get("ip") or ""
                ok = ctrl.select(ident)
                msg = "已选中设备" if ok else "找不到这台设备，先点重新扫描"
                return self._json({"ok": ok, "error": "" if ok else msg})
            if api == "cast_file":
                return self._json(ctrl.cast_file(payload.get("path", "")))
            if api == "cast_url":
                return self._json(ctrl.cast_url(payload.get("url", ""),
                                                payload.get("title")))
            if api == "mirror/start":
                return self._json(ctrl.start_mirror(**payload))
            if api == "mirror/stop":
                return self._json(ctrl.stop_mirror())
            if api == "control":
                return self._json(ctrl.control(payload.get("action", ""),
                                               payload.get("value")))
            if api == "ffmpeg/fetch":
                from .ffmpeg_fetch import fetch_state, start_fetch
                start_fetch()
                return self._json({"ok": True, "state": fetch_state()})
            if api == "ffmpeg/fetch-status":
                from .ffmpeg_fetch import fetch_state
                return self._json({"ok": True, "state": fetch_state()})
            if api == "ffmpeg/refresh":
                from .mirror import find_ffmpeg, FfmpegInfo
                ctrl.ffmpeg_path = find_ffmpeg(payload.get("path"))
                ctrl.ffmpeg_info = FfmpegInfo(ctrl.ffmpeg_path)
                ctrl.mirror.ffmpeg = ctrl.ffmpeg_path or "ffmpeg"
                return self._json({"ok": True, "ffmpeg": ctrl.ffmpeg_info.to_dict()})
            return self._json({"ok": False, "error": f"未知接口 {api}"}, 404)
        except Exception as e:
            return self._json({"ok": False, "error": f"{type(e).__name__}: {e}"}, 500)

    def _handle_upload(self, request_path: str) -> dict:
        """接收拖拽进来的二进制文件，落盘后按普通本地文件推送。"""
        from . import uploads
        qs = parse_qs(urlparse(request_path).query)
        raw_name = unquote(qs.get("name", [""])[0]) or "unnamed"
        length = int(self.headers.get("Content-Length") or 0)
        if not length:
            return {"ok": False, "error": "收到空文件"}
        if length > 4 * 1024 * 1024 * 1024:
            return {"ok": False, "error": "文件超过 4GB，请直接在文件列表里选择"}
        try:
            data = self.rfile.read(length)
        except OSError as e:
            return {"ok": False, "error": f"接收失败：{e}"}
        path = uploads.save(data, raw_name)
        self.controller.log("info", f"接收上传文件 {os.path.basename(path)}")
        return self.controller.cast_file(path, title=uploads.safe_name(raw_name))

    def do_HEAD(self):
        self.do_GET()


class _ConsoleHTTPServer(ThreadingHTTPServer):
    # Windows 的 SO_REUSEADDR 会让多个进程同时绑到一个端口，关掉它，
    # 端口冲突才能正常暴露出来并被下面的重试逻辑捕获
    allow_reuse_address = sys.platform != "win32"
    daemon_threads = True

    def server_bind(self):
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        ThreadingHTTPServer.server_bind(self)


class ConsoleServer:
    """端口被占用时自动往后找，避免静默抢占导致界面打不开。"""

    MAX_TRIES = 20

    def __init__(self, controller, port: int = 8770):
        self.port = port
        self.controller = controller
        handler = type("ConsoleHandler", (_ConsoleHandler,), {"controller": controller})
        last_error = None
        for offset in range(self.MAX_TRIES):
            candidate = port + offset
            try:
                self._httpd = _ConsoleHTTPServer(("127.0.0.1", candidate), handler)
                break
            except OSError as e:
                last_error = e
        else:
            raise RuntimeError(
                f"控制台端口 {port}~{port + self.MAX_TRIES - 1} 都被占用了：{last_error}")
        self._httpd.daemon_threads = True

    @property
    def real_port(self) -> int:
        return self._httpd.server_address[1]

    def start(self, open_browser: bool = True):
        thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        thread.start()
        if open_browser:
            threading.Timer(0.8, lambda: webbrowser.open(
                f"http://127.0.0.1:{self.real_port}/")).start()

    def stop(self):
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass
