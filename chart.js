/**
 * ============================================================
 * chart.js —— 音游曲谱解析器（浏览器 + node 通用，UMD 风格）
 *
 * 谱面格式（music/<id>/<id>.txt）：
 *   #TITLE:标题 / #BPM:数字 / #KEY:6K / #OFFSET:毫秒 / #SILENCE:毫秒
 *   每行:  time  tr1 tr2 tr3 tr4 tr5 tr6
 *   记号:  D = 短按(tap)   B = 长按开头   E = 长按结尾
 *          . 或 # = 无操作（# 同时代表"正在长按"的行）
 *   时间戳单位 ms，0ms = 歌曲出现声音的时刻。
 *
 * 语义：
 *   #OFFSET   加到每个音符的原始时间上。谱面时间列是"出声之后的相对时间"，
 *             所以口径统一为 OFFSET = SILENCE + 音乐后移量(2160)：
 *             音符 t = rawT + OFFSET，而它真正出声于音频文件位置 SILENCE + rawT。
 *   #SILENCE  音频文件开头的静音时长（detect_offset.py 检测）。
 *             播放页的 musicLeadMs（音频文件 0 对应的 songTime）必须按
 *             **OFFSET - SILENCE** 算（见 player.html 的 musicLeadFor）。
 *             不能用"首音符 t - SILENCE"——那会把每条音符提前 rawFirst 毫秒。
 *
 * 浏览器：window.RhythmChart = { parseChart, validateHolds }
 * node：  const { parseChart, validateHolds } = require('./chart.js')
 * ============================================================
 */
(function (root, factory) {
  if (typeof module === 'object' && module.exports) {
    module.exports = factory();
  } else {
    root.RhythmChart = factory();
  }
}(typeof self !== 'undefined' ? self : this, function () {
  'use strict';

  /** 解析单个曲谱文本 → 元信息 + notes（纯函数） */
  function parseChart(text) {
    var meta = { title: '', bpm: 0, keyCount: 6, offset: 0, silence: 0 };
    var rows = [];
    var lines = String(text).split(/\r?\n/);

    for (var i = 0; i < lines.length; i++) {
      var raw = lines[i];
      var line = raw.trim();
      if (!line) continue;

      // 元信息行 #KEY:xxx
      if (line.charAt(0) === '#') {
        var m = line.match(/^#(\w+)\s*[:=]\s*(.*)$/);
        if (!m) continue;
        var key = m[1].toUpperCase();
        var val = m[2].trim();
        if (key === 'TITLE') meta.title = val;
        else if (key === 'BPM') meta.bpm = parseFloat(val) || 0;
        else if (key === 'KEY') meta.keyCount = parseInt(val, 10) || 6;
        else if (key === 'OFFSET') meta.offset = parseInt(val, 10) || 0;
        else if (key === 'SILENCE') meta.silence = parseInt(val, 10) || 0;
        continue;
      }

      // 表头行（含 time 与 tr1）
      if (/^time\b/i.test(line)) continue;

      // 数据行：按空白切分 → [time, c1..c6]
      var cells = line.split(/\s+/).filter(function (s) { return s.length > 0; });
      if (cells.length < 2) continue;
      var t = parseInt(cells[0], 10);
      if (!isFinite(t)) continue;
      rows.push({ t: t, cells: cells.slice(1) });
    }

    // 每条轨道的待闭合长按 B
    var openHold = [];
    for (var k = 0; k < meta.keyCount; k++) openHold.push(null);
    var notes = [];

    for (var r = 0; r < rows.length; r++) {
      var row = rows[r];
      var t = row.t + meta.offset;
      for (var j = 0; j < meta.keyCount; j++) {
        var c = (row.cells[j] || '.').toUpperCase();
        if (c === 'D') {
          notes.push({ t: t, track: j, type: 1 });
        } else if (c === 'B') {
          if (openHold[j] !== null) {
            throw new Error('track ' + (j + 1) + ' 在 ' + t + 'ms 出现未闭合的连续 B');
          }
          openHold[j] = t;
        } else if (c === 'E') {
          var start = openHold[j];
          if (start === null) {
            throw new Error('track ' + (j + 1) + ' 在 ' + t + 'ms 出现没有 B 的孤例 E');
          }
          notes.push({ t: start, track: j, type: 2, end: t });
          openHold[j] = null;
        }
        // '.' / '#' → 无操作（含长按持续中的行）
      }
    }

    var unclosed = -1;
    for (var u = 0; u < openHold.length; u++) {
      if (openHold[u] !== null) { unclosed = u; break; }
    }
    if (unclosed !== -1) {
      throw new Error('track ' + (unclosed + 1) + ' 存在未以 E 结束的长按');
    }

    notes.sort(function (a, b) { return a.t - b.t || a.track - b.track; });
    return { meta: meta, notes: notes };
  }

  /** 校验：同轨长按区间不得重叠；返回长按数 */
  function validateHolds(notes) {
    var holds = notes.filter(function (n) { return n.type === 2; });
    var byTrack = {};
    for (var i = 0; i < holds.length; i++) {
      var h = holds[i];
      if (!byTrack[h.track]) byTrack[h.track] = [];
      byTrack[h.track].push(h);
    }
    var tracks = Object.keys(byTrack);
    for (var t = 0; t < tracks.length; t++) {
      var list = byTrack[tracks[t]];
      list.sort(function (a, b) { return a.t - b.t; });
      for (var j = 1; j < list.length; j++) {
        if (list[j].t < list[j - 1].end) {
          throw new Error('track ' + (tracks[t] * 1 + 1) + ' 长按重叠: ' + list[j].t + 'ms < ' + list[j - 1].end + 'ms');
        }
      }
    }
    return holds.length;
  }

  return { parseChart: parseChart, validateHolds: validateHolds };
}));
