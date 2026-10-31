// 交互反馈（四态）E2E：加载中 / 成功 / 失败可见 / 可重试 + 全局兜底
// 用法（desktop/ 下）: node ui_feedback_e2e.mjs [--port-file <path>]
//
// 断言都是"用户能看见/能操作"的事实，不用 mock 断言内部实现：
//   1. 点会发请求的按钮 → 请求进行中按钮 disabled + 文案变化（page.route 延迟 800ms 造窗口），
//      结束后按钮复原（disabled/文案/aria-busy 全部回到原样）
//   2. 请求返回 500 → 面板里出现 .inline-error（中文）→ 点「重试」该条消失并再发请求 → 恢复后正常渲染
//   3. Provider 保存失败 / 项目添加失败（真实 Host 校验错误）→ 错误人话可见 + 按钮复原 + 不靠 15s 超时
//   4. 未捕获 promise rejection / 未捕获异常 → 右下角 toast 出现，且同一错误 5 秒内去重
//   5. 全过程零 pageerror（除刻意触发的探针）
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const DESKTOP = path.dirname(fileURLToPath(import.meta.url));
const argPort = process.argv.indexOf('--port-file');
const PORT_FILE = argPort > 0
  ? process.argv[argPort + 1]
  : path.join(DESKTOP, '..', '.clawd_host_port');

const log = (m) => console.log(`[feedback-e2e] ${m}`);
const results = [];
const check = (name, ok, extra = '') => {
  results.push([name, ok, extra]);
  console.log(`[feedback-e2e] ${ok ? 'PASS' : 'FAIL'} ${name}${extra ? ' — ' + extra : ''}`);
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const hasCJK = (s) => /[\u4e00-\u9fa5]/.test(String(s || ''));

if (!fs.existsSync(PORT_FILE)) { console.error(`端口文件不存在: ${PORT_FILE}`); process.exit(2); }
const info = JSON.parse(fs.readFileSync(PORT_FILE, 'utf-8'));

const SCREENS = path.join(DESKTOP, 'screenshots');
if (!fs.existsSync(SCREENS)) fs.mkdirSync(SCREENS, { recursive: true });

// 刻意触发的探针会各产生一条 pageerror，按标记过滤后必须为 0
const PROBE_MARKS = ['__e2e_probe_rejection__', '__e2e_probe_error__'];
const pageErrors = [];
const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1360, height: 860 } });
page.on('pageerror', (e) => {
  const s = String(e);
  pageErrors.push(s);
  log(`pageerror: ${s.slice(0, 180)}`);
});

const usageCtl = { mode: 'slow', hits: 0 };
const ctxCtl = { mode: 'ok', hits: 0 };

function usageBody() {
  const now = Math.floor(Date.now() / 1000);
  return {
    totals: {
      cost: 0.0123, requests: 7, total_tokens: 1234,
      prompt_tokens: 900, completion_tokens: 334, cache_hit_rate: 0.25, cache_read_tokens: 123,
    },
    hourly: [{ bucket: now, time_label: 'now', tokens: 900, cost: 0.001 }],
    recent: [{
      ts: now, client: 'e2e', provider: 'mock', model: 'mock-model', cost: 0.001,
      prompt_tokens: 900, completion_tokens: 334, cache_read_tokens: 123, steps: 1, status: 'ok',
    }],
  };
}

await page.route(/\/api\/usage(\?|$)/, async (route) => {
  usageCtl.hits += 1;
  if (usageCtl.mode === 'slow') {
    await sleep(800);
    return route.fulfill({
      status: 200, contentType: 'application/json; charset=utf-8', body: JSON.stringify(usageBody()),
    });
  }
  if (usageCtl.mode === 'err500') {
    return route.fulfill({ status: 500, contentType: 'application/json', body: '{"error":"boom"}' });
  }
  return route.continue();
});

await page.route(/\/api\/context(\?|$)/, async (route) => {
  ctxCtl.hits += 1;
  if (ctxCtl.mode === 'err500') {
    return route.fulfill({ status: 500, contentType: 'application/json', body: '{"error":"boom"}' });
  }
  return route.continue();
});

await page.goto(`http://127.0.0.1:${info.port}/?token=${info.token}`, { waitUntil: 'networkidle' });
await page.waitForFunction(
  () => ((document.querySelector('#connText') || {}).textContent || '').includes('已连接'),
  null, { timeout: 20000 },
).catch(() => {});
const connected = await page.evaluate(
  () => ((document.querySelector('#connText') || {}).textContent || ''),
);
check('页面已连上 Host（前置条件）', connected.includes('已连接'), connected);

// ---------- 1. 按钮忙态：请求进行中 disabled + 文案变化，结束后复原 ----------
usageCtl.mode = 'slow';
await page.click('#btnUsage');
await page.waitForTimeout(1500);          // 首次打开（slow 800ms）先让面板出数
const openOk = await page.evaluate(() => ({
  open: document.querySelector('#usageOverlay').classList.contains('show'),
  kpis: document.querySelectorAll('#usageKpis .kpi').length,
}));
check('用量面板正常打开并出数（前置条件）', openOk.open && openOk.kpis === 4, JSON.stringify(openOk));
await page.screenshot({ path: path.join(SCREENS, '40-feedback-usage-ok.png') });

const refreshBefore = await page.evaluate(() => {
  const b = document.querySelector('#usageRefresh');
  return {
    text: (b.textContent || '').trim(),
    disabled: b.disabled,
    aria: b.getAttribute('aria-busy'),
  };
});
await page.click('#usageRefresh');
await page.waitForTimeout(150);           // 请求被拖到 800ms，这里正好处于忙态窗口内
const refreshDuring = await page.evaluate(() => {
  const b = document.querySelector('#usageRefresh');
  return {
    text: (b.textContent || '').trim(),
    disabled: b.disabled,
    aria: b.getAttribute('aria-busy'),
    loadingText: (document.querySelector('#usageKpis') || {}).textContent || '',
  };
});
check('忙态：按钮 disabled + 文案变化 + aria-busy',
  refreshDuring.disabled === true
  && refreshDuring.aria === 'true'
  && refreshDuring.text !== refreshBefore.text
  && refreshDuring.text.length > 0,
  JSON.stringify({ before: refreshBefore, during: refreshDuring }));
check('忙态：面板同时显示"加载中"（不是空白）',
  refreshDuring.loadingText.includes('加载中'), JSON.stringify({ loadingText: refreshDuring.loadingText.slice(0, 40) }));
await page.screenshot({ path: path.join(SCREENS, '41-feedback-busy.png') });

await page.waitForTimeout(1400);
const refreshAfter = await page.evaluate(() => {
  const b = document.querySelector('#usageRefresh');
  return {
    text: (b.textContent || '').trim(),
    disabled: b.disabled,
    aria: b.getAttribute('aria-busy'),
    kpis: document.querySelectorAll('#usageKpis .kpi').length,
  };
});
check('忙态结束：按钮文案/disabled/aria-busy 全部复原',
  refreshAfter.disabled === false
  && refreshAfter.aria === null
  && refreshAfter.text === refreshBefore.text
  && refreshAfter.kpis === 4,
  JSON.stringify({ before: refreshBefore, after: refreshAfter }));

// ---------- 2. 失败可见 + 重试：/api/usage 返回 500 ----------
usageCtl.mode = 'err500';
const hitsBeforeErr = usageCtl.hits;
await page.click('#usageRefresh');
let inlineShown = false;
try {
  await page.waitForSelector('#usageKpis .inline-error', { timeout: 10000 });
  inlineShown = true;
} catch (_) { inlineShown = false; }
const errState = await page.evaluate(() => {
  const el = document.querySelector('#usageKpis .inline-error');
  return {
    exists: !!el,
    text: el ? (el.textContent || '').trim() : '',
    hasRetry: !!(el && el.querySelector('.ie-retry')),
    retryLabel: el && el.querySelector('.ie-retry') ? (el.querySelector('.ie-retry').textContent || '').trim() : '',
    kpis: document.querySelectorAll('#usageKpis .kpi').length,
    // 错误条必须横跨整行，不能被 4 列 grid 挤成一根竖面条（真实布局缺陷）
    width: el ? Math.round(el.getBoundingClientRect().width) : 0,
    usageEmptyVisible: (document.querySelector('#usageEmpty') || {}).style
      ? document.querySelector('#usageEmpty').style.display !== 'none' : false,
  };
});
check('500 失败：面板内出现 .inline-error 且是中文人话',
  inlineShown && errState.exists && hasCJK(errState.text) && errState.text.includes('500'),
  JSON.stringify(errState));
check('500 失败：错误条横跨整行（没被 grid 挤成窄条）', errState.width > 400, `width=${errState.width}px`);
check('500 失败：错误条带「重试」按钮', errState.hasRetry && errState.retryLabel === '重试', JSON.stringify(errState));
check('500 失败：不再同时显示"还没有用量记录"（不留矛盾空态）',
  errState.kpis === 0 && errState.usageEmptyVisible === false, JSON.stringify(errState));
check('500 失败：重试次数 ≥3（fetchJsonRetry 真的重试过）',
  usageCtl.hits - hitsBeforeErr >= 3, `hits=${usageCtl.hits - hitsBeforeErr}`);
await page.screenshot({ path: path.join(SCREENS, '42-feedback-inline-error.png') });

const hitsBeforeRetry = usageCtl.hits;
await page.click('#usageKpis .inline-error .ie-retry');
await page.waitForTimeout(250);
const afterRetryClick = await page.evaluate(() => ({
  inline: document.querySelectorAll('#usageKpis .inline-error').length,
  loading: ((document.querySelector('#usageKpis') || {}).textContent || '').includes('加载中'),
}));
check('点「重试」：该错误条立即消失并进入加载态',
  afterRetryClick.inline === 0 && afterRetryClick.loading === true,
  JSON.stringify(afterRetryClick));

let retryHitsOk = false;
for (let i = 0; i < 30; i += 1) {
  if (usageCtl.hits > hitsBeforeRetry) { retryHitsOk = true; break; }
  await sleep(100);
}
check('点「重试」：真的发出了第二次请求', retryHitsOk, `hits +${usageCtl.hits - hitsBeforeRetry}`);

// 让重试成功 → 面板必须能自己恢复（不是死面板）
usageCtl.mode = 'ok';
let recovered = false;
try {
  await page.waitForFunction(
    () => document.querySelectorAll('#usageKpis .kpi').length === 4
      && document.querySelectorAll('#usageKpis .inline-error').length === 0,
    null, { timeout: 10000 },
  );
  recovered = true;
} catch (_) { recovered = false; }
check('重试成功后面板恢复（4 个 KPI，错误条消失）', recovered);
await page.evaluate(() => document.querySelector('#usageClose')?.click());
await page.waitForTimeout(300);

// ---------- 3. Provider 保存失败（真实 Host 校验错误，不是 mock） ----------
await page.click('#btnSettings');
await page.waitForTimeout(1000);
const provT0 = Date.now();
await page.click('#provSave');            // 表单为空 → Host 返回 E_PROVIDER_INVALID
let provErrShown = false;
try {
  await page.waitForFunction(
    () => ((document.querySelector('#setNote') || {}).textContent || '').includes('保存失败'),
    null, { timeout: 8000 },
  );
  provErrShown = true;
} catch (_) { provErrShown = false; }
const provElapsed = Date.now() - provT0;
const provErr = await page.evaluate(() => {
  const note = document.querySelector('#setNote');
  const btn = document.querySelector('#provSave');
  const toasts = Array.from(document.querySelectorAll('#toastHost .toast')).map((el) => (el.textContent || '').trim());
  return {
    note: (note.textContent || '').trim(),
    noteClass: note.className,
    btnText: (btn.textContent || '').trim(),
    btnDisabled: btn.disabled,
    btnAria: btn.getAttribute('aria-busy'),
    toasts,
  };
});
check('Provider 保存失败：提示是人话中文（不是裸 Error/请求超时）',
  provErrShown
  && provErr.note.includes('保存失败')
  && hasCJK(provErr.note)
  && !provErr.note.includes('请求超时')
  && provErr.noteClass.includes('err'),
  JSON.stringify(provErr));
check('Provider 保存失败：按钮复原（文案/disabled/aria-busy）',
  provErr.btnDisabled === false && provErr.btnAria === null && provErr.btnText === '保存提供商',
  JSON.stringify({ btnText: provErr.btnText, btnDisabled: provErr.btnDisabled, btnAria: provErr.btnAria }));
check('Provider 保存失败：失败原因立刻可见（不靠 15s 超时兜底）',
  provElapsed < 5000, `elapsed=${provElapsed}ms`);
check('Provider 保存失败：右下角有失败 toast',
  provErr.toasts.some((t) => t.includes('保存提供商失败')), JSON.stringify(provErr.toasts));
await page.screenshot({ path: path.join(SCREENS, '43-feedback-provider-error.png') });

// ---------- 4. Provider 保存成功：成功 toast + 列表出现 ----------
await page.fill('#provId', 'e2e-feedback');
await page.fill('#provName', 'E2E 反馈测试');
await page.selectOption('#provKind', 'openai');
await page.fill('#provModel', 'mock-model');
await page.fill('#provBaseUrl', 'https://example.invalid/v1');
await page.fill('#provKeyEnv', 'E2E_FEEDBACK_KEY');
await page.click('#provSave');
await page.waitForTimeout(1500);
const provOk = await page.evaluate(() => ({
  items: Array.from(document.querySelectorAll('#provList .prov-item'))
    .map((el) => (el.textContent || '').replace(/\s+/g, ' ').trim()),
  note: ((document.querySelector('#setNote') || {}).textContent || '').trim(),
  btnText: (document.querySelector('#provSave') || {}).textContent || '',
  toasts: Array.from(document.querySelectorAll('#toastHost .toast')).map((el) => (el.textContent || '').trim()),
}));
check('Provider 保存成功：列表出现 + 成功提示',
  provOk.items.some((t) => t.includes('E2E 反馈测试')) && provOk.note.includes('已保存'),
  JSON.stringify({ items: provOk.items.slice(0, 3), note: provOk.note }));
check('Provider 保存成功：成功 toast 可见（四态的成功态）',
  provOk.toasts.some((t) => t.includes('提供商已保存')), JSON.stringify(provOk.toasts));
await page.evaluate(() => document.querySelector('#settingsClose')?.click());
await page.waitForTimeout(300);

// ---------- 5. 添加项目失败（真实 Host：目录不存在）+ pickFolder 兜底 ----------
await page.click('#btnAddProject');
await page.waitForTimeout(400);
const projT0 = Date.now();
await page.fill('#projPathInput', 'C:\\__e2e_no_such_dir__\\nope');
await page.click('#projPathSave');
let projErrShown = false;
try {
  await page.waitForFunction(
    () => ((document.querySelector('#projNote') || {}).textContent || '').includes('添加失败'),
    null, { timeout: 8000 },
  );
  projErrShown = true;
} catch (_) { projErrShown = false; }
const projElapsed = Date.now() - projT0;
const projErr = await page.evaluate(() => {
  const note = document.querySelector('#projNote');
  const btn = document.querySelector('#projPathSave');
  return {
    note: (note.textContent || '').trim(),
    noteClass: note.className,
    btnText: (btn.textContent || '').trim(),
    btnDisabled: btn.disabled,
    toasts: Array.from(document.querySelectorAll('#toastHost .toast')).map((el) => (el.textContent || '').trim()),
  };
});
check('添加项目失败：错误可见且是人话（含"目录不存在"）',
  projErrShown && projErr.note.includes('添加失败') && hasCJK(projErr.note)
  && projErr.noteClass.includes('err'),
  JSON.stringify(projErr));
check('添加项目失败：按钮复原 + 失败 toast + 不走 15s 超时',
  projErr.btnDisabled === false && projErr.btnText === '添加'
  && projErr.toasts.some((t) => t.includes('添加项目失败'))
  && projElapsed < 5000,
  JSON.stringify({ btn: projErr.btnText, disabled: projErr.btnDisabled, elapsed: projElapsed, toasts: projErr.toasts }));
await page.screenshot({ path: path.join(SCREENS, '44-feedback-project-error.png') });

// 浏览器里没有桌面壳 → pickFolder 必须给出明确提示（以前是静默）
await page.fill('#projPathInput', '');
await page.evaluate(() => document.querySelectorAll('#toastHost .toast').forEach((n) => n.remove()));
await page.click('#projBrowse');
await page.waitForTimeout(400);
const pickInfo = await page.evaluate(() => ({
  toasts: Array.from(document.querySelectorAll('#toastHost .toast')).map((el) => (el.textContent || '').trim()),
  focused: (document.activeElement || {}).id || '',
  placeholder: (document.querySelector('#projPathInput') || {}).placeholder || '',
  btnText: ((document.querySelector('#projBrowse') || {}).textContent || '').replace(/\s+/g, ' ').trim(),
}));
check('没有原生选择器时 pickFolder 给出提示（不再静默）',
  pickInfo.toasts.some((t) => t.includes('没有文件夹选择器'))
  && pickInfo.focused === 'projPathInput'
  && pickInfo.placeholder.includes('粘贴路径'),
  JSON.stringify(pickInfo));
await page.evaluate(() => document.querySelector('#projectClose')?.click());
await page.waitForTimeout(300);

// ---------- 6. 上下文面板失败 → inline 错误 → 重试 → 恢复 ----------
ctxCtl.mode = 'err500';
const ctxHitsBefore = ctxCtl.hits;
await page.click('#btnContext');
let ctxErrShown = false;
try {
  await page.waitForSelector('#ctxItems .inline-error', { timeout: 10000 });
  ctxErrShown = true;
} catch (_) { ctxErrShown = false; }
const ctxErr = await page.evaluate(() => {
  const el = document.querySelector('#ctxItems .inline-error');
  return {
    exists: !!el,
    text: el ? (el.textContent || '').trim() : '',
    hasRetry: !!(el && el.querySelector('.ie-retry')),
    total: ((document.querySelector('#ctxTotal') || {}).textContent || '').trim(),
  };
});
check('上下文面板失败：inline 错误 + 重试按钮（中文）',
  ctxErrShown && ctxErr.exists && hasCJK(ctxErr.text) && ctxErr.hasRetry,
  JSON.stringify(ctxErr));
check('上下文面板失败：头部不再显示技术细节（只留"不可用"）',
  ctxErr.total === '上下文统计不可用', ctxErr.total);

const ctxHitsAtRetry = ctxCtl.hits;
await page.click('#ctxItems .inline-error .ie-retry');
await page.waitForTimeout(250);
const ctxAfterRetry = await page.evaluate(() => ({
  inline: document.querySelectorAll('#ctxItems .inline-error').length,
}));
let ctxRetryHits = false;
for (let i = 0; i < 30; i += 1) {
  if (ctxCtl.hits > ctxHitsAtRetry) { ctxRetryHits = true; break; }
  await sleep(100);
}
check('上下文面板：点「重试」错误条消失并再发请求',
  ctxAfterRetry.inline === 0 && ctxRetryHits,
  JSON.stringify({ ...ctxAfterRetry, hits: ctxCtl.hits - ctxHitsAtRetry, firstHits: ctxCtl.hits - ctxHitsBefore }));

ctxCtl.mode = 'ok';
let ctxRecovered = false;
try {
  await page.waitForFunction(
    () => document.querySelectorAll('#ctxItems .ctx-item').length >= 2,
    null, { timeout: 10000 },
  );
  ctxRecovered = true;
} catch (_) { ctxRecovered = false; }
check('上下文面板：重试成功后真实渲染出用量条目', ctxRecovered);
await page.screenshot({ path: path.join(SCREENS, '45-feedback-ctx-retry.png') });
await page.evaluate(() => document.querySelector('#ctxClose')?.click());
await page.waitForTimeout(300);

// ---------- 7. 全局兜底：未捕获 rejection / 未捕获异常 → toast（且 5 秒去重） ----------
await page.evaluate(() => document.querySelectorAll('#toastHost .toast').forEach((n) => n.remove()));
await page.evaluate(() => {
  setTimeout(() => { Promise.reject(new Error('__e2e_probe_rejection__')); }, 0);
});
await page.waitForTimeout(600);
const rejToast = await page.evaluate(() => Array.from(document.querySelectorAll('#toastHost .toast'))
  .map((el) => (el.textContent || '').trim()));
check('未捕获 promise rejection → 右下角出现中文 toast',
  rejToast.some((t) => t.includes('有一个操作失败了')), JSON.stringify(rejToast));
await page.screenshot({ path: path.join(SCREENS, '46-feedback-unhandled.png') });

// 同一条错误 5 秒内再来一次 → 不得刷屏（去重）
const countBeforeDedup = rejToast.length;
await page.evaluate(() => {
  setTimeout(() => { Promise.reject(new Error('__e2e_probe_rejection__')); }, 0);
});
await page.waitForTimeout(700);
const afterDedup = await page.evaluate(
  () => document.querySelectorAll('#toastHost .toast').length,
);
check('同一条未捕获错误 5 秒内去重（不刷屏）', afterDedup <= countBeforeDedup, `${countBeforeDedup} → ${afterDedup}`);

await page.evaluate(() => document.querySelectorAll('#toastHost .toast').forEach((n) => n.remove()));
await page.evaluate(() => {
  setTimeout(() => { throw new Error('__e2e_probe_error__'); }, 0);
});
await page.waitForTimeout(600);
const errToast = await page.evaluate(() => Array.from(document.querySelectorAll('#toastHost .toast'))
  .map((el) => (el.textContent || '').trim()));
check('未捕获异常（window error）→ 右下角出现中文 toast',
  errToast.some((t) => t.includes('页面出错了')), JSON.stringify(errToast));

// 资源加载失败（img 404）→ 走 window error 捕获阶段，也要有 toast
await page.evaluate(() => document.querySelectorAll('#toastHost .toast').forEach((n) => n.remove()));
await page.evaluate(() => {
  const img = document.createElement('img');
  img.id = '__e2e_broken_img';
  img.src = '/__e2e_missing_resource__.png';
  document.body.appendChild(img);
});
await page.waitForTimeout(900);
const resToast = await page.evaluate(() => Array.from(document.querySelectorAll('#toastHost .toast'))
  .map((el) => (el.textContent || '').trim()));
check('资源加载失败（img 404）→ toast 提示（捕获阶段接线）',
  resToast.some((t) => t.includes('资源加载失败')), JSON.stringify(resToast));
await page.evaluate(() => document.querySelector('#__e2e_broken_img')?.remove());

// ---------- 8. 零 pageerror（除刻意探针） ----------
const realErrors = pageErrors.filter((s) => !PROBE_MARKS.some((m) => s.includes(m)));
check('全过程零 pageerror（除刻意触发的探针）',
  realErrors.length === 0,
  realErrors.length ? JSON.stringify(realErrors.slice(0, 3)) : `pageerror 总数 ${pageErrors.length}（全为探针）`);

await browser.close();
const failed = results.filter(([, ok]) => !ok);
log(`合计 ${results.length} 项，通过 ${results.length - failed.length}，失败 ${failed.length}`);
if (failed.length) log(`失败项: ${failed.map(([n]) => n).join(' | ')}`);
process.exit(failed.length === 0 ? 0 : 1);
