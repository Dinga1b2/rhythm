/* 自动生成，请勿手改 —— 由 gen_palette.js 扫描 role/<皮肤>/ 生成。
   重新生成：node build.js（或 node gen_palette.js）
   新增皮肤：在 role/ 下新建文件夹，放 Background.png / D.png / R.png / Trailing.png，重跑即可。
   顺序即播放页右侧皮肤栏的顺序；可在 role/<皮肤>/skin.json 里写 {"name":"显示名","order":10}。 */
window.RHYTHM_SKINS = [
  {
    "id": "furina",
    "name": "芙宁娜",
    "order": 10,
    "background": "role/furina/Background.png",
    "tap": "role/furina/D.png",
    "head": "role/furina/R.png",
    "trail": "role/furina/Trailing.png",
    "palette": "furina",
    "preview": "role/furina/Background.png"
  },
  {
    "id": "firefly",
    "name": "流萤",
    "order": 20,
    "background": "role/firefly/Background.png",
    "tap": "role/firefly/D.png",
    "head": "role/firefly/R.png",
    "trail": "role/firefly/Trailing.png",
    "palette": "firefly",
    "preview": "role/firefly/Background.png"
  },
  {
    "id": "miyabi",
    "name": "星见雅",
    "order": 30,
    "background": "role/miyabi/Background.png",
    "tap": "role/miyabi/D.png",
    "head": "role/miyabi/R.png",
    "trail": "role/miyabi/Trailing.png",
    "palette": "miyabi",
    "preview": "role/miyabi/Background.png"
  }
];
window.RHYTHM_SKINS_DEFAULT = "furina";
