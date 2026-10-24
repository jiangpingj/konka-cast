# -*- coding: utf-8 -*-
"""批量把 HEVC/H.265 视频转成电视能硬解的 H.264。

用法:
    python tools/batch_transcode.py <视频根目录> [--log 日志路径]

特性:
- ffprobe 检测编码,已是 H.264 的直接跳过,不浪费时间
- NVENC 硬编优先(RTX 显卡),失败自动回退 CPU libx264
- 输出 <原名>_x264.mp4,与源文件同目录
- 断点续转:输出已存在且 >50MB 视为完成,重复跑安全
- 启动时若检测到 ffmpeg 还在跑(比如上一个转码任务),先等待其退出
"""
import json
import os
import subprocess
import sys
import time

# ffmpeg/ffprobe 位置:项目 bin/ 优先,再补充运行时目录
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(HERE, "bin")
EXTRA_RUNTIME_DIRS = [
    os.path.join(HERE, "bin"),
]

MIN_DONE_BYTES = 50 * 1024 * 1024  # 输出超过 50MB 视为转码完成
VIDEO_EXT = (".mp4", ".mkv", ".m2ts", ".ts", ".mov", ".avi")
MARK = "_x264"


def build_env():
    env = os.environ.copy()
    paths = [BIN]
    # 追加已知可用的运行时目录（分号分隔），本机需 ComfyUI 的 Library\bin
    extra = env.get("KONKA_CAST_RUNTIME_DIRS")
    if extra:
        paths += [p for p in extra.split(";") if p.strip()]
    # 兼容 conda/嵌入式发行版自带的 UCRT 运行时
    conda = env.get("CONDA_PREFIX")
    if conda and os.path.isdir(os.path.join(conda, "Library", "bin")):
        paths.append(os.path.join(conda, "Library", "bin"))
    env["PATH"] = os.pathsep.join(paths) + os.pathsep + env.get("PATH", "")
    return env


def log(msg, logfile):
    line = time.strftime("[%Y-%m-%d %H:%M:%S] ") + msg
    print(line, flush=True)
    if logfile:
        try:
            with open(logfile, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError:
            pass


def ffmpeg_path():
    return os.path.join(BIN, "ffmpeg.exe")


def ffprobe_path():
    return os.path.join(BIN, "ffprobe.exe")


def wait_existing_ffmpeg(env, logfile, poll=15):
    """若有别的 ffmpeg 在跑(比如手动转码中),等它退出再开工。"""
    while True:
        try:
            r = subprocess.run(
                ["tasklist", "/FI", "IMAGENAME eq ffmpeg.exe"],
                capture_output=True, text=True, timeout=30,
            )
            if "ffmpeg.exe" not in (r.stdout or ""):
                return
        except Exception:
            return
        log("检测到 ffmpeg 仍在运行(可能是别的转码任务),等待...", logfile)
        time.sleep(poll)


def probe_codec(src, env):
    try:
        r = subprocess.run(
            [ffprobe_path(), "-v", "error", "-select_streams", "v:0",
             "-show_entries", "stream=codec_name,width,height",
             "-of", "json", src],
            capture_output=True, text=True, env=env, timeout=120,
        )
        if r.returncode != 0:
            return None
        streams = json.loads(r.stdout or "{}").get("streams", [])
        return streams[0].get("codec_name", "") if streams else None
    except Exception:
        return None


def transcode(src, dst, env):
    # -pix_fmt yuv420p：10bit HEVC 片源必须先转 8bit，否则 h264_nvenc 初始化
    # 失败会静默回退到 CPU，慢一个数量级
    base = [ffmpeg_path(), "-y", "-i", src, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k",
            "-movflags", "+faststart"]
    nvenc = base + ["-c:v", "h264_nvenc", "-preset", "p1",
                    "-b:v", "5000k", "-maxrate", "6500k",
                    "-bufsize", "10000k", dst]
    cpu = base + ["-c:v", "libx264", "-preset", "veryfast",
                  "-crf", "21", dst]
    r = subprocess.run(nvenc, env=env)
    if r.returncode != 0:
        r = subprocess.run(cpu, env=env)
    return r.returncode == 0


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("用法: python tools/batch_transcode.py <视频根目录> [--log 日志路径]")
        sys.exit(1)
    root = os.path.abspath(args[0])
    logfile = os.path.join(HERE, "transcode_log.txt")
    argv = sys.argv[1:]
    if "--log" in argv:
        logfile = argv[argv.index("--log") + 1]

    env = build_env()
    log("=== 批量转码启动,根目录: %s ===" % root, logfile)
    wait_existing_ffmpeg(env, logfile)

    targets = []
    for dirpath, _dirs, files in os.walk(root):
        for fn in files:
            low = fn.lower()
            if not low.endswith(VIDEO_EXT) or MARK in fn:
                continue
            targets.append(os.path.join(dirpath, fn))
    log("共发现 %d 个待检视频" % len(targets), logfile)

    done = fail = skip = 0
    for i, src in enumerate(targets, 1):
        name = os.path.basename(src)
        base = os.path.splitext(name)[0]
        dst = os.path.join(os.path.dirname(src), base + MARK + ".mp4")
        if os.path.exists(dst) and os.path.getsize(dst) > MIN_DONE_BYTES:
            skip += 1
            log("[%d/%d] 跳过(已转过): %s" % (i, len(targets), name), logfile)
            continue
        codec = probe_codec(src, env)
        if not codec:
            fail += 1
            log("[%d/%d] 无法读取,跳过: %s" % (i, len(targets), name), logfile)
            continue
        if codec == "h264":
            skip += 1
            log("[%d/%d] 已是 H.264,无需转: %s" % (i, len(targets), name), logfile)
            continue
        gb = os.path.getsize(src) / 1e9
        log("[%d/%d] 转码 %s (%s, %.1fGB) ..." % (i, len(targets), name, codec, gb), logfile)
        t0 = time.time()
        ok = transcode(src, dst, env)
        dt = (time.time() - t0) / 60
        if ok:
            done += 1
            log("    完成,用时 %.1f 分钟 -> %s" % (dt, os.path.basename(dst)), logfile)
        else:
            fail += 1
            log("    失败(rc!=0),用时 %.1f 分钟" % dt, logfile)
            try:
                if os.path.exists(dst) and os.path.getsize(dst) < MIN_DONE_BYTES:
                    os.remove(dst)
            except OSError:
                pass

    log("=== 全部结束: 转码完成 %d, 跳过 %d, 失败 %d ===" % (done, skip, fail), logfile)


if __name__ == "__main__":
    main()
