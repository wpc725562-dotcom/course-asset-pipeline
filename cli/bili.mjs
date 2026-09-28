// bili.mjs — B站视频提取统一 CLI
// 保留原有提取逻辑（cookie 引导 / 搜索 / 盘点 / 质量评分），并扩展字幕探测层。
//
// 用法：
//   node bili.mjs search  <关键词...> [--limit 8] [--order totalrank|click] [--json]
//   node bili.mjs survey  <BV号...> [--parts] [--json] [--from <file>]
//   node bili.mjs score   <survey.json> [--json]
//   node bili.mjs subs    <BV号> [--p 1,2,3] [--json]
//
// 设计要点见同目录 SKILL.md。

import fs from 'node:fs';

const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36';

// ---------------------------------------------------------------- 共享层

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

let COOKIE = null;

/** 步骤 1：访问首页拿 buvid3。缺少它时搜索接口会返回 aba.bilibili.com 的 HTML 错误页。 */
async function getCookie() {
  if (COOKIE) return COOKIE;
  const r = await fetch('https://www.bilibili.com/', { headers: { 'User-Agent': UA } });
  COOKIE = r.headers
    .getSetCookie()
    .map((c) => c.split(';')[0])
    .join('; ');
  return COOKIE;
}

/** 统一接口调用：带 UA / Referer / Cookie，返回 JSON。 */
async function api(path, params = {}, referer = 'https://www.bilibili.com/') {
  const ck = await getCookie();
  const qs = new URLSearchParams(params).toString();
  const url = `https://api.bilibili.com${path}${qs ? '?' + qs : ''}`;
  const res = await fetch(url, {
    headers: { 'User-Agent': UA, Referer: referer, Cookie: ck },
  });
  const text = await res.text();
  if (text.trimStart().startsWith('<')) {
    // 被风控重定向到 aba 错误页 —— 通常是 cookie 失效
    throw new Error(`接口返回 HTML（疑似风控）：${path}。请重新获取 cookie。`);
  }
  return JSON.parse(text);
}

/** 清理搜索结果标题里的 <em class="keyword"> 高亮标签与 HTML 实体。 */
function stripTags(s) {
  return String(s || '')
    .replace(/<[^>]+>/g, '')
    .replace(/&quot;/g, '"')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&#39;/g, "'");
}

function fmtNum(n) {
  n = Number(n) || 0;
  if (n >= 100000000) return (n / 100000000).toFixed(1) + '亿';
  if (n >= 10000) return (n / 10000).toFixed(1) + '万';
  return String(n);
}

function fmtDur(sec) {
  // ⚠️ 两种输入形态，别只处理一种：
  //   search/type  → duration 是 "MM:SS" / "HH:MM:SS" 字符串
  //   web-interface/view → duration 是秒数
  // 只按秒数处理时 Number("12:34") === NaN ⇒ 搜索结果时长全被格式化成 0:00（实测踩过）。
  if (typeof sec === 'string' && /^\d{1,2}(:\d{1,2}){1,2}$/.test(sec.trim())) return sec.trim();
  sec = Number(sec) || 0;
  const h = Math.floor(sec / 3600);
  const m = Math.floor((sec % 3600) / 60);
  const s = sec % 60;
  return h > 0
    ? `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`
    : `${m}:${String(s).padStart(2, '0')}`;
}

function fmtHM(min) {
  min = Math.round(min);
  return min >= 60 ? `${Math.floor(min / 60)}h${String(min % 60).padStart(2, '0')}m` : `${min}m`;
}

const pct = (a, b) => (b ? ((a / b) * 100).toFixed(2) + '%' : '-');

// ---------------------------------------------------------------- CLI 解析

function parseArgs(argv) {
  const out = { _: [], flags: {} };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a.startsWith('--')) {
      const key = a.slice(2);
      const next = argv[i + 1];
      if (next === undefined || next.startsWith('--')) {
        out.flags[key] = true;
      } else {
        out.flags[key] = next;
        i++;
      }
    } else {
      out._.push(a);
    }
  }
  return out;
}

// ---------------------------------------------------------------- L1 搜索

async function cmdSearch(args) {
  const kws = args._;
  if (!kws.length) throw new Error('search 需要至少一个关键词');
  const limit = Number(args.flags.limit) || 8;
  const order = args.flags.order || 'totalrank';
  const asJson = !!args.flags.json;

  const results = [];
  for (const kw of kws) {
    try {
      const j = await api(
        '/x/web-interface/search/type',
        { search_type: 'video', keyword: kw, page: 1, page_size: 20, order },
        'https://search.bilibili.com/'
      );
      if (j.code !== 0) {
        results.push({ kw, error: `${j.code} ${j.message}` });
      } else {
        results.push({
          kw,
          list: (j.data?.result || []).slice(0, limit).map((v) => ({
            title: stripTags(v.title),
            author: v.author,
            play: v.stat?.view ?? v.play,
            playText: fmtNum(v.stat?.view ?? v.play),
            danmaku: v.stat?.danmaku ?? v.danmaku,
            duration: fmtDur(v.duration),
            date: v.pubdate ? new Date(v.pubdate * 1000).toISOString().slice(0, 10) : '',
            bvid: v.bvid,
            url: `https://www.bilibili.com/video/${v.bvid}`,
          })),
        });
      }
    } catch (e) {
      results.push({ kw, error: String(e.message || e) });
    }
    await sleep(600); // 限速，避免触发风控
  }

  if (asJson) return console.log(JSON.stringify(results, null, 1));
  for (const r of results) {
    if (r.error) {
      console.log(`\n### ${r.kw}  [ERROR] ${r.error}`);
      continue;
    }
    console.log(`\n### ${r.kw}`);
    r.list.forEach((v, i) => {
      console.log(
        `${i + 1}. ${v.title} | ${v.author} | 播放${v.playText} | 弹幕${fmtNum(v.danmaku)} | ${v.duration} | ${v.date} | ${v.url}`
      );
    });
  }
}

// ---------------------------------------------------------------- L2 盘点

/** 单视频元信息 + 分P + 互动数据。这是盘点层的原子操作，survey / subs 都复用它。 */
async function fetchVideo(bvid) {
  const j = await api(
    '/x/web-interface/view',
    { bvid },
    `https://www.bilibili.com/video/${bvid}`
  );
  if (j.code !== 0) throw new Error(`${j.code} ${j.message}`);
  const d = j.data;
  return {
    bvid,
    url: `https://www.bilibili.com/video/${bvid}`,
    title: d.title,
    owner: d.owner.name,
    mins: Math.round(d.duration / 60),
    pages: d.videos,
    pubdate: new Date(d.pubdate * 1000).toISOString().slice(0, 10),
    stat: {
      view: d.stat.view,
      danmaku: d.stat.danmaku,
      reply: d.stat.reply,
      fav: d.stat.favorite,
      like: d.stat.like,
      coin: d.stat.coin,
    },
    parts: (d.pages || []).map((p) => ({
      p: p.page,
      t: p.part,
      m: Math.round(p.duration / 60),
      cid: p.cid,
    })),
  };
}

async function cmdSurvey(args) {
  let bvids = args._.slice();
  if (args.flags.from) {
    bvids = bvids.concat(
      fs
        .readFileSync(args.flags.from, 'utf8')
        .split(/\r?\n/)
        .map((s) => s.trim())
        .filter((s) => /^BV[0-9A-Za-z]{10}$/.test(s))
    );
  }
  if (!bvids.length) throw new Error('survey 需要 BV 号，或用 --from <文件>');

  const out = [];
  for (const bvid of bvids) {
    try {
      const rec = await fetchVideo(bvid);
      if (!args.flags.parts) delete rec.parts;
      out.push(rec);
      console.error(`[ok] ${bvid} ${rec.title}`);
    } catch (e) {
      out.push({ bvid, err: String(e.message || e) });
      console.error(`[err] ${bvid} ${e.message || e}`);
    }
    await sleep(700);
  }

  if (args.flags.json) return console.log(JSON.stringify(out, null, 1));
  for (const d of out) {
    if (d.err) {
      console.log(`\n### ${d.bvid}  [ERR] ${d.err}`);
      continue;
    }
    const s = d.stat;
    console.log(`\n### ${d.title}  (${d.bvid})`);
    console.log(`UP: ${d.owner} | 发布: ${d.pubdate} | 分P: ${d.pages} | 总时长: ${fmtHM(d.mins)}`);
    console.log(
      `播放 ${fmtNum(s.view)} | 弹幕 ${fmtNum(s.danmaku)} | 评论 ${fmtNum(s.reply)} | 点赞 ${fmtNum(s.like)} | 收藏 ${fmtNum(s.fav)} | 投币 ${fmtNum(s.coin)}`
    );
    console.log(`弹幕/集: ${d.pages ? Math.round(s.danmaku / d.pages) : '-'}`);
    if (d.parts?.length) {
      const head = d.parts.slice(0, 4).map((p) => `P${p.p} ${p.t}(${p.m}m)`).join(' ｜ ');
      const tail =
        d.parts.length > 6
          ? ` …… 末3P: ${d.parts.slice(-3).map((p) => `P${p.p} ${p.t}(${p.m}m)`).join(' ｜ ')}`
          : '';
      console.log(`大纲: ${head}${tail}`);
    }
  }
}

// ---------------------------------------------------------------- L3 评分

/**
 * 质量分 = 收藏率×0.40 + 投币率×0.35 + 点赞率×0.25，各指标按样本最大值归一化 ×100。
 * 局限：体量大的课程会被系统性低估（用户当教材用，不会"收藏待看"）；
 *       单集爆款会被系统性高估。仅用于第一轮筛选，不能替代试听。
 */
function cmdScore(args) {
  const file = args._[0];
  if (!file) throw new Error('score 需要 survey.json 路径');
  const data = JSON.parse(fs.readFileSync(file, 'utf8')).filter((d) => !d.err && d.stat);

  const rows = data.map((d) => ({
    ...d,
    favR: d.stat.fav / d.stat.view,
    coinR: d.stat.coin / d.stat.view,
    likeR: d.stat.like / d.stat.view,
  }));
  const max = (k) => Math.max(...rows.map((r) => r[k]), 1e-9);
  const mF = max('favR'), mC = max('coinR'), mL = max('likeR');

  for (const r of rows) {
    r.score = Math.round(
      ((r.favR / mF) * 0.4 + (r.coinR / mC) * 0.35 + (r.likeR / mL) * 0.25) * 100
    );
  }
  rows.sort((a, b) => b.score - a.score);

  if (args.flags.json) return console.log(JSON.stringify(rows, null, 1));
  console.log('排名 | 课程 | 集数 | 总时长 | 播放 | 收藏率 | 投币率 | 点赞率 | 弹幕/集 | 质量分');
  console.log('-'.repeat(110));
  rows.forEach((r, i) => {
    console.log(
      [
        String(i + 1).padStart(2),
        r.title.slice(0, 22).padEnd(22),
        String(r.pages).padStart(4),
        fmtHM(r.mins).padStart(7),
        fmtNum(r.stat.view).padStart(8),
        pct(r.stat.fav, r.stat.view).padStart(7),
        pct(r.stat.coin, r.stat.view).padStart(7),
        pct(r.stat.like, r.stat.view).padStart(7),
        String(r.pages ? Math.round(r.stat.danmaku / r.pages) : 0).padStart(7),
        String(r.score).padStart(6),
      ].join(' | ')
    );
  });
}

// ---------------------------------------------------------------- L3.5 字幕探测（扩展层）

/** 硬字幕信号：标题或分P名里出现这些词，说明字幕烧进了画面，CC 接口拿不到，必须走 OCR。 */
const HARDSUB_PATTERNS = [/【?字幕版】?/, /有字幕/, /中文字幕/, /双语字幕/, /字幕已/];

function detectHardsub(video) {
  const hits = [];
  if (HARDSUB_PATTERNS.some((re) => re.test(video.title))) hits.push('标题');
  for (const p of video.parts || []) {
    if (HARDSUB_PATTERNS.some((re) => re.test(p.t))) hits.push(`P${p.p}`);
  }
  return hits;
}

/**
 * 字幕可用性探测。
 * 关键判据：响应里 login_mid === 0 表示匿名访问 —— 此时 subtitles 为空
 * 是「登录态限制」而非「视频没有字幕」，两者必须区分，否则会误判。
 */
async function probeSubs(bvid, wantPages) {
  const video = await fetchVideo(bvid);
  const parts = wantPages?.length
    ? video.parts.filter((p) => wantPages.includes(p.p))
    : video.parts.slice(0, 3);

  const perPart = [];
  let loginMid = null;
  for (const p of parts) {
    try {
      const j = await api(
        '/x/player/v2',
        { bvid, cid: p.cid },
        `https://www.bilibili.com/video/${bvid}`
      );
      if (loginMid === null) loginMid = j.data?.login_mid;
      const subs = j.data?.subtitle?.subtitles || [];
      perPart.push({
        p: p.p,
        part: p.t,
        count: subs.length,
        langs: subs.map((x) => x.lan_doc || x.lan),
      });
    } catch (e) {
      perPart.push({ p: p.p, part: p.t, error: String(e.message || e) });
    }
    await sleep(350);
  }

  const hardsub = detectHardsub(video);
  const anyCc = perPart.some((x) => x.count > 0);

  let verdict, advice;
  if (anyCc) {
    verdict = 'CC 字幕可用';
    advice = '直接取 subtitle_url 下载 srt，无需转写。';
  } else if (loginMid === 0) {
    verdict = '未知（未登录）';
    advice =
      '接口匿名返回空。需登录态（SESSDATA 或 CDP）才能确认到底有没有 CC 字幕。' +
      (hardsub.length ? ` 注意：该视频疑似硬字幕（${hardsub.join('、')}），即使登录也拿不到文本，必须走 OCR。` : '');
  } else if (hardsub.length) {
    verdict = '无 CC 字幕（硬字幕）';
    advice = `字幕烧进画面（${hardsub.join('、')}），CC 接口无解 → 走 video-subtitle-extractor OCR。`;
  } else {
    verdict = '无字幕';
    advice = '既无 CC 也无硬字幕 → 走音频下载 + faster-whisper 转写。';
  }

  return {
    bvid,
    title: video.title,
    loginMid,
    perPart,
    hardsubSignals: hardsub,
    verdict,
    advice,
  };
}

async function cmdSubs(args) {
  const bvid = args._[0];
  if (!bvid) throw new Error('subs 需要 BV 号');
  const wantPages = args.flags.p
    ? String(args.flags.p)
        .split(',')
        .map((n) => Number(n.trim()))
    : null;
  const r = await probeSubs(bvid, wantPages);

  if (args.flags.json) return console.log(JSON.stringify(r, null, 1));
  console.log(`### ${r.title}  (${r.bvid})`);
  console.log(`login_mid: ${r.loginMid} ${r.loginMid === 0 ? '（匿名，字幕列表不可信）' : '（已登录）'}`);
  r.perPart.forEach((x) =>
    console.log(
      `  P${x.p} ${x.part} → ${x.error ? '[ERR] ' + x.error : x.count + ' 条字幕' + (x.langs.length ? ' [' + x.langs.join(',') + ']' : '')}`
    )
  );
  console.log(`硬字幕信号: ${r.hardsubSignals.length ? r.hardsubSignals.join('、') : '无'}`);
  console.log(`结论: ${r.verdict}`);
  console.log(`建议: ${r.advice}`);
}

// ---------------------------------------------------------------- 入口

const USAGE = `bili.mjs — B站视频提取统一 CLI

  search  <关键词...> [--limit 8] [--order totalrank|click] [--json]
  survey  <BV号...>   [--parts] [--json] [--from <文件>]
  score   <survey.json> [--json]
  subs    <BV号>      [--p 1,2,3] [--json]
`;

async function main() {
  const argv = process.argv.slice(2);
  const cmd = argv[0];
  const args = parseArgs(argv.slice(1));
  try {
    switch (cmd) {
      case 'search': return await cmdSearch(args);
      case 'survey': return await cmdSurvey(args);
      case 'score': return cmdScore(args);
      case 'subs': return await cmdSubs(args);
      default:
        console.log(USAGE);
        process.exit(cmd ? 1 : 0);
    }
  } catch (e) {
    console.error(`[fatal] ${e.message || e}`);
    process.exit(1);
  }
}

main();
