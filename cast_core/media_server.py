# -*- coding: utf-8 -*-
"""本地 HTTP 媒体服务。
把本机文件映射到 /m/<token>/<filename>，补齐 Range 支持和 DLNA 专有响应头，
这样电视才能原生解码、随意拖动进度条（电脑几乎不耗 CPU）。
"""
from __future__ import annotations

import os
import socket
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import quote, unquote

from .upnp import guess_mime

# Windows 上 SO_REUSEADDR 的语义和 Unix 不同：它允许多个进程同时绑定同一个
# 端口，后启动的会静默抢走请求——这是极难排查的坑，必须关掉。
ALLOW_REUSE = sys.platform != "win32"


class MediaLibrary:
    """文件路径 -> 服务 token 的注册表。"""

    def __init__(self):
        self._lock = threading.Lock()
        self._files: dict[int, str] = {}
        self._next = 1

    def add(self, abs_path: str) -> tuple[int, str]:
        with self._lock:
            for token, existing in self._files.items():
                if os.path.normcase(existing) == os.path.normcase(abs_path):
                    return token, os.path.basename(abs_path)
            token = self._next
            self._files[token] = abs_path
            self._next += 1
            return token, os.path.basename(abs_path)

    def get(self, token: int) -> str | None:
        with self._lock:
            return self._files.get(token)

    def clear(self) -> None:
        with self._lock:
            self._files.clear()

    def __len__(self) -> int:
        return len(self._files)


class _MediaHandler(BaseHTTPRequestHandler):
    library: MediaLibrary = None  # type: ignore  由 make_server 注入
    server_name = "KonkaCast/1.0 UPnP/1.1 DLNADOC/1.50"
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):
        pass  # 静音：控制台有自己的日志面板

    # ---------- helpers ----------
    def _send_404(self):
        body = b"KonkaCast 404 Not Found"
        self.send_response(404)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if self.command != "HEAD":
            try:
                self.wfile.write(body)
            except OSError:
                pass

    def _parse_range(self, header: str, size: int):
        """返回 (start, end) 闭区间；非法返回 None。"""
        if not header:
            return None
        spec = header.strip()
        if not spec.lower().startswith("bytes="):
            return None
        spec = spec.split("=", 1)[1].strip()
        try:
            if spec.endswith("-"):
                start = int(spec[:-1]) if spec[:-1] else 0
                end = size - 1
            elif spec.startswith("-"):
                start = max(0, size - int(spec[1:]))
                end = size - 1
            else:
                first, last = spec.split("-", 1)
                start = int(first)
                end = int(last) if last else size - 1
        except ValueError:
            return None
        if start < 0 or start >= size:
            return None
        return start, min(end, size - 1)

    def _resolve(self):
        path = unquote(self.path.split("?", 1)[0])
        parts = [p for p in path.split("/") if p]
        if len(parts) < 2 or parts[0] != "m":
            return None
        try:
            token = int(parts[1])
        except ValueError:
            return None
        real = self.library.get(token)
        if not real or not os.path.isfile(real):
            return None
        return real

    def _common_headers(self, size: int, mime: str, seekable: bool = True):
        self.send_header("Content-Type", mime)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Server", self.server_name)
        self.send_header("transferMode.dlna.org", "Streaming")
        self.send_header("realTimeInfo.dlna.org", "DLNA.ORG_TLAG=*")
        op_flags = "DLNA.ORG_OP=01;DLNA.ORG_OP=10" if seekable else "DLNA.ORG_OP=01"
        self.send_header("contentFeatures.dlna.org", f"{op_flags};DLNA.ORG_CI=0")
        self.send_header("Cache-Control", "no-cache")

    def _emit(self, real_path: str):
        size = os.path.getsize(real_path)
        mime = guess_mime(real_path)
        rng = self._parse_range(self.headers.get("Range"), size)

        try:
            fh = open(real_path, "rb")
        except OSError:
            self._send_404()
            return

        with fh:
            if rng:
                start, end = rng
                length = end - start + 1
                self.send_response(206)
                self.send_header(
                    "Content-Range", f"bytes {start}-{end}/{size}")
                self.send_header("Content-Length", str(length))
                self._common_headers(size, mime, seekable=True)
                self.end_headers()
                if self.command == "HEAD":
                    return
                self._stream(fh, start, length)
            else:
                self.send_response(200)
                self.send_header("Content-Length", str(size))
                self._common_headers(size, mime, seekable=True)
                self.end_headers()
                if self.command == "HEAD":
                    return
                self._stream(fh, 0, size)

    def _stream(self, fh, start: int, length: int):
        """分块推送文件，遇到客户端断开静默退出。"""
        fh.seek(start)
        remaining = length
        chunk = 256 * 1024
        try:
            while remaining > 0:
                data = fh.read(min(chunk, remaining))
                if not data:
                    break
                self.wfile.write(data)
                remaining -= len(data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            self.close_connection = True

    # ---------- verbs ----------
    def do_GET(self):
        real = self._resolve()
        if not real:
            self._send_404()
            return
        self._emit(real)

    def do_HEAD(self):
        real = self._resolve()
        if not real:
            self._send_404()
            return
        self._emit(real)

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Allow", "OPTIONS, GET, HEAD")
        self.send_header("Content-Length", "0")
        self.end_headers()


class _MediaHTTPServer(ThreadingHTTPServer):
    allow_reuse_address = ALLOW_REUSE
    daemon_threads = True

    def server_bind(self):
        # Windows 专属：独占端口（防止第二个实例抢请求），
        # 又不会像 allow_reuse_address=False 那样被 TIME_WAIT 卡住
        if sys.platform == "win32" and hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except OSError:
                pass
        ThreadingHTTPServer.server_bind(self)


class MediaServer:
    """ThreadingHTTPServer 薄封装。

    端口被占用时自动往后找（默认最多试 20 个）——否则会出现
    「绑定成功但请求全被上一个实例吃掉」这种极难排查的静默失败。
    """

    MAX_TRIES = 20

    def __init__(self, port: int = 8899, bind: str = "", verbose: bool = True):
        self.library = MediaLibrary()
        self.port = port
        handler = type("MediaHandler", (_MediaHandler,), {"library": self.library})
        last_error = None
        for offset in range(self.MAX_TRIES):
            candidate = port + offset
            try:
                self._httpd = _MediaHTTPServer((bind, candidate), handler)
                break
            except OSError as e:
                last_error = e
        else:
            raise RuntimeError(
                f"媒体服务端口 {port}~{port + self.MAX_TRIES - 1} 都被占用了：{last_error}")
        if self.real_port != port and verbose:
            print(f"  [提示] 端口 {port} 已被占用，媒体服务改用 {self.real_port}")
        self._httpd.daemon_threads = True
        self._thread: threading.Thread | None = None

    @property
    def real_port(self) -> int:
        return self._httpd.server_address[1]

    def start(self):
        self._thread = threading.Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()

    def stop(self):
        try:
            self._httpd.shutdown()
            self._httpd.server_close()
        except Exception:
            pass

    def register(self, abs_path: str, host_url: str) -> tuple[str, str]:
        """把文件登记到媒体库，返回 (url, filename)。"""
        token, fname = self.library.add(os.path.abspath(abs_path))
        # 中文/空格文件名必须百分号编码，服务端 _resolve 会 unquote 还原
        url = f"{host_url}/m/{token}/{quote(fname)}"
        return url, fname
