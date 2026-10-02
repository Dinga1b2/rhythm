'use strict';
/**
 * ============================================================
 * _term.js —— 终端输出小工具（Windows 中文乱码防护）
 *
 * 背景：Windows 控制台默认代码页是 936(GBK)，而 Node 永远按 UTF-8 输出字节。
 *   两者不一致时中文必然花屏。最经典的例子：
 *     cmd 的「系统找不到指定的路径。」(GBK)
 *     被按 UTF-8 解码后显示成「ϵͳ�Ҳ���ָ����·����」
 *   —— 这不是脚本的输出，是 cmd 自己的报错，但读起来完全没法看。
 *
 * 策略（三层，任何一层都能保证信息可读）：
 *   1) 尽量把控制台切到 UTF-8(65001)。chcp 子进程与父进程共用同一个控制台，
 *      所以它改的是父控制台的代码页，对后续输出生效。
 *   2) 切不动、且输出是真正的终端（TTY）时，说明终端一定按 GBK 解释字节，
 *      中文必花 —— 这时退化成纯 ASCII：选中/英分支，再把残留的非 ASCII 字符
 *      转成 \uXXXX 转义（英文文案里也会插进中文，比如角色名来自文件夹名）。
 *      管道（非 TTY）时不退化：上层运行面板基本都按 UTF-8 解码，中文能正常显示。
 *   3) 无论哪种情况，都把完整中文报告写进 UTF-8 日志文件 —— 日志永远可读。
 *
 * 用法：
 *   const term = require('./_term');
 *   term.say('扫描 role/ 下的角色', 'scanning roles in role/');   // 控制台按环境选语言
 *   term.log('只进日志、不打印的行');                            // 追加到日志
 *   term.flush(LOG_FILE);                                        // 落盘
 *
 * 约定：say() 的控制台文案随环境变（中文/英文/转义），但**写进日志的永远是中文原文**。
 *   这样日志是一份不随控制台代码页变化的完整中文报告，事后排查不用猜当时显示的是哪种语言。
 *   不要在 say() 之后再补一句内容相同的 log() —— 那会在日志里出现两遍。
 *
 * 调试开关：RHYTHM_TERM_LANG=ascii|utf8 可强制指定控制台语言，绕过自动探测。
 * ============================================================
 */
const fs = require('fs');
const { execSync } = require('child_process');

function readCodePage() {
  try {
    /* chcp 的输出用 latin1 读：中文标签会变成乱码字符，但数字是 ASCII，一定读得对 */
    const out = String(execSync('chcp', { encoding: 'latin1', stdio: ['ignore', 'pipe', 'ignore'] }));
    const m = /(\d{3,5})/.exec(out);
    return m ? parseInt(m[1], 10) : NaN;
  } catch (e) { return NaN; }
}

function tryChcp65001() {
  try { execSync('chcp 65001', { stdio: ['ignore', 'ignore', 'ignore'] }); return true; }
  catch (e) { return false; }
}

/**
 * 决定用中文还是 ASCII 输出。依赖全部可注入，便于测试四象限：
 *   非 Windows                                   → utf8（不管代码页）
 *   Windows + 已经是 65001                       → utf8
 *   Windows + 切到 65001 成功                    → utf8
 *   Windows + 切不动 + 真终端(TTY)               → ASCII（终端铁定按 GBK 解字节，中文必花）
 *   Windows + 切不动 + 管道(非 TTY)              → utf8（上层面板基本按 UTF-8 解码）
 */
function detect(opts) {
  const o = opts || {};
  const readCp = o.readCodePage || readCodePage;
  const chcp = o.tryChcp || tryChcp65001;
  const platform = o.platform || process.platform;
  const tty = o.tty != null ? !!o.tty : !!process.stdout.isTTY;

  if (platform !== 'win32') return { utf8: true, cp: 'utf-8', tty: tty, switched: false };

  const before = readCp();
  if (before === 65001) return { utf8: true, cp: before, tty: tty, switched: false };

  chcp();
  const after = readCp();
  if (after === 65001) return { utf8: true, cp: after, tty: tty, switched: true };

  return { utf8: !tty, cp: after || before, tty: tty, switched: false };
}

/**
 * 控制台只能吃 ASCII 时，把非 ASCII 字符转成 \uXXXX 转义。
 * 为什么需要：英文文案里也会插进中文，比如皮肤显示名来自 role/<id>/skin.json，
 *   say('  [furina] → 芙宁娜', '  [furina] → 芙宁娜') 两边的字面量都是中文。
 *   只挑"英文分支"挡不住它。
 *   转义后既不丢信息（日志里仍是原文），又保证输出里一个高位字节都没有。
 */
function toAscii(s) {
  return String(s).replace(/[^\x00-\x7F]/g, (c) => {
    const cp = c.codePointAt(0);
    if (cp > 0xFFFF) {                       // 星形/表情等是代理对，展开成两个转义
      const v = cp - 0x10000;
      return '\\u' + (0xD800 + (v >> 10)).toString(16).toUpperCase().padStart(4, '0') +
             '\\u' + (0xDC00 + (v & 0x3FF)).toString(16).toUpperCase().padStart(4, '0');
    }
    return '\\u' + cp.toString(16).toUpperCase().padStart(4, '0');
  });
}

/* 手动覆盖，方便在切不动代码页的机器上强制试英文输出 */
const FORCE = process.env.RHYTHM_TERM_LANG;
const env = FORCE === 'ascii' ? { utf8: false, cp: 'forced-ascii', tty: false, switched: false }
  : FORCE === 'utf8' ? { utf8: true, cp: 'forced-utf8', tty: false, switched: false }
    : detect();
const buffer = [];

/**
 * 打印一行：控制台按当前环境选中/英，日志里恒定记中文原文。
 * 非 UTF-8 环境下再做一次 ASCII 兜底，保证控制台输出纯 ASCII。
 * 返回实际打印出去的字符串（测试用）。
 */
function say(zh, en) {
  let line = env.utf8 ? zh : (en == null ? zh : en);
  if (!env.utf8) line = toAscii(line);
  buffer.push(zh);
  console.log(line);
  return line;
}

function note(zh, en) { return say(zh, en); }
function warn(zh, en) { return say('[warn] ' + zh, '[warn] ' + en); }
function err(zh, en) { return say('[err] ' + zh, '[err] ' + en); }

/** 只写进日志、不打印（给完整中文报告用） */
function log(zh) { buffer.push(zh); }

function flush(file) {
  try {
    fs.writeFileSync(file, buffer.join('\n') + '\n', 'utf8');
    return true;
  } catch (e) { return false; }
}

function describe() {
  return 'console: cp=' + env.cp + ' tty=' + env.tty +
    ' utf8=' + env.utf8 + (env.switched ? ' (switched to 65001)' : '');
}

module.exports = { env, describe, say, note, warn, err, log, flush, detect, readCodePage, toAscii };
