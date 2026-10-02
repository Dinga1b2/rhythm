# 音游 · 六键下落式

一个**纯前端**的六键下落式音游：HTML + CSS + 原生 JavaScript，**没有任何依赖、没有构建步骤**。
下载解压后**双击 `index.html` 就能玩**，不需要装 Node、Python 或任何东西。

---

## 最快开始（3 步）

1. 双击 **`index.html`** —— 进入选曲页
2. 点任意一首曲子 —— 会在**新标签页**打开游玩页
3. 点「开始（3 秒后歌曲响起）」—— 3 秒准备期后音乐出声，音符开始下落

> **没有 `build.js` / `build.cmd` / Python 也完全能玩。** 曲库清单（`music/charts.js`）、
> 配色（`role/palette.js`）、皮肤清单（`role/skins.js`）和谱面都**已经包含在仓库里**，
> 双击即用。构建脚本只在你**自己新增曲目或皮肤**时才需要。

### 玩法

| 操作 | 说明 |
|---|---|
| `S` `D` `F` `J` `K` `L` | 六条轨道，音符落到判定线时按下 |
| 短按音符（圆形） | 按一下即可 |
| 长按音符（长条） | **按住直到尾巴结束**再松开；头尾分别判定 |
| `Esc` | 暂停 / 从结算页返回选曲 |
| 右侧皮肤栏 | 点一下即换皮肤（背景 + 音符图 + 配色一起换） |

满分 1,000,000；评级 SS / S / A / B / C / D。每首曲子的最高分会记在浏览器本地。

### 环境要求

任何现代浏览器（Edge / Chrome / Firefox）都行，**直接双击 `index.html` 以 `file://` 打开即可**。
项目刻意避开了 `file://` 下受限的能力（不用 `fetch` 读数据、不用 canvas 读像素），
所以**不需要起本地服务器**。

---

## 目录结构

```
index.html            选曲页（入口，双击这个）
player.html           游玩页（由选曲页自动打开）
chart.js              谱面解析器
build.js              一键打包脚本（可选，需要 Node）
build.cmd             Windows 双击版一键构建（可选）
gen_songs.js          曲目 → music/charts.js
gen_palette.js        皮肤 → role/palette.js + role/skins.js
_term.js              终端中文编码防护
detect_offset.py      工具：测音频开头静音时长（可选）

music/
  charts.js           ★ 曲库清单（运行时必需，由 gen_songs.js 生成）
  Sheet Music Maker.py  谱面自动生成器（可选，需要 Python + librosa）
  Da_Capo/            每首曲子一个文件夹
    Da_Capo.mp3         音频
    Da_Capo.txt         谱面（纯文本）
  Only_By_Chasing_the_Wind/
  qinglian/

role/                 皮肤，每套一个文件夹
  furina/   Background.png  D.png(短按)  R.png(长按)  Trailing.png(拖尾)
            skin.json    ← 可选：中文显示名 / 排序，如 {"name":"芙宁娜","order":10}
  firefly/  （同上，显示名「流萤」）
  miyabi/   （同上，显示名「星见雅」）
  palette.js          ★ 配色（运行时必需）
  skins.js            ★ 皮肤清单（运行时必需）
```

★ 标记的三个文件是**运行时真正读取的数据**，删掉游戏会打不开。它们看起来像"构建产物"，但**必须留在仓库里**。

> **文件夹名（皮肤 id）一律用纯 ASCII，中文只写在 `skin.json` 里。**
> 原因是 zip 的文件名编码：zip 用「通用位标志第 11 位」标记文件名是否为 UTF-8，而
> **Windows 自带的解压器会忽略这个标志**，一律按系统代码页（简中 = GBK）解码 ——
> GitHub 在 Linux 上打的包，只要含中文文件名，到 Windows 解压出来必然乱码。
> 而 `skins.js` / `charts.js` 里记录的是 UTF-8 路径，浏览器一请求就是 404：
> 皮肤全丢、音乐不响。全部改成 ASCII 之后，任何解压工具都不会再乱码。

---

## 自己新增曲目 / 皮肤（这一步才是可选的）

### 新增一首曲子

1. 在 `music/` 下新建文件夹，**文件夹名就是曲名**，例如 `music/MySong/`
2. 放一个 `.mp3` 进去（**不需要自己写谱面**）
3. 生成谱面并重新打包：

| 你的系统 | 怎么做 |
|---|---|
| Windows | 双击 **`build.cmd`**（自动补谱面 + 重打包，打一次命令就够） |
| macOS / Linux | 先装 Python 3 与 Node，然后 `cd rhythm && python "music/Sheet Music Maker.py" --missing && node build.js` |

已有的曲目和皮肤**完全不会被改动**。

### 新增一套皮肤

在 `role/` 下新建文件夹（**文件夹名即皮肤 id，必须纯 ASCII**，例如 `myhero`），
放四张 png（缺图不会报错，会自动降级）：

| 文件 | 用途 | 必须 |
|---|---|---|
| `Background.png` | 游玩页背景 | 可缺（退化为纯色） |
| `D.png` | 短按音符图 | 可缺（借用 R.png） |
| `R.png` | 长按音符头/尾图 | 可缺（借用 D.png） |
| `Trailing.png` | 长按拖尾图 | 可缺 |

中文显示名和排序写在同目录的 `skin.json` 里（`name` 可以随便用中文）：

```json
{ "name": "我的角色", "order": 10 }
```

`order` 越小越靠前；不写则排在最后。然后跑一次 `node build.js`（或双击 `build.cmd`）。

---

## 常见问题

**Q：我直接双击了压缩包预览里的 `build.cmd`，报 `can't open file ... [Errno 2]`？**
A：压缩包预览窗口（以及下载管理器、聊天软件的附件预览）**只会把那一个文件**解压到临时目录再运行，
项目其他文件不在旁边，所以必然失败。
→ **先把压缩包完整解压**（右键 → 全部解压 / Extract All），再进解压出的文件夹里双击。
`build.cmd` 现在也会检测这种情况并直接告诉你该怎么做。

**Q：解压后中文文件名/文件夹名变成乱码，皮肤或音乐加载不出来？**
A：某些解压工具对 zip 里的中文名处理不当。请改用 **7-Zip**、**Bandizip** 或
**Windows 自带的"全部解压"**（而不是第三方压缩软件的"快速查看"）。GitHub Code 按钮下载的
zip 同理。

**Q：我没有 Node / Python，能用吗？**
A：**能。** 直接双击 `index.html`。构建脚本只有你想自己加曲子/皮肤时才需要。

**Q：music 下的 `.txt` 谱面文件是干什么的？**
A：谱面的**纯文本源文件**。运行时实际读的是 `music/charts.js`（已把谱面内嵌进去），
`.txt` 用于重新生成时的比对与增量更新（`--missing`）。

**Q：皮肤换了但没变化？**
A：点一下右侧皮肤栏里的缩略图即可，不需要刷新。选择会记在浏览器本地，下次自动沿用。

---

## 关于音频素材

`music/*/` 下的音频仅用于本地游玩演示，**版权归原作者所有**，请勿再分发或商用。
