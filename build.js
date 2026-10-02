#!/usr/bin/env node
/**
 * ============================================================
 * build.js —— 音游一键构建（曲库 + 皮肤）
 *
 * 作用：把"新增曲目 / 新增皮肤"的本地操作收敛成**一条命令**。
 *   第 1 步 gen_songs.js   扫描 music/<曲目>/  →  music/charts.js
 *   第 2 步 gen_palette.js 扫描 role/<皮肤>/   →  role/skins.js + role/palette.js
 *
 * 新增曲目（一首一个文件夹）：
 *   1) 在 music/ 下新建文件夹，名字就是曲名，例如 music/MySong/
 *   2) 放一个 .mp3 进去（**不需要**自己准备谱面）
 *   3) node build.js      （在 game/ 下则 node rhythm/build.js）
 *   ★ 谱面由谁生成：build.cmd（Windows 双击）会先调 Sheet Music Maker.py --missing
 *     把"有音频但没谱面"的曲目补齐，再跑本脚本。直接跑 node build.js 只打包不补谱面，
 *     所以纯命令行用户要自己先跑一次那个 Python 脚本。
 *
 * 新增皮肤（一套一个文件夹，可多套，播放页右侧皮肤栏会一一列出）：
 *   1) 在 role/ 下新建文件夹，名字就是皮肤名，例如 role/芙宁娜/
 *   2) 放 png：Background.png / D.png / R.png / Trailing.png
 *      （缺图不报错：没背景就纯色底，没 D.png 借用 R.png，拖尾严格只用 Trailing.png）
 *   3) node build.js
 *
 * 用法（脚本用 __dirname 定位，与当前工作目录无关）：
 *   在 game/rhythm/ 下：node build.js
 *   在 game/ 下：        node rhythm/build.js
 *   Windows 一键（推荐）：双击 game/rhythm/build.cmd —— 它会先补缺失的谱面再调本脚本。
 *
 * 为什么拆成子进程跑：两个打包器各自负责自己的失败提示、ASCII 降级与日志文件，
 *   这里只负责"按时序跑完 + 汇总"。任一步失败立刻停下并指出是哪一步。
 *   完整报告在 music/charts.log.txt 与 role/palette.log.txt（UTF-8，永远可读）。
 * ============================================================
 */
'use strict';
const path = require('path');
const { spawnSync } = require('child_process');
const term = require('./_term');

const STEPS = [
  { file: 'gen_songs.js',   what: '曲库　music/<曲目>/ → music/charts.js' },
  { file: 'gen_palette.js', what: '皮肤　role/<皮肤>/ → role/skins.js + role/palette.js' }
];

function main() {
  term.say('音游一键构建：共 ' + STEPS.length + ' 步', 'rhythm build: ' + STEPS.length + ' step(s)');
  const done = [];
  let failed = null;

  for (const step of STEPS) {
    term.say('', '');
    term.say('▶ ' + step.what, '> ' + step.what);
    const r = spawnSync(process.execPath, [path.join(__dirname, step.file)], { stdio: 'inherit' });
    const code = r.status == null ? 1 : r.status;      // status=null ⇒ 被信号杀掉
    if (code !== 0) {
      failed = { file: step.file, code };
      term.err('✖ ' + step.file + ' 失败（退出码 ' + code + '）', 'x ' + step.file + ' failed (exit ' + code + ')');
      break;
    }
    done.push(step.file);
  }

  term.say('', '');
  if (failed) {
    term.say('构建中断：' + (done.length ? '已完成 ' + done.join('、') + '；' : '') +
             failed.file + ' 未完成。修复后重跑本命令即可（已生成的产物会被重新生成，无副作用）。',
             'build stopped at ' + failed.file + '. Fix and rerun; regenerating is idempotent.');
    return 1;
  }
  term.say('全部完成。刷新播放页即可看到新增的曲目 / 皮肤（皮肤栏在页面右侧）。',
           'all done. reload the player to see new songs / skins (skin bar on the right).');
  return 0;
}

if (require.main === module) {
  let code = 0;
  try { code = main() || 0; }
  catch (e) {
    term.err('失败：' + (e && e.message), 'failed: ' + (e && e.message));
    code = 1;
  }
  process.exitCode = code;
}

module.exports = { STEPS, main };
