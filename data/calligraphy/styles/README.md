# 行书 / 草书 / 隶书 / 篆书 毛笔轨迹库（2026-10-25）

与 `../glyphs.sqlite`（楷书）格式相同（`brush-glyphs-v1`，50 单位字格，X 向右、Y 向下，关键帧 `[x, y, 提按 0–1, 速度比例]`），由 `tools/build_style_glyphs.py` 生成。手机「毛笔写字」页可选书体；楷书仍为默认，旧的楷书预览、规划和修订号不变。

| 文件 | 书体 | 字体来源 | 收录 |
|---|---|---|---:|
| `li.sqlite` | 隶书 | Windows 隶书 SimLi（系统字体，仅本机自用） | 2287 |
| `xing.sqlite` | 行书 | 志莽行书 Zhi Mang Xing（SIL OFL 1.1） | 1412 |
| `zhuan.sqlite` | 篆书 | 中研院崇羲篆體（公开免费使用，禁止修改字体本身；简→繁用 OpenCC STCharacters/TWVariants，Apache-2.0） | 877 |
| `cao.sqlite` | 草书 | 刘建毛草 Liu Jian Mao Cao（SIL OFL 1.1） | 473 |

收录数少于 3500 是有意的：只收“每一个标准笔画都能在该字体上一笔对一笔描出来”的字。做不到的字不收，手机上会提示该书体未收录，而不会用错误笔顺去写。未收录原因列在各库 manifest 的 `rejected` 字段。字体文件本身不随库分发：OFL 字体在 `../../../../fonts_ofl/`，篆书字体与 OpenCC 表在 `../../../../fonts_seal_dl/`。

## 生成方法（2026-10-25 第二版：一笔一画、标准笔顺）

1. 用字体渲染字形（256 px 字格），平滑后 Zhang-Suen 细化成骨架。
2. 笔顺、笔画数和每笔方向取自 Make Me a Hanzi：简体字用楷书库，篆书的繁体字形优先用 Make Me a Hanzi 中该繁体字自己的笔顺（覆盖 1129 字）。把这些标准笔画中线非刚性配准到目标骨架上。
3. **每个标准笔画 = 一次落笔**：在骨架上找从该笔起点到终点、最贴近该笔的路径（交叉处直接穿过，不会在交叉点被拆开），起止端在墨迹内沿原笔方向补全笔尖。顺序和方向与标准笔顺一致。
4. 骨架上还没写到的部分：挨着某一笔端点的并入那一笔（笔尖、钩），独立的才作为该书体自有的笔画，排在离它最近的标准笔画之后，按从左到右、从上到下书写。
5. 校验（任一项不通过则整字不收）：每笔都在墨迹内；每笔长度与对应标准笔画相当（0.4～2.5 倍，防止一笔“搭”到相邻笔画上导致笔顺错乱）；两笔不得描同一条线；墨迹覆盖率 ≥ 0.85。
6. 提按按该处字体笔画半宽换算，起笔、收笔为 0；速度比例随提按减小。

## 重建

```
python tools/build_style_glyphs.py --style cao --font ../fonts_ofl/LiuJianMaoCao-Regular.ttf --font-label "刘建毛草 Liu Jian Mao Cao" --font-license "SIL Open Font License 1.1"
python tools/build_style_glyphs.py --style zhuan --font ../fonts_seal_dl/chongxi_seal.otf --st-table ../fonts_seal_dl/STCharacters.txt --variants ../fonts_seal_dl/TWVariants.txt --font-label "崇羲篆體（中央研究院）" --font-license "..."
```

每次重建版本号随内容变化，手机端需重新预览。结构检查与离线规划已通过；实际毛笔墨迹效果尚未实写验证。
