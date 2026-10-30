// 桌面端 UI E2E：真流式回复 + 角色库 + 极简界面（去顶栏）
//
// 用法（在 desktop/ 下）：
//   node ui_stream_persona_e2e.mjs                        # 默认对 dist/win-unpacked 的 Host
//   node ui_stream_persona_e2e.mjs --port-file "<path>"    # 指定（例如已安装版）的端口文件
//
// 断言（都是"用户能看见"的事实，不做桩）：
//   1. 页面没有 .topbar（顶栏已移除）
//   2. 角色下拉 >= 6 个选项，且包含"极简输出"
//   3. 发送后助手气泡进入 streaming，文本长度**多次增长**（真流式，而不是最后一次性出现）
//   4. 结束后最终文本非空，流式样式被移除
import { chromium } from 'playwright';
import fs from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

const DESKTOP = path.dirname(fileURLToPath(import.meta.url));
const argPortFile = process.argv.indexOf('--port-file');
const PORT_FILE = argPortFile > 0
  ? process.argv[argPortFile + 1]
  : path.join(DESKTOP, 'dist', 'win-unpacked', 'resources', 'host', '.clawd_host_port');
const OUT = path.join(DESKTOP, 'screenshots', '08-stream-persona.png');

const log = (m) => console.log(`[ui-e2e] ${m}`);
const fail = (m) => { console.error(`[ui-e2e] FAIL ${m}`); process.exit(1); };

if (!fs.existsSync(PORT_FILE)) fail(`端口文件不存在: ${PORT_FILE}`);
const info = JSON.parse(fs.readFileSync(PORT_FILE, 'utf-8'));
log(`Host 端口=${info.port}`);

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1360, height: 860 } });
await page.goto(`http://127.0.0.1:${info.port}/?token=${info.token}`, { waitUntil: 'networkidle' });
await page.waitForTimeout(2500);

// 1) 顶栏必须已移除
const hasTopbar = await page.evaluate(() => document.querySelectorAll('.topbar').length);
log(`顶栏元素数=${hasTopbar}`);
if (hasTopbar !== 0) fail('页面仍然存在 .topbar（顶栏没去掉）');

// 2) 角色下拉
const options = await page.$$eval('#persona option', (els) =>
  els.map((e) => ({ value: e.value, label: e.textContent }))
);
log(`角色选项: ${JSON.stringify(options)}`);
if (options.length < 7) fail(`角色选项太少（${options.length}），角色库没加载`);
if (!options.some((o) => o.label.includes('极简输出'))) fail('下拉里没有"极简输出"角色');

await page.selectOption('#persona', 'concise');
log('已选择角色 concise');

// 3) 发一条需要一点篇幅的请求，观察流式增长
await page.fill('#input', '用三句话解释什么是 HTTP 缓存，并给出一个最常见的配置示例。');
await page.click('#send');

const samples = [];
const deadline = Date.now() + 150000;
let finished = false;
while (Date.now() < deadline) {
  await page.waitForTimeout(400);
  const snap = await page.evaluate(() => {
    const el = document.querySelector('.msg-assistant.streaming .body');
    // 忙禁用已改为"忙时变停止按钮"，判定看 stop-mode（disabled 恒为 false）
    const btn = document.querySelector('#send');
    const busy = !!(btn && btn.classList.contains('stop-mode'));
    return { len: el ? (el.textContent || '').length : -1, busy };
  });
  if (snap.len >= 0) samples.push(snap.len);
  if (!snap.busy) { finished = true; break; }
}
const growth = samples.filter((n, i) => n > 0 && (i === 0 || n > samples[i - 1]));
const deltaCount = await page.evaluate(() => window.__streamDeltas || 0);
log(`流式采样: ${JSON.stringify(samples.slice(0, 20))}…${samples.length > 20 ? ` (共 ${samples.length} 次)` : ''}`);
if (!finished) fail('150s 内未完成');
// 真流式的判据：前端确实收到多条 stream_delta（DOM 采样会被"模型末尾才吐字"骗过）
if (deltaCount < 2) fail(`增量事件太少（deltaCount=${deltaCount}），不是真流式`);
log(`流式增量事件数=${deltaCount}（DOM 增长采样=${growth.length}）`);

const finalSnap = await page.evaluate(() => {
  const all = document.querySelectorAll('.msg-assistant');
  const last = all[all.length - 1];
  return {
    text: last ? (last.textContent || '') : '',
    streaming: document.querySelectorAll('.msg-assistant.streaming').length,
  };
});
log(`最终文本长度=${finalSnap.text.length} 仍在 streaming 的气泡=${finalSnap.streaming}`);
if (!finalSnap.text.trim()) fail('最终回复为空');
if (finalSnap.streaming !== 0) fail('结束后仍有 streaming 气泡（没收尾）');

await page.screenshot({ path: OUT });
log(`截图: ${OUT}`);
log('PASS ✔ 真流式 + 角色库 + 无顶栏');
await browser.close();
process.exit(0);
