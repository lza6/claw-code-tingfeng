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

// ---------- 0. 输入框必须在视口内（真实事故：长会话把 composer 顶到 y=1895，用户以为没有输入框） ----------
const layout = await page.evaluate(() => {
  const cw = document.querySelector('.composer-wrap');
  const box = cw ? cw.getBoundingClientRect() : null;
  const input = document.querySelector('#input');
  const ibox = input ? input.getBoundingClientRect() : null;
  return {
    exists: !!cw,
    composerInView: box ? (box.top >= 0 && box.bottom <= window.innerHeight + 1) : false,
    composerY: box ? Math.round(box.top) : null,
    inputInView: ibox ? (ibox.top >= 0 && ibox.bottom <= window.innerHeight + 1 && ibox.height > 8) : false,
    innerH: window.innerHeight,
    mainScroll: Math.round(document.querySelector('main.main')?.getBoundingClientRect().height || 0),
  };
});
check('输入框在视口内（composer 未被顶出屏幕）',
  layout.exists && layout.composerInView && layout.inputInView && layout.mainScroll <= layout.innerH + 1,
  JSON.stringify(layout));

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

// ---------- 2.7 图片附件（粘贴 → chip → 发送） ----------
const pasted = await page.evaluate(async () => {
  // 造一个 1x1 PNG，模拟"从剪贴板粘贴图片"
  const b64 = 'iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8AAAwAB/wD/AL0AAAAASUVORK5CYII=';
  const bytes = Uint8Array.from(atob(b64), (c) => c.charCodeAt(0));
  const file = new File([bytes], 'pasted.png', { type: 'image/png' });
  const dt = new DataTransfer();
  dt.items.add(file);
  const evt = new ClipboardEvent('paste', { clipboardData: dt, bubbles: true, cancelable: true });
  document.querySelector('#input').dispatchEvent(evt);
  await new Promise((r) => setTimeout(r, 400));
  return {
    chips: document.querySelectorAll('#attachBar .attach-chip').length,
    hasImg: !!document.querySelector('#attachBar .attach-chip img'),
  };
});
check('粘贴图片出现附件缩略图', pasted.chips >= 1 && pasted.hasImg, JSON.stringify(pasted));

if (pasted.chips >= 1) {
  await page.fill('#input', '这张图是什么颜色？一句话即可。');
  await page.click('#send');
  const deadline2 = Date.now() + 150000;
  let done = false;
  while (Date.now() < deadline2) {
    await page.waitForTimeout(1500);
    const busy = await page.$eval('#send', (b) => b.classList.contains('stop-mode'));
    if (!busy) { done = true; break; }
  }
  const after = await page.evaluate(() => ({
    chips: document.querySelectorAll('#attachBar .attach-chip').length,
    last: (() => {
      const all = document.querySelectorAll('.msg-assistant .body');
      return all.length ? (all[all.length - 1].textContent || '').slice(0, 120) : '';
    })(),
    err: (() => {
      const all = document.querySelectorAll('.msg-err');
      return all.length ? (all[all.length - 1].textContent || '').slice(0, 120) : '';
    })(),
    base64Leak: (document.querySelector('#chat')?.textContent || '').includes('data:image/png;base64'),
    msgs: Array.from(document.querySelectorAll('#chat > *')).slice(-3).map((el) => ({
      cls: el.className,
      len: (el.textContent || '').length,
      kids: Array.from(el.children).map((c) => c.className).slice(0, 4),
    })),
  }));
  // 断言只负责"发送链路走完 + 附件清空 + 不泄漏 base64"。
  // 模型有没有回复取决于外部端点（本轮实测会 APIConnectionError），
  // 有错误提示同样证明链路已结束 —— 不把外部可用性当产品门禁。
  // send 解锁比"流式收尾"早（前端有 1.2s 兜底把 pendingFinal 灌进气泡），等它稳定再断言
  await page.waitForTimeout(2200);
  const sendStillBusy = await page.$eval('#send', (b) => b.classList.contains('stop-mode'));
  check('带图消息发送完成且附件已清空',
    done && after.chips === 0 && (after.last.length > 0 || after.err.length > 0),
    JSON.stringify({ ...after, done, sendStillBusy }));
  check('消息里没有把 base64 直接铺到对话区', after.base64Leak === false);
}

// ---------- 2.8 工具调用折叠组 ----------
const fold = await page.evaluate(async () => {
  // 真实 run 可能已经产生过一组；这里先"换组"（发一条用户消息会关闭当前组），再模拟 3 次工具
  const before = document.querySelectorAll('.tool-group').length;
  const u = document.createElement('div');
  u.className = 'msg-user';
  u.textContent = '__e2e_fold_probe__';
  document.querySelector('#chat').appendChild(u);
  // addUser 会把当前组关掉；再模拟新的 3 条工具事件
  window.__clawdAddTool('BashTool', '{"command":"pytest -q"}', true);
  window.__clawdAddTool('FileReadTool', '{"file_path":"app.js"}', true);
  window.__clawdAddTool('BashTool', '{"command":"false"}', false, 'Error: exit 1');
  await new Promise((r) => setTimeout(r, 200));
  const groups = document.querySelectorAll('.tool-group');
  const group = groups[groups.length - 1];
  const collapsed = group ? !group.classList.contains('open') : false;
  const summary = (group?.querySelector('.tg-summary')?.textContent || '').trim();
  const items = group ? group.querySelectorAll('.tg-item').length : 0;
  if (group) group.querySelector('.tg-head').click();
  await new Promise((r) => setTimeout(r, 200));
  return {
    groupsAfter: groups.length,
    before,
    collapsedByDefault: collapsed,
    summary,
    items,
    openAfterClick: !!group?.classList.contains('open'),
  };
});
// 断言不能依赖"组数比之前多"：真实 run 已经可能产生过工具组，新事件会复用同一组
check('工具调用默认折叠成一组', fold.collapsedByDefault === true && fold.groupsAfter >= 1, JSON.stringify(fold));
check('折叠标题带分类计数', fold.summary.includes('命令') && fold.summary.includes('读取'), fold.summary);
// 同理：同组里可能已有前序 run 的工具条目，断言"至少 3 条且能展开"
check('展开后逐条可见', fold.items >= 3 && fold.openAfterClick === true, JSON.stringify(fold));

// ---------- 2.8 正文不得露出工具协议原文（真实缺陷：<tool>{...}</tool> 直接显示在气泡里） ----------
const proto = await page.evaluate(() => {
  const raw = '让我用程序分析一下。' + String.fromCharCode(10)
    + '<tool>{"name": "BashTool", "args": {"command": "python3 -c \\"print(1)\\""}}</tool> </tool_call>';
  window.__clawdAddAssistant(raw);
  const last = document.querySelectorAll('#chat .msg-assistant');
  const el = last[last.length - 1];
  const text = el.textContent || '';
  return {
    hasProtocol: text.includes('<tool>') || text.includes('</tool') || text.includes('tool_call'),
    hasSummary: !!el.querySelector('.tool-summary'),
    summaryText: (el.querySelector('.tool-summary')?.textContent || ''),
    bodyText: (el.querySelector('.body')?.textContent || '').slice(0, 80),
  };
});
check('正文不露工具协议原文（折叠成摘要）',
  proto.hasProtocol === false && proto.hasSummary && proto.summaryText.includes('BashTool'),
  JSON.stringify(proto));
await page.screenshot({ path: path.join(DESKTOP, 'screenshots', '26-tool-fold.png') });

// ---------- 2.9 上下文用量面板 ----------
await page.click('#btnContext');
await page.waitForTimeout(1000);
const ctx = await page.evaluate(() => ({
  open: document.querySelector('#ctxOverlay').classList.contains('show'),
  total: (document.querySelector('#ctxTotal')?.textContent || '').trim(),
  items: document.querySelectorAll('#ctxItems .ctx-item').length,
}));
check('上下文面板可用', ctx.open && ctx.items >= 2, JSON.stringify(ctx));
await page.screenshot({ path: path.join(DESKTOP, 'screenshots', '28-context-panel.png') });
await page.evaluate(() => document.querySelector('#ctxClose')?.click());

// ---------- 2.95 项目 / 模型选择器 / 会话计时 ----------
await page.click('#btnAddProject');
await page.waitForTimeout(500);
await page.fill('#projPathInput', process.cwd().replace(/\desktop$/, ''));
await page.click('#projPathSave');
await page.waitForTimeout(1200);
const projects = await page.evaluate(() => ({
  count: document.querySelectorAll('#projectList .project-item').length,
  active: document.querySelectorAll('#projectList .project-item.active').length,
  first: (document.querySelector('#projectList .project-item .p-name')?.textContent || '').trim(),
}));
check('添加项目后出现在侧栏并可选中', projects.count >= 1 && projects.active === 1, JSON.stringify(projects));

await page.click('#btnModel');
await page.waitForTimeout(800);
const modelUi = await page.evaluate(() => ({
  open: document.querySelector('#modelOverlay').classList.contains('show'),
  items: document.querySelectorAll('#modelList .model-item').length,
  efforts: document.querySelectorAll('#modelEffort button').length,
  hasFast: !!document.querySelector('#modelFast'),
}));
check('模型选择器可用（列表+推理强度+快速模式）',
  modelUi.open && modelUi.items >= 1 && modelUi.efforts === 5 && modelUi.hasFast, JSON.stringify(modelUi));
await page.evaluate(() => {
  const fast = document.querySelector('#modelFast'); if (fast) fast.click();
  document.querySelector('#modelClose')?.click();
});
const fastState = await page.evaluate(() => ({
  pressed: document.querySelector('#modelFast')?.getAttribute('aria-pressed'),
  label: (document.querySelector('#modelBtnLabel')?.textContent || ''),
}));
check('快速模式可切换且按钮标注变化',
  fastState.pressed === 'true' && fastState.label.includes('快速'), JSON.stringify(fastState));

// 模型列表要标出"能不能看图"，且 UI 标记必须与后端判定一致
await page.click('#btnModel');
await page.waitForTimeout(600);
const visionUi = await page.evaluate(async () => {
  const r = await fetch('/api/models');
  const d = await r.json();
  const apiVision = (d.models || []).filter((m) => m.vision).length;
  const rows = Array.from(document.querySelectorAll('#modelList .model-item'));
  const uiVision = rows.filter((el) => (el.querySelector('.m-sub')?.textContent || '').includes('👁')).length;
  return { apiVision, uiVision, total: rows.length, hasField: (d.models || []).every((m) => 'vision' in m) };
});
check('模型列表标注视觉能力（UI 与后端一致）',
  visionUi.hasField && visionUi.uiVision === visionUi.apiVision && visionUi.total >= 1,
  JSON.stringify(visionUi));
await page.evaluate(() => document.querySelector('#modelClose')?.click());

// ---------- 2.9 忙时"发送"变"停止"且永远可点（端点挂住也能中断） ----------
const busyUi = await page.evaluate(async () => {
  window.__clawdSetBusy(true);
  await new Promise((r) => setTimeout(r, 120));
  const btn = document.querySelector('#send');
  const on = {
    disabled: btn.disabled,
    stopClass: btn.classList.contains('stop-mode'),
    label: (btn.textContent || '').trim(),
    title: btn.title,
  };
  window.__clawdSetBusy(false);
  await new Promise((r) => setTimeout(r, 120));
  const off = {
    disabled: btn.disabled,
    stopClass: btn.classList.contains('stop-mode'),
    label: (btn.textContent || '').trim(),
  };
  return { on, off };
});
check('忙时按钮变停止且可点（不锁死用户）',
  busyUi.on.disabled === false && busyUi.on.stopClass === true
  && busyUi.off.stopClass === false && busyUi.off.disabled === false,
  JSON.stringify(busyUi));

// ---------- 3. 用量页 ----------
await page.click('#btnUsage');
await page.waitForTimeout(1200);
const usage = await page.evaluate(() => ({
  open: document.querySelector('#usageOverlay').classList.contains('show'),
  panelText: (document.querySelector('#usageKpis')?.textContent || '').slice(0, 160),
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

// ---------- 5. 会话按项目分组 ----------
await page.click('#settingsClose').catch(() => {});
await page.waitForTimeout(300);
const grouped = await page.evaluate(async () => {
  const r = await fetch('/api/sessions');
  const d = await r.json();
  const list = (d.sessions || []);
  const workdirs = new Set(list.map((x) => x.workdir || ''));
  const doc = document.querySelector('#sessionList');
  const heads = doc ? doc.querySelectorAll('.session-group') : [];
  const items = doc ? doc.querySelectorAll('.session-item') : [];
  return {
    api: list.length,
    apiWorkdirs: workdirs.size,
    apiHasWorkdirField: list.length === 0 || list.every((x) => 'workdir' in x),
    heads: heads.length,
    items: items.length,
    headTexts: Array.from(heads).map((h) => h.textContent.trim()).slice(0, 4),
    itemCountsSum: Array.from(doc ? doc.querySelectorAll('.session-group-count') : []).map((c) => Number(c.textContent)).reduce((a, b) => a + b, 0),
  };
});
check('会话接口返回 workdir 字段', grouped.apiHasWorkdirField, JSON.stringify(grouped));
// 侧栏每项目默认只渲染最近 8 条（其余折成"还有 N 条 ▾"），所以 items ≤ api，
// 但**分组标题上的计数必须等于真实总数**（itemCountsSum），否则折叠就变成数据丢失。
check('侧栏分组数 = 唯一项目数 且计数与实际一致',
  grouped.heads === grouped.apiWorkdirs
  && grouped.itemCountsSum === grouped.api
  && grouped.items <= grouped.api && grouped.items > 0,
  JSON.stringify(grouped));
if (grouped.heads > 0) {
  await page.screenshot({ path: path.join(DESKTOP, 'screenshots', '31-session-groups.png') });
}

// ---------- 6. 右下角 toast（更新提示不再挤正文） ----------
const toastInfo = await page.evaluate(() => {
  const handle = window.__clawdToast({ title: 'E2E 更新提示', detail: '右下角非阻塞', kind: 'ok', timeout: 0 });
  const host = document.getElementById('toastHost');
  if (!host || !handle) return { error: 'no-toast-host' };
  const rect = host.getBoundingClientRect();
  const el = host.lastElementChild;
  const text = el ? el.textContent : '';
  const style = el ? getComputedStyle(el) : null;
  const out = {
    count: host.children.length,
    offsetRight: Math.round(window.innerWidth - rect.right),
    offsetBottom: Math.round(window.innerHeight - rect.bottom),
    text,
    position: style ? style.position : '',
    hasActionSlot: !!el.querySelector('.t-btn') || !!el.querySelector('.t-act'),
  };
  handle.close();
  return out;
});
check('toast 出现在右下角',
  !toastInfo.error && toastInfo.offsetRight < 40 && toastInfo.offsetBottom < 40 && toastInfo.text.includes('E2E 更新提示'),
  JSON.stringify(toastInfo));
await page.screenshot({ path: path.join(DESKTOP, 'screenshots', '32-toast.png') });

// ---------- 4.5 会话管理：重命名 / 搜索 / 删除（只用最新那条，不动其它历史） ----------
const admin = await page.evaluate(async () => {
  const r = await fetch('/api/sessions');
  const d = await r.json();
  const target = (d.sessions || [])[0];
  if (!target) return { skip: true };

  // 行内操作按钮存在（悬停才显示，但 DOM 里必须有）
  const rows = Array.from(document.querySelectorAll('#sessionList .session-item'));
  const hasTools = rows.some((el) => el.querySelector('.session-tools .st-btn'));

  const tok = encodeURIComponent(window.__CLAWD_TOKEN__ || '');
  // 安全回归保护：不带 token 的写操作必须被拒（此前可被网页 CSRF 直接删会话/配置）
  const noTok = await fetch('/api/session/delete?id=' + encodeURIComponent(target.id));
  const noTokStatus = noTok.status;

  const q1 = await fetch('/api/session/rename?id=' + encodeURIComponent(target.id)
    + '&title=' + encodeURIComponent('E2E 重命名目标') + '&token=' + tok);
  const renamed = await q1.json();

  const input = document.querySelector('#sessionSearch');
  input.value = 'E2E 重命名目标';
  input.dispatchEvent(new Event('input'));
  await new Promise((res) => setTimeout(res, 900));
  const filtered = document.querySelectorAll('#sessionList .session-item').length;

  const q2 = await fetch('/api/session/delete?id=' + encodeURIComponent(target.id) + '&token=' + tok);
  const deleted = await q2.json();

  input.value = '';
  input.dispatchEvent(new Event('input'));
  await new Promise((res) => setTimeout(res, 700));
  const afterDelete = (await (await fetch('/api/sessions')).json()).count;

  return {
    id: target.id,
    hasTools,
    renamedTitle: renamed.title,
    okRename: !!renamed.ok && renamed.title === 'E2E 重命名目标',
    filtered,
    okDelete: !!deleted.ok,
    noTokStatus,
    afterDelete,
  };
});
check('会话可重命名 + 搜索过滤 + 删除（只动那一条）',
  !admin.skip && admin.hasTools && admin.okRename && admin.filtered === 1 && admin.okDelete,
  JSON.stringify(admin));
check('未带 token 的写操作被拒绝（403）', admin.noTokStatus === 403, JSON.stringify({ noTokStatus: admin.noTokStatus }));

await browser.close();
const failed = results.filter(([, ok]) => !ok);
log(`合计 ${results.length} 项，通过 ${results.length - failed.length}，失败 ${failed.length}`);
process.exit(failed.length === 0 ? 0 : 1);
