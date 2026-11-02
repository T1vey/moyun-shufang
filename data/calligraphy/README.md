# 常用 3500 字毛笔轨迹库

`glyphs.sqlite` 为运行时只读库；`glyphs.jsonl` 为可编辑来源；`常用3500字.txt` 是当前收录清单。`常用300字.txt` 保留为首版清单，用于兼容性核查。

当前包含《通用规范汉字表》（2013）一级字表全部 3500 字、33,959 笔。两份公开字表逐字、逐序交叉核对一致，来源与 SHA256 见 `sources/repertoire-provenance.json`。原 300 字的轨迹、压力和速度关键帧完全保留。

保留 Make Me a Hanzi 的原始逐笔顺序和方向，按 50 单位、X 向右/Y 向下保存几何。提按使用项目已有毛笔模块包络。结构检查不等于已经逐字人工审校笔顺或逐字实写；实际七轴轨迹仍需运行时预检。完整说明见 `../../docs/3500字库扩展_使用与验证_20261022.md`。

SQLite 约 26.4 MiB，按字读取，LRU 最多缓存 128 个字，不全量加载轨迹。40～70 mm 字号、200 字符输入限制及当前纸面标定保持不变。扩库不代表已实现 500 mm 单纸功能。

版权和许可：原始字体 © 1999 Arphic Technology，数据来自 https://github.com/skishore/makemeahanzi，经现有资料中的 graphics.txt 导入。2026-10-22 修改：选取 3500 字、转换坐标、补充毛笔动作关键帧、生成 SQLite。派生字形数据使用 Arphic Public License，见 `APL-English.txt`、`COPYING.makemeahanzi`；无担保。独立编写的应用代码与字形数据分开保存。
