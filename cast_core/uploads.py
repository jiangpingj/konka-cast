# -*- coding: utf-8 -*-
"""临时文件上传目录管理与 API 挂载逻辑。
把拖拽进来的文件落到临时目录，然后走与普通本地文件完全一样的推送流程。
"""
from __future__ import annotations

import os
import re
import tempfile
import time

UPLOAD_DIR = os.path.join(tempfile.gettempdir(), "konkacast-uploads")


def ensure_dir() -> str:
    os.makedirs(UPLOAD_DIR, exist_ok=True)
    return UPLOAD_DIR


def safe_name(name: str) -> str:
    name = os.path.basename((name or "").replace("/", "\\"))
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name)
    return name or f"upload-{int(time.time())}"


def save(data: bytes, raw_name: str) -> str:
    """写入临时目录，返回绝对路径。"""
    d = ensure_dir()
    target = os.path.join(d, safe_name(raw_name))
    base, ext = os.path.splitext(target)
    i = 1
    while os.path.exists(target):
        target = f"{base}({i}){ext}"
        i += 1
    with open(target, "wb") as fh:
        fh.write(data)
    return target
