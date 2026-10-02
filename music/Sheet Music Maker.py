# -*- coding: utf-8 -*-
"""
Sheet Music Maker.py —— 适配 rhythm 音游的曲谱制造器（v3.5）

输入：任意 .mp3/.wav 音频
输出：与 rhythm/chart.js parseChart 兼容的谱面文本
  头：#TITLE / #BPM:110 / #KEY:6K / #OFFSET / #SILENCE
  体：每行 `time   tr1..tr6`，标记 D=短按 / B=长按头 / E=长按尾 / # 或 .=空

用法：
  python "Sheet Music Maker.py" --missing               # ★ 只给"有音频但还没谱面"的新曲目生成
  python "Sheet Music Maker.py" <音频>                  # 输出 = 同目录已有的唯一 .txt
  python "Sheet Music Maker.py" <音频> <输出.txt>        # 旧写法仍兼容（末尾 .txt 视为输出）
  python "Sheet Music Maker.py" <音频> -o <输出.txt>     # 显式指定
  python "Sheet Music Maker.py" <音频1> <音频2> <音频3>   # 批处理：同一进程依次处理
  python "Sheet Music Maker.py" --all                   # 重生成 music/ 下每一首（会覆盖已有谱面）
  python "Sheet Music Maker.py"                         # 不给参数 = 曲库里排序第一的那首

  ★ 新增一首歌请直接用 rhythm/build.cmd（一键：补谱面 + 重打包曲库与皮肤）。
    --missing 就是它的第 1 步：只挑"有音频、但没有 .txt 谱面"的目录；
    并且在没有待生成曲目时**立刻退出**（连 librosa 都不导入，约 0.3s），
    所以放在一键流程里几乎没有额外开销。
  ★ 目录定位一律基于**本文件所在位置**（__file__），与当前工作目录无关，
    全文不含任何硬编码盘符或用户路径 —— rhythm/ 整体拷到任何位置都能跑。
  ★ 批处理是唯一能摊掉冷启动的手段：每开一个进程都要重付约 4.5s 的
    scipy/librosa 冷启动（`librosa.stft` 首调用，与音频长度无关，
    与 numba JIT 无关）——同进程内第二次调用只需 0.06s。
  ★ 输出路径缺省 = **复用同目录已有的唯一 .txt（原地更新）**，
    没有或不止一个才用 <音频同名>.txt —— 避免"音频名 ≠ 谱面名时
    误写一个新文件、而旧谱面原地不动"。

生成流程（7 步，与运行时打印的 [n/7] 一一对应）：
  [1] 加载音频（pygame → librosa 兜底）
  [2] 前导静音 SILENCE：ffmpeg silencedetect（noise=-40dB:d=0.05），失败退回 RMS 阈值
  [3] onset 检测 + 显著性：onset_strength 取每个候选的强度（不再跑 pyin / CQT）
  [4] 能量包络 → 按 SEGMENT_MS 分段，每段算 intensity(0~1) → 目标 notes/s
  [5] 帧级能量衰减估计每个音符的持续时长（据此区分短音/长音候选）
  [6] 三档显著性筛选（明显/较明显/不明显）→ 轨道分配 → 短长按均衡 → 逐轨定 E 时刻；
      最多 MAX_ROUNDS 轮缩放密度，取"短长按最均衡"的一轮
  [7] 写出谱面文本 + 终检（validate_no_overlap）

硬约束（均由用户逐条裁定，改动前请先确认）：
  - 疏密：高潮密、非高潮疏；幂次曲线 DENSITY_GAMMA>1 拉开对比
  - 显著性：明显的音符必须体现；较明显的不与明显音符冲突就加入；
            不明显的只在段内密度 < 目标 × EMPTY_SEG_RATIO 时才补
  - 选轨优先级 FJ > DK > SL（TRACK_PRIORITY_GROUPS），组内左右交替保双手均衡
  - 任何形式的音符重叠都不允许（含显示层间距 ≥ DISPLAY_SAFE_GAP_MS）
  - 短按 : 长按 数量比 ≤ TAP_HOLD_RATIO_MAX
  - 间距下限只管同轨：同轨 ≥ MIN_TRACK_GAP_MS；明显档跨轨只保留
    MIN_CROSS_TRACK_GAP_MS（原 120ms 跨轨限制已按用户裁定放宽，见 v3.5）
  - 事件元组统一为 (trk, t, etype) —— 轨道在前，写统计/排序时别搞反

节奏游戏的约定（与 rhythm/chart.js 对齐）：
  - 谱面 #OFFSET = #SILENCE + 2160（音乐后移），保证所有音符均速从顶端下落
  - #SILENCE 与 rhythm/detect_offset.py 口径完全一致，
    输出可直接用于 rhythm/music/<id>/<id>.txt
  - 轨道 0..5 对应键盘 S D F J K L
"""

import os
import re          # 修复：原版漏了这行，导致 ffmpeg silencedetect 分支永远走不到
import struct
import subprocess
import sys
import wave
import math
import time
import argparse
import bisect

sys.stdout.reconfigure(encoding='utf-8')
sys.stderr.reconfigure(encoding='utf-8')

# ==================== 曲库定位与扫描 ====================
# 为什么这段必须放在第三方依赖**之前**：build.cmd 每次都先跑一次 --missing，
# 而"没有待生成曲目"是常态（绝大多数时候曲库是齐的）。放在 ensure_package /
# import librosa 之前，那条分支才能在 ~0.3s 内退出，不必为了问一句"有没有新歌"
# 白等 2~3s 的 librosa 导入。
#
# 定位一律用 __file__：双击运行和从任意终端运行，当前工作目录都不一样，
# 只靠相对路径会在"从 game/ 启动"时全部失效；写死盘符更是换机器就废。
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))   # …/rhythm/music
MUSIC_DIR = SCRIPT_DIR                                    # 曲库根 = 本脚本所在目录

# 能拿去生成谱面的音频。注意 gen_songs.js 打包时**只认 .mp3**（口径更窄），
# 所以 --missing 会对"只有非 mp3 音频"的目录单独警告，避免"谱面生成了、
# 页面里却看不到这首歌"的静默失败。
AUDIO_EXTS = ('.mp3', '.wav', '.flac', '.m4a', '.ogg')


def _scan_song_dirs():
    """列出 music/ 下每个曲目目录 → [(目录名, 绝对路径, [音频…], [谱面…])]，按目录名排序。

    约定：一个子目录 = 一首歌；忽略隐藏目录；`.bak*` 不算谱面。
    """
    out = []
    if not os.path.isdir(MUSIC_DIR):
        return out
    for name in sorted(os.listdir(MUSIC_DIR)):
        sub = os.path.join(MUSIC_DIR, name)
        if name.startswith('.') or not os.path.isdir(sub):
            continue
        files = sorted(os.listdir(sub))
        audios = [f for f in files if f.lower().endswith(AUDIO_EXTS)]
        charts = [f for f in files
                  if f.lower().endswith('.txt') and '.bak' not in f.lower()]
        out.append((name, sub, audios, charts))
    return out


def discover_all_audio():
    """--all 用：每个曲目目录里的第一个音频。"""
    return [os.path.join(sub, a[0]) for _, sub, a, _ in _scan_song_dirs() if a]


def discover_missing_charts():
    """--missing 用：有音频、但还没有 .txt 谱面的曲目（新增曲目的典型状态）。"""
    return [os.path.join(sub, a[0]) for _, sub, a, c in _scan_song_dirs() if a and not c]


def default_audio():
    """不给参数时的默认曲目 = 曲库里排序第一的那首（没有则返回空串）。

    原实现写死一条绝对路径（…/music/qinglian/qinglian_lavaguelette.mp3），
    换机器、换盘符、甚至只是把项目挪个位置就失效。更隐蔽的是：--all 的扫描根
    当年也是从它 os.path.dirname 推导的 —— 那只剥到 music/qinglian/，
    于是 --all 永远扫出 0 首。改成基于 __file__ 定位后，两个问题一起消失。
    """
    all_audio = discover_all_audio()
    return all_audio[0] if all_audio else ''


# ---- --missing 早退（必须在第三方依赖之前）----
# 无待生成曲目 → 立刻退出；有待生成 → 把 argv 改写成显式音频列表，
# 于是 main() 里一行 --missing 分支都不需要，走的仍是既有的批处理路径。
if '--missing' in sys.argv[1:]:
    _extra = [a for a in sys.argv[1:] if a != '--missing']
    if _extra:
        print("[错误] --missing 的含义是“只挑出还没有谱面的曲目”，不能再搭配其它参数："
              + ' '.join(_extra))
        raise SystemExit(2)

    _pairs = [(sub, aud, ch) for _, sub, aud, ch in _scan_song_dirs()]
    _missing = discover_missing_charts()
    if not _missing:
        print("[--missing] 曲库里所有曲目都已有 .txt 谱面，无需生成。")
        raise SystemExit(0)

    # 谱面生成器支持 5 种音频格式，但打包器只认 .mp3 —— 口径不一致要主动报出来
    _non_mp3 = [os.path.join(sub, aud[0]) for sub, aud, ch in _pairs
                if aud and not ch and not any(x.lower().endswith('.mp3') for x in aud)]
    if _non_mp3:
        print("[警告] 以下曲目只有非 .mp3 音频：谱面能生成，但 gen_songs.js 打包时"
              "只认 .mp3，")
        print("       结果是在选曲页里看不到这首歌。请补一个 .mp3（或把音频转成 .mp3）。")
        for _a in _non_mp3:
            print(f"    {os.path.relpath(_a, MUSIC_DIR)}")
        print()

    print(f"[--missing] 找到 {len(_missing)} 首还没有谱面的曲目：")
    for _a in _missing:
        print(f"    {os.path.relpath(_a, MUSIC_DIR)}")
    print()
    sys.argv = [sys.argv[0]] + _missing

# ==================== 自动安装依赖 ====================
def ensure_package(module_name, pip_name=None):
    """module_name: python import 的模块名; pip_name: pip 安装包名，缺省同 module_name"""
    if pip_name is None:
        pip_name = module_name
    try:
        __import__(module_name)
    except ImportError:
        print(f"正在安装 {pip_name}...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", pip_name, "-q"])

ensure_package("numpy")
ensure_package("pygame")
ensure_package("librosa")
# 重点：模块名叫 imageio_ffmpeg，pip 包名叫 imageio-ffmpeg
ensure_package("imageio_ffmpeg", pip_name="imageio-ffmpeg")

import warnings
warnings.filterwarnings('ignore')

os.environ['SDL_AUDIODRIVER'] = 'dummy'
import numpy as np
import pygame
import librosa
from collections import Counter

# ==================== 配置 ====================
# 默认曲目不再写死路径：由上方 "曲库定位与扫描" 区的 default_audio() 决定
# （= 本脚本所在曲库里排序第一的那首）。此处原本是一条绝对路径常量。

# ---- 密度分段（高潮密 / 非高潮疏 的核心参数）----
SEGMENT_MS = 2000             # 密度分段长度：每 2 秒一段，各自有独立的目标密度
NPS_QUIET = 0.6               # 最安静段的目标密度（notes per second）
NPS_LOUD  = 3.4               # 最高潮段的目标密度（notes per second）
DENSITY_GAMMA = 1.8           # 强度→密度的幂次曲线（>1 压低中低强度段，拉开疏密对比）
SMOOTH_SEGS = 3               # 段强度滑动平均窗口（段数），避免相邻段密度跳变

# ---- 轨道分配 ----
# 键位优先级（用户约束）：FJ > DK > SL（轨道 0..5 = S D F J K L）
# 中排食指键最好按 → 优先落音符；组内左右交替（F↔J、D↔K、S↔L）保持双手平衡。
TRACK_PRIORITY_GROUPS = [(2, 3), (1, 4), (0, 5)]   # (F,J) > (D,K) > (S,L)

# 显示层安全间距推导（player.html 实际几何）：
#   音符圆直径 = 轨宽 × 0.80（TAP_RATIO = HOLD_RATIO = 0.80，短按圆与长按头/尾圆同大小）；
#   下落像素速度 pxPerMs = (判定线高 + 80) / approach，最快档 approach = 3000ms。
#   同轨两音符不重叠要求 Δt ≥ 0.8×轨宽×approach/(判定线+80)。
#   常见桌面几何（轨宽 124px、下落区 ≥ 640px）最快档 ≈ 450ms；
#   默认档(2100ms)/慢速档(1350ms)在任意窗口下均 < 450ms，全覆盖。
DISPLAY_SAFE_GAP_MS = 450
MIN_TRACK_GAP_MS = DISPLAY_SAFE_GAP_MS  # 同一列两个音符头的最小间隔（显示不重叠 + 手速下限）

# ---- 长音 ----
SHORT_NOTE_THRESHOLD_MS = 100 # 能量持续时间 >= 此值 → 长音候选
MIN_HOLD_MS = DISPLAY_SAFE_GAP_MS  # 长按最短时长：头/尾圆同直径 0.8×轨宽，短于此二者显示重叠
ENERGY_DECAY_RATIO = 0.10     # 能量衰减比率（越低长音越长）
MAX_HOLD_SEARCH_SEC = 4.0     # 单个音符向后搜索能量衰减点的最长时间

# ---- 短按/长按数量目标（软目标：最多重试 MAX_ROUNDS 轮，取最均衡的一轮）----
TARGET_SHORT_COUNT = 100
TARGET_LONG_COUNT = 100
MAX_ROUNDS = 3
SCALE_STEP = 1.2              # 每轮未达标时的密度缩放步长
SCALE_MAX = 2.2               # 缩放上限，防止把"疏密对比"抹平
TAP_HOLD_RATIO_MAX = 1.5      # 短按/长按数量比上限：多的一方按持续时长就近换边

# ---- 音符显著性（三档筛选，v3.3 用户约束）----
# 规则：明显的音符必须体现；较明显的不与明显音符冲突就加入；
#       不明显的只在谱面十分空旷（段内密度 < 目标 × EMPTY_SEG_RATIO）时才补。
# 判定 = "段内局部峰值" 与 "全局分位" 结合：
#   段内比值高 = 这一刻相对突出（安静段的主旋律也能被认出来），
#   全局分位高 = 全曲意义上的强音；两者互补，避免把安静段的噪声当强音。
SALIENCE_HI_PCT = 67          # 全局强度分位：≥ 此值 → 明显档
SALIENCE_LO_PCT = 33          # 全局强度分位：≥ 此值 → 至少是较明显档
LOCAL_PEAK_HI = 0.75          # 段内强度 / 段内峰值 ≥ 此值且 ≥ 全局 lo → 明显档
LOCAL_PEAK_MID = 0.50         # 段内强度 / 段内峰值 ≥ 此值且 ≥ 全局 lo → 较明显档
MIN_CROSS_TRACK_GAP_MS = 60   # 明显档的跨轨最小间隔（≈110BPM 三十二分音符 68ms）
                              # 用户裁定：120ms 那类下限只应约束同轨 —— 换轨可承载更快连打。
                              # 同轨间距由 assign_tracks 的 MIN_TRACK_GAP_MS(450ms) 兜住。
EMPTY_SEG_RATIO = 0.5         # 段内已选密度 < 目标 × 此值 → 视为"十分空旷"，允许补入不明显档
# =============================================


def load_audio_with_pygame(path):
    """pygame 走 SDL_mixer 解码 mp3，比 librosa.load(走 audioread/ffmpeg) 快一个量级。"""
    pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=4096)
    try:
        sound = pygame.mixer.Sound(path)
        raw_array = pygame.sndarray.array(sound)
        if len(raw_array.shape) == 2:
            y = raw_array.mean(axis=1).astype(np.float32)
        else:
            y = raw_array.astype(np.float32)
        y = y / 32768.0
        sr = 44100
        print(f"      [pygame] 加载成功，采样率 {sr} Hz，长度 {len(y)/sr:.2f}秒")
        return y, sr
    except Exception as e:
        print(f"      [pygame] 失败: {e}")
        return None, None
    finally:
        pygame.mixer.quit()


def load_audio_robust(path):
    path = os.path.abspath(path)
    print("      尝试使用 pygame 加载...")
    y, sr = load_audio_with_pygame(path)
    if y is not None:
        return y, sr

    if path.lower().endswith('.wav'):
        try:
            with wave.open(path, 'rb') as wf:
                sr = wf.getframerate()
                n_channels = wf.getnchannels()
                sampwidth = wf.getsampwidth()
                n_frames = wf.getnframes()
                raw = wf.readframes(n_frames)
            if sampwidth == 2:
                samples = struct.unpack(f"{n_frames * n_channels}h", raw)
                y = np.array(samples, dtype=np.float32) / 32768.0
                if n_channels == 2:
                    y = y.reshape(-1, 2).mean(axis=1)
            elif sampwidth == 1:
                samples = struct.unpack(f"{n_frames * n_channels}B", raw)
                y = (np.array(samples, dtype=np.float32) - 128.0) / 128.0
                if n_channels == 2:
                    y = y.reshape(-1, 2).mean(axis=1)
            print(f"      [wave] 加载成功，采样率 {sr} Hz")
            return y, sr
        except Exception as e:
            print(f"      [wave] 失败: {e}")

    try:
        from scipy.io import wavfile
        sr, data = wavfile.read(path)
        if data.ndim == 2:
            data = data.mean(axis=1)
        if data.dtype == np.int16:
            y = data.astype(np.float32) / 32768.0
        elif data.dtype == np.int32:
            y = data.astype(np.float32) / 2147483648.0
        elif data.dtype == np.uint8:
            y = (data.astype(np.float32) - 128.0) / 128.0
        else:
            y = data.astype(np.float32)
            if y.max() > 1.0 or y.min() < -1.0:
                y /= np.max(np.abs(y))
        print(f"      [scipy] 加载成功，采样率 {sr} Hz")
        return y, sr
    except Exception as e:
        print(f"      [scipy] 失败: {e}")

    # 最终兜底：librosa 自带解码（慢，但胜在依赖已装、格式支持广）
    try:
        y, sr = librosa.load(path, sr=None, mono=True)
        y = y.astype(np.float32)
        print(f"      [librosa] 加载成功，采样率 {sr} Hz")
        return y, sr
    except Exception as e:
        print(f"      [librosa] 失败: {e}")

    print("\n[ERROR] 无法加载音频文件！")
    sys.exit(1)


def detect_leading_silence_ffmpeg(audio_path, noise_db="-40", min_dur=0.05):
    """用 ffmpeg silencedetect 测开头静音时长，返回毫秒 (int) 或 None。

    与 rhythm/detect_offset.py 保持一致，保证 #SILENCE 可直接互用。
    """
    try:
        import imageio_ffmpeg
        ff = imageio_ffmpeg.get_ffmpeg_exe()
        cmd = [
            ff, "-i", audio_path,
            "-af", f"silencedetect=noise={noise_db}dB:d={min_dur}",
            "-f", "null", "-",
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              encoding="utf-8", errors="replace")
        started_at_zero = False
        for line in proc.stderr.splitlines():
            ms = re.search(r"silence_start:\s*([0-9.]+)", line)
            me = re.search(r"silence_end:\s*([0-9.]+)", line)
            if ms and float(ms.group(1)) == 0.0:
                started_at_zero = True
            if started_at_zero and me:
                return int(round(float(me.group(1)) * 1000))
        return None
    except Exception as e:
        print(f"      [ffmpeg] silencedetect 失败: {e}")
        return None


# ==================== 密度分段 / 时长估计 / 轨道分配 ====================

def compute_segment_intensity(rms, sr, hop, total_ms):
    """把歌切成 SEGMENT_MS 一段，返回每段一个 0~1 的 intensity（能量越高越接近 1）。

    用对数域能量 + 分位数归一化：能量差几个数量级，线性归一会让"高潮"被极端值压扁；
    P30/P90 锚点对歌曲动态范围的适应性也比 min/max 稳。
    """
    n_seg = max(1, int(math.ceil(total_ms / SEGMENT_MS)))
    frames_per_seg = max(1, int(round(SEGMENT_MS / 1000.0 * sr / hop)))
    seg_energy = np.zeros(n_seg)
    for i in range(n_seg):
        a, b = i * frames_per_seg, min((i + 1) * frames_per_seg, len(rms))
        if b > a:
            seg_energy[i] = float(np.mean(rms[a:b]))
    # 对数域 + 分位数归一化到 0..1
    le = np.log(seg_energy + 1e-9)
    lo, hi = np.percentile(le, 30), np.percentile(le, 90)
    if hi - lo < 1e-9:
        intensity = np.full(n_seg, 0.5)
    else:
        intensity = np.clip((le - lo) / (hi - lo), 0.0, 1.0)
    # 段间滑动平均（边缘复制填充），防止相邻段密度跳变
    if SMOOTH_SEGS > 1 and n_seg >= SMOOTH_SEGS:
        pad = np.pad(intensity, SMOOTH_SEGS // 2, mode='edge')
        intensity = np.convolve(pad, np.ones(SMOOTH_SEGS) / SMOOTH_SEGS, mode='valid')[:n_seg]
    return np.clip(intensity, 0.0, 1.0)


def segment_target_nps(intensity, scale_quiet, scale_loud):
    """每段的目标密度（notes/s）：intensity 0 → NPS_QUIET，1 → NPS_LOUD。

    幂次曲线（DENSITY_GAMMA>1）让中等音量的段落明显偏向"疏"，
    只有真正的高潮才配得上高密度 —— 线性插值时一半强度的段落就有 (Q+L)/2 的密度，
    实测会把非高潮段顶到 2 notes/s 以上，疏密对比不足。
    """
    i = np.power(np.clip(intensity, 0.0, 1.0), DENSITY_GAMMA)
    q = NPS_QUIET * scale_quiet
    l = NPS_LOUD * scale_loud
    return q + (l - q) * i


def estimate_durations_frames(onset_frames, rms, hop_sec, next_frame_hint):
    """帧级能量衰减法估计每个音符的持续时间（ms）。

    与旧版 estimate_duration_v2 等价，但从"每 128 采样点做一次 2048 点求和"
    改成"在与 onset 相同 hop 的帧能量序列上向后找第一个衰减点"，
    每步从 O(2048) 的求和降到 O(1) 的标量比较。
    next_frame_hint[i] = 该音符允许搜索到的最晚帧（通常是下一个 onset + 0.15s）。
    """
    n = len(rms)
    win_frames = max(1, int(round(0.05 / hop_sec)))                 # onset 后 ~50ms 作为起始能量参考
    max_search = int(MAX_HOLD_SEARCH_SEC / hop_sec)
    durations = np.zeros(len(onset_frames))
    for i, of in enumerate(onset_frames):
        a = min(of + 1, n - 1)
        b = min(of + 1 + win_frames, n)
        if b <= a:
            continue
        start_energy = float(np.max(rms[a:b]))
        threshold = start_energy * ENERGY_DECAY_RATIO
        end_f = min(n, of + max_search, next_frame_hint[i])
        found = end_f
        for f in range(a, end_f):
            if rms[f] < threshold:
                found = f
                break
        durations[i] = max(0.0, (found - of) * hop_sec * 1000.0)
    return durations


def assign_tracks(selected):
    """给每个入选音符分配轨道（0..5 = S D F J K L）。

    规则（按优先级）：
      1. 键位优先级 FJ > DK > SL（TRACK_PRIORITY_GROUPS）：优先落中排；
         组内左右交替（F↔J、D↔K、S↔L），双手均衡；
      2. 显示不重叠：同一列下一个音符头必须 ≥ 上一音符头(或长按尾) + MIN_TRACK_GAP_MS。
         长按按 [头, 尾] 全程占用轨道（reservation），从源头杜绝
         "音符落在长按身体里、finalize 再收缩降级"的旧路径；
      3. 所有轨道都忙才丢弃音符（dropped 计数，报告可见）。

    注：v3.4 删除了原来的「同一列连续音符 ≤ MAX_SAME_TRACK_RUN」限制 ——
    实测它从未触发过（三首谱面"相邻同轨"均为 0 次），因为第 2 条的同轨
    450ms 间隔 + 第 1 条的组内左右交替已经把这个约束强得多地覆盖了。

    v3.2 起不再依赖音高映射选轨（音高分箱会把音符堆到左侧轨道，与 FJ>DK>SL 相悖）。
    返回 (events, dropped)。
    """
    next_free = [-10**9] * 6     # 每轨下一次可放音符头的最早时间
    last_in_group = [None, None, None]   # 每组上次用的轨道（组内交替）
    out = []
    dropped = 0
    for t, dur in selected:
        kind = 'B' if dur >= SHORT_NOTE_THRESHOLD_MS else 'D'
        # 候选顺序：组优先级 FJ→DK→SL；组内先试"上次没用的一边"
        order = []
        for gi, (a, b) in enumerate(TRACK_PRIORITY_GROUPS):
            first, second = (b, a) if last_in_group[gi] == a else (a, b)
            order.extend([first, second])
        chosen = None
        for trk in order:
            if t >= next_free[trk]:
                chosen = trk
                break
        if chosen is None:
            dropped += 1
            continue
        for gi, group in enumerate(TRACK_PRIORITY_GROUPS):
            if chosen in group:
                last_in_group[gi] = chosen
        if kind == 'B':
            hold_end = t + max(dur, MIN_HOLD_MS)
            next_free[chosen] = hold_end + MIN_TRACK_GAP_MS   # 长按全程占用 + 尾部缓冲
        else:
            next_free[chosen] = t + MIN_TRACK_GAP_MS
        out.append((t, chosen, kind, float(dur)))
    return out, dropped


def balance_taps_holds(events, ratio_max=TAP_HOLD_RATIO_MAX):
    """短按/长按数量均衡：比值压到 ratio_max 以内，多的一方按持续时长就近换边。

    音符类型本来就来自能量衰减时长的软分类（SHORT_NOTE_THRESHOLD_MS 只是经验线），
    所以把"持续时间最短的长按"降级成短按、"持续时间最长的短按"升级成长按，
    都只是微调那条分类线 —— 不改变密度、轨道布局与同列连击限制。

    输入/输出事件均为 (t, trk, kind, dur)。返回 (events, down_conv, up_conv)：
      down_conv = 长按→短按 个数（长按过多时）
      up_conv   = 短按→长按 个数（短按过多时；dur 提到 MIN_HOLD_MS 保证 finalize
                  不会立刻把它降回去）
    """
    evs = [list(e) for e in events]
    down_conv = up_conv = 0
    while True:
        holds = sorted((e for e in evs if e[2] == 'B'), key=lambda e: e[3])   # 短→长
        taps = sorted((e for e in evs if e[2] == 'D'), key=lambda e: e[3], reverse=True)  # 长→短
        n_h, n_d = len(holds), len(taps)
        if n_h == 0 or n_d == 0:
            # 单边为 0：只要另一边还有 ≥2 个就换一个边过来，否则确实无解
            if n_d == 0 and n_h >= 2:
                holds[0][2] = 'D'
                down_conv += 1
                continue
            if n_h == 0 and n_d >= 2:
                taps[0][2] = 'B'
                taps[0][3] = max(taps[0][3], float(MIN_HOLD_MS))
                up_conv += 1
                continue
            break
        if n_h > n_d * ratio_max:
            e = holds[0]
            e[2] = 'D'
            down_conv += 1
        elif n_d > n_h * ratio_max:
            e = taps[0]
            e[2] = 'B'
            e[3] = max(e[3], float(MIN_HOLD_MS))
            up_conv += 1
        else:
            break
    return [tuple(e) for e in evs], down_conv, up_conv


def final_balance_events(events, ratio_max=TAP_HOLD_RATIO_MAX):
    """成品事件兜底均衡（作用于 (trk, t, etype)）：比值仍超 ratio_max 时换边。

    为什么需要兜底：finalize_holds 会把与下一同轨音符冲突的长按收缩、
    不足 MIN_HOLD_MS 再降级回短按 —— 换边上来的长按可能被这样打回去，比值回弹。

      长按过多 → (E−B) 最小的长按降级为短按（改 B→D、删配对 E）——只减少占用，安全；
      短按过多 → 同轨有空隙的短按升级为长按（D→B、插 E 于 t+MIN_HOLD_MS，
                  与下一同轨事件至少隔 MIN_TRACK_GAP_MS，否则不选它）。
    返回 (events, downgraded, upgraded)。
    """
    evs = [[trk, t, et] for trk, t, et in events]

    def counts():
        h = sum(1 for e in evs if e[2] == 'B')
        d = sum(1 for e in evs if e[2] == 'D')
        return d, h

    def track_events(trk):
        return sorted((e for e in evs if e[0] == trk), key=lambda e: e[1])

    downgraded = upgraded = 0
    while True:
        d, h = counts()
        need_down = h > 0 and ((d == 0 and h >= 2) or (d > 0 and h > d * ratio_max))
        need_up = d > 0 and ((h == 0 and d >= 2) or (h > 0 and d > h * ratio_max))
        if need_down:
            # 配对挑持续时间最短的长按（同轨 B 之后第一个 E 即配对，生成器保证交替）
            best_ev, best_e_ev = None, None
            for trk in set(e[0] for e in evs):
                open_b = None
                for e in track_events(trk):
                    if e[2] == 'B':
                        open_b = e
                    elif e[2] == 'E' and open_b is not None:
                        if best_e_ev is None or (e[1] - open_b[1]) < (best_e_ev[1] - best_ev[1]):
                            best_ev, best_e_ev = open_b, e
                        open_b = None
            if best_ev is None:
                break
            best_ev[2] = 'D'
            best_e_ev[2] = None
            evs = [e for e in evs if e[2] is not None]
            downgraded += 1
        elif need_up:
            # 找同轨空隙足够的短按升级（时间最早的优先）
            target = None
            for trk in sorted(set(e[0] for e in evs)):
                te = track_events(trk)
                for i, e in enumerate(te):
                    if e[2] != 'D':
                        continue
                    nxt = te[i + 1][1] if i + 1 < len(te) else 10**9
                    if e[1] + MIN_HOLD_MS + MIN_TRACK_GAP_MS <= nxt:
                        target = e
                        break
                if target:
                    break
            if target is None:
                break
            target[2] = 'B'
            evs.append([target[0], target[1] + MIN_HOLD_MS, 'E'])
            upgraded += 1
        else:
            break
    return [tuple(e) for e in evs], downgraded, upgraded


def finalize_holds(events):
    """逐轨确定长按的 E 时刻（第二遍，此时该轨下一个事件已知）。

    release = t + max(dur, MIN_HOLD_MS)，若与该轨下一个按下冲突则收缩；
    收缩后不足 MIN_HOLD_MS → 降级为短按。降级只会减少占用，不会破坏
    assign_tracks 已保证的"同轨两次按下至少隔 MIN_TRACK_GAP_MS"。
    """
    by_track = {}
    for t, trk, kind, dur in events:
        by_track.setdefault(trk, []).append((t, kind, dur))
    final = []
    downgraded = 0
    for trk in sorted(by_track.keys()):
        evs = sorted(by_track[trk], key=lambda x: x[0])
        for idx, (t, kind, dur) in enumerate(evs):
            if kind == 'D':
                final.append((trk, int(t), 'D'))
                continue
            release = t + max(dur, MIN_HOLD_MS)
            if idx + 1 < len(evs):
                limit = evs[idx + 1][0] - MIN_TRACK_GAP_MS
                if release > limit:
                    release = limit
            if release - t < MIN_HOLD_MS:
                final.append((trk, int(t), 'D'))
                downgraded += 1
            else:
                final.append((trk, int(t), 'B'))
                final.append((trk, int(round(release)), 'E'))
    return final, downgraded


def salience_tiers(salience, seg_of, n_seg):
    """把候选按"显著性"分三档（用户约束的分级依据）。

    结合两种视角：
      - 全局分位：全曲意义上的强/弱（避免安静段的噪声被当成强音）；
      - 段内峰值比：这一刻相对本段是否突出（安静段的主旋律也能被认出来）。

    返回 (tiers, glo_hi, glo_lo)；tiers: 2=明显 / 1=较明显 / 0=不明显
    """
    glo_hi = float(np.percentile(salience, SALIENCE_HI_PCT))
    glo_lo = float(np.percentile(salience, SALIENCE_LO_PCT))
    seg_max = np.zeros(n_seg)
    for s in range(n_seg):
        m = seg_of == s
        if m.any():
            seg_max[s] = float(np.max(salience[m]))
    local = np.array([salience[i] / max(seg_max[seg_of[i]], 1e-9) for i in range(len(salience))])
    tiers = np.zeros(len(salience), dtype=int)
    for i, s in enumerate(salience):
        if s >= glo_hi or (local[i] >= LOCAL_PEAK_HI and s >= glo_lo):
            tiers[i] = 2                       # 明显：必须体现
        elif s >= glo_lo or (local[i] >= LOCAL_PEAK_MID and s >= glo_lo):
            tiers[i] = 1                       # 较明显：不冲突就加入
        else:
            tiers[i] = 0                       # 不明显：只在空旷段补
    return tiers, glo_hi, glo_lo


def select_by_salience(times, tiers, gap_ms, seg_of, n_seg):
    """三档分层填充（取代旧的"纯时间贪心"）。

      第 1 轮 明显档(tier2)：必选 —— 只受 MIN_CROSS_TRACK_GAP_MS 跨轨下限
              （可突破该段目标密度；用户裁定：明显音符优先于密度曲线，
                且该下限只管"跨轨也不许几乎同时"，同轨间距留给 assign_tracks）。
      第 2 轮 较明显档(tier1)：距已选音符 ≥ 该段目标间隔才加入，
              且该段已选数不超过目标配额（不与明显档抢位置）。
      第 3 轮 不明显档(tier0)：仅当该段"十分空旷"（已选 < 目标 × EMPTY_SEG_RATIO）
              才按目标间隔补入，补到配额为止。

    每段独立统计，不再有旧贪心的跨段 carry-over（旧实现里高潮段末尾会挡住安静段开头）。
    返回 (入选下标升序, 统计 dict)。
    """
    seg_len_s = SEGMENT_MS / 1000.0
    gap_ms = np.asarray(gap_ms, dtype=float)
    quota = np.maximum(1.0, (1000.0 / np.maximum(gap_ms, 1e-6)) * seg_len_s)  # 每段目标音符数

    times = np.asarray(times, dtype=int)
    kept = []                       # 已入选时间（升序）
    kept_seg_count = np.zeros(n_seg)
    picked = {2: 0, 1: 0, 0: 0}
    dropped = {2: 0, 1: 0, 0: 0}

    def gap_ok(t, need):
        """与左右最近已选音符的间隔是否都 ≥ need"""
        if not kept:
            return True
        p = bisect.bisect_left(kept, t)
        if p > 0 and t - kept[p - 1] < need:
            return False
        if p < len(kept) and kept[p] - t < need:
            return False
        return True

    order = np.argsort(times)
    for want_tier, need_from_quota in ((2, False), (1, True), (0, True)):
        for i in order:
            if tiers[i] != want_tier:
                continue
            s = int(seg_of[i])
            if need_from_quota and kept_seg_count[s] >= quota[s]:
                dropped[want_tier] += 1
                continue
            # 不明显档额外要求：该段"十分空旷"才补
            if want_tier == 0 and kept_seg_count[s] >= quota[s] * EMPTY_SEG_RATIO:
                dropped[0] += 1
                continue
            t = int(times[i])
            need = float(gap_ms[s]) if need_from_quota else MIN_CROSS_TRACK_GAP_MS
            if gap_ok(t, need):
                bisect.insort(kept, t)
                kept_seg_count[s] += 1
                picked[want_tier] += 1
            else:
                dropped[want_tier] += 1

    # 时间 → 候选下标（同一时间可能有多条候选，取第一条）
    first_idx = {}
    for i in range(len(times)):
        first_idx.setdefault(int(times[i]), i)
    sel_idx = [first_idx[t] for t in kept if t in first_idx]
    stats = {'picked': picked, 'dropped': dropped, 'quota': quota,
             'kept_seg_count': kept_seg_count, 'kept': set(kept)}
    return sel_idx, stats


def validate_no_overlap(events):
    """唯一的终检：任何形式的音符重叠（含显示层间距）。事件元组 (trk, t, etype)。

    检查三类问题（返回问题列表，空 = 通过）：
      1. 同轨任意相邻事件间隔：普通对 ≥ MIN_TRACK_GAP_MS（显示不重叠）；
         B→E 自身是长按，要求 ≥ MIN_HOLD_MS（头/尾圆不重叠）；
      2. 任何 D/B 音符头落在长按 [B, E] 区间内（长按身体里穿音符）；
      3. 同轨长按区间互相重叠 / B 无配对 E / 孤立 E / B 未闭合又遇 B。

    本函数是 chart.js 可解析性的**充分条件**：parseChart 的三类 throw
    （连续 B、孤立 E、结尾未闭合 B）与 validateHolds 的"同轨长按重叠"
    都被上面第 3 条覆盖，因此不需要再单独写一个"等价于 validateHolds"的检查。
    （历史上曾有一个 validate_holds_no_overlap 做这件事，但它只比较"与前一条
      长按 release"的关系，会漏掉 B@t1,B@t2,E 这种连续 B —— 已删除。）
    """
    issues = []
    by_track = {}
    for trk, t, et in events:
        by_track.setdefault(trk, []).append((t, et))
    for trk in sorted(by_track.keys()):
        evs = sorted(by_track[trk])
        for (t1, c1), (t2, c2) in zip(evs, evs[1:]):
            if c1 == 'B' and c2 == 'E':
                if t2 - t1 < MIN_HOLD_MS:
                    issues.append(f"轨{trk}: 长按 {t1}→{t2} 仅 {t2-t1}ms < MIN_HOLD_MS({MIN_HOLD_MS})")
            elif t2 - t1 < MIN_TRACK_GAP_MS:
                issues.append(f"轨{trk}: {c1}@{t1} 与 {c2}@{t2} 间隔 {t2-t1}ms "
                              f"< MIN_TRACK_GAP_MS({MIN_TRACK_GAP_MS})")
        # 长按区间与音符头包含关系
        holds, open_b = [], None
        for t, c in evs:
            if c == 'B':
                if open_b is not None:
                    issues.append(f"轨{trk}: B@{open_b} 未闭合又遇 B@{t}")
                open_b = t
            elif c == 'E':
                if open_b is None:
                    issues.append(f"轨{trk}: 孤立 E@{t}")
                else:
                    holds.append((open_b, t))
                    open_b = None
            else:   # D
                for b, e in holds:
                    if b < t < e:
                        issues.append(f"轨{trk}: D@{t} 落在长按 [{b},{e}] 区间内")
        if open_b is not None:
            issues.append(f"轨{trk}: B@{open_b} 无配对 E")
        for a, b in zip(holds, holds[1:]):
            if b[0] < a[1]:
                issues.append(f"轨{trk}: 长按 {a} 与 {b} 重叠")
    return issues


def resolve_output(audio_path):
    """决定输出 .txt 路径 —— 消除"音频文件名 ≠ 谱面名 → 误写新文件、旧谱面原地不动"的坑。

    优先复用音频同目录下**已有的唯一** .txt（重生成时即"原地更新"）；
    没有或不止一个才退回 <音频同名>.txt。`.bak*` 备份不参与判断。
    """
    d = os.path.dirname(os.path.abspath(audio_path)) or '.'
    try:
        charts = [f for f in os.listdir(d)
                  if f.lower().endswith('.txt') and '.bak' not in f.lower()]
    except OSError:
        charts = []
    if len(charts) == 1:
        return os.path.join(d, charts[0])
    return os.path.splitext(audio_path)[0] + ".txt"


def process_song(audio_path, output_path):
    """处理单首曲目：加载 → 检测 → 生成 → 写盘 → 终检报告。

    独立成函数是为了批量模式：同一进程依次处理多首时，只需付一次
    scipy / librosa 的冷启动（实测每进程约 4.5s，与音频长度无关）。
    成功返回统计 dict；无法生成任何音符时返回 None（批量模式跳过该首、不中断）。
    """
    t_total0 = time.time()
    stage = {}
    AUDIO = os.path.abspath(audio_path)
    OUTPUT = os.path.abspath(output_path)

    # ---------- [1] 加载音频 ----------
    t0 = time.time()
    print("[1/7] 加载音频...")
    y, sr = load_audio_robust(AUDIO)
    total_duration = len(y) / sr
    stage['load'] = time.time() - t0
    print(f"      总时长: {total_duration:.2f}秒")

    # ---------- [2] 前导静音（SILENCE） ----------
    t0 = time.time()
    print("[2/7] 检测音乐实际开始位置...")
    hop_length = 512
    frame_length = 2048
    ffmpeg_silence = detect_leading_silence_ffmpeg(AUDIO, noise_db="-40", min_dur=0.05)
    if ffmpeg_silence is not None:
        silence_ms = ffmpeg_silence
        music_start_sample = int(round(silence_ms / 1000 * sr))
        silence_src = "ffmpeg silencedetect (noise=-40dB:d=0.05)"
        print(f"      [ffmpeg silencedetect] 前导无声时长: {silence_ms} ms")
    else:
        print("      [ffmpeg 不可用，回退 RMS 阈值]")
        rms0 = librosa.feature.rms(y=y, frame_length=frame_length, hop_length=hop_length)[0]
        threshold = np.max(rms0) * 0.05
        music_start_frame = np.where(rms0 > threshold)[0][0]
        music_start_time = librosa.frames_to_time(music_start_frame, sr=sr, hop_length=hop_length)
        silence_ms = int(music_start_time * 1000)
        music_start_sample = int(music_start_time * sr)
        # 兜底口径与 detect_offset.py 不同 → 必须如实标注，否则 #SILENCE 来源无法追溯
        silence_src = "RMS 阈值兜底 ⚠ 口径与 detect_offset.py 不一致，请核对"
        print(f"      [RMS 兜底] 前导无声时长: {silence_ms} ms")
    y_music = y[music_start_sample:]
    title_name = os.path.splitext(os.path.basename(AUDIO))[0].replace('_', ' ')
    stage['silence'] = time.time() - t0
    print(f"      音乐开始于文件第 {silence_ms/1000:.3f}秒，已剔除前导静音")

    # ---------- [3] Onset 检测 + 显著性（强度）分析 ----------
    t0 = time.time()
    print("[3/7] Onset 检测与显著性（强度）分析...")
    # v3.3：onset 包络（强度）此前从未取过 —— 旧版候选完全等权，
    # 导致"全曲最强的音符命中率只有一半、弱音却占了谱面 1/4"。
    onset_env = librosa.onset.onset_strength(y=y_music, sr=sr, hop_length=hop_length)
    onset_frames = librosa.onset.onset_detect(
        onset_envelope=onset_env, sr=sr, hop_length=hop_length,
        backtrack=False, pre_max=10, post_max=10,
        pre_avg=100, post_avg=100, delta=0.02, wait=1.5
    )
    onset_times_ms = (librosa.frames_to_time(onset_frames, sr=sr, hop_length=hop_length) * 1000).astype(int)
    onset_salience = onset_env[onset_frames]     # 每个候选的"显著性"
    print(f"      检测到 {len(onset_frames)} 个 onset 候选"
          f"（强度 {onset_salience.min():.2f}~{onset_salience.max():.2f}）"
          if len(onset_frames) else "      检测到 0 个 onset 候选")

    # v3.4 清理：CQT 音高分析整块已删除（约 8-9s，占总耗时一半）。
    # 它原本只服务于"音高分箱选轨"，而 v3.2 起轨道分配改为 FJ>DK>SL 键位优先级，
    # 音高结果只剩"打印一行旋律音高范围"这一个用途 —— 属于典型的无用开销。
    stage['onset'] = time.time() - t0

    # ---------- [4] 能量包络 + 密度分段 ----------
    t0 = time.time()
    print("[4/7] 能量包络与密度分段（高潮密 / 非高潮疏）...")
    rms = librosa.feature.rms(y=y_music, frame_length=frame_length, hop_length=hop_length)[0]
    hop_sec = hop_length / float(sr)
    total_music_ms = len(y_music) / sr * 1000.0
    intensity = compute_segment_intensity(rms, sr, hop_length, total_music_ms)
    n_seg = len(intensity)
    stage['envelope'] = time.time() - t0
    climax_segs = int(np.sum(intensity >= 0.6))
    print(f"      分为 {n_seg} 段（每段 {SEGMENT_MS}ms），高潮段(强度>=0.6)占 {climax_segs} 段")
    print(f"      段强度: min={intensity.min():.2f} max={intensity.max():.2f} mean={intensity.mean():.2f}")

    # ---------- [5] 音符持续时间（帧级，向量化替代逐样本循环） ----------
    t0 = time.time()
    print("[5/7] 音符持续时间估计（帧级能量衰减）...")
    next_frame_hint = []
    for i, of in enumerate(onset_frames):
        if i + 1 < len(onset_frames):
            next_frame_hint.append(int(onset_frames[i + 1] + 0.15 * sr / hop_length))
        else:
            next_frame_hint.append(len(rms))
    durations = estimate_durations_frames(onset_frames, rms, hop_sec, next_frame_hint)
    stage['duration'] = time.time() - t0
    short_candidates = int(np.sum(durations < SHORT_NOTE_THRESHOLD_MS))
    long_candidates = int(np.sum(durations >= SHORT_NOTE_THRESHOLD_MS))
    print(f"      短音候选: {short_candidates}, 长音候选: {long_candidates}")
    print(f"      平均持续时间: {np.mean(durations):.1f}ms")

    # ---------- [6] 按段密度生成 + 短/长目标软校正（最多 MAX_ROUNDS 轮） ----------
    print("[6/7] 按段密度筛选音符并分配轨道（FJ>DK>SL 优先级）...")
    all_candidates = list(zip([int(t) for t in onset_times_ms], durations))
    cand_times = [int(t) for t in onset_times_ms]
    cand_seg = np.array([min(n_seg - 1, max(0, t // SEGMENT_MS)) for t in cand_times])
    # 显著性分档（段内峰值 + 全局分位结合）
    cand_tiers, glo_hi, glo_lo = salience_tiers(onset_salience, cand_seg, n_seg)
    tier_total = {k: int(np.sum(cand_tiers == k)) for k in (2, 1, 0)}
    print(f"      显著性分档（全局 P{SALIENCE_LO_PCT}={glo_lo:.2f} / P{SALIENCE_HI_PCT}={glo_hi:.2f}）："
          f"明显 {tier_total[2]}，较明显 {tier_total[1]}，不明显 {tier_total[0]}")
    scale_quiet, scale_loud = 1.0, 1.0
    best = None   # (score, short_count, long_count, final_events, sal_stats)

    for rnd in range(MAX_ROUNDS):
        nps = segment_target_nps(intensity, scale_quiet, scale_loud)
        gap_ms = 1000.0 / np.maximum(nps, 0.05)

        # 6a. 三档分层筛选（v3.3）：明显必选 → 较明显填空 → 不明显仅空旷段补
        sel_idx, sal_stats = select_by_salience(
            cand_times, cand_tiers, gap_ms, cand_seg, n_seg)
        selected = [(all_candidates[i][0], float(all_candidates[i][1])) for i in sel_idx]

        # 6b. 轨道分配（FJ>DK>SL 优先级 + 同轨连击限制 + 长按全程占用）
        assigned, dropped = assign_tracks(selected)

        # 6c. 短/长按数量均衡（比值不超过 TAP_HOLD_RATIO_MAX，按持续时长就近换边）
        assigned, bal_down, bal_up = balance_taps_holds(assigned)

        # 6d. 逐轨确定长按 E 时刻
        final_events, downgraded = finalize_holds(assigned)

        short_count = sum(1 for e in final_events if e[2] == 'D')
        long_count = sum(1 for e in final_events if e[2] == 'B')
        ratio = max(short_count, long_count) / max(1, min(short_count, long_count))
        p = sal_stats['picked']
        print(f"      第 {rnd+1} 轮  密度缩放 quiet×{scale_quiet:.2f}/loud×{scale_loud:.2f}"
              f" → 短按 {short_count}, 长按 {long_count}（比值 {ratio:.2f}x）")
        print(f"               显著性入选 明显 {p[2]}/{tier_total[2]}，"
              f"较明显 {p[1]}/{tier_total[1]}，不明显 {p[0]}/{tier_total[0]}"
              f"（丢轨 {dropped}，均衡换边 ↓{bal_down}/↑{bal_up}，长按降级 {downgraded}）")

        score = min(short_count / TARGET_SHORT_COUNT, long_count / TARGET_LONG_COUNT)
        cand = (score, short_count, long_count, final_events, sal_stats)
        if best is None or score > best[0]:
            best = cand

        if short_count >= TARGET_SHORT_COUNT and long_count >= TARGET_LONG_COUNT:
            print(f"      达成目标（短按>={TARGET_SHORT_COUNT} 且 长按>={TARGET_LONG_COUNT}），提前结束")
            break
        # 未达标的调整方向：短按不足 → 高潮更密（更多长按被挤成短按）；
        #                    长按不足 → 安静段更密（更多音符能撑成长按）
        if short_count < TARGET_SHORT_COUNT:
            scale_loud = min(SCALE_MAX, scale_loud * SCALE_STEP)
        if long_count < TARGET_LONG_COUNT:
            scale_quiet = min(SCALE_MAX, scale_quiet * SCALE_STEP)

    if best is None:
        print("      警告：无法生成任何音符，请检查音频和参数")
        return None
    score, best_short, best_long, final_events, best_sal = best
    # 兜底均衡：finalize 造成的比值回弹在这里压回 TAP_HOLD_RATIO_MAX 以内
    final_events, fix_down, fix_up = final_balance_events(final_events)
    if fix_down or fix_up:
        best_short = sum(1 for e in final_events if e[2] == 'D')
        best_long = sum(1 for e in final_events if e[2] == 'B')
        print(f"      兜底均衡：长按降级 {fix_down}，短按升级 {fix_up} → 短按 {best_short}, 长按 {best_long}")
    stage['generate'] = time.time() - t0
    print(f"      采用最优轮：短按 {best_short}, 长按 {best_long}（均衡分 {score:.2f}）")

    # ---------- [7] 生成曲谱文本 ----------
    t0 = time.time()
    print("[7/7] 生成曲谱文本...")
    events_dict = {}
    for trk, t, etype in final_events:
        if t not in events_dict:
            events_dict[t] = ['#', '#', '#', '#', '#', '#']
        events_dict[t][trk] = etype
    sorted_times = sorted(events_dict.keys())

    # 终检：任何形式的重叠（含显示间距）+ chart.js 可解析性（见 validate_no_overlap）
    overlap_issues = validate_no_overlap(final_events)
    if overlap_issues:
        print("      [校验] 重叠终检（含显示间距）发现问题:")
        for it in overlap_issues[:10]:
            print("        " + it)
    else:
        print(f"      [校验] 重叠终检（含显示间距 ≥{MIN_TRACK_GAP_MS}ms）✓ 同轨长按无重叠 ✓")

    # 音游约定：#OFFSET = #SILENCE + 2160
    MUSIC_LEAD_MS = 2160
    offset_ms = silence_ms + MUSIC_LEAD_MS

    audio_total_ms = int(len(y) / sr * 1000)
    if sorted_times:
        first_final_t = sorted_times[0] + offset_ms
        last_final_t = sorted_times[-1] + offset_ms
        # ★ 时间轴对齐（v3.5.1）：last_final_t 在 **songTime 域**（rawT + OFFSET），
        #   而 audio_total_ms 是 **音频文件域** 时长，两者相差 MUSIC_LEAD_MS
        #   （= OFFSET − SILENCE，即音频文件 0 秒对应的 songTime）。
        #   直接互比会把阈值整体偏移 MUSIC_LEAD_MS：只要末音符距音频末尾不足 2160ms
        #   就被误判为"超出总时长"（Da_Capo 实测余量 +1854ms，却被报了越界）。
        #   正确的越界判据是"音符在音频文件里的位置 > 音频时长"。
        last_file_pos = last_final_t - MUSIC_LEAD_MS
        tail_margin = audio_total_ms - last_file_pos
        print(f"      首音符 songTime: {first_final_t} ms，末音符 songTime: {last_final_t} ms"
              f"（音频内位置 {last_file_pos} ms），音频总时长: {audio_total_ms} ms")
        if tail_margin < 0:
            print(f"      [警告] 末音符音频内位置 ({last_file_pos} ms) 超出音频总时长 "
                  f"({audio_total_ms} ms) {abs(tail_margin)} ms —— 尾段无法播放（多为长按尾越界），"
                  f"需裁掉或改为不延伸到结束的短按")
        else:
            print(f"      末音符距音频末尾余量 {tail_margin} ms ✓")

    lines = []
    lines.append(f"#TITLE:{title_name}")
    lines.append("#BPM:110")
    lines.append("#KEY:6K")
    lines.append(f"#OFFSET:{offset_ms}")
    lines.append(f"#SILENCE:{silence_ms}")
    lines.append("time    tr1 tr2 tr3 tr4 tr5 tr6")
    for t in sorted_times:
        a = events_dict[t]
        lines.append(f"{t:5d}   {a[0]:3s}   {a[1]:3s}   {a[2]:3s}   {a[3]:3s}   {a[4]:3s}   {a[5]:3s}")

    os.makedirs(os.path.dirname(OUTPUT) or '.', exist_ok=True)
    with open(OUTPUT, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))
    stage['write'] = time.time() - t0

    # ---------- 报告 ----------
    tap_count = sum(1 for e in final_events if e[2] == 'D')
    hold_count = sum(1 for e in final_events if e[2] == 'B')
    print(f"\n[OK] 完成！曲谱已保存至: {OUTPUT}")
    print(f"   总行数: {len(lines)} 行 (含 5 行头 + 1 行表头 + {len(sorted_times)} 行数据)")
    if sorted_times:
        span = sorted_times[-1] - sorted_times[0]
        density = (tap_count + hold_count) / max(1, span / 1000)
        print(f"   谱面时间跨度: {sorted_times[0]}ms ~ {sorted_times[-1]}ms（{span/1000:.2f}s）")
        print(f"   音符密度: 短按 {tap_count} + 长按 {hold_count} = {tap_count+hold_count} 个，"
              f"约 {density:.2f} notes/s")
    # 短/长按比例（用户约束：不得超过 1.5 倍）
    if tap_count > 0 and hold_count > 0:
        th_ratio = max(tap_count, hold_count) / min(tap_count, hold_count)
        flag = "✓" if th_ratio <= TAP_HOLD_RATIO_MAX else "✗ 超标！"
        print(f"   短/长按比例: {tap_count} : {hold_count}（比值 {th_ratio:.2f}x，"
              f"上限 {TAP_HOLD_RATIO_MAX}x {flag}）")
    # 密度分段效果：高潮段 vs 非高潮段的实际 notes/s
    seg_notes = np.zeros(n_seg)
    for t in sorted_times:
        seg_notes[min(n_seg - 1, t // SEGMENT_MS)] += 1
    seg_dur_s = SEGMENT_MS / 1000.0
    seg_nps = seg_notes / seg_dur_s
    hot = intensity >= 0.6
    if hot.any() and (~hot).any():
        print(f"   密度对比: 高潮段平均 {seg_nps[hot].mean():.2f} notes/s vs "
              f"非高潮段平均 {seg_nps[~hot].mean():.2f} notes/s"
              f"（比值 {seg_nps[hot].mean() / max(seg_nps[~hot].mean(), 1e-6):.2f}x）")
    hot_t = np.argmax(seg_nps) * SEGMENT_MS / 1000.0
    cold_t = np.argmin(seg_nps) * SEGMENT_MS / 1000.0
    print(f"   最密段 {seg_nps.max():.2f} notes/s @ {hot_t:.1f}s | 最疏段 {seg_nps.min():.2f} notes/s @ {cold_t:.1f}s")
    # 显著性验收（用户约束：明显的必须体现 / 不明显的只在空旷处）
    p = best_sal['picked']
    print(f"   显著性入选: 明显 {p[2]}/{tier_total[2]}"
          f"（命中率 {p[2]/max(1,tier_total[2])*100:.0f}%），"
          f"较明显 {p[1]}/{tier_total[1]}"
          f"（{p[1]/max(1,tier_total[1])*100:.0f}%），"
          f"不明显 {p[0]}/{tier_total[0]}"
          f"（{p[0]/max(1,tier_total[0])*100:.0f}%，仅空旷段补）")
    top_n = min(50, len(onset_salience))
    top_idx = np.argsort(onset_salience)[::-1][:top_n]
    hit = sum(1 for i in top_idx if int(onset_times_ms[i]) in best_sal['kept'])
    print(f"   最强 {top_n} 个音符命中: {hit}/{top_n}（{hit/max(1,top_n)*100:.0f}%）")
    # 明显档命中率不足 100% 时点名（用户硬约束：明显的必须体现）
    miss2 = tier_total[2] - p[2]
    if miss2 > 0:
        print(f"   [警告] 有 {miss2} 个明显档音符未进谱面"
              f"（跨轨间隔 < MIN_CROSS_TRACK_GAP_MS={MIN_CROSS_TRACK_GAP_MS}ms，或该轮丢轨）")
    # 轨道分布（S D F J K L 标签 + FJ/DK/SL 组统计，验证优先级）
    trk_dist = Counter(e[0] for e in final_events if e[2] in 'DB')
    labels = 'SDFJKL'
    per_track = ' '.join(f"{labels[i]}:{trk_dist.get(i, 0)}" for i in range(6))
    g_fj = trk_dist.get(2, 0) + trk_dist.get(3, 0)
    g_dk = trk_dist.get(1, 0) + trk_dist.get(4, 0)
    g_sl = trk_dist.get(0, 0) + trk_dist.get(5, 0)
    prio_ok = g_fj > g_dk > g_sl or (g_fj > g_dk and g_dk >= g_sl and g_sl == 0)
    print(f"   轨道分布: {per_track}")
    print(f"   优先级组: FJ={g_fj} > DK={g_dk} > SL={g_sl}"
          f"{' ✓' if prio_ok else ' ✗ 不满足 FJ>DK>SL！'}")
    # 用户裁定：外轨闲置不改谱面，但必须可见 —— 否则"谱面挤在中间 4 列"会一直是隐性事实
    if g_sl == 0:
        print(f"   [提示] S / L 两轨使用 0 次：严格执行 FJ>DK>SL 的结果，"
              f"谱面集中在中间 4 列（FJ={g_fj}, DK={g_dk}）。若要铺满 6 键需另设外轨最低占比。")
    print(f"   #SILENCE:{silence_ms}（{silence_src}）")
    print(f"   #OFFSET:{offset_ms} = SILENCE {silence_ms} + 音乐后移 {MUSIC_LEAD_MS}")
    print(f"   下一步：node rhythm/gen_songs.js → rhythm/music/charts.js 即可被 index.html 读取")

    print("\n   各阶段耗时:")
    order = ['load', 'silence', 'onset', 'envelope', 'duration', 'generate', 'write']
    for k in order:
        if k in stage:
            print(f"     {k:<10s} {stage[k]:7.2f}s")
    total_s = time.time() - t_total0
    print(f"     {'total':<10s} {total_s:7.2f}s")

    return {'audio': AUDIO, 'output': OUTPUT, 'tap': tap_count, 'hold': hold_count,
            'notes': tap_count + hold_count, 'seconds': total_s, 'stage': stage}


def main():
    ap = argparse.ArgumentParser(
        description="rhythm 音游曲谱制造器 v3.6",
        epilog="一个进程处理多首可摊掉 ~4.5s 的 scipy/librosa 冷启动；"
               "输出路径缺省 = 复用同目录已有的唯一 .txt（原地更新），否则 <音频同名>.txt。"
               "新增一首歌建议直接用 rhythm/build.cmd（本脚本的 --missing 是它的第 1 步）。")
    ap.add_argument("audio", nargs="*", default=None,
                    help="一个或多个音频；不给则用曲库里排序第一的那首")
    ap.add_argument("-o", "--output", default=None,
                    help="输出 .txt（仅单首时可用；缺省见上）")
    ap.add_argument("--all", action="store_true",
                    help="重生成 music/ 下**每一首**（已有谱面会被覆盖）")
    ap.add_argument("--missing", action="store_true",
                    help="只处理有音频、但还没有 .txt 谱面的曲目；无待生成时立刻退出")
    # 兼容旧写法：`... <音频> <输出.txt>`（第二个位置参数以 .txt 结尾即视为输出）
    argv = sys.argv[1:]
    legacy_out = None
    if not args_is_output_flag(argv) and len(argv) >= 2 and argv[-1].lower().endswith('.txt'):
        legacy_out = argv[-1]
    args = ap.parse_args()
    if legacy_out:
        args.audio = [a for a in args.audio if a != legacy_out]
        if args.output is None:
            args.output = legacy_out

    if args.all:
        audios = discover_all_audio()
        if not audios:
            print(f"[错误] music/ 下没有任何可处理的曲目（{MUSIC_DIR}）")
            sys.exit(2)
    elif args.audio:
        audios = args.audio
    else:
        d = default_audio()
        if not d:
            print(f"[错误] music/ 下没有找到音频（{MUSIC_DIR}）；"
                  f"请显式给出音频路径，或用 --all / --missing")
            sys.exit(2)
        audios = [d]

    if args.output and len(audios) > 1:
        print("[错误] --output 只能用于单首；处理多首时请让输出路径自动决定（同目录唯一 .txt）")
        sys.exit(2)

    jobs = []
    for a in audios:
        if not os.path.isfile(a):
            print(f"[错误] 找不到音频: {a}")
            sys.exit(2)
        jobs.append((a, args.output if args.output else resolve_output(a)))

    t_all0 = time.time()
    results = []
    for i, (a, o) in enumerate(jobs, 1):
        if len(jobs) > 1:
            print(f"\n{'='*72}\n[{i}/{len(jobs)}] {os.path.basename(a)}"
                  f"\n{'='*72}")
        r = process_song(a, o)
        if r:
            results.append(r)

    if len(jobs) > 1:
        print(f"\n{'='*72}\n[批量汇总] {len(results)}/{len(jobs)} 首成功，"
              f"总耗时 {time.time() - t_all0:.2f}s")
        for r in results:
            print(f"   {os.path.basename(r['output']):<44} {r['tap']:>4}+{r['hold']:<4}"
                  f" = {r['notes']:>4} 音符   {r['seconds']:5.2f}s")
        first = next((r for r in results if 'load' in r['stage']), None)
        if first:
            print(f"   （单首净耗时已扣除冷启动：首首 {first['seconds']:.2f}s 含"
                  f" scipy/librosa 冷启动，后续可直接对比）")
    if len(results) < len(jobs):
        sys.exit(1)


def args_is_output_flag(argv):
    """argv 里是否已显式给出 -o/--output（给了就不必再猜旧的位置参数写法）。"""
    return any(a == '-o' or a.startswith('--output') for a in argv)


if __name__ == "__main__":
    main()