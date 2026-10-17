# KonkaCast · 通用 DLNA 电视投屏控制台 / Universal DLNA TV Casting Console

> 把 Windows 电脑上的画面、视频、音乐、照片投到局域网里的智能电视。
> Cast your Windows screen, video, music and photos to any smart TV on the same LAN.

基于标准 **DLNA / UPnP** 协议，**电视端不需要安装任何 App**，纯 Python 标准库实现，**零第三方依赖**。ffmpeg 已随源码打包（含 UCRT 运行时），**开箱即用，无需联网下载**。
Built on the standard **DLNA / UPnP** protocol. **No app needed on the TV.** Pure Python standard-library implementation with **zero third-party dependencies**. ffmpeg (with UCRT runtime) is bundled, so it works **out of the box, no download required**.

> 这是一套**通用 DLNA/UPnP 投屏内核**，适配所有支持 DLNA 接收端的智能设备（索尼/三星/LG/小米/海信/TCL/创维/华为/康佳等），并非康佳电视专用。
> This is a **generic DLNA/UPnP casting core** that works with any DLNA-capable device (Sony / Samsung / LG / Xiaomi / Hisense / TCL / Skyworth / Huawei / Konka …). It is **not** Konka-specific.

---

## 目录 / Table of Contents

- [中文文档](#中文文档)
  - [特性](#特性)
  - [部署（快速开始）](#部署快速开始)
  - [使用说明](#使用说明)
  - [常见问题](#常见问题)
  - [开源许可](#开源许可)
- [English](#english)
  - [Features](#features)
  - [Deployment (Quick Start)](#deployment-quick-start)
  - [Usage](#usage)
  - [FAQ](#faq)
  - [License](#license)

---

# 中文文档

## 特性

- **通用投屏**：基于 DLNA/UPnP 标准，几乎所有智能电视/盒子/投屏 App 都能用，不挑品牌。
- **三种方式**：推送文件（原画质）、屏幕镜像（实时直播流）、推送网址。
- **零依赖**：纯 Python 标准库，无需 `pip install`；ffmpeg 已自包含。
- **中文控制台**：本地网页控制台，扫描 → 选择电视 → 一键投屏。
- **自动选源**：同一台电视上多个接收端时，按可靠性自动锁定最优的那个。

## 部署（快速开始）

### 环境要求

- **操作系统**：Windows 7 / 10 / 11（64 位）。屏幕镜像依赖 ffmpeg + Windows `gdigrab` 抓屏。
- **Python**：3.8+（推荐 3.10+）。**无需安装任何第三方包**，标准库即可运行。
- **电视**：支持 DLNA 接收端的智能电视 / 盒子 / 投屏 App（乐播投屏、AirScreen 等）。原生仅支持 AirPlay 的设备（如未装 DLNA 接收 App 的 Apple TV）需另装接收端。

### 获取源码

```bash
git clone <你的仓库地址> konka-cast
cd konka-cast
```

或直接下载仓库 ZIP 解压即可。

### 启动（两种方式）

**方式 A —— 双击启动（推荐）**
双击 `启动投屏.bat`，脚本会自动探测本机 Python（优先 `py -3`，回退系统 `python`）。

**方式 B —— 命令行**
```bash
python run.py            # 安全启动：崩溃自动落盘，窗口不闪退
# 或 / or
python main.py           # 普通启动，控制台 8770、媒体服务 8899
python main.py --port 9000        # 换控制台端口
python main.py --no-browser      # 不自动开浏览器（当服务跑）
```

启动后浏览器会自动打开 `http://127.0.0.1:8770`。

### 防火墙

首次运行 Windows 防火墙会弹窗，**务必点「允许访问」**，否则电视收不到流。

## 使用说明

### 第一步：扫描并选择电视

1. 控制台点 **扫描**；
2. 列表里选中你的电视（同名多接收端时按可靠性自动选最优）；
3. 点 **开投**。

> 电视和电脑必须在**同一局域网**（同属 `192.168.x.x`）。

### 三种投屏方式

| 方式 | 适合 | 画质 | 延迟 | 电脑负载 | 电视可拖进度条 |
|----|----|----|----|----|----|
| **推送文件** | 本地电影/剧集/相册 | 无损原画质 | 无 | 几乎为零 | 能 |
| **屏幕镜像** | 开会演示、网页视频、游戏 | 由码率决定 | 1~4 秒 | 需要编码 | 不能 |
| **推送网址** | 视频/图片直链 | 无损 | 无 | 几乎为零 | 看情况 |

- **推送文件**：在「推送文件」卡片浏览本地目录，点文件名即投，也支持拖拽。电视自己解码，**画质原盘级**，进度条/倍速由电视控制。
- **屏幕镜像**：ffmpeg 抓屏 → H.264/AAC → MPEG-TS 直播流推给电视。有 N 卡自动走 NVENC 硬编，否则 CPU 软编。参数建议：30fps 日常、8Mbps 通用；WiFi 弱降到 4Mbps。
- **推送网址**：填 `.mp4` / `.m3u8` / `.jpg` 直链。爱奇艺/腾讯等加密地址电视解不开，请用屏幕镜像。

### 播放控制

暂停 / 播放 / 停止 / 进度由控制台「播放控制」卡片操作，部分能力受电视固件限制。

### 自动选源

一台电视可能同时跑多个 DLNA 服务（如乐播 HappyCast + 腾讯极光）。程序用**完整描述地址**（非 IP）做唯一标识，按可靠性打分自动选最优，避免「刷新一下就换接收端」。

### 兼容性

| 设备类型 | 能否用 | 说明 |
|----|----|----|
| 国产安卓智能电视 | ✅ | 大多内置乐播/当贝 DLNA，镜像首选 |
| 索尼/三星/LG | ✅ | 原生 DLNA 稳，老款镜像或仅支持推文件 |
| 电视盒子 | ✅ | 安卓盒子 DLNA 支持好 |
| 投屏接收 App | ✅ | 装哪台设备上哪台当接收端 |
| 非智能电视 | ❌ | 无网络接收端，接不动 |
| Apple TV（原生 AirPlay） | ❌ | 协议不同；装 DLNA 接收 App（如 AirScreen）即可 |

## 常见问题

**Q：镜像有 1~4 秒延迟？** DLNA 推的是直播流，缓冲+编码+网络叠加即此量级。要低延迟需 Miracast，兼容性差。日常看视频无感，打游戏会难受。

**Q：镜像没声音？** Windows 默认不提供录制系统内部声音的设备。去 `声音设置 → 声音控制面板 → 录制` 启用「立体声混音」，或装 VB-CABLE 虚拟声卡，重启控制台后即可选。

**Q：推送时电视提示不支持的格式？** 电视自身解码能力有限（部分老款不支持 HEVC/某些音轨），改用屏幕镜像由电脑转码。

**Q：数据会传到外网吗？** 不会。所有流量留局域网内，无外网请求。

## 开源许可

- 主许可证 **MIT**（见 `LICENSE`），可自由使用、修改、再分发。
- 随源码分发的 **ffmpeg**（GPL 构建）与 **UCRT/MSVC 运行时** 为第三方组件，各自遵循原许可，详见 `THIRD_PARTY.md`。
- 源码完全自包含：clone 或解压后双击 `启动投屏.bat` 即用，**无需联网、无需装依赖**。

### 自包含目录结构

```
konka-cast/
├─ 启动投屏.bat / 环境自检.bat / 安装ffmpeg.bat
├─ main.py / run.py            入口（run.py 崩溃自动落盘）
├─ cast_core/                  纯标准库 DLNA/UPnP 内核
├─ web/                       控制台前端（原生 HTML/CSS/JS）
├─ tools/                     自检与诊断脚本
├─ bin/                       ffmpeg 7.1.1 + UCRT 运行时（已附带，自包含）
├─ LICENSE / THIRD_PARTY.md   开源许可与第三方声明
└─ README.md
```

---

# English

## Features

- **Generic casting**: standard DLNA/UPnP — works with almost any smart TV / box / casting app, brand-agnostic.
- **Three modes**: push local files (original quality), live screen mirror, or cast a URL.
- **Zero dependencies**: pure Python standard library, no `pip install`; ffmpeg is bundled.
- **Chinese web console**: scan → pick your TV → cast, all from a local web UI.
- **Auto source selection**: when a TV exposes multiple renderers, the most reliable one is picked automatically.

## Deployment (Quick Start)

### Requirements

- **OS**: Windows 7 / 10 / 11 (64-bit). Screen mirroring relies on ffmpeg + Windows `gdigrab`.
- **Python**: 3.8+ (3.10+ recommended). **No third-party packages required** — standard library only.
- **TV**: any DLNA-capable smart TV / box / casting app (HappyCast, AirScreen, …). Devices that only speak AirPlay (e.g. Apple TV without a DLNA receiver app) need an extra receiver app.

### Get the source

```bash
git clone <your-repo-url> konka-cast
cd konka-cast
```

Or just download and unzip the repository.

### Launch (two ways)

**Way A — double-click (recommended)**
Double-click `启动投屏.bat`. It auto-detects Python (`py -3` first, then system `python`).

**Way B — command line**
```bash
python run.py            # safe launch: crashes are dumped to disk, no flicker
# or
python main.py           # normal launch, console :8770, media :8899
python main.py --port 9000        # change console port
python main.py --no-browser      # don't open browser (run as a service)
```

The browser opens `http://127.0.0.1:8770` automatically.

### Firewall

On first run Windows Firewall will prompt — **click "Allow access"**, otherwise the TV cannot receive the stream.

## Usage

### Step 1: scan and select your TV

1. Click **扫描 (Scan)** in the console;
2. Pick your TV from the list (if multiple renderers share a name, the best one is auto-selected);
3. Click **开投 (Cast)**.

> PC and TV must be on the **same LAN** (same `192.168.x.x` subnet).

### Three casting modes

| Mode | Best for | Quality | Latency | PC load | Seek on TV |
|----|----|----|----|----|----|
| **Push file** | local movies / albums | lossless | none | near zero | yes |
| **Screen mirror** | meetings, web video, games | bitrate-dependent | 1–4 s | needs encode | no |
| **Push URL** | direct video/image links | lossless | none | near zero | varies |

- **Push file**: browse local dirs in the "推送文件" card and click a file, or drag & drop. The TV decodes itself — **original quality**, with seek/speed controlled by the TV.
- **Screen mirror**: ffmpeg captures the screen → H.264/AAC → MPEG-TS live stream to the TV. NVENC hardware encoding is used automatically when an NVIDIA GPU is present, otherwise libx264. Suggestions: 30fps daily, 8Mbps default; drop to 4Mbps on weak WiFi.
- **Push URL**: paste a direct link ending in `.mp4` / `.m3u8` / `.jpg`. Encrypted links from iQiyi/Tencent won't play on the TV — use screen mirror instead.

### Playback control

Pause / play / stop / seek via the "播放控制" card. Some capabilities depend on the TV firmware.

### Auto source selection

A TV may run several DLNA services at once (e.g. HappyCast + Tencent Aurora). The program identifies each by its **full description URL** (not IP) and auto-picks the highest-reliability renderer, so it won't flip between receivers on refresh.

### Compatibility

| Device | Works | Notes |
|----|----|----|
| Chinese Android TVs | ✅ | usually ship HappyCast/当贝 DLNA; best for mirroring |
| Sony / Samsung / LG | ✅ | solid native DLNA; older models may mirror poorly or push files only |
| TV boxes | ✅ | Android boxes have good DLNA support |
| Casting receiver apps | ✅ | runs wherever you install it |
| Non-smart TVs | ❌ | no network renderer |
| Apple TV (native AirPlay) | ❌ | different protocol; install a DLNA receiver (e.g. AirScreen) |

## FAQ

**Q: Why 1–4 s latency on mirroring?** DLNA mirrors a live stream; buffering + encoding + network add up to that range. Low latency needs Miracast, which has poor compatibility. Fine for video, bad for gaming.

**Q: No audio in mirror?** Windows doesn't expose a "record system audio" device by default. Enable **Stereo Mix** in `Sound settings → Recording`, or install VB-CABLE, then restart the console to see it.

**Q: TV says unsupported format when pushing?** The TV's decoder is limited (some older models lack HEVC/certain audio). Use screen mirror so the PC transcodes.

**Q: Does data leave the LAN?** No. All traffic stays on the local network; there are no outbound requests.

## License

- Main license **MIT** (see `LICENSE`) — free to use, modify and redistribute.
- The bundled **ffmpeg** (GPL build) and **UCRT/MSVC runtime** are third-party components under their own licenses; see `THIRD_PARTY.md`.
- Fully self-contained: after clone/unzip, double-click `启动投屏.bat` — **no network, no dependency install**.

### Self-contained layout

```
konka-cast/
├─ 启动投屏.bat / 环境自检.bat / 安装ffmpeg.bat
├─ main.py / run.py            entry points (run.py dumps traceback on crash)
├─ cast_core/                  pure-stdlib DLNA/UPnP core
├─ web/                       console front-end (vanilla HTML/CSS/JS)
├─ tools/                     self-check & diagnostic scripts
├─ bin/                       ffmpeg 7.1.1 + UCRT runtime (bundled, self-contained)
├─ LICENSE / THIRD_PARTY.md   license & third-party notices
└─ README.md
```
