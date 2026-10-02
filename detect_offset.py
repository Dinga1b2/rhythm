# -*- coding: utf-8 -*-
"""
detect_offset.py —— 检测音频开头静音时长，得到谱面 #SILENCE 值

为什么需要：音游音频文件开头常有一段静音（本曲 qinglian 约 840ms）。
谱面的 0ms 应指向"真正出声"的时刻，否则首个音符会落在静音段里，
与音乐错位。用本脚本测出静音时长，填入谱面头 #SILENCE:<毫秒>。
（v2.9 起：静音记在 #SILENCE；#OFFSET = 静音 + 音乐后移量，保证音符从顶端下落。）

用法（在 rhythm/ 目录下）：
  python detect_offset.py music/qinglian/qinglian_lavaguelette.mp3

依赖：imageio-ffmpeg（自带静态 ffmpeg，无需系统安装 ffmpeg）
  安装：pip install imageio-ffmpeg
"""
import re
import subprocess
import sys

import imageio_ffmpeg


def detect_leading_silence(audio_path, noise_db="-40", min_dur=0.05):
    """用 ffmpeg silencedetect 找开头静音时长，返回秒数（float）或 None。"""
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    cmd = [
        ff, "-i", audio_path,
        "-af", "silencedetect=noise={0}dB:d={1}".format(noise_db, min_dur),
        "-f", "null", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    # 找第一条 silence_start: 0 对应的 silence_end
    started_at_zero = None
    for line in proc.stderr.splitlines():
        m_start = re.search(r"silence_start:\s*([0-9.]+)", line)
        m_end = re.search(r"silence_end:\s*([0-9.]+)", line)
        if m_start and float(m_start.group(1)) == 0.0:
            started_at_zero = True
        if started_at_zero and m_end:
            return float(m_end.group(1))
    return None


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python detect_offset.py <音频文件.mp3> [噪声dB默认-40]")
        sys.exit(1)
    path = sys.argv[1]
    noise = sys.argv[2] if len(sys.argv) > 2 else "-40"
    sec = detect_leading_silence(path, noise_db=noise)
    if sec is None:
        print("未检测到开头静音（音频可能直接从出声开始），#SILENCE 填 0 即可")
    else:
        ms = round(sec * 1000)
        print("开头静音时长: {:.3f}s → #SILENCE: {} (约 {} ms)".format(sec, ms, ms))
        print("把谱面头改成:  #SILENCE:{}".format(ms))
        print("（#OFFSET 仍填 静音 + 音乐后移量，例如 3000，保证音符从顶端下落）")
        print("然后执行:  node gen_songs.js")
