// fmtDur() 回归测试 —— 针对「B站搜索接口的 duration 是『总分钟数:秒』字符串」这一形态。
//
// 背景（2026-09-28 实测）：这个函数被修过两次，第二次才是对的。
//   ① 只按秒数处理            → Number("12:34") === NaN → 全部 0:00
//   ② 正则限制冒号前 1~2 位    → "1349:25" 不匹配 → 又回 NaN → 0:00
//      而短视屏（"19:57"）恰好正常显示，所以第②版**看起来是修好的**，
//      实际只覆盖了 2 位数分钟的数据，长课程/合集全部静默归零。
//
// 所以这里的关键不是「能不能格式化」，而是**边界样本不能归零**。
// 期望值均来自与 web-interface/view 的 duration（秒）交叉核对，8/8 吻合。

import test from 'node:test';
import assert from 'node:assert/strict';

import { fmtDur } from '../cli/bili.mjs';

test('秒数（web-interface/view 形态）按 h:mm:ss 格式化', () => {
  assert.equal(fmtDur(0), '0:00');
  assert.equal(fmtDur(59), '0:59');
  assert.equal(fmtDur(60), '1:00');
  assert.equal(fmtDur(3599), '59:59');
  assert.equal(fmtDur(3600), '1:00:00');
  assert.equal(fmtDur(80965), '22:29:25');
});

test('两位数分钟（短视屏）—— 第②版修复覆盖到的那一半', () => {
  // "19:57" = 19 分 57 秒
  assert.equal(fmtDur('19:57'), '19:57');
  assert.equal(fmtDur('7:45'), '7:45');
  assert.equal(fmtDur('2:27'), '2:27');
});

test('三位数分钟 —— 第②版正则的崩溃边界', () => {
  // "132:38" = 132 分 38 秒 = 7958s = 2:12:38
  assert.equal(fmtDur('132:38'), '2:12:38');
  // "144:37" = 8677s = 2:24:37
  assert.equal(fmtDur('144:37'), '2:24:37');
});

test('★ 四位数分钟（长合集）—— 回归守卫：绝不能是 0:00', () => {
  // 这几条是真实样本（已脱敏：只保留时长与分P数），
  // 换算结果均与详情接口的 duration（秒）交叉核对过。
  const cases = [
    ['1349:25', 80965, '22:29:25'], // 82 分P
    ['2270:35', 136235, '37:50:35'], // 199 分P
    ['2054:19', 123259, '34:14:19'], // 169 分P
    ['1006:55', 60415, '16:46:55'], // 134 分P
  ];
  for (const [raw, sec, want] of cases) {
    const got = fmtDur(raw);
    assert.equal(got, want, `${raw} 应格式化为 ${want}，实际 ${got}`);
    // 显式钉死「不得归零」——这是当初出错的症状
    assert.notEqual(got, '0:00', `${raw} 被错误地归零了（分钟位数超过正则上限）`);
    // 且换算结果必须与秒数输入一致
    assert.equal(got, fmtDur(sec), `${raw} 与等价秒数 ${sec} 的格式化结果不一致`);
  }
});

test('三位数分钟的进位边界（100 分钟 = 1:40:00）', () => {
  assert.equal(fmtDur('100:00'), '1:40:00');
  assert.equal(fmtDur('99:59'), '1:39:59');
});

test('时:分:秒 三段式走防御性分支', () => {
  assert.equal(fmtDur('1:02:03'), '1:02:03');
  assert.equal(fmtDur('0:00:30'), '0:30');
});

test('空值 / 脏值不抛异常，退化为 0:00', () => {
  assert.equal(fmtDur(undefined), '0:00');
  assert.equal(fmtDur(null), '0:00');
  assert.equal(fmtDur(''), '0:00');
  assert.equal(fmtDur('abc'), '0:00');
  // 广告位/聚合卡片没有 duration，会出现这种形态
  assert.equal(fmtDur('   '), '0:00');
});

test('字符串两侧空白被容忍', () => {
  assert.equal(fmtDur(' 1349:25 '), '22:29:25');
});
