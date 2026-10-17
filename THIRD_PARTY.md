# 第三方组件与许可（Third-party notices）

本项目主许可证为 **GPL-3.0**（见 `LICENSE`）。以下组件以独立方式随源码分发，
各自遵循其原有许可证。本项目以**独立子进程**方式调用 ffmpeg，并未静态或
动态链接 FFmpeg 库，因此属于独立聚合分发（mere aggregation）。

---

## FFmpeg（位于 `bin/ffmpeg.exe` 及配套 `*.dll`）

- **版本**：7.1.1（GPL build）
- **许可**：GNU GPL v2.0+ / GNU LGPL v2.1+（本仓库分发的是 **GPL** 构建）
- **版权**：© 2000–2024 the FFmpeg developers
- **源码**：
  - 官方仓库：https://git.ffmpeg.org/ffmpeg.git
  - GitHub 镜像（tag `n7.1.1`）：https://github.com/FFmpeg/FFmpeg
- **说明**：FFmpeg 以独立可执行文件形式存放于 `bin/`，由本程序在运行时
  调用。你可自行替换为任意兼容构建（含 static / shared、GPL / LGPL 版本），
  只需保证 `bin/ffmpeg.exe` 存在即可。

如你仅以个人用途运行本程序，FFmpeg 的 GPL 条款对你基本无额外义务；若你
将本程序再分发，**须同时提供你所分发的 FFmpeg 构建对应的源码**（上述链接
即可满足）。

---

## UCRT / MSVC 运行时（位于 `bin/` 内的运行库）

`bin/` 内附带的以下文件用于在**缺失 Universal CRT 转发的 Windows** 上让
ffmpeg 正常加载；正常 Windows 10/11 系统自带这些组件，不会冲突：

- `api-ms-win-crt-*.dll`
- `ucrtbase.dll`
- `vcruntime140.dll` / `vcruntime140_1.dll` / `vcruntime140_threads.dll`
- `msvcp140*.dll`
- `concrt140.dll`

- **来源**：Microsoft Visual C++ 可再发行运行时 / conda-forge 构建
- **许可**：Microsoft Visual Studio / VC++ Runtime 许可；conda-forge 包为
  BSD-3-Clause。均允许随应用程序再分发。

---

如需移除任意第三方组件，请参考各自许可证中的再分发条款。
