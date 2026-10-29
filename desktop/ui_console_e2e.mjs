// 控制台级 UI E2E：滚动 / Markdown+图片 / 用量页 / 多 provider
// 用法（desktop/ 下）: node ui_console_e2e.mjs [--port-file <path>]
//
// 断言都是"用户能看见/能操作"的事实：
//   1. 长历史能滚动；往上翻时出现"回到最新"按钮，点它回到底部
//   2. Markdown：标题/列表/表格/代码块都渲染成真 DOM（不是 ``` 原文）；图片能内联加载
//   3. 用量页：4 个 KPI + 柱状图 + 请求日志表
//   4. 多 provider：保存后出现在列表里，密钥只显示掩码/环境变量
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const DESKTOP = path.dirname(fileURLToPath(import.meta.url));
const argPort = process.argv.indexOf('--port-file');
const PORT_FILE = argPort > 0
  ? process.argv[argPort + 1]
  : path.join(DESKTOP, 'dist', 'win-unpacked', 'resources', 'host', '.clawd_host_port');

const argImg = process.argv.indexOf('--img-path');
// 安装版里工作区是 resources/host，仓库的 screenshots 不存在 → 允许传一个已放进工作区的探针图
const IMG_PATH = argImg > 0 ? process.argv[argImg + 1] : 'desktop/screenshots/01-main.png';
const log = (m) => console.log(`[console-e2e] ${m}`);
const results = [];
const check = (name, ok, extra = '') => {
  results.push([name, ok, extra]);
  console.log(`[console-e2e] ${ok ? 'PASS' : 'FAIL'} ${name}${extra ? ' — ' + extra : ''}`);
};

if (!fs.existsSync(PORT_FILE)) { console.error(`端口文件不存在: ${PORT_FILE}`); process.exit(2); }
const info = JSON.parse(fs.readFileSync(PORT_FILE, 'utf-8'));

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1360, height: 860 } });
page.on('pageerror', (e) => console.log('[pageerror]', String(e).slice(0, 200)));
await page.goto(`http://127.0.0.1:${info.port}/?token=${info.token}`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2000);

// ---------- 1. 滚动 ----------
await page.evaluate(() => {
  const chat = document.querySelector('#chat');
  for (let i = 0; i < 40; i += 1) {
    const u = document.createElement('div'); u.className = 'msg-user'; u.textContent = '历史消息 ' + i;
    const a = document.createElement('div'); a.className = 'msg-assistant';
    const b = document.createElement('div'); b.className = 'body'; b.textContent = '回复 ' + i + ' '.repeat(20);
    a.appendChild(b); chat.appendChild(u); chat.appendChild(a);
  }
});
await page.waitForTimeout(300);
const scrollInfo = await page.evaluate(() => {
  const v = document.querySelector('.view');
  v.scrollTop = 0;
  return { scrollHeight: v.scrollHeight, clientHeight: v.clientHeight, scrollable: v.scrollHeight > v.clientHeight + 20 };
});
check('长历史可滚动', scrollInfo.scrollable, `scrollHeight=${scrollInfo.scrollHeight} clientHeight=${scrollInfo.clientHeight}`);

await page.evaluate(() => {
  const v = document.querySelector('.view');
  v.scrollTop = 0;
  v.dispatchEvent(new Event('scroll'));
});
await page.waitForTimeout(200);
const jumpShown = await page.evaluate(() => document.querySelector('#jumpBottom').classList.contains('show'));
check('上翻后出现"回到最新"按钮', jumpShown === true);
await page.click('#jumpBottom');
await page.waitForTimeout(400);
const nearBottom = await page.evaluate(() => {
  const v = document.querySelector('.view');
  return v.scrollHeight - v.scrollTop - v.clientHeight < 120;
});
check('点击"回到最新"回到底部', nearBottom === true);

// ---------- 2. Markdown + 图片（走真实渲染器） ----------
await page.evaluate((imgPath) => {
  const host = document.createElement('div');
  host.id = '__md_probe';
  host.className = 'msg-assistant';
  const body = document.createElement('div');
  body.className = 'body';
  host.appendChild(body);
  document.querySelector('#chat').appendChild(host);
  window.__clawdRenderRich(body, [
    '# 标题一',
    '',
    '- 项目 A',
    '- 项目 B',
    '',
    '1. 第一步',
    '2. 第二步',
    '',
    '> 引用一句',
    '',
    '| 方法 | 幂等 |',
    '|---|---|',
    '| GET | 是 |',
    '| POST | 否 |',
    '',
    '```python',
    'print("hi")',
    '```',
    '',
    '文字里有 `inline` 和 **粗体**，还有链接 [官网](https://example.com)。',
    '',
    '![](' + imgPath + ')',
  ].join('\n'));
}, IMG_PATH);
await page.waitForTimeout(600);

const md = await page.evaluate(() => {
  const probe = document.querySelector('#__md_probe .body');
  return {
    h1: probe.querySelectorAll('h1').length,
    ul: probe.querySelectorAll('ul li').length,
    ol: probe.querySelectorAll('ol li').length,
    quote: probe.querySelectorAll('blockquote').length,
    tableRows: probe.querySelectorAll('table tr').length,
    codeWraps: probe.querySelectorAll('.code-wrap').length,
    inlineCode: probe.querySelectorAll('.inline-code').length,
    links: probe.querySelectorAll('a').length,
    imgs: probe.querySelectorAll('img').length,
    rawFence: (probe.textContent || '').includes('```'),
  };
});
check('Markdown 标题/列表/引用', md.h1 >= 1 && md.ul >= 2 && md.ol >= 2 && md.quote >= 1, JSON.stringify(md));
check('Markdown 表格渲染', md.tableRows >= 3, `rows=${md.tableRows}`);
check('代码块渲染（无 ``` 原文）', md.codeWraps >= 1 && md.rawFence === false, `codeWraps=${md.codeWraps} rawFence=${md.rawFence}`);
check('行内代码/链接', md.inlineCode >= 1 && md.links >= 1);

const imgOk = await page.evaluate(async () => {
  const img = document.querySelector('#__md_probe img');
  if (!img) return { ok: false, reason: 'no img element' };
  if (img.complete && img.naturalWidth > 0) return { ok: true, w: img.naturalWidth, src: img.getAttribute('src') };
  await new Promise((r) => setTimeout(r, 1500));
  return { ok: img.complete && img.naturalWidth > 0, w: img.naturalWidth, src: img.getAttribute('src') };
});
check('图片内联渲染（/api/file 出图）', imgOk.ok === true, JSON.stringify(imgOk));

// ---------- 2.5 会话列表（侧栏历史） ----------
await page.waitForTimeout(800);
const sess = await page.evaluate(() => {
  const items = Array.from(document.querySelectorAll('#sessionList .session-item'));
  const empty = (document.querySelector('#sessionList')?.textContent || '').includes('还没有历史会话');
  return { count: items.length, empty, firstText: items[0]?.textContent || '' };
});
check('侧栏会话列表可用（有历史或明确空态）', sess.count > 0 || sess.empty === true, JSON.stringify(sess));
if (sess.count > 0) {
  await page.click('#sessionList .session-item');
  await page.waitForTimeout(900);
  const loaded = await page.evaluate(() => ({
    title: (document.querySelector('#sessionTitle')?.textContent || '').trim(),
    bubbles: document.querySelectorAll('#chat .msg-assistant, #chat .msg-user').length,
  }));
  check('点开会话能加载历史', loaded.bubbles >= 1 && loaded.title.length > 0, JSON.stringify(loaded));
}

// ---------- 3. 用量页 ----------
await page.click('#btnUsage');
await page.waitForTimeout(1200);
const usage = await page.evaluate(() => ({
  open: document.querySelector('#usageOverlay').classList.contains('show'),
  kpis: document.querySelectorAll('#usageKpis .kpi').length,
  bars: document.querySelectorAll('#usageChart rect').length,
  rows: document.querySelectorAll('#usageRows tr').length,
  empty: document.querySelector('#usageEmpty').style.display !== 'none',
}));
check('用量页打开 + 4 个 KPI', usage.open && usage.kpis === 4, JSON.stringify(usage));
check('用量页有日志行或明确空态', usage.rows > 0 || usage.empty === true, `rows=${usage.rows}`);
await page.screenshot({ path: path.join(DESKTOP, 'screenshots', '10-usage-panel.png') });
await page.click('#usageClose');

// ---------- 4. 多 provider ----------
await page.click('#btnSettings');
await page.waitForTimeout(600);
await page.fill('#provId', 'e2e-deepseek');
await page.fill('#provName', 'E2E DeepSeek');
await page.selectOption('#provKind', 'openai');
await page.fill('#provModel', 'deepseek-chat');
await page.fill('#provBaseUrl', 'https://api.deepseek.com/v1');
await page.fill('#provKeyEnv', 'DEEPSEEK_API_KEY');
await page.click('#provSave');
await page.waitForTimeout(1200);
const prov = await page.evaluate(() => {
  const items = Array.from(document.querySelectorAll('#provList .prov-item'));
  return {
    count: items.length,
    texts: items.map((i) => i.textContent.replace(/\s+/g, ' ').trim()).slice(0, 4),
  };
});
check('provider 保存后出现在列表', prov.count >= 1 && prov.texts.some((t) => t.includes('E2E DeepSeek')), JSON.stringify(prov));
check('列表只显示 env 名/掩码（无明文密钥）', prov.texts.some((t) => t.includes('env:DEEPSEEK_API_KEY')), JSON.stringify(prov.texts));
await page.screenshot({ path: path.join(DESKTOP, 'screenshots', '11-providers.png') });

await browser.close();
const failed = results.filter(([, ok]) => !ok);
log(`合计 ${results.length} 项，通过 ${results.length - failed.length}，失败 ${failed.length}`);
process.exit(failed.length === 0 ? 0 : 1);
