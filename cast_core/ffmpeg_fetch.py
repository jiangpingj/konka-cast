# -*- coding: utf-8 -*-
"""按需下载便携版 ffmpeg 到 项目/bin/ffmpeg.exe。

单线程从 CDN 拉 zip 在国内经常被压到几十 KB/s，这里做多线程分块下载，
实测能快好几倍。不支持 Range 的源自动降级为单线程。
"""
from __future__ import annotations

import os
import threading
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN_DIR = os.path.join(HERE, "bin")

SOURCES = [
    ("Gyan essentials 7.1",
     "https://github.com/GyanD/codexffmpeg/releases/download/7.1/ffmpeg-7.1-essentials_build.zip"),
    ("BtbN master win64",
     "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl.zip"),
    ("Gyan 官网镜像",
     "https://www.gyan.dev/ffmpeg/builds/packages/ffmpeg-7.1-essentials_build.zip"),
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

_state = {
    "running": False, "done": False, "ok": False, "stage": "", "percent": 0,
    "message": "", "error": "", "source": "", "path": "", "speed": "",
}
_thread: threading.Thread | None = None


def fetch_state() -> dict:
    return dict(_state)


def _reset():
    _state.update({
        "running": True, "done": False, "ok": False, "stage": "准备",
        "percent": 0, "message": "", "error": "", "source": "", "path": "", "speed": "",
    })


def _head(url: str) -> tuple[int, bool]:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA}, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as r:
            total = int(r.headers.get("Content-Length") or 0)
            return total, r.headers.get("Accept-Ranges") == "bytes"
    except Exception:
        return 0, False


def _download_parallel(url: str, dest: str, workers: int = 8) -> bool:
    total, supports_range = _head(url)
    if not total:
        return False
    if not supports_range:
        return _download_serial(url, dest)

    workers = max(1, min(workers, 16))
    part = -(-total // workers)
    ranges = [(i * part, min(total - 1, (i + 1) * part - 1)) for i in range(workers)]

    with open(dest, "wb") as fh:
        fh.truncate(total)

    progress = [0] * workers
    errors: list[str] = []
    start_ts = [0.0]
    lock = threading.Lock()

    def rate() -> str:
        elapsed = max(0.1, time.time() - start_ts[0])
        spd = sum(progress) / elapsed / 1024
        if spd > 1024:
            return f"{spd / 1024:.1f} MB/s"
        return f"{spd:.0f} KB/s"

    def worker(idx: int, start: int, end: int):
        if start > end:
            return
        headers = {"User-Agent": UA, "Range": f"bytes={start}-{end}"}
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "r+b") as out:
                out.seek(start)
                while True:
                    chunk = resp.read(1024 * 128)
                    if not chunk:
                        break
                    out.write(chunk)
                    with lock:
                        progress[idx] += len(chunk)
                        _state["percent"] = min(92, int(sum(progress) / total * 88))
                        _state["message"] = f"{sum(progress) // (1024 * 1024)}MB / {total // (1024 * 1024)}MB"
                        _state["speed"] = rate()
        except Exception as e:
            errors.append(f"{type(e).__name__}: {e}")

    start_ts[0] = time.time()
    threads = [threading.Thread(target=worker, args=(i, s, e), daemon=True)
               for i, (s, e) in enumerate(ranges)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    if errors or sum(progress) < total * 0.98:
        if errors:
            _state["error"] = "; ".join(errors[:2])
        return False
    return True


def _download_serial(url: str, dest: str) -> bool:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as out:
            total = int(resp.headers.get("Content-Length") or 0)
            written = 0
            while True:
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                out.write(chunk)
                written += len(chunk)
                if total:
                    _state["percent"] = min(92, int(written / total * 88))
                    _state["message"] = f"{written // (1024 * 1024)}MB / {total // (1024 * 1024)}MB"
        return True
    except Exception as e:
        _state["error"] = f"{type(e).__name__}: {e}"
        return False


def _extract(zip_path: str) -> str | None:
    os.makedirs(BIN_DIR, exist_ok=True)
    with zipfile.ZipFile(zip_path) as zf:
        candidates = [n for n in zf.namelist()
                      if n.replace("\\", "/").endswith("/bin/ffmpeg.exe")]
        if not candidates:
            return None
        candidates.sort(key=lambda n: zf.getinfo(n).file_size, reverse=True)
        with zf.open(candidates[0]) as src, open(os.path.join(BIN_DIR, "ffmpeg.exe"), "wb") as dst:
            while True:
                chunk = src.read(1024 * 512)
                if not chunk:
                    break
                dst.write(chunk)
    return os.path.join(BIN_DIR, "ffmpeg.exe")


def _try_source(name: str, url: str) -> tuple[bool, str]:
    tmp = os.path.join(BIN_DIR, "_download.tmp.zip")
    os.makedirs(BIN_DIR, exist_ok=True)
    if os.path.exists(tmp):
        try:
            os.remove(tmp)
        except OSError:
            pass

    _state["stage"] = "连接…"
    _state["message"] = name
    if not _download_parallel(url, tmp):
        if not _download_serial(url, tmp):
            return False, _state.get("error") or "下载失败"

    if os.path.getsize(tmp) < 1024 * 1024:
        return False, "下载 结果太小，可能不是真正的压缩包"

    _state["stage"] = "解压中"
    _state["percent"] = 95
    extracted = _extract(tmp)
    try:
        os.remove(tmp)
    except OSError:
        pass
    if not extracted:
        return False, "压缩包里没有 bin/ffmpeg.exe"
    _state["percent"] = 100
    return True, extracted


def _worker():
    for name, url in SOURCES:
        _state["source"] = name
        ok, detail = _try_source(name, url)
        if ok:
            _state.update({"ok": True, "running": False, "done": True,
                           "stage": "完成", "message": detail})
            return
        _state["error"] = f"{name} → {detail}"
        _state["speed"] = ""
    _state.update({
        "ok": False, "running": False, "done": True, "stage": "失败",
        "message": "自动下载失败，请手动下载 ffmpeg.exe 放到项目 bin/ 目录",
    })


def start_fetch() -> dict:
    global _thread
    if _state["running"]:
        return fetch_state()
    _reset()
    _thread = threading.Thread(target=_worker, daemon=True)
    _thread.start()
    return fetch_state()
