# API notes

`cli/bili.mjs` 用到的接口字段与陷阱速查。**每条都实测过。**

---

## 1. Cookie 引导（最容易踩的坑）

调任何接口前，先访问首页拿 `buvid3`：

```js
const r = await fetch('https://www.bilibili.com/', { headers: { 'User-Agent': UA } });
const cookie = r.headers.getSetCookie().map(c => c.split(';')[0]).join('; ');
```

**不带 cookie 的后果**：接口不返回 JSON，而是返回 `aba.bilibili.com` 的 **HTML 错误页**。

因为返回的是 HTML 而不是错误码，很容易误判成「接口下线了」，从而放弃整条路径。

> **判据**：响应体以 `<` 开头 → 是风控页，不是接口问题。重取 cookie 即可。

---

## 2. `search/type` —— 搜索

```
GET https://api.bilibili.com/x/web-interface/search/type
  ?search_type=video&keyword=<kw>&page=1&page_size=20&order=totalrank
```

| 字段 | 说明 |
|:--|:--|
| `title` | **带 `<em class="keyword">` 高亮标签**，必须 strip，并还原 `&quot;` `&amp;` 等实体 |
| `duration` | **字符串** `"MM:SS"` / `"HH:MM:SS"`，不是秒数 |
| `author` / `bvid` / `pubdate` | 直接可用，`pubdate` 是 Unix 秒 |
| `stat.view` / `stat.danmaku` | 播放与弹幕 |

### 陷阱一：`duration` 是字符串

```js
Number("12:34")  // NaN  →  格式化后变成 "0:00"
```

`web-interface/view` 返回的 `duration` 却是**秒数**。两个接口形态不同，只处理一种的话，
**搜索结果里所有时长都会显示成 `0:00`**，而且不报错、不影响其它字段，很容易被忽略。

### 陷阱二：排序参数

用 `order=totalrank`（综合排序）。默认排序噪声很大。

### 陷阱三：关键词本身会被污染

这是选关键词时才会遇到的问题，但影响很大：

| 关键词类型 | 实测后果 |
|:--|:--|
| 含「复盘」「经验」等词 | 被股市 / 考公内容占据。搜「秋招 项目 复盘」6 条结果里 0 条相关 |
| 含「应届生」等无技术指向的词 | 会把其它专业的同类教程一起拉进来 |

**做法**：先用 `--limit 5` 跑一批候选词看真实返回，再决定用哪几个。别凭空想。

---

## 3. `web-interface/view` —— 课程盘点

```
GET https://api.bilibili.com/x/web-interface/view?bvid=<bvid>
```

一次拿全：

- `title` / `owner.name` / `pubdate`
- `videos`（分P总数）/ `duration`（总秒数，**不是字符串**）
- `pages[]` —— 每个分P的 `part`（标题）、`duration`、`cid`。这是生成课程大纲的来源
- `stat` —— `view` / `danmaku` / `reply` / `favorite` / `like` / `coin`

`pages[].cid` 是查字幕的关键，务必保留。

---

## 4. 质量评分（自建指标，有已知局限）

```
质量分 = 收藏率×0.40 + 投币率×0.35 + 点赞率×0.25     （各指标按样本最大值归一化 ×100）

收藏率 = 收藏 ÷ 播放     「以后还要再看」的强意愿
投币率 = 投币 ÷ 播放     B站最高成本行为（硬币有限），最硬的证据
点赞率 = 点赞 ÷ 播放     轻量认可
弹幕/集 = 弹幕 ÷ 分P数   活跃度，单列不计分
```

### 三条必须知道的局限

1. **体量大的课程被系统性低估。** 104 集、30 小时的课，用户当教材用，不会「收藏待看」，收藏率可能只有 1.6%。它的真实证据在弹幕/集和总播放量上。
2. **单集爆款被系统性高估。** 单集视频天然比合集容易获得高收藏率。
3. **不反映「适不适合具体的人」。** 热度 ≠ 适合。

> **结论：分数只做第一轮筛选，必须配合试听 2–3 集再定主力课程。**

---

## 5. `player/v2` —— 字幕探测

```
GET https://api.bilibili.com/x/player/v2?bvid=<bvid>&cid=<cid>
```

返回 `data.subtitle.subtitles[]`。**但匿名访问时它永远是空数组**，响应里的 `login_mid: 0` 暴露了原因。

区分三种「没字幕」：

```
subtitles 为空 + login_mid === 0        →  未知（登录态限制），不能断言「没字幕」
subtitles 为空 + 已登录 + 有硬字幕信号   →  硬字幕，需要 OCR
subtitles 为空 + 已登录 + 无硬字幕信号   →  真没字幕，走 ASR
subtitles 非空                          →  直接下载 CC 字幕，最省事
```

**硬字幕信号**（正则匹配标题与分P名）：`【字幕版】` / `有字幕` / `中文字幕` / `双语字幕`

命中的意思是**字幕烧进了画面**，即使登录也拿不到文本，必须 OCR。

---

## 6. 批量请求的礼貌约定

- 请求间隔 ≥ **600ms**，不要并发轰炸
- `--sleep-requests 0.6` 配合 `--retries 5 --fragment-retries 5 --ignore-errors`
- 不绕过任何登录校验。拿不到的就是拿不到
