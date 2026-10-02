/**
 * ============================================================
 * gen_songs.js —— 音游曲库打包器
 *
 * 用法（脚本用 __dirname 定位目录，与当前工作目录无关，两种都行）：
 *   一键构建（推荐：补谱面 + 曲库 + 皮肤一起）：node build.js（或 node rhythm/build.js；
 *     Windows 直接双击 rhythm/build.cmd，它会先补好缺失的谱面再打包）
 *   只重建曲库：
 *   在 game/rhythm/ 下执行：node gen_songs.js
 *   在 game/ 下执行：       node rhythm/gen_songs.js
 *
 * 新增曲目（三步，不需要改任何 HTML/JS）：
 *   1) 在 music/ 下新建文件夹，名字就是曲名（显示名 = 文件夹名），例如 music/MySong/
 *   2) 放两个文件：任意文件名的 .txt 谱面 + 任意文件名的 .mp3（各一个即可）
 *   3) 跑一次 node build.js
 *   谱面头部：#TITLE/#BPM/#KEY:6K/#OFFSET/#SILENCE，其中 OFFSET = SILENCE + 2160
 *   （用 Sheet Music Maker.py 从 mp3 自动生成，或 detect_offset.py 实测 SILENCE）。
 *
 * 功能：
 *   扫描 music 目录下的每个子文件夹（每个子文件夹 = 一个独立音游/一首歌）：
 *     music/<id>/<id>.txt        曲谱（chart.js 的 parseChart 可解析）
 *     music/<id>/<任意名>.mp3    音频（每个子文件夹恰好一个 .mp3）
 *   把每个曲谱原文 + 头部元数据（#TITLE/#BPM/#KEY/#OFFSET/#SILENCE）打包进
 *   music/charts.js（挂 window.RHYTHM_SONGS），供 index.html / player.html
 *   用 <script src> 直接加载，运行时由 chart.js parseChart 解析出 notes。
 *
 *   为什么用 <script src> 而非 fetch：
 *   浏览器在 file:// 协议下无法 fetch 本地文件（受 CORS 限制），但 <script>
 *   标签可以加载本地 .js。用 charts.js 打包谱面原文，网站双击即可运行，
 *   同时保留"运行时解析谱面（chart.js）"的特性，无需预编译 notes。
 *
 *   charts.js 结构（对象映射，key = id）：
 *     window.RHYTHM_SONGS = {
 *       "<id>": { id, title, bpm, keyCount, offset, silence,
 *                 audio, chart, tapCount, holdCount, noteCount }
 *     }
 *   - audio  相对 rhythm/ 的音频路径（供 <audio src> 直接加载）
 *   - chart  谱面原文（供 parseChart 运行时解析）
 *
 * 中文输出：见 _term.js。控制台代码页不是 UTF-8 时会自动退化成 ASCII 文案，
 *   同时把完整报告写进 music/charts.log.txt（UTF-8，永远可读）。
 * ============================================================
 */
'use strict';
const fs = require('fs');
const path = require('path');
const { parseChart, validateHolds } = require('./chart.js');
const term = require('./_term');

const RHYTHM_DIR = __dirname;
const MUSIC_DIR = path.join(RHYTHM_DIR, 'music');
const OUT_FILE = path.join(MUSIC_DIR, 'charts.js');
const LOG_FILE = path.join(MUSIC_DIR, 'charts.log.txt');

function main() {
  if (!fs.existsSync(MUSIC_DIR)) {
    term.err(`找不到 music 目录: ${MUSIC_DIR}`, `music directory not found: ${MUSIC_DIR}`);
    return 1;
  }

  const songs = {};
  const dirs = fs
    .readdirSync(MUSIC_DIR)
    .filter((d) => {
      const full = path.join(MUSIC_DIR, d);
      return fs.statSync(full).isDirectory() && !d.startsWith('.');
    })
    .sort();

  for (const id of dirs) {
    const subDir = path.join(MUSIC_DIR, id);
    const files = fs.readdirSync(subDir);

    // 谱面：子文件夹内唯一 .txt
    const chartFiles = files.filter((f) => f.toLowerCase().endsWith('.txt'));
    // 音频：子文件夹内唯一 .mp3
    const audioFiles = files.filter((f) => f.toLowerCase().endsWith('.mp3'));

    if (chartFiles.length === 0) {
      term.warn(`${id}: 缺少 .txt 谱面，跳过`, `${id}: no .txt chart, skipped`);
      continue;
    }
    if (audioFiles.length === 0) {
      term.warn(`${id}: 缺少 .mp3 音频，跳过`, `${id}: no .mp3 audio, skipped`);
      continue;
    }
    if (audioFiles.length > 1) {
      term.warn(`${id}: 存在多个 .mp3（${audioFiles.join(', ')}），取第一个`,
                `${id}: multiple .mp3 (${audioFiles.join(', ')}), using the first`);
    }

    const chartFile = chartFiles[0];
    const audioFile = audioFiles[0];
    const text = fs.readFileSync(path.join(subDir, chartFile), 'utf-8');
    const { meta, notes } = parseChart(text);
    const holdCount = validateHolds(notes);
    const tapCount = notes.length - holdCount;

    songs[id] = {
      id,
      title: id,                          // 显示名 = 子文件夹名（谱面 #TITLE 可能重复，不作为显示名）
      bpm: meta.bpm,
      keyCount: meta.keyCount,
      offset: meta.offset,
      silence: meta.silence,
      audio: `music/${id}/${audioFile}`,   // 相对 rhythm/，供 <audio src> 直接加载
      chart: text,                          // 谱面原文，运行时由 parseChart 解析
      tapCount,
      holdCount,
      noteCount: notes.length
    };

    /* 这一行本来就是全 ASCII，两种语言一致；色值/数字在任何控制台都读得对 */
    term.say(
      `[ok] ${id}: ${tapCount} tap + ${holdCount} hold = ${notes.length} notes, ` +
      `BPM ${meta.bpm}, ${meta.keyCount}K, OFFSET ${meta.offset}, SILENCE ${meta.silence}`,
      `[ok] ${id}: ${tapCount} tap + ${holdCount} hold = ${notes.length} notes, ` +
      `BPM ${meta.bpm}, ${meta.keyCount}K, OFFSET ${meta.offset}, SILENCE ${meta.silence}`
    );
  }

  const banner =
    '/**\n' +
    ' * charts.js —— 音游曲库（由 gen_songs.js 自动生成，请勿手改）\n' +
    ' * 重新生成：在 rhythm/ 目录下执行  node gen_songs.js\n' +
    ' * chart 为谱面原文，运行时由 chart.js parseChart 解析；audio 为相对 rhythm/ 的音频路径。\n' +
    ' */\n';
  const body = 'window.RHYTHM_SONGS = ' + JSON.stringify(songs, null, 2) + ';\n';
  fs.writeFileSync(OUT_FILE, banner + body, 'utf-8');

  const rel = path.relative(path.join(RHYTHM_DIR, '..'), OUT_FILE);
  term.say(`写出 ${rel}（共 ${Object.keys(songs).length} 首）`,
           `wrote ${rel} (${Object.keys(songs).length} song(s))`);
  term.log('环境：' + term.describe());
  term.flush(LOG_FILE);
  return 0;
}

if (require.main === module) {
  let code = 0;
  try { code = main() || 0; }
  catch (e) {
    term.err('失败：' + (e && e.message), 'failed: ' + (e && e.message));
    code = 1;
  }
  term.flush(LOG_FILE);
  process.exitCode = code;
}
