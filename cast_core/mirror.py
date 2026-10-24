# -*- coding: utf-8 -*-
"""屏幕镜像：抓屏 -> H.264/AAC 编码 -> 经本进程内 HTTP 服务推给电视。

电视端拿到的是一个直播流地址，因此延迟天然在 1~4 秒量级，
这是 DLNA 路线的固有成本（低延迟要走 Miracast / 私有协议）。

设计要点（踩坑后）：
- ffmpeg 的 `-listen 1` 内置 HTTP 服务极其脆弱，电视一断开/重连就会
  WSAECONNABORTED(-10053) 直接退出，镜像流断掉。
- 改成本进程内常驻 HTTP 服务：ffmpeg 持续编码写 stdout -> 环形缓冲，
  服务按每个电视连接把缓冲里的实时流推过去。电视断开/重连只结束那条
  HTTP 响应，ffmpeg 永远活着，重连即恢复。
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.request import urlopen

from .util import local_ip

# Windows 下隐藏子进程窗口
CREATE_NO_WINDOW = 0x08000000


def _runtime_dirs() -> list[str]:
    """寻找本机可用的 UCRT/VC++ 运行时目录。

    部分机器（如本机）System32 缺 api-ms-win-crt-* API 集转发 DLL，
    ffmpeg 直接跑会 0xC0000135。conda / ComfyUI 的 Library\\bin 自带完整运行时，
    把它加进 PATH 即可让 ffmpeg 正常加载。
    """
    # 项目自带 ffmpeg + UCRT 运行时优先（已随源码打包进 bin/，开箱即用）
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    # 用户/启动脚本可用环境变量追加已知可用的运行时目录（分号分隔），
    # 例如本机依赖 ComfyUI 自带的运行时：KONKA_CAST_RUNTIME_DIRS=D:\ComfyUI\.ext\Library\bin
    extra_env = os.environ.get("KONKA_CAST_RUNTIME_DIRS")
    candidates: list[str] = [os.path.join(here, "bin")]
    if extra_env:
        candidates += [p for p in extra_env.split(";") if p.strip()]
    candidates += [
        r"C:\ProgramData\Anaconda3\Library\bin",
        r"C:\ProgramData\Miniconda3\Library\bin",
    ]
    # 通用 conda 用户环境（从环境变量推断，不硬编码用户名）
    conda = os.environ.get("CONDA_PREFIX")
    if conda:
        candidates.append(os.path.join(conda, "Library", "bin"))
    dirs: list[str] = []
    for d in candidates:
        if d and os.path.isdir(d) and os.path.exists(
            os.path.join(d, "api-ms-win-crt-runtime-l1-1-0.dll")
        ):
            dirs.append(d)
    return dirs


def ffmpeg_env() -> dict:
    """返回给 ffmpeg 子进程用的环境变量，已把运行时目录前置到 PATH。"""
    env = os.environ.copy()
    extra = _runtime_dirs()
    if extra:
        env["PATH"] = ";".join(extra + [env.get("PATH", "")])
    return env


VIDEO_SUFFIX = (".mp4", ".mkv", ".mov", ".avi", ".wmv", ".flv", ".webm", ".ts",
                ".m2ts", ".rmvb", ".rm", ".mpg", ".mpeg", ".vob", ".m4v", ".3gp")
AUDIO_SUFFIX = (".mp3", ".flac", ".wav", ".aac", ".m4a", ".ogg", ".opus", ".wma", ".ape")
IMAGE_SUFFIX = (".jpg", ".jpeg", ".png", ".bmp", ".gif", ".webp", ".heic", ".tif", ".tiff")


def is_video(path: str) -> bool:
    return path.lower().endswith(VIDEO_SUFFIX)


def is_audio(path: str) -> bool:
    return path.lower().endswith(AUDIO_SUFFIX)


def is_image(path: str) -> bool:
    return path.lower().endswith(IMAGE_SUFFIX)


def find_ffmpeg(custom: str | None = None) -> str | None:
    """按优先级找 ffmpeg：用户指定 -> 本目录 bin -> PATH。"""
    if custom and os.path.isfile(custom):
        return custom
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for candidate in ("ffmpeg.exe", "ffmpeg"):
        probe = os.path.join(here, "bin", candidate)
        if os.path.isfile(probe):
            return probe
    return shutil.which("ffmpeg")


class FfmpegInfo:
    def __init__(self, path: str | None):
        self.path = path
        self.ok = bool(path)
        self.version = ""
        self.has_nvenc = False
        self.has_qsv = False
        self.has_amf = False
        self.audio_devices: list[str] = []
        self.error = "" if path else "未找到 ffmpeg.exe"
        if self.ok:
            self._probe()

    def _run(self, args: list[str], timeout: float = 8.0) -> str:
        try:
            res = subprocess.run(
                [self.path] + args,
                capture_output=True, timeout=timeout,
                creationflags=CREATE_NO_WINDOW,
                env=ffmpeg_env(),
            )
            return (res.stdout + res.stderr).decode("utf-8", "ignore")
        except Exception as e:
            self.error = f"{type(e).__name__}: {e}"
            return ""

    def _probe(self):
        out = self._run(["-version"])
        m = re.search(r"ffmpeg version (\S+)", out)
        self.version = m.group(1) if m else "未知"

        enc = self._run(["-hide_banner", "-encoders"])
        self.has_nvenc = "h264_nvenc" in enc
        self.has_qsv = "h264_qsv" in enc
        self.has_amf = "h264_amf" in enc

        dev_out = self._run([
            "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"
        ], timeout=12.0)
        for m in re.finditer(r'\[dshow @ [^\]]+\]\s+"([^"]+)"\s+\(audio\)', dev_out):
            name = m.group(1)
            if name not in self.audio_devices:
                self.audio_devices.append(name)

    def to_dict(self) -> dict:
        return {
            "ok": self.ok,
            "path": self.path or "",
            "version": self.version,
            "nvenc": self.has_nvenc,
            "qsv": self.has_qsv,
            "amf": self.has_amf,
            "audio_devices": self.audio_devices,
            "error": self.error,
        }


class RingBuffer:
    """有上限的环形字节缓冲：写满后丢弃最旧数据，读端可实时跟随。"""

    def __init__(self, max_bytes: int = 8 * 1024 * 1024):
        self.max = max_bytes
        self.buf = bytearray()
        self.lock = threading.Lock()
        self.cond = threading.Condition(self.lock)
        self.stop_evt: threading.Event | None = None

    def write(self, data: bytes):
        if not data:
            return
        with self.lock:
            self.buf.extend(data)
            if len(self.buf) > self.max:
                del self.buf[: len(self.buf) - self.max]
            self.cond.notify_all()

    def stream(self, block: int = 65536):
        """生成器：从当前最新位置开始，实时吐出后续写入的字节。"""
        with self.lock:
            i = len(self.buf)
        while True:
            with self.lock:
                if i < len(self.buf):
                    chunk = bytes(self.buf[i:i + block])
                    i += len(chunk)
                    if chunk:
                        yield chunk
                        continue
                stop = bool(self.stop_evt and self.stop_evt.is_set())
            if stop:
                return
            with self.cond:
                self.cond.wait(timeout=0.3)


class _LiveStreamHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path in ("/live.ts", "/live", ""):
            self._serve()
        else:
            self.send_error(404)

    def _serve(self):
        ring = self.server.ring
        self.send_response(200)
        self.send_header("Content-Type", "video/mpeg")
        self.send_header("Cache-Control", "no-cache")
        self.send_header("Pragma", "no-cache")
        self.send_header("Connection", "close")
        self.end_headers()
        try:
            for chunk in ring.stream():
                if getattr(self.wfile, "closed", False):
                    break
                self.wfile.write(chunk)
                try:
                    self.wfile.flush()
                except Exception:
                    break
        except (BrokenPipeError, ConnectionResetError, OSError):
            # 电视断开：只是结束这一条响应，ffmpeg 继续活着
            pass

    def log_message(self, *args):
        pass


class _LiveServer(ThreadingHTTPServer):
    ring: RingBuffer | None = None


class MirrorSession:
    """一次屏幕镜像会话：ffmpeg 常驻编码 -> 环形缓冲 -> 本进程 HTTP 服务。"""

    def __init__(self, ffmpeg_path: str, port: int = 8900, host_ip: str | None = None):
        self.ffmpeg = ffmpeg_path
        self.port = port
        self.host_ip = host_ip or local_ip()
        self.proc: subprocess.Popen | None = None
        self._lock = threading.Lock()
        self.stderr_tail: list[str] = []
        self._reader: threading.Thread | None = None
        self._pump: threading.Thread | None = None
        self.ring = RingBuffer(max_bytes=8 * 1024 * 1024)
        self._stop_evt = threading.Event()
        self.ring.stop_evt = self._stop_evt
        self._httpd: _LiveServer | None = None
        self._server_thread: threading.Thread | None = None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    @property
    def stream_url(self) -> str:
        return f"http://{self.host_ip}:{self.port}/live.ts"

    def _read_stderr(self):
        if not self.proc or not self.proc.stderr:
            return
        try:
            for line in self.proc.stderr:
                text = line.decode("utf-8", "ignore").rstrip()
                self.stderr_tail.append(text)
                if len(self.stderr_tail) > 60:
                    self.stderr_tail.pop(0)
        except Exception:
            pass

    def _pump_stdout(self):
        try:
            while self.proc and self.proc.poll() is None:
                data = self.proc.stdout.read(65536)
                if not data:
                    break
                self.ring.write(data)
        except Exception:
            pass

    def _start_server(self):
        httpd = _LiveServer(("0.0.0.0", self.port), _LiveStreamHandler)
        httpd.ring = self.ring
        httpd.daemon_threads = True
        t = threading.Thread(target=httpd.serve_forever, daemon=True)
        t.start()
        self._httpd = httpd
        self._server_thread = t

    def _stop_server(self):
        if self._httpd:
            try:
                self._httpd.shutdown()
            except Exception:
                pass
            try:
                self._httpd.server_close()
            except Exception:
                pass
            self._httpd = None

    def start(
        self,
        width: int | None = None,
        height: int | None = None,
        fps: int = 30,
        bitrate: int = 8000,
        encoder: str = "auto",
        audio_device: str | None = None,
        offset_x: int = 0,
        offset_y: int = 0,
        scale: bool = True,
    ) -> dict:
        if self.running:
            return {"ok": True, "url": self.stream_url, "note": "已在推流"}

        enc = encoder
        if enc == "auto":
            enc = "libx264"
        if enc == "h264_nvenc":
            video_args = [
                "-c:v", "h264_nvenc", "-preset", "p1", "-tune", "ll",
                "-profile:v", "high", "-rc", "cbr",
                "-pix_fmt", "yuv420p",
            ]
        elif enc == "h264_qsv":
            video_args = [
                "-c:v", "h264_qsv", "-preset", "veryfast",
                "-look_ahead", "0", "-pix_fmt", "yuv420p",
            ]
        else:
            video_args = [
                "-c:v", "libx264", "-preset", "ultrafast", "-tune", "zerolatency",
                "-pix_fmt", "yuv420p",
            ]

        cmd: list[str] = [self.ffmpeg, "-hide_banner", "-loglevel", "warning"]

        # 输入 1：屏幕
        cmd += [
            "-f", "gdigrab",
            "-framerate", str(fps),
            "-offset_x", str(offset_x),
            "-offset_y", str(offset_y),
        ]
        if width and height:
            cmd += ["-video_size", f"{width}x{height}"]
        cmd += ["-i", "desktop"]

        # 输入 2：音频（可选）
        audio_used = False
        if audio_device:
            cmd += [
                "-f", "dshow",
                "-rtbufsize", "64M",
                "-i", f"audio={audio_device}",
            ]
            audio_used = True

        # 缩放：电视多为 1080p，超采样没有意义
        if scale:
            cmd += ["-vf", "scale='min(1920,iw)':'min(1080,ih)':force_original_aspect_ratio=decrease,"
                          "pad=ceil(iw/2)*2:ceil(ih/2)*2"]

        cmd += video_args
        cmd += [
            "-b:v", f"{bitrate}k",
            "-maxrate", f"{int(bitrate * 1.2)}k",
            "-bufsize", f"{int(bitrate * 2)}k",
            "-g", str(fps * 2),
            "-r", str(fps),
        ]

        if audio_used:
            cmd += ["-c:a", "aac", "-b:a", "128k", "-ac", "2", "-ar", "44100"]

        # 输出：MPEG-TS 写 stdout，由本进程内 HTTP 服务推给电视
        cmd += ["-flush_packets", "1", "-f", "mpegts", "-"]

        # 1) 先起 HTTP 服务（电视连的是它，而不是 ffmpeg 本身）
        self._stop_evt.clear()
        try:
            self._start_server()
        except Exception as e:
            return {"ok": False, "error": f"镜像服务端口 {self.port} 启动失败：{e}"}

        # 2) 起 ffmpeg（stdout 接到环形缓冲）
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                stdin=subprocess.DEVNULL,
                bufsize=0,
                creationflags=CREATE_NO_WINDOW,
                env=ffmpeg_env(),
            )
        except Exception as e:
            self._stop_server()
            return {"ok": False, "error": f"{type(e).__name__}: {e}", "cmd": " ".join(cmd)}

        self._pump = threading.Thread(target=self._pump_stdout, daemon=True)
        self._pump.start()
        self._reader = threading.Thread(target=self._read_stderr, daemon=True)
        self._reader.start()

        # 3) 探测端口是否真的起来了
        for _ in range(20):
            time.sleep(0.15)
            if not self.running:
                tail = "\n".join(self.stderr_tail[-12:])
                self._stop_server()
                return {"ok": False, "error": f"ffmpeg 启动失败：\n{tail}", "cmd": " ".join(cmd)}
            if self._probe_port():
                return {
                    "ok": True, "url": self.stream_url, "encoder": enc,
                    "audio": audio_device or "", "pid": self.proc.pid,
                }
        tail = "\n".join(self.stderr_tail[-12:])
        self._stop_server()
        return {
            "ok": True, "url": self.stream_url, "encoder": enc,
            "note": "进程已启动但端口未即时响应，可能仍在初始化",
            "stderr": tail,
        }

    def _probe_port(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self.port), timeout=0.5):
                return True
        except Exception:
            return False

    def stop(self) -> dict:
        with self._lock:
            self._stop_evt.set()
            if self.proc:
                try:
                    self.proc.terminate()
                    try:
                        self.proc.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        self.proc.kill()
                except Exception:
                    pass
                self.proc = None
            self._stop_server()
            self.stderr_tail.clear()
        return {"ok": True}
