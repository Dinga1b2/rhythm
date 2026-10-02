#!/usr/bin/env node
/**
 * ============================================================
 * 皮肤打包器 —— 扫描 role/<皮肤>/，生成两个文件：
 *   role/palette.js  从 D.png / R.png / Trailing.png 提取"关键色"（打碎粉末用）
 *   role/skins.js    皮肤清单（window.RHYTHM_SKINS）——播放页右侧皮肤栏按它一一列出，
 *                    并按选中项一次性套用 背景 + 短按图 + 长按头图 + 拖尾图 + 粉末配色
 *
 * 新增皮肤（本地操作，三步，不需要改任何 HTML/CSS）：
 *   1) 在 role/ 下新建文件夹，文件夹名即皮肤 id，例如 role/furina/
 *      ★ id 必须纯 ASCII：中文名在 Windows 自带解压器下会乱码（见 rhythm/README.md 分发说明）；
 *        中文显示名写在该文件夹的 skin.json 里：{"name":"芙宁娜","order":10}
 *   2) 放四张 png：Background.png（背景）/ D.png（短按）/ R.png（长按头尾）/ Trailing.png（长按拖尾）
 *      缺哪张都不报错：少背景就只有纯色底，少 D.png 会借用 R.png，拖尾严格只用 Trailing.png
 *      可选：放一个 skin.json = {"name":"显示名","order":10} 覆盖显示名与排序
 *   3) 跑一次  node build.js   （在 game/ 下则 node rhythm/build.js）
 *   完成。刷新播放页，右侧皮肤栏会多出一项。
 *
 * 为什么要在构建期做，而不是运行时用 canvas 取样：
 *   项目是"双击即玩"的纯前端（file://）。把本地图片画进 canvas 会污染画布，
 *   getImageData 直接抛 SecurityError（和 charts.js 不能走 fetch 是同一个坑）。
 *   所以沿用 gen_songs.js 的思路：构建期读出静态数据写成 .js，
 *   页面用 <script src="role/skins.js"> / <script src="role/palette.js"> 加载。
 *
 * 零依赖：PNG 解码只用 Node 内置 zlib（解 IDAT）+ 手工反滤波。
 *   支持 8bit、非交错、颜色类型 0/2/3/4/6；其余情况明确报错，不静默出错。
 *
 * 用法（两种都行，脚本用 __dirname 定位目录，与当前工作目录无关）：
 *   在 game/rhythm/ 下：node gen_palette.js
 *   在 game/ 下：        node rhythm/gen_palette.js
 *
 * 中文输出：见 _term.js。若控制台代码页不是 UTF-8，会自动退化成 ASCII 文案，
 *   同时把完整中文报告写进 role/palette.log.txt（UTF-8，永远可读）。
 * ============================================================
 */
'use strict';

const fs = require('fs');
const path = require('path');
const zlib = require('zlib');
const term = require('./_term');

const ROLE_DIR = path.join(__dirname, 'role');
const OUT_FILE = path.join(ROLE_DIR, 'palette.js');
const SKINS_FILE = path.join(ROLE_DIR, 'skins.js');
const LOG_FILE = path.join(ROLE_DIR, 'palette.log.txt');

/* ============ 1. PNG 解码（仅用 zlib） ============ */
const CHANNELS = { 0: 1, 2: 3, 3: 1, 4: 2, 6: 4 };

function decodePng(buf) {
  if (buf.readUInt32BE(0) !== 0x89504e47) throw new Error('不是 PNG');

  let off = 8, ihdr = null;
  const idat = [];
  let plte = null;
  while (off < buf.length) {
    const len = buf.readUInt32BE(off);
    const type = buf.toString('ascii', off + 4, off + 8);
    const data = buf.subarray(off + 8, off + 8 + len);
    if (type === 'IHDR') {
      ihdr = {
        w: data.readUInt32BE(0), h: data.readUInt32BE(4),
        depth: data[8], colorType: data[9],
        compression: data[10], filter: data[11], interlace: data[12]
      };
    } else if (type === 'PLTE') {
      plte = Buffer.from(data);
    } else if (type === 'IDAT') {
      idat.push(Buffer.from(data));
    } else if (type === 'IEND') {
      break;
    }
    off += 12 + len;
  }
  if (!ihdr) throw new Error('缺少 IHDR');
  if (ihdr.depth !== 8) throw new Error('仅支持 8bit 位深，实际 ' + ihdr.depth);
  if (ihdr.interlace !== 0) throw new Error('不支持交错 PNG');
  if (!CHANNELS[ihdr.colorType]) throw new Error('不支持颜色类型 ' + ihdr.colorType);

  const raw = zlib.inflateSync(Buffer.concat(idat));
  const ch = CHANNELS[ihdr.colorType];
  const stride = ihdr.w * ch;
  const out = Buffer.alloc(ihdr.h * stride);

  // 反滤波（PNG spec 9.2）
  let pos = 0;
  for (let y = 0; y < ihdr.h; y++) {
    const ft = raw[pos++];
    const line = raw.subarray(pos, pos + stride);
    pos += stride;
    const cur = out.subarray(y * stride, (y + 1) * stride);
    const prev = y > 0 ? out.subarray((y - 1) * stride, y * stride) : null;
    for (let i = 0; i < stride; i++) {
      const a = i >= ch ? cur[i - ch] : 0;
      const b = prev ? prev[i] : 0;
      const c = (prev && i >= ch) ? prev[i - ch] : 0;
      let v = line[i];
      switch (ft) {
        case 0: break;
        case 1: v = (v + a) & 0xff; break;
        case 2: v = (v + b) & 0xff; break;
        case 3: v = (v + ((a + b) >> 1)) & 0xff; break;
        case 4: {
          const p = a + b - c;
          const pa = Math.abs(p - a), pb = Math.abs(p - b), pc = Math.abs(p - c);
          const pr = (pa <= pb && pa <= pc) ? a : (pb <= pc ? b : c);
          v = (v + pr) & 0xff;
          break;
        }
        default: throw new Error('未知滤波类型 ' + ft + ' @row ' + y);
      }
      cur[i] = v;
    }
  }

  // 统一输出 RGBA
  const rgba = new Uint8Array(ihdr.w * ihdr.h * 4);
  for (let i = 0, p = 0; i < ihdr.w * ihdr.h; i++, p += ch) {
    let r, g, b, a = 255;
    if (ihdr.colorType === 0) { r = g = b = out[p]; }
    else if (ihdr.colorType === 4) { r = g = b = out[p]; a = out[p + 1]; }
    else if (ihdr.colorType === 2) { r = out[p]; g = out[p + 1]; b = out[p + 2]; }
    else if (ihdr.colorType === 6) { r = out[p]; g = out[p + 1]; b = out[p + 2]; a = out[p + 3]; }
    else { // 3 = 调色板
      const idx = out[p] * 3;
      if (!plte || idx + 2 >= plte.length) { r = g = b = 0; }
      else { r = plte[idx]; g = plte[idx + 1]; b = plte[idx + 2]; }
    }
    rgba[i * 4] = r; rgba[i * 4 + 1] = g; rgba[i * 4 + 2] = b; rgba[i * 4 + 3] = a;
  }
  return { w: ihdr.w, h: ihdr.h, rgba };
}

/* ============ 2. 采样：跳过透明像素，均匀抽稀 ============ */
function samplePixels(img, maxSamples) {
  const { w, h, rgba } = img;
  const total = w * h;
  const step = Math.max(1, Math.floor(total / (maxSamples || 20000)));
  const out = [];
  for (let i = 0; i < total; i += step) {
    const a = rgba[i * 4 + 3];
    if (a < 128) continue;                       // 透明背景不算颜色
    out.push([rgba[i * 4], rgba[i * 4 + 1], rgba[i * 4 + 2]]);
  }
  return out;
}

/* ============ 3. k-means 取主色 ============ */
function dist2(a, b) {
  const dr = a[0] - b[0], dg = a[1] - b[1], db = a[2] - b[2];
  return dr * dr + dg * dg + db * db;
}

/* 用粗直方图的峰值做初始化，比随机初始化稳定得多（k-means 对初值敏感） */
function seedCentroids(px, k) {
  const bins = new Map();
  for (const p of px) {
    const key = ((p[0] >> 4) << 8) | ((p[1] >> 4) << 4) | (p[2] >> 4);
    let e = bins.get(key);
    if (!e) { e = { n: 0, r: 0, g: 0, b: 0 }; bins.set(key, e); }
    e.n++; e.r += p[0]; e.g += p[1]; e.b += p[2];
  }
  const list = [...bins.values()].map(e => ({ n: e.n, c: [e.r / e.n, e.g / e.n, e.b / e.n] }))
    .sort((a, b) => b.n - a.n);
  const seeds = [];
  for (const e of list) {
    if (seeds.length >= k) break;
    if (seeds.every(s => dist2(s, e.c) > 40 * 40)) seeds.push(e.c);
  }
  while (seeds.length < k && list.length) seeds.push(list[seeds.length % list.length].c);
  return seeds;
}

function kmeans(px, k, iters) {
  let cents = seedCentroids(px, k);
  const assign = new Int32Array(px.length);
  for (let it = 0; it < (iters || 12); it++) {
    let moved = 0;
    for (let i = 0; i < px.length; i++) {
      let best = 0, bd = Infinity;
      for (let c = 0; c < cents.length; c++) {
        const d = dist2(px[i], cents[c]);
        if (d < bd) { bd = d; best = c; }
      }
      if (assign[i] !== best) { assign[i] = best; moved++; }
    }
    const sum = cents.map(() => [0, 0, 0, 0]);
    for (let i = 0; i < px.length; i++) {
      const s = sum[assign[i]], p = px[i];
      s[0] += p[0]; s[1] += p[1]; s[2] += p[2]; s[3]++;
    }
    cents = cents.map((c, i) => sum[i][3]
      ? [sum[i][0] / sum[i][3], sum[i][1] / sum[i][3], sum[i][2] / sum[i][3]]
      : c);
    if (!moved) break;
  }
  const count = new Array(cents.length).fill(0);
  for (let i = 0; i < px.length; i++) count[assign[i]]++;
  return cents.map((c, i) => ({ c, n: count[i] / px.length }))
    .filter(e => e.n > 0)
    .sort((a, b) => b.n - a.n);
}

/* ============ 4. 颜色工具 ============ */
const clamp255 = v => Math.max(0, Math.min(255, Math.round(v)));

function rgb2hsl(r, g, b) {
  r /= 255; g /= 255; b /= 255;
  const mx = Math.max(r, g, b), mn = Math.min(r, g, b), d = mx - mn;
  let h = 0;
  if (d) {
    if (mx === r) h = ((g - b) / d) % 6;
    else if (mx === g) h = (b - r) / d + 2;
    else h = (r - g) / d + 4;
    h *= 60; if (h < 0) h += 360;
  }
  const l = (mx + mn) / 2;
  const s = d === 0 ? 0 : d / (1 - Math.abs(2 * l - 1));
  return [h, s, l];
}

function hsl2rgb(h, s, l) {
  s = Math.max(0, Math.min(1, s)); l = Math.max(0, Math.min(1, l));
  const c = (1 - Math.abs(2 * l - 1)) * s;
  const hp = ((h % 360) + 360) % 360 / 60;
  const x = c * (1 - Math.abs(hp % 2 - 1));
  let r = 0, g = 0, b = 0;
  if (hp < 1) { r = c; g = x; } else if (hp < 2) { r = x; g = c; }
  else if (hp < 3) { g = c; b = x; } else if (hp < 4) { g = x; b = c; }
  else if (hp < 5) { r = x; b = c; } else { r = c; b = x; }
  const m = l - c / 2;
  return [clamp255((r + m) * 255), clamp255((g + m) * 255), clamp255((b + m) * 255)];
}

function adjust(rgb, { sat = 1, light = 0 } = {}) {
  const [h, s, l] = rgb2hsl(rgb[0], rgb[1], rgb[2]);
  return hsl2rgb(h, s * sat, Math.max(0.08, Math.min(0.95, l + light)));
}

/**
 * 把相对亮度钳到 [min, max] 区间（保持色相/饱和度不变，只调明度）。
 * 为什么需要：图片里常有色相很好但极暗的颜色（furina 的 D.png 里的 #130f1d 近黑），
 * 直接拿来做粉末在深色背景上等于看不见。粉末是加亮的视觉元素，必须有亮度下限。
 */
function clampLum(rgb, min, max) {
  let [h, s, l] = rgb2hsl(rgb[0], rgb[1], rgb[2]);
  let out = rgb;
  for (let i = 0; i < 16; i++) {
    const y = lum(out);
    if (y >= min && y <= max) break;
    l += (y < min ? (min - y) : (max - y)) * 0.75;
    l = Math.max(0.05, Math.min(0.97, l));
    out = hsl2rgb(h, s, l);
  }
  return out;
}

const hex = rgb => '#' + rgb.map(v => clamp255(v).toString(16).padStart(2, '0')).join('');
const lum = rgb => (0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]) / 255;

/**
 * 从图片提取"关键色"：
 *   k-means 出 k 个簇 → 丢掉占比过小的 → 按明度方差去重 → 保证有亮色也有主色
 * 返回 { key: 主色, colors: 关键色数组 }
 */
function keyColors(file, k, keep) {
  const img = decodePng(fs.readFileSync(file));
  const px = samplePixels(img, 20000);
  if (!px.length) throw new Error(path.basename(file) + ' 没有不透明像素');
  const clusters = kmeans(px, k || 8, 14);

  const picked = [];
  for (const cl of clusters) {
    if (cl.n < 0.03) continue;                       // 占比 <3% 的杂色丢掉
    const c = cl.c.map(clamp255);
    if (picked.some(p => dist2(p, c) < 42 * 42)) continue;   // 去重
    picked.push(c);
    if (picked.length >= (keep || 6)) break;
  }
  if (!picked.length) picked.push(clusters[0].c.map(clamp255));

  /* 关键色排序：亮色在前（粉末要亮才看得见），并保证至少一个亮色 */
  picked.sort((a, b) => lum(b) - lum(a));
  const lums = picked.map(lum);
  if (Math.max(...lums) < 0.45) picked[0] = adjust(picked[0], { light: 0.45 - lums[0] });

  return {
    w: img.w, h: img.h,
    key: hex(picked[0]),
    colors: picked,
    coverage: clusters.slice(0, picked.length).reduce((s, c) => s + c.n, 0)
  };
}

/* ============ 5. 生成 role/palette.js + role/skins.js ============
   一次扫描产出两份文件，各管一件事：
     palette.js  只有颜色（window.RHYTHM_ROLE_PALETTE），供打碎粉末取色；
     skins.js    皮肤清单（window.RHYTHM_SKINS），供播放页右侧"皮肤栏"一一列出。
   为什么要拆成 SKINS 清单：以前换皮肤要手改 player.html 里的 4 处 url('role/<名>/...')，
   改了背景忘了改音符图就会"背景换了、音符还是旧的"。现在四张图 + 配色全登记在清单里，
   页面按清单统一套用，新增皮肤 = 丢一个文件夹 + 重跑本脚本，不用碰任何 HTML/CSS。 */
const ASSETS = { tap: 'D.png', head: 'R.png', trail: 'Trailing.png' };
const ASSET_FILE = Object.assign({ background: 'Background.png' }, ASSETS);

/** 可选的 role/<皮肤>/skin.json：{"name":"显示名","order":10}，都不填也能用（默认文件夹名 + 排最后） */
function readSkinMeta(dir) {
  const p = path.join(dir, 'skin.json');
  if (!fs.existsSync(p)) return {};
  try { return JSON.parse(fs.readFileSync(p, 'utf8')) || {}; }
  catch (e) { term.warn('skin.json 解析失败，按默认处理: ' + e.message, 'skin.json invalid, using defaults: ' + e.message); return {}; }
}

function buildRole(dir, name) {
  const res = {};
  const files = {};        // 槽位 → 磁盘上真实存在的文件名
  const missing = [];
  for (const [slot, file] of Object.entries(ASSET_FILE)) {
    const p = path.join(dir, file);
    if (!fs.existsSync(p)) { missing.push(file); continue; }
    files[slot] = file;
    if (slot === 'background') continue;          // 背景只登记路径，不参与抽色
    res[slot] = keyColors(p, 8, 6);
  }
  if (missing.length) {
    term.warn('  [' + name + '] 缺文件（不影响使用，会按可用素材降级）: ' + missing.join(', '),
              '  [' + name + '] missing (falls back gracefully): ' + missing.join(', '));
  }
  if (!res.tap && !res.head) throw new Error(name + '：至少需要 D.png 或 R.png');

  /* 命中粉末：保持图片原色相，提亮 + 略提饱和 → "被击碎时迸出的亮屑"
     未命中粉末：同色系去饱和 + 压暗但保底亮度 → "烧尽的灰"
     两者都钳亮度，避免近黑色粒子在深色轨道上看不见。 */
  function push(hitArr, missArr, c, isFirst) {
    const bright = clampLum(adjust(c, { sat: 1.14, light: isFirst ? 0.10 : 0.02 }), 0.46, 0.97);
    const ash = clampLum(adjust(c, { sat: 0.16 }), 0.34, 0.70);
    const hb = hex(bright), ha = hex(ash);
    if (!hitArr.includes(hb)) hitArr.push(hb);
    if (!missArr.includes(ha)) missArr.push(ha);
  }

  /* 短按音符号 = D.png 的图 → 粉末也用 D.png 的色 */
  const tapHit = [], tapMiss = [];
  (res.tap || res.head).colors.forEach((c, i) => push(tapHit, tapMiss, c, i === 0));

  /* 长按音符号 = R.png（头/尾）+ Trailing.png（拖尾）→ 粉末混合两者的色 */
  const holdHit = [], holdMiss = [];
  const holdSrc = [];
  if (res.head) holdSrc.push(...res.head.colors.slice(0, 4));
  if (res.trail) holdSrc.push(...res.trail.colors.slice(0, 3));
  holdSrc.forEach((c, i) => push(holdHit, holdMiss, c, i === 0));

  return {
    files: files,                     // 槽位 → 真实文件名（给 skins.js 用）
    palette: {
      tap: tapHit.slice(0, 6),
      tapMiss: tapMiss.slice(0, 4),
      hold: holdHit.slice(0, 6),
      holdMiss: holdMiss.slice(0, 4),
      key: (res.tap || res.head).key,
      _src: Object.fromEntries(Object.entries(res).map(([k, v]) => [k, v.w + 'x' + v.h]))
    }
  };
}

/**
 * 由"存在哪些文件"推导出该皮肤的四张图路径。
 *  - 短按图缺 D.png 时退回 R.png（音符至少看得见，而不是变成空白）
 *  - 长按头缺 R.png 时退回 D.png
 *  - 拖尾严格只用 Trailing.png（项目约定：不能拿别的图顶替），缺了就是没有
 * preview 用于右侧皮肤栏的缩略图：优先背景，其次短按图。
 */
function skinEntry(id, name, files, order) {
  const rel = f => 'role/' + id + '/' + f;
  const tapFile = files.tap || files.head;
  const headFile = files.head || files.tap;
  const trailFile = files.trail;
  const bgFile = files.background;
  return {
    id: id,
    name: name,
    order: order,
    background: bgFile ? rel(bgFile) : '',
    tap: tapFile ? rel(tapFile) : '',
    head: headFile ? rel(headFile) : '',
    trail: trailFile ? rel(trailFile) : '',
    palette: id,
    preview: rel(bgFile || tapFile || headFile)
  };
}

function main() {
  /* 脚本用 __dirname 定位，和当前工作目录无关；但如果运行器连工作目录都进不去，
     就会在 Node 启动前被 cmd 拦下，只留一句 GBK 的「系统找不到指定的路径。」
     —— 那不是本脚本的输出，本脚本一个字都没来得及打印。见文件末尾的 runHint()。 */
  if (!fs.existsSync(ROLE_DIR)) {
    term.err('找不到 role/ 目录：' + ROLE_DIR, 'role/ directory not found: ' + ROLE_DIR);
    runHint();
    return 1;
  }
  const roles = fs.readdirSync(ROLE_DIR, { withFileTypes: true })
    .filter(d => d.isDirectory()).map(d => d.name);

  if (!roles.length) {
    term.err('role/ 下没有角色子文件夹', 'no role sub-folders under role/');
    runHint();
    return 1;
  }

  const out = {};       // 皮肤 id → 配色（写进 palette.js）
  const skins = [];     // 皮肤清单（写进 skins.js，顺序即右侧皮肤栏顺序）
  const sorted = roles.slice().sort((a, b) => a.localeCompare(b, 'zh'));
  term.say('扫描 role/ 下的皮肤：' + sorted.join(', '),
           'scanning skins under role/: ' + sorted.join(', '));
  /* say() 自己会把中文版记进日志，这里不要再补一句 log()，否则日志同一行出现两次 */
  for (const name of sorted) {
    const r = buildRole(path.join(ROLE_DIR, name), name);
    out[name] = r.palette;
    const meta = readSkinMeta(path.join(ROLE_DIR, name));
    const display = (typeof meta.name === 'string' && meta.name.trim()) ? meta.name.trim() : name;
    const order = Number.isFinite(Number(meta.order)) ? Number(meta.order) : 999;
    skins.push(skinEntry(name, display, r.files, order));
    /* 色值本身是 ASCII，标签才需要挑语言；所以下面每行两种语言只差在标签上 */
    term.say('  [' + name + ']' + (display === name ? '' : ' → ' + display), '  [' + name + ']' + (display === name ? '' : ' → ' + display));
    term.say('    tap       ' + r.palette.tap.join(' '), '    tap       ' + r.palette.tap.join(' '));
    term.say('    tapMiss   ' + r.palette.tapMiss.join(' '), '    tapMiss   ' + r.palette.tapMiss.join(' '));
    term.say('    hold      ' + r.palette.hold.join(' '), '    hold      ' + r.palette.hold.join(' '));
    term.say('    holdMiss  ' + r.palette.holdMiss.join(' '), '    holdMiss  ' + r.palette.holdMiss.join(' '));
  }

  /* 皮肤栏顺序：skin.json 的 order 小的在前，其次按 id 排（稳定、可预期） */
  skins.sort((a, b) => (a.order - b.order) || a.id.localeCompare(b.id, 'zh'));
  const defId = skins.length ? skins[0].id : '';

  /* ---------- 体检 1：疑似"新旧两版叠加"造成的重复皮肤 ----------
     真实踩过的坑：旧版皮肤文件夹用中文名（role/芙宁娜），v2.16 起统一改成 ASCII
     （role/furina）并由 skin.json 提供中文显示名。Windows 解压**不会删除**已存在的
     旧文件夹 —— 把新包解压到旧包目录上，role/ 下就会新旧并存，于是皮肤栏出现 6 项、
     名字两两重复（用户报告的原话："有六个皮肤，实际上只有 3 个，剩下三个重复了"）。
     只警告不阻断：极小概率是"故意做了两套同名皮肤"，不该因此拒绝构建。 */
  const byDisplayName = {};
  skins.forEach((s) => { (byDisplayName[s.name] = byDisplayName[s.name] || []).push(s.id); });
  Object.keys(byDisplayName).forEach((nm) => {
    const ids = byDisplayName[nm];
    if (ids.length < 2) return;
    term.warn(
      `疑似重复皮肤：显示名「${nm}」对应 ${ids.length} 个文件夹 —— ${ids.join(' / ')}。` +
      `最常见的原因是把新版本解压到了旧版本目录上（Windows 解压不会删掉已有的旧文件夹），` +
      `新旧皮肤文件夹并存，皮肤栏就会多出重复项。` +
      `处理：删掉旧的那套皮肤文件夹（旧版是中文文件夹名），或重新解压到空目录，再重跑 build。`,
      `possible duplicate skins: the display name "${nm}" is shared by ${ids.length} folders ` +
      `(${ids.join(' / ')}). This usually means a new version was extracted over an old one; ` +
      `remove the stale skin folder(s) and rebuild.`
    );
  });

  /* ---------- 体检 2：皮肤 id（文件夹名）含非 ASCII ----------
     分发硬约束：zip 的 UTF-8 标志位会被 Windows 自带解压器忽略，含中文名的包解压后
     必然乱码，而 skins.js 记的是 UTF-8 路径 → 请求 404 → 皮肤全丢。
     显示名想用中文请写进 role/<id>/skin.json 的 name 字段。 */
  const nonAsciiIds = skins.map((s) => s.id).filter((id) => !/^[\x20-\x7E]+$/.test(id));
  if (nonAsciiIds.length) {
    term.warn(
      `皮肤文件夹名含非 ASCII 字符：${nonAsciiIds.join(', ')}。` +
      `这类名字在 Windows 自带解压器下会乱码（zip 的 UTF-8 标志位被忽略），` +
      `别人下载 zip 解压后会找不到图片。请把文件夹名改成纯英文，` +
      `中文显示名写进该文件夹的 skin.json（{"name":"显示名","order":10}）。`,
      `skin folder name(s) contain non-ASCII characters: ${nonAsciiIds.join(', ')}. ` +
      `They will be mojibake'd by Windows' built-in unzip (which ignores the zip UTF-8 flag), ` +
      `so downloaded copies will 404. Rename to plain ASCII and put the display name in skin.json.`
    );
  }

  /* palette.js —— 保持既有格式（单条赋值；测试按 "= " 与 ";" 切片解析，别改结构） */
  const js = '/* 自动生成，请勿手改 —— 由 gen_palette.js 从 role/<角色>/*.png 提取关键色。\n' +
    '   重新生成：node gen_palette.js\n' +
    '   为什么不用运行时 canvas 取样：file:// 下画布会被污染，getImageData 抛 SecurityError。 */\n' +
    'window.RHYTHM_ROLE_PALETTE = ' + JSON.stringify(out, null, 2) + ';\n';
  fs.writeFileSync(OUT_FILE, js, 'utf8');

  /* skins.js —— 皮肤清单。播放页读它把右侧皮肤栏一一列出，并按选中项一次性套用
     背景 + 短按图 + 长按头图 + 拖尾图 + 粉末配色。新增皮肤不用碰 player.html。 */
  const skinsJs =
    '/* 自动生成，请勿手改 —— 由 gen_palette.js 扫描 role/<皮肤>/ 生成。\n' +
    '   重新生成：node build.js（或 node gen_palette.js）\n' +
    '   新增皮肤：在 role/ 下新建文件夹，放 Background.png / D.png / R.png / Trailing.png，重跑即可。\n' +
    '   顺序即播放页右侧皮肤栏的顺序；可在 role/<皮肤>/skin.json 里写 {"name":"显示名","order":10}。 */\n' +
    'window.RHYTHM_SKINS = ' + JSON.stringify(skins, null, 2) + ';\n' +
    'window.RHYTHM_SKINS_DEFAULT = ' + JSON.stringify(defId) + ';\n';
  fs.writeFileSync(SKINS_FILE, skinsJs, 'utf8');

  const relOut = path.relative(path.join(__dirname, '..'), OUT_FILE);
  const relSkins = path.relative(path.join(__dirname, '..'), SKINS_FILE);
  term.say('写出 ' + relOut + '（' + Object.keys(out).length + ' 个皮肤的配色）',
           'wrote ' + relOut + ' (' + Object.keys(out).length + ' palette(s))');
  term.say('写出 ' + relSkins + '（皮肤栏顺序：' + skins.map(s => s.name).join(' → ') + '）',
           'wrote ' + relSkins + ' (skin bar order: ' + skins.map(s => s.id).join(' -> ') + ')');
  term.say('提示：新增皮肤 = 在 role/ 下新建文件夹放 Background.png / D.png / R.png / Trailing.png，' +
           '再跑一次 node build.js；播放页右侧皮肤栏会自动列出。',
           'tip: to add a skin, drop a folder under role/ with Background/D/R/Trailing.png and rerun node build.js.');

  /* 日志补充：控制台不显示的源图信息 + 环境说明。
     这几行始终写中文 —— 日志是事后排查用的，不受控制台语言影响。 */
  term.log('');
  term.log('环境：' + term.describe());
  term.log('默认皮肤：' + (defId || '(无)'));
  for (const [name, r] of Object.entries(out)) {
    term.log(name + '  源图尺寸 ' + JSON.stringify(r._src));
  }
  if (term.flush(LOG_FILE)) {
    term.say('（完整中文报告已写入 ' + path.basename(LOG_FILE) + '，控制台乱码时看它）',
             '(full report written to ' + path.basename(LOG_FILE) + ')');
  }
  return 0;
}

/** 打印"怎么把它跑起来"，专门针对 Windows 中文/空格路径下的运行器问题 */
function runHint() {
  /* 控制台上也给一句，否则失败时用户只能从日志里找原因 */
  term.note('提示：那句「系统找不到指定的路径。」是 cmd 报的，发生在 Node 启动之前。' +
            '请在 game/ 目录下执行 node rhythm/gen_palette.js',
            'hint: that "path not found" line came from cmd before Node started. ' +
            'Run: node rhythm/gen_palette.js from game/');
  term.log('');
  term.log('【若控制台只显示「系统找不到指定的路径。」】');
  term.log('  那句是 cmd 报的，发生在 Node 启动之前 —— 本脚本一个字都没打印。');
  term.log('  原因是运行器进不去配置的工作目录（编辑器"运行"按钮在含空格/中文的路径上常见）。');
  term.log('  可靠做法：打开集成终端，在 game/ 目录下执行  node rhythm/gen_palette.js');
  term.log('  本脚本用 __dirname 定位目录，从任何工作目录运行都能找到 role/。');
}

if (require.main === module) {
  let code = 0;
  try {
    code = main() || 0;
  } catch (e) {
    term.err('失败：' + (e && e.message), 'failed: ' + (e && e.message));
    runHint();
    code = 1;
  }
  term.flush(LOG_FILE);
  process.exitCode = code;
}

module.exports = {
  decodePng, samplePixels, kmeans, keyColors, rgb2hsl, hsl2rgb, adjust, clampLum,
  skinEntry, readSkinMeta, ASSET_FILE
};
