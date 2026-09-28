# course-asset-pipeline

**把一批视频课程，变成一套可校验、可去重、可检索的本地知识库。**

下载器解决的是「文件有没有到手」。这个工具解决的是后面那些问题：文件是不是真的完整？哪些集其实是同一讲的两个上传版本？哪些内容根本不用看？转成文字之后怎么用？

---

## 为什么需要它

批量下载一门 100 集的课程，你会在四个地方卡住，而且**每一个都不会报错**：

| 现象 | 为什么朴素检查抓不到 |
|:--|:--|
| 文件存在、体积正常，但放不出来 | 字节数看起来完全合理（几 MB 到几十 MB），坏的是容器头。只有打开容器才知道 |
| 下完 90 集，课程其实有 104 集 | 「文件在不在」这种检查不会告诉你少了什么 |
| 同一讲存在两个上传版本 | 两个版本的**标题措辞完全不同**，字符串比对匹配不上 |
| 分不清哪一集是什么 | 下载器有时把整门课的标题填进每个文件，N 个文件只差一个序号 |

这个工具把上述四件事变成四步可重复的操作，并且在每一步都留下可回滚的证据。

---

## 流水线

```
情报层（Node，纯接口，秒级）
  cli/bili.mjs search   关键词找课程
  cli/bili.mjs survey   分P大纲 + 互动数据  ──→ survey.json
  cli/bili.mjs score    质量评分与排名
  cli/bili.mjs subs     字幕可用性探测

内容层（Python）
  yt-dlp               音频下载（外部依赖，见下）
  cap normalize        文件名规范化：还原分P标题、全角字符、超长截断
  cap verify           三重校验：数量对账 + 时长探测 + SHA-256 留档
  cap redownload       只重下校验失败的，不重跑整批

整理层
  cap classify         分类归并：重复 / 旧版 / 不选 / 非教学
  cap fingerprint      音频级比对，验证「同讲多版本」
  cap quarantine       移入隔离区（移动而非删除），可一键还原

产出层
  cap transcribe       语音转写（可选依赖）
  cap notes            转写 → 带时间戳的 Markdown
```

---

## 快速开始

```bash
git clone https://github.com/wpc725562-dotcom/course-asset-pipeline
cd course-asset-pipeline
pip install -e ".[dev]"          # 核心依赖：numpy, av

# 1) 盘点课程结构，拿到分P标题（后面规范化要用）
node cli/bili.mjs survey BV1Aa4y1B7cD --parts --json > survey.json

# 2) 下载音频（外部工具）
python -m yt_dlp -f bestaudio \
  -o "library/01_cs/BV1Aa4y1B7cD_ds/%(autonumber)03d_%(title)s.%(ext)s" \
  --no-overwrites --windows-filenames --trim-filenames 80 \
  --sleep-requests 0.6 --retries 5 --ignore-errors \
  "https://www.bilibili.com/video/BV1Aa4y1B7cD"

# 3) 规范化文件名（默认 dry-run，确认后再 --apply）
cap normalize library --parts survey.json
cap normalize library --parts survey.json --apply --map rename_map.json

# 4) 校验
cap verify library --expect survey.json

# 5) 只重下校验失败的文件
cap redownload library/_manifest/manifest.json --root library
cap verify library --expect survey.json      # 复查，直到 abnormal 归零

# 6) 整理
cap classify survey.json library --out classify.json
cap quarantine classify.json --root library            # 预览
cap quarantine classify.json --root library --apply    # 执行

# 7) 还原（任何时候都可以）
cap restore library/_quarantine
```

转写需要额外依赖：

```bash
pip install -e ".[asr]"          # faster-whisper
cap transcribe library/01_cs/BV1Aa4y1B7cD_ds transcripts --model medium
cap notes transcripts/001_xxx.json notes/001.md --title "Lecture 1"
```

---

## 三个值得说的设计点

### 1. 校验必须是三层，因为只有一层能抓到真正的坏文件

「文件在不在」和「字节数是不是 0」这类检查，在批量下载里几乎抓不到东西。实际会发生的故障是：**文件体积完全正常，内容是随机字节**。

```
正常文件头 : 0000 0024 6674 7970 6973 6f6d   ....ftypisom  (合法 MP4)
损坏文件头 : 650c d2ee 1697 10e3 ad4e 3251   随机字节，不是任何已知容器
```

在损坏文件里搜 `ftyp` / `moov`（MP4 必需的原子），**从头到尾一个都找不到** —— 所以它不是「下了一半的 MP4」，而是内容压根不是目标音频。

只有打开容器头做时长探测才能发现。所以 `cap verify` 跑三层：数量对账、时长探测、SHA-256 留档。

> 结论：**批量下载后一定要跑一次时长探测。** 只做数量校验的话，这批文件会被当成 100% 成功交付，而它们一个都放不出来。

### 2. 「同讲多版本」不能靠标题比对，要做音频级验证

同一个讲的两份上传，标题可能长得完全不像：

```
P1   第一章 行列式 一、行列式的概念+二、行列式的性质     [63 min]
P14  【字幕版】第一章 行列式一、二-全                    [63 min]
```

所以 `cap fingerprint` 比对的是**音频本身**：在时长中点取窗口 → 解码单声道 PCM → 算 20ms 粒度的 RMS 能量包络 → 归一化互相关。

两个参数决定成败，两个都踩过坑：

| 参数 | 取值 | 踩过的坑 |
|:--|:--|:--|
| 分析窗 | **90 秒** | 40 秒窗的包络区分度不足，不同语音段之间也会出现 0.2–0.3 的偶然相关 |
| 对齐搜索窗 | **±25 秒** | 两版时长差 14 秒时，中点处偏移约 7 秒。搜索窗只给 ±3 秒，**同一录音会被判成「不相关」（实测 0.2457）** |

**必须同时跑负对照**（同一门课的另一讲，应当不相关）才能校准阈值。放宽参数后的实测分布：

| 比对 | 相关系数 | 判定 |
|:--|:--|:--|
| 同一讲的两个上传版本 | **0.9983** | 同一录音 |
| 不同讲（负对照） | **0.1948** | 不相关 |

`tests/test_fingerprint.py` 把这两个参数固化成了回归测试：如果有人把搜索窗「优化」回窄窗口，测试会直接失败。

### 3. 整理只做标注，剔除只做移动

一次批量下载要跑一小时，而多留一份冗余文件的代价是几百 MB。这个不对称决定了默认动作必须是**可逆**的。

所以：

- `cap classify` 只产出清单，不删任何东西
- `cap quarantine` 把候选文件**移动**到 `<root>/_quarantine/`，保留原科目/课程层级
- 同时写出 `_move_log.json`（逐条 src/dst）和 `RESTORE.md`（一键还原说明）
- 执行后做**守恒校验**：资料库剩余 + 隔离区 = 原总数。对不上就说明丢了东西
- `cap restore` 随时把所有文件按原路径放回去

隔离区目录以 `_` 开头，所以 `cap verify` 会自动跳过它 —— 剔除后重跑校验拿到的才是资料库主体的真实数字。

---

## 项目结构

```
course-asset-pipeline/
├── cap/                        Python 包
│   ├── media.py                共享工具：扩展名、体积、哈希、时长探测
│   ├── normalize.py            文件名规范化
│   ├── verify.py               三重校验与清单生成
│   ├── redownload.py           定点重下
│   ├── classify.py             分类归并（规则是数据，不是代码）
│   ├── fingerprint.py          音频级去重
│   ├── quarantine.py           可回滚隔离
│   ├── transcribe.py           语音转写（可选依赖）
│   ├── notes.py                转写 → Markdown
│   ├── default_rules.json      默认分类规则，可替换
│   └── cli.py                  统一命令行入口
├── cli/bili.mjs                元数据层（Node，无第三方依赖）
├── tests/                      88 个测试，全部离线可跑
├── examples/                   示例 survey
├── docs/
│   ├── design-notes.md         关键设计决策与踩过的坑
│   └── api-notes.md            接口字段与陷阱速查
└── SPEC.md                     需求、数据模型、验收标准
```

---

## 测试

```bash
pytest
```

88 个测试，**全部离线**：指纹比对用合成信号验证数学，分类/规范化/隔离用临时目录验证逻辑，转写层只验证断点续传的记账（不加载模型）。跑完不到 1 秒。

---

## 环境要求

- Python ≥ 3.10（核心依赖 `numpy`、`av`）
- Node ≥ 18（仅元数据层需要，无第三方依赖）
- 可选：`faster-whisper`（转写）、`yt-dlp`（下载）

---

## 合规与范围

- 本工具**只处理公开可见的元数据**，抓取间隔遵守站点策略
- 下载功能用于**个人学习目的的离线观看与笔记整理**，不得二次分发或商用
- 元数据层不绕过任何登录校验：拿不到的字幕就是不拿，不做规避
- 项目不附带任何课程内容，`examples/` 里的数据是合成的

---

## 许可

MIT © 2026 wpc725562-dotcom
