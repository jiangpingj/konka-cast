# -*- coding: utf-8 -*-
"""KonkaCast - 局域网内把电脑内容投到智能电视（DLNA / UPnP）。

纯 Python 标准库实现，无第三方依赖。
  ssdp          设备发现
  upnp          SOAP 控制点
  media_server  本地媒体 HTTP 服务（支持 Range / DLNA 头）
  mirror        ffmpeg 屏幕镜像
  controller    状态机
  console       REST API + 网页控制台
"""

__version__ = "1.0.0"

from .controller import Controller  # noqa: F401
from .console import ConsoleServer  # noqa: F401
