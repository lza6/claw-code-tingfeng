/**
 * Clawd Desktop Web UI — DSH 质感版
 *
 * 协议（src/server/handlers.py MessageRouter）:
 *   → auth / run / ping；← 顶层 {type:"error", code} / response / event
 * 市场: GET /api/plugins（Host 提供: 已安装 + 市场目录）
 */
(function () {
  'use strict';

  const TOKEN = (typeof window !== 'undefined' && window.__CLAWD_TOKEN__)
    || new URLSearchParams(location.search).get('token') || '';
  const DEGRADE_THRESHOLD = 64 * 1024;

  let ws = null;
  let authenticated = false;
  let reconnectDelay = 1000;
  let everConnected = false;
  let turnCount = 0;
  let streamEl = null;        // 当前正在流式输出的助手气泡
  let projectsCache = [];
  let activeProject = null;
  let modelsCache = [];
  let selectedModel = '';
  let reasoningEffort = '最大';
  let fastMode = false;
  let sessionStartedAt = 0;
  let elapsedTimer = null;
  let loadedHistory = [];   // 点开旧会话后载入的历史（续聊时作为 prior_messages 发送）
  let attachments = [];     // 待发送图片（data URL）
  let pendingFinal = null;    // 已收到 response 的最终文本，等 STREAM_COMPLETED 收尾
  let finalizedAt = 0;        // 上次收尾时间（用于丢弃迟到 delta）
  let callCount = 0;
  const pending = Object.create(null);
  let reqSeq = 0;

  /** 发送请求并等待同 id 的 response/error（设置面板等一次性调用） */
  function request(type, payload, timeoutMs) {
    return new Promise((resolve, reject) => {
      if (!ws || ws.readyState !== 1) { reject(new Error('未连接')); return; }
      const id = type + '-' + (++reqSeq);
      pending[id] = { resolve, reject };
      ws.send(JSON.stringify(Object.assign({ type: type, id: id }, payload || {})));
      setTimeout(() => {
        if (pending[id]) { delete pending[id]; reject(new Error('请求超时')); }
      }, timeoutMs || 8000);
    });
  }

  const $ = (id) => document.getElementById(id);
  const $conn = $('conn'), $connText = $('connText'), $banner = $('banner');
  const $chat = $('chat'), $trace = $('trace'), $input = $('input'), $send = $('send');

  function setConn(ok, text) {
    $conn.className = 'conn' + (ok ? ' ok' : '');
    $connText.textContent = text;
  }
  function showBanner(t) { $banner.textContent = t; $banner.style.display = 'block'; }
  function hideBanner() { $banner.style.display = 'none'; }

  // —— 右下角 toast ——
  // 非阻塞信息（更新提示等）走这里，不挤占正文；返回句柄支持原地更新同一条。
  function toast(opts) {
    const host = $('toastHost');
    if (!host) return { close() {}, update() {} };
    const o = opts || {};
    const el = document.createElement('div');
    el.className = 'toast' + (o.kind ? ' ' + o.kind : '');
    const ico = document.createElement('span');
    ico.className = 't-ico';
    ico.textContent = o.icon || '🔔';
    const body = document.createElement('div');
    body.className = 't-body';
    const title = document.createElement('div');
    title.className = 't-title';
    const detail = document.createElement('div');
    detail.className = 't-detail';
    const act = document.createElement('div');
    act.className = 't-act';
    body.appendChild(title); body.appendChild(detail); body.appendChild(act);
    const close = document.createElement('button');
    close.className = 't-close';
    close.type = 'button';
    close.textContent = '✕';
    close.title = '关闭';
    el.appendChild(ico); el.appendChild(body); el.appendChild(close);
    host.appendChild(el);

    let timer = null;
    const api = {
      el,
      close() {
        if (timer) { clearTimeout(timer); timer = null; }
        el.classList.add('out');
        setTimeout(() => el.remove(), 180);
      },
      update(next) {
        const n = next || {};
        if (n.kind !== undefined) el.className = 'toast' + (n.kind ? ' ' + n.kind : '');
        if (n.icon !== undefined) ico.textContent = n.icon;
        if (n.title !== undefined) title.textContent = n.title;
        if (n.detail !== undefined) { detail.textContent = n.detail; detail.style.display = n.detail ? '' : 'none'; }
        act.innerHTML = '';
        for (const a of n.actions || []) {
          const b = document.createElement('button');
          b.type = 'button';
          b.className = 't-btn' + (a.primary ? ' primary' : '');
          b.textContent = a.label;
          b.onclick = () => { if (a.onClick) a.onClick(); if (a.keepOpen !== true) api.close(); };
          act.appendChild(b);
        }
        act.style.display = (n.actions || []).length ? '' : 'none';
        if (n.timeout !== undefined) {
          if (timer) { clearTimeout(timer); timer = null; }
          if (n.timeout > 0) timer = setTimeout(() => api.close(), n.timeout);
        }
      },
    };
    close.onclick = () => api.close();
    api.update({ title: o.title || '', detail: o.detail || '', actions: o.actions || [] });
    detail.style.display = o.detail ? '' : 'none';
    act.style.display = (o.actions || []).length ? '' : 'none';
    const timeout = o.timeout === undefined ? 4000 : o.timeout;
    if (timeout > 0) timer = setTimeout(() => api.close(), timeout);
    return api;
  }
  window.__clawdToast = toast;

  function updateStats() {
    $('stTurns').textContent = turnCount + ' 轮';
    $('stCalls').textContent = '工具 ' + callCount + ' 次';
  }

  // —— 消息渲染 ——
  function addUser(text) {
    closeToolGroup();
    const d = document.createElement('div');
    d.className = 'msg-user';
    d.textContent = text;
    $chat.appendChild(d);
    scrollEnd();
  }

  // —— Markdown 渲染（安全：全部用 textContent / createElement，不碰 innerHTML） ——
  // 支持：标题 / 无序·有序列表 / 引用 / 分隔线 / 表格 / 链接 / 图片 / 围栏代码块 / 行内代码 / 粗体斜体
  function renderRich(container, text) {
    container.textContent = '';
    const src = String(text == null ? '' : text).replace(/\r\n/g, '\n');
    const lines = src.split('\n');
    let i = 0;
    while (i < lines.length) {
      const line = lines[i];

      // 围栏代码块 ```lang
      const fence = line.match(/^\s*```\s*([\w+-]*)\s*$/);
      if (fence) {
        const lang = fence[1] || '';
        const buf = [];
        i += 1;
        while (i < lines.length && !/^\s*```\s*$/.test(lines[i])) { buf.push(lines[i]); i += 1; }
        i += 1;
        container.appendChild(makeCodeBlock(buf.join('\n'), lang));
        continue;
      }

      // 标题
      const heading = line.match(/^\s*(#{1,6})\s+(.*)$/);
      if (heading) {
        const level = Math.min(heading[1].length, 3);
        const el = document.createElement('h' + level);
        appendInline(el, heading[2]);
        container.appendChild(el);
        i += 1;
        continue;
      }

      // 分隔线
      if (/^\s*(-{3,}|\*{3,}|_{3,})\s*$/.test(line)) {
        container.appendChild(document.createElement('hr'));
        i += 1;
        continue;
      }

      // 引用
      if (/^\s*>\s?/.test(line)) {
        const block = document.createElement('blockquote');
        const buf = [];
        while (i < lines.length && /^\s*>\s?/.test(lines[i])) {
          buf.push(lines[i].replace(/^\s*>\s?/, ''));
          i += 1;
        }
        appendInline(block, buf.join('\n'));
        container.appendChild(block);
        continue;
      }

      // 表格：| a | b |  +  |---|---|
      if (/^\s*\|.*\|\s*$/.test(line) && i + 1 < lines.length && /^\s*\|[\s:\-|]+\|\s*$/.test(lines[i + 1])) {
        const rows = [];
        const header = splitTableRow(line);
        i += 2;
        while (i < lines.length && /^\s*\|.*\|\s*$/.test(lines[i])) {
          rows.push(splitTableRow(lines[i]));
          i += 1;
        }
        container.appendChild(makeTable(header, rows));
        continue;
      }

      // 无序列表
      if (/^\s*[-*+]\s+/.test(line)) {
        const ul = document.createElement('ul');
        while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
          const li = document.createElement('li');
          appendInline(li, lines[i].replace(/^\s*[-*+]\s+/, ''));
          ul.appendChild(li);
          i += 1;
        }
        container.appendChild(ul);
        continue;
      }

      // 有序列表
      if (/^\s*\d+[.)]\s+/.test(line)) {
        const ol = document.createElement('ol');
        while (i < lines.length && /^\s*\d+[.)]\s+/.test(lines[i])) {
          const li = document.createElement('li');
          appendInline(li, lines[i].replace(/^\s*\d+[.)]\s+/, ''));
          ol.appendChild(li);
          i += 1;
        }
        container.appendChild(ol);
        continue;
      }

      // 普通段落（保留空行分隔）
      if (line.trim() === '') { i += 1; continue; }
      const para = document.createElement('div');
      para.className = 'para';
      appendInline(para, line);
      container.appendChild(para);
      i += 1;
    }
  }

  // E2E 钩子：把渲染器暴露出来，便于用真实浏览器断言 Markdown/图片渲染
  window.__clawdRenderRich = (container, text) => renderRich(container, text);

  function splitTableRow(line) {
    const body = line.trim().replace(/^\|/, '').replace(/\|$/, '');
    return body.split('|').map((c) => c.trim());
  }

  function makeTable(header, rows) {
    const table = document.createElement('table');
    const thead = document.createElement('thead');
    const tr = document.createElement('tr');
    for (const cell of header) {
      const th = document.createElement('th');
      appendInline(th, cell);
      tr.appendChild(th);
    }
    thead.appendChild(tr);
    table.appendChild(thead);
    const tbody = document.createElement('tbody');
    for (const row of rows) {
      const r = document.createElement('tr');
      for (let c = 0; c < header.length; c += 1) {
        const td = document.createElement('td');
        appendInline(td, row[c] == null ? '' : row[c]);
        r.appendChild(td);
      }
      tbody.appendChild(r);
    }
    table.appendChild(tbody);
    return table;
  }

  function makeCodeBlock(code, lang) {
    const wrap = document.createElement('div');
    wrap.className = 'code-wrap';
    const head = document.createElement('div');
    head.className = 'code-head';
    const langEl = document.createElement('span');
    langEl.className = 'lang';
    langEl.textContent = lang || 'text';
    head.appendChild(langEl);
    const copy = document.createElement('button');
    copy.className = 'copy';
    copy.textContent = '复制';
    copy.onclick = () => { navigator.clipboard.writeText(code); copy.textContent = '已复制'; };
    head.appendChild(copy);
    wrap.appendChild(head);
    const pre = document.createElement('pre');
    pre.className = 'code-block';
    const codeEl = document.createElement('code');
    codeEl.textContent = code;
    pre.appendChild(codeEl);
    wrap.appendChild(pre);
    return wrap;
  }

  // 行内：`code` / **粗体** / *斜体* / [文本](链接) / ![alt](图片)
  function appendInline(parent, line) {
    const re = /(`[^`]+`|\*\*[^*]+\*\*|\*[^*\n]+\*|!\[[^\]]*\]\([^)]+\)|\[[^\]]+\]\([^)]+\))/g;
    let last = 0;
    let m;
    while ((m = re.exec(line)) !== null) {
      if (m.index > last) parent.appendChild(document.createTextNode(line.slice(last, m.index)));
      const token = m[0];
      if (token.startsWith('`')) {
        const code = document.createElement('code');
        code.className = 'inline-code';
        code.textContent = token.slice(1, -1);
        parent.appendChild(code);
      } else if (token.startsWith('**')) {
        const strong = document.createElement('strong');
        strong.textContent = token.slice(2, -2);
        parent.appendChild(strong);
      } else if (token.startsWith('*')) {
        const em = document.createElement('em');
        em.textContent = token.slice(1, -1);
        parent.appendChild(em);
      } else if (token.startsWith('![')) {
        const mm = token.match(/^!\[([^\]]*)\]\(([^)]+)\)$/);
        parent.appendChild(makeImage(mm ? mm[1] : '', mm ? mm[2] : ''));
      } else {
        const mm = token.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
        const a = document.createElement('a');
        a.textContent = mm ? mm[1] : token;
        a.href = mm ? mm[2] : '#';
        a.target = '_blank';
        a.rel = 'noreferrer';
        parent.appendChild(a);
      }
      last = m.index + token.length;
    }
    if (last < line.length) parent.appendChild(document.createTextNode(line.slice(last)));
  }

  // 图片：http(s) 直接用；工作区相对路径走 Host 的 /api/file（只放行图片且有路径守卫）
  function makeImage(alt, src) {
    const img = document.createElement('img');
    img.alt = alt || '';
    img.loading = 'lazy';
    if (/^https?:\/\//i.test(src) || src.startsWith('data:image/')) {
      img.src = src;
    } else {
      img.src = '/api/file?path=' + encodeURIComponent(src.replace(/^\.?\//, ''));
    }
    img.onerror = () => {
      const ph = document.createElement('span');
      ph.className = 'inline-code';
      ph.textContent = `[图片加载失败: ${alt || src}]`;
      img.replaceWith(ph);
    };
    return img;
  }

  function addAssistant(text, opts) {
    closeToolGroup();
    const wrap = document.createElement('div');
    wrap.className = 'msg-assistant';
    if (text.length > DEGRADE_THRESHOLD) wrap.classList.add('degraded');
    const who = document.createElement('div');
    who.className = 'who';
    who.textContent = (opts && opts.who) || 'Clawd';
    const body = document.createElement('div');
    body.className = 'body';
    renderRich(body, text);
    const actions = document.createElement('div');
    actions.className = 'msg-actions';
    const copy = document.createElement('button');
    copy.textContent = '复制';
    copy.onclick = () => navigator.clipboard.writeText(text);
    actions.appendChild(copy);
    wrap.appendChild(who); wrap.appendChild(body);
    if (!(opts && opts.streaming)) wrap.appendChild(actions);
    $chat.appendChild(wrap);
    scrollEnd();
    return wrap;
  }

  // —— 流式：开始 / 追加 / 收尾（orca 式：正文边到边显示） ——
  function beginStream() {
    if (streamEl) return streamEl;
    streamEl = addAssistant('', { streaming: true });
    streamEl.classList.add('streaming');
    const caret = document.createElement('span');
    caret.className = 'caret';
    streamEl.querySelector('.body').appendChild(caret);
    return streamEl;
  }
  function appendStream(text) {
    if (!text) return;
    window.__streamDeltas = (window.__streamDeltas || 0) + 1; // E2E 观测点
    if (!streamEl && (Date.now() - finalizedAt) < 3000) return; // 迟到的增量：丢弃
    const el = beginStream();
    const body = el.querySelector('.body');
    const caret = body.querySelector('.caret');
    if (caret) caret.remove();
    body.appendChild(document.createTextNode(text));
    const c2 = document.createElement('span');
    c2.className = 'caret';
    body.appendChild(c2);
    scrollEnd();
  }
  function endStream(finalText) {
    if (!streamEl) return false;
    const body = streamEl.querySelector('.body');
    const caret = body.querySelector('.caret');
    if (caret) caret.remove();
    if (typeof finalText === 'string' && finalText.trim()) renderRich(body, finalText);
    streamEl.classList.remove('streaming');
    const text = body.textContent || '';
    if (text.length > DEGRADE_THRESHOLD) streamEl.classList.add('degraded');
    const actions = document.createElement('div');
    actions.className = 'msg-actions';
    const copy = document.createElement('button');
    copy.textContent = '复制';
    copy.onclick = () => navigator.clipboard.writeText(text);
    actions.appendChild(copy);
    streamEl.appendChild(actions);
    streamEl = null;
    finalizedAt = Date.now();
    scrollEnd();
    return true;
  }

  // 收尾当前流式气泡（若没有则不做事），优先用 response 给的最终文本
  function finalizeStream() {
    if (!streamEl) return false;
    const text = pendingFinal;
    pendingFinal = null;
    return endStream(text || '');
  }

  function addError(text) {
    pendingFinal = null;
    endStream('');
    const d = document.createElement('div');
    d.className = 'msg-err';
    d.textContent = '⚠ ' + text;
    $chat.appendChild(d);
    scrollEnd();
  }

  // —— 工具调用：折叠成一组（参考 orca 的 "运行 36 命令 和 编辑 5 文件 ⌄"） ——
  const TOOL_KIND_LABEL = {
    bash: '命令', file_read: '读取', file_write: '编辑', grep: '搜索',
    glob: '查找', lsp: '代码智能', world: '世界模型', other: '工具',
  };

  function toolKind(name) {
    const n = String(name || '').toLowerCase();
    if (n.includes('bash') || n.includes('shell') || n.includes('command')) return 'bash';
    if (n.includes('edit') || n.includes('write') || n.includes('patch')) return 'file_write';
    if (n.includes('read')) return 'file_read';
    if (n.includes('grep') || n.includes('search')) return 'grep';
    if (n.includes('glob') || n.includes('list') || n.includes('find')) return 'glob';
    if (n.includes('lsp')) return 'lsp';
    if (n.includes('world') || n.includes('map')) return 'world';
    return 'other';
  }

  let toolGroup = null; // {el, listEl, summaryEl, counts, running}

  function closeToolGroup() { toolGroup = null; }

  function ensureToolGroup() {
    if (toolGroup) return toolGroup;
    const el = document.createElement('div');
    el.className = 'tool-group';

    const head = document.createElement('button');
    head.className = 'tg-head';
    const chev = document.createElement('span');
    chev.className = 'tg-chev';
    chev.textContent = '⌄';
    const summary = document.createElement('span');
    summary.className = 'tg-summary';
    summary.textContent = '工具调用';
    head.appendChild(chev);
    head.appendChild(summary);

    const list = document.createElement('div');
    list.className = 'tg-list';

    head.onclick = () => {
      el.classList.toggle('open');
      chev.textContent = el.classList.contains('open') ? '⌃' : '⌄';
    };

    el.appendChild(head);
    el.appendChild(list);
    $chat.appendChild(el);
    toolGroup = { el, listEl: list, summaryEl: summary, counts: {}, running: 0 };
    return toolGroup;
  }

  function describeGroup(group) {
    const parts = [];
    for (const [kind, n] of Object.entries(group.counts)) {
      if (!n) continue;
      parts.push(`${TOOL_KIND_LABEL[kind] || kind} ${n}`);
    }
    const tail = group.running > 0 ? ' · 执行中…' : '';
    return parts.length ? `${parts.join(' · ')}${tail}` : `工具调用${tail}`;
  }

  function addToolEvent(name, argsText, ok, detail) {
    callCount += 1; updateStats();
    const group = ensureToolGroup();
    const kind = toolKind(name);
    group.counts[kind] = (group.counts[kind] || 0) + 1;
    group.summaryEl.textContent = describeGroup(group);

    const row = document.createElement('div');
    row.className = 'tg-item' + (ok === false ? ' failed' : '');
    const icon = document.createElement('span');
    icon.className = 'tg-item-ico';
    icon.textContent = ok === false ? '✗' : '▸';
    const nameEl = document.createElement('span');
    nameEl.className = 'tg-item-name';
    nameEl.textContent = name || 'tool';
    const argEl = document.createElement('span');
    argEl.className = 'tg-item-arg';
    argEl.textContent = String(argsText || '').slice(0, 120);
    row.appendChild(icon); row.appendChild(nameEl); row.appendChild(argEl);
    if (detail) {
      const det = document.createElement('div');
      det.className = 'tg-item-detail';
      det.textContent = String(detail).slice(0, 2000);
      row.appendChild(det);
      row.onclick = (ev) => { ev.stopPropagation(); row.classList.toggle('show-detail'); };
    }
    group.listEl.appendChild(row);
    scrollEnd();

    // 轨迹区保留完整时间线
    const tr = document.createElement('div');
    tr.className = 'tool-row open';
    const lab = document.createElement('span'); lab.className = 't-label';
    lab.textContent = `${ok === false ? '✗' : '✓'} ${name} ${String(argsText || '').slice(0, 100)}`;
    const det = document.createElement('div'); det.className = 't-detail';
    det.textContent = detail || '(无输出)';
    tr.appendChild(lab); tr.appendChild(det);
    $trace.appendChild(tr);
  }

  // E2E 钩子：把工具分组暴露出来，便于用真实浏览器断言折叠行为（不改变运行逻辑）
  window.__clawdAddTool = (name, args, ok, detail) => addToolEvent(name, args, ok, detail);

  // 兼容旧调用（其它地方还在用 addToolRow）
  function addToolRow(label, detail) {
    const name = String(label || '').replace(/^[^A-Za-z\u4e00-\u9fa5]+/, '').split(/[ :（(]/)[0] || 'tool';
    addToolEvent(name, '', null, detail);
  }

  // 仅当用户「本来就在底部附近」时才自动跟随；否则保持用户位置（消息一多也能往上翻）
  const NEAR_BOTTOM_PX = 96;
  function isNearBottom() {
    const view = document.querySelector('.view');
    if (!view) return true;
    return view.scrollHeight - view.scrollTop - view.clientHeight < NEAR_BOTTOM_PX;
  }
  function scrollEnd(force) {
    const view = document.querySelector('.view');
    if (!view) return;
    if (force || isNearBottom()) {
      view.scrollTop = view.scrollHeight;
      hideJump();
    } else {
      showJump();
    }
  }
  function showJump() { const b = $('jumpBottom'); if (b) b.classList.add('show'); }
  function hideJump() { const b = $('jumpBottom'); if (b) b.classList.remove('show'); }
  document.addEventListener('DOMContentLoaded', () => {
    const view = document.querySelector('.view');
    const btn = $('jumpBottom');
    if (btn) btn.onclick = () => scrollEnd(true);
    if (view) view.addEventListener('scroll', () => { isNearBottom() ? hideJump() : showJump(); });
  });

  // —— WS（断流重连） ——
  function connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    setConn(false, '连接中…');
    try { ws = new WebSocket(proto + '://' + location.host + '/ws'); }
    catch (_) { scheduleReconnect(); return; }

    ws.onopen = () => ws.send(JSON.stringify({ type: 'auth', token: TOKEN, id: 'auth' }));
    ws.onmessage = (ev) => { try { handleMessage(JSON.parse(ev.data)); } catch (_) {} };
    ws.onclose = () => {
      authenticated = false;
      setConn(false, '已断开');
      if (everConnected) showBanner('连接已断开，正在重连…');
      scheduleReconnect();
    };
    ws.onerror = () => {};
  }
  function scheduleReconnect() {
    setTimeout(connect, reconnectDelay);
    reconnectDelay = Math.min(reconnectDelay * 1.5, 10000);
  }

  function handleMessage(msg) {
    if (msg.type === 'error') {
      if (msg.code === 'E_AUTH_REQUIRED') return;
      addError(msg.message || msg.code);
      $send.disabled = false;
      return;
    }
    if (msg.type === 'response' && pending[msg.id]) {
      const { resolve } = pending[msg.id];
      delete pending[msg.id];
      resolve({ ok: true, data: msg.data || msg.result || {} });
      return;
    }
    if (msg.type === 'error' && msg.id && pending[msg.id]) {
      const { reject } = pending[msg.id];
      delete pending[msg.id];
      reject(new Error(msg.message || msg.code || '请求失败'));
      return;
    }
    if (msg.type === 'error' && pending[msg.id]) {
      return;
    }
    if (msg.type === 'response') {
      if (msg.id === 'auth') {
        // Host 响应: {id:'auth', type:'response', data:{status:'authenticated'}}
        const ok = msg.data?.status === 'authenticated' || msg.result;
        if (ok) {
          authenticated = true; reconnectDelay = 1000; everConnected = true;
          hideBanner(); setConn(true, '已连接 · 就绪');
          loadPersonas();
          loadProjects();
          loadModels();
          loadSessions();
        } else {
          setConn(false, '认证失败');
          showBanner('认证失败：token 无效。请通过 Host 入口访问。');
        }
        return;
      }
      // personas 响应: {id, type:'response', data:{personas:[...]}}
      const d0 = msg.data || msg.result || {};
      if (d0 && Array.isArray(d0.personas)) { applyPersonas(d0.personas); return; }
      // run 响应: {id, type:'response', data:{status, result, steps, elapsed_seconds}}
      const d = msg.data || msg.result || {};
      if (typeof d === 'object' && d.status === 'completed') {
        if (streamEl) {
          pendingFinal = d.result || '';
          setTimeout(() => { if (streamEl) finalizeStream(); }, 1200);
        } else {
          addAssistant(d.result || '(无输出)');
        }
        const st = $('stTurns');
        st.textContent = `${turnCount} 轮`;
        if (d.elapsed_seconds) $('stCalls').textContent = `工具 ${callCount} 次 · ${d.elapsed_seconds}s · ${d.steps} 步`;
        $send.disabled = false;
        stopElapsed();
        loadSessions(); // 跑完一轮刷新侧栏历史
        return;
      }
      const out = typeof d === 'string' ? d : (d.result || JSON.stringify(d, null, 2));
      if (out && out !== 'null') addAssistant(out);
      $send.disabled = false;
    }
    if (msg.type === 'event') {
      const d = msg.data || {};
      const raw = msg.event || d.type || 'event';
      // 事件名美化（DSH 式轻量折叠行）
      const LABELS = {
        AGENT_TASK_STARTED: ['▶', '任务开始'],
        AGENT_TASK_COMPLETED: ['✔', '任务完成'],
        AGENT_TASK_ERROR: ['✖', '任务出错'],
        AGENT_LLM_CALL_STARTED: ['…', 'LLM 调用中'],
        AGENT_LLM_CALL_COMPLETED: ['✔', 'LLM 调用完成'],
        AGENT_TOOL_EXEC_STARTED: ['⚙', null],  // 标签动态生成
        AGENT_TOOL_EXEC_COMPLETED: ['✓', null],
        AGENT_TOKEN_USAGE: ['$', 'Token 统计'],
      };
      if (raw === 'AGENT_STREAM_STARTED') { beginStream(); return; }
      if (raw === 'AGENT_STREAM_DELTA') { appendStream(d.text || ''); return; }
      if (raw === 'AGENT_STREAM_COMPLETED') { finalizeStream(); return; }
      if (raw === 'AGENT_TOOL_EXEC_STARTED') {
        const group = ensureToolGroup();
        group.running += 1;
        group.summaryEl.textContent = describeGroup(group);
        addToolEvent(d.tool_name || '?', JSON.stringify(d.tool_args || {}), null, '');
        const g2 = ensureToolGroup();
        g2.running = Math.max(0, g2.running - 1);
        g2.summaryEl.textContent = describeGroup(g2);
        return;
      }
      if (raw === 'AGENT_TOOL_EXEC_COMPLETED') {
        const argsText = JSON.stringify(d.tool_args || {});
        addToolEvent(d.tool_name || '?', argsText, d.success !== false, d.success === false ? '(失败)' : '');
        return;
      }

      const [ico, fixedLabel] = LABELS[raw] || ['·', raw];
      let label;
      if (raw === 'AGENT_LLM_CALL_STARTED') {
        label = `LLM 第 ${d.iteration || '?'} 轮`;
      } else if (raw === 'AGENT_LLM_CALL_COMPLETED') {
        label = `LLM 第 ${d.iteration || '?'} 轮完成 (${d.usage?.total_tokens || 0} tok)`;
      } else if (raw === 'AGENT_TASK_COMPLETED') {
        return; // 与 response 重复，跳过（最终回复由 response 渲染）
      } else if (raw === 'AGENT_TASK_STARTED') {
        // 同一次 run 可能双发（handlers + engine_events），去重
        if ($chat.querySelector('.tool-row')) return;
        label = fixedLabel;
      } else {
        label = fixedLabel || JSON.stringify(d).slice(0, 120);
      }
      const detail = JSON.stringify(d, null, 2);
      const tr = document.createElement('div');
      tr.className = 'tool-row open';
      const lab = document.createElement('span');
      lab.className = 't-label';
      lab.textContent = `${ico} ${label}`;
      const det = document.createElement('div');
      det.className = 't-detail';
      det.textContent = detail;
      tr.appendChild(lab); tr.appendChild(det);
      $trace.appendChild(tr);
      return;
    }
    addToolRow(msg.type || '?', JSON.stringify(msg, null, 2).slice(0, 4000));
  }

  // —— 上下文用量面板 ——
  function fmtTok(n) {
    const v = Number(n || 0);
    if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(1) + 'k';
    return String(Math.round(v));
  }

  async function openContext() {
    $('ctxOverlay').classList.add('show');
    const totalEl = $('ctxTotal');
    const itemsEl = $('ctxItems');
    totalEl.textContent = '加载中…';
    itemsEl.innerHTML = '';
    try {
      const data = await fetchJsonRetry('/api/context', 2);
      totalEl.textContent = fmtTok(data.used) + ' / ' + fmtTok(data.context_window)
        + '（' + (Number(data.used_percent || 0) * 100).toFixed(0) + '%）';
      $('ctxBarFill').style.width = Math.min(100, Number(data.used_percent || 0) * 100) + '%';
      for (const item of (data.items || [])) {
        const row = document.createElement('div');
        row.className = 'ctx-item';
        const label = document.createElement('span');
        label.className = 'ck-label';
        label.textContent = item.label;
        const val = document.createElement('span');
        val.className = 'ck-val';
        val.textContent = fmtTok(item.tokens) + ' · ' + (Number(item.percent || 0) * 100).toFixed(1) + '%';
        row.appendChild(label); row.appendChild(val);
        itemsEl.appendChild(row);
        if (item.note) {
          const note = document.createElement('div');
          note.className = 'ck-note';
          note.textContent = item.note;
          itemsEl.appendChild(note);
        }
      }
    } catch (e) {
      totalEl.textContent = '上下文统计不可用: ' + e.message;
    }
  }

  // —— 图片附件（粘贴 / 拖拽）：交给 Host 落盘，模型能读到路径；不支持视觉就如实说看不到 ——
  function renderAttachments() {
    const bar = $('attachBar');
    if (!bar) return;
    bar.innerHTML = '';
    bar.classList.toggle('show', attachments.length > 0);
    attachments.forEach((a, idx) => {
      const chip = document.createElement('div');
      chip.className = 'attach-chip';
      const img = document.createElement('img');
      img.src = a.dataUrl;
      img.alt = a.name || 'image';
      const del = document.createElement('button');
      del.textContent = 'x';
      del.title = '移除';
      del.onclick = () => { attachments.splice(idx, 1); renderAttachments(); };
      chip.appendChild(img); chip.appendChild(del);
      // 当前模型不支持看图时说清楚，别让用户以为模型"装看不见"
      const cur = (modelsCache || []).find((m) => m.id === selectedModel);
      if (cur && cur.vision === false) {
        chip.title = '当前模型不支持图像输入：图片会保存到本机，模型只能看到路径';
        chip.classList.add('no-vision');
      } else if (cur && cur.vision) {
        chip.title = '当前模型支持看图：图片会作为图像内容一起发送';
      }
      bar.appendChild(chip);
    });
  }

  function clearAttachments() {
    attachments = [];
    renderAttachments();
  }

  function addFiles(fileList) {
    for (const file of Array.from(fileList || [])) {
      if (!file || !file.type || !file.type.startsWith('image/')) continue;
      if (attachments.length >= 4) break;
      const reader = new FileReader();
      reader.onload = () => {
        attachments.push({ name: file.name || 'pasted.png', dataUrl: String(reader.result || '') });
        renderAttachments();
      };
      reader.readAsDataURL(file);
    }
  }

  const composerEl = $('composer');
  const inputEl = $('input');
  if (inputEl) {
    inputEl.addEventListener('paste', (e) => {
      const items = (e.clipboardData || {}).items || [];
      const files = [];
      for (const it of items) {
        if (it.kind === 'file') { const f = it.getAsFile(); if (f) files.push(f); }
      }
      if (files.length) { e.preventDefault(); addFiles(files); }
    });
  }
  if (composerEl) {
    ['dragenter', 'dragover'].forEach((ev) => composerEl.addEventListener(ev, (e) => {
      e.preventDefault(); composerEl.classList.add('dragover');
    }));
    ['dragleave', 'drop'].forEach((ev) => composerEl.addEventListener(ev, (e) => {
      e.preventDefault(); composerEl.classList.remove('dragover');
    }));
    composerEl.addEventListener('drop', (e) => {
      addFiles((e.dataTransfer && e.dataTransfer.files) || []);
    });
  }

  // —— 用量统计页 ——
  function openUsage() {
    $('usageOverlay').classList.add('show');
    loadUsage();
  }
  function closeUsage() { $('usageOverlay').classList.remove('show'); }

  function fmtNum(n) {
    const v = Number(n || 0);
    if (v >= 1e9) return (v / 1e9).toFixed(2) + 'B';
    if (v >= 1e6) return (v / 1e6).toFixed(2) + 'M';
    if (v >= 1e3) return (v / 1e3).toFixed(1) + 'K';
    return String(v);
  }
  function fmtTime(ts) {
    const d = new Date(Number(ts) * 1000);
    return d.toLocaleString('zh-CN', { hour12: false });
  }

  // Host 刚结束一轮任务时可能短暂不可用（同一端口上 WS/HTTP 共用一个事件循环）：
  // 一次失败就清空面板对用户是"莫名其妙空了"，所以这里做一次短重试。
  async function fetchJsonRetry(url, attempts = 3, delayMs = 700) {
    let lastErr = null;
    for (let i = 0; i < attempts; i += 1) {
      try {
        const resp = await fetch(url, { cache: 'no-store' });
        if (!resp.ok) throw new Error('HTTP ' + resp.status);
        return await resp.json();
      } catch (e) {
        lastErr = e;
        await new Promise((r) => setTimeout(r, delayMs * (i + 1)));
      }
    }
    throw lastErr;
  }

  let usageRange = 'today';
  async function loadUsage() {
    const kpis = $('usageKpis');
    const rowsEl = $('usageRows');
    kpis.innerHTML = '<div class="usage-empty">加载中…</div>';
    try {
      const data = await fetchJsonRetry('/api/usage?range=' + encodeURIComponent(usageRange));
      const t = data.totals || {};
      kpis.innerHTML = '';
      const cards = [
        ['总成本', '$' + Number(t.cost || 0).toFixed(4), '累计（今天）'],
        ['总请求数', String(t.requests || 0), '今天'],
        ['真实消耗 Tokens', fmtNum(t.total_tokens), `新增输入 ${fmtNum(t.prompt_tokens)} / 输出 ${fmtNum(t.completion_tokens)}`],
        ['缓存命中率', (Number(t.cache_hit_rate || 0) * 100).toFixed(1) + '%', `缓存读 ${fmtNum(t.cache_read_tokens)}`],
      ];
      for (const [label, value, sub] of cards) {
        const div = document.createElement('div');
        div.className = 'kpi';
        div.innerHTML = '<div class="k-label"></div><div class="k-value"></div><div class="k-sub"></div>';
        div.querySelector('.k-label').textContent = label;
        div.querySelector('.k-value').textContent = value;
        div.querySelector('.k-sub').textContent = sub;
        kpis.appendChild(div);
      }
      drawUsageChart(data.hourly || []);
      renderUsageRows(data.recent || []);
    } catch (e) {
      kpis.innerHTML = '';
      const div = document.createElement('div');
      div.className = 'usage-empty';
      div.textContent = '用量服务不可用（Host 未提供 /api/usage）: ' + e;
      kpis.appendChild(div);
    }
  }

  function drawUsageChart(hourly) {
    const svg = $('usageChart');
    svg.innerHTML = '';
    const W = 800, H = 180, pad = 26;
    const NS = 'http://www.w3.org/2000/svg';
    if (!hourly.length) {
      const tx = document.createElementNS(NS, 'text');
      tx.setAttribute('x', String(W / 2)); tx.setAttribute('y', String(H / 2));
      tx.setAttribute('fill', '#8a8a8a'); tx.setAttribute('text-anchor', 'middle');
      tx.setAttribute('font-size', '12');
      tx.textContent = '暂无数据';
      svg.appendChild(tx);
      return;
    }
    const max = Math.max(...hourly.map((h) => Number(h.tokens || 0)), 1);
    const slot = (W - pad * 2) / hourly.length;
    const bw = Math.min(slot * 0.7, 42);  // 柱宽上限：只有 1~2 个小时时不要把柱子糊满
    [0, 0.5, 1].forEach((ratio) => {
      const y = H - pad - (H - pad * 2) * ratio;
      const line = document.createElementNS(NS, 'line');
      line.setAttribute('x1', String(pad)); line.setAttribute('x2', String(W - pad));
      line.setAttribute('y1', String(y)); line.setAttribute('y2', String(y));
      line.setAttribute('stroke', '#3a3a3a'); line.setAttribute('stroke-dasharray', '3 3');
      svg.appendChild(line);
      const tick = document.createElementNS(NS, 'text');
      tick.setAttribute('x', String(pad - 6)); tick.setAttribute('y', String(y + 3));
      tick.setAttribute('fill', '#8a8a8a'); tick.setAttribute('font-size', '9');
      tick.setAttribute('text-anchor', 'end');
      tick.textContent = fmtNum(Math.round(max * ratio));
      svg.appendChild(tick);
    });
    hourly.forEach((h, idx) => {
      const v = Number(h.tokens || 0);
      const bh = Math.max(2, (H - pad * 2) * (v / max));
      const rect = document.createElementNS(NS, 'rect');
      rect.setAttribute('x', String(pad + idx * slot + (slot - bw) / 2));
      rect.setAttribute('y', String(H - pad - bh));
      rect.setAttribute('width', String(bw));
      rect.setAttribute('height', String(bh));
      rect.setAttribute('rx', '3');
      rect.setAttribute('fill', '#2ca6b8');
      const title = document.createElementNS(NS, 'title');
      title.textContent = `${h.time_label || ''} ${fmtNum(v)} tokens · $${Number(h.cost || 0).toFixed(4)}`;
      rect.appendChild(title);
      svg.appendChild(rect);
      const label = document.createElementNS(NS, 'text');
      label.setAttribute('x', String(pad + idx * slot + slot / 2));
      label.setAttribute('y', String(H - 8));
      label.setAttribute('fill', '#8a8a8a');
      label.setAttribute('font-size', '10');
      label.setAttribute('text-anchor', 'middle');
      const dt = new Date(Number(h.bucket) * 1000);
      label.textContent = String(dt.getHours()).padStart(2, '0') + ':00';
      svg.appendChild(label);
    });
  }

  function renderUsageRows(rows) {
    const el = $('usageRows');
    const empty = $('usageEmpty');
    el.innerHTML = '';
    if (!rows.length) { empty.style.display = ''; return; }
    empty.style.display = 'none';
    for (const r of rows) {
      const tr = document.createElement('tr');
      const cells = [
        fmtTime(r.ts), r.client || '-', r.provider || '-', r.model || '-',
        '$' + Number(r.cost || 0).toFixed(4), fmtNum(r.prompt_tokens), fmtNum(r.completion_tokens),
        fmtNum(r.cache_read_tokens), String(r.steps || 0), r.status || '-',
      ];
      cells.forEach((c, idx) => {
        const td = document.createElement('td');
        if (idx >= 4 && idx <= 8) td.className = 'num';
        td.textContent = c;
        tr.appendChild(td);
      });
      el.appendChild(tr);
    }
  }

  // —— 多 provider 设置 ——
  let providersCache = [];

  function wsRequest(payload, idPrefix) {
    return new Promise((resolve, reject) => {
      if (!ws || ws.readyState !== 1) return reject(new Error('未连接'));
      const id = (idPrefix || 'req') + '-' + Date.now() + '-' + Math.floor(Math.random() * 1e4);
      pending[id] = { resolve, reject };
      ws.send(JSON.stringify({ ...payload, id }));
      setTimeout(() => {
        if (pending[id]) { delete pending[id]; reject(new Error('请求超时: ' + (payload.type || ''))); }
      }, 15000);
    });
  }

  async function loadProviders() {
    try {
      const res = await wsRequest({ type: 'providers_list' }, 'providers');
      providersCache = (res.data && res.data.providers) || [];
    } catch (_) {
      try {
        const data = await fetchJsonRetry('/api/providers', 2);
        providersCache = data.providers || [];
      } catch (__) { providersCache = []; }
    }
    renderProviders();
  }

  function renderProviders() {
    const list = $('provList');
    if (!list) return;
    list.innerHTML = '';
    if (!providersCache.length) {
      const div = document.createElement('div');
      div.className = 'usage-empty';
      div.textContent = '还没有配置提供商 —— 填下面的表单保存一个（密钥建议用环境变量名）。';
      list.appendChild(div);
      return;
    }
    for (const p of providersCache) {
      const item = document.createElement('div');
      item.className = 'prov-item' + (p.is_default ? ' active' : '');
      const info = document.createElement('div');
      const name = document.createElement('div');
      name.className = 'p-name';
      name.textContent = p.name + (p.is_default ? ' · 默认' : '');
      const sub = document.createElement('div');
      sub.className = 'p-sub';
      sub.textContent = `${p.kind} · ${p.model || '未填模型'} · ${p.key_env ? 'env:' + p.key_env : (p.key_masked || '无密钥')}`;
      info.appendChild(name); info.appendChild(sub);
      item.appendChild(info);
      const actions = document.createElement('div');
      actions.className = 'p-actions';
      const mk = (label, fn) => { const b = document.createElement('button'); b.textContent = label; b.onclick = fn; return b; };
      actions.appendChild(mk('设为默认', async () => {
        await wsRequest({ type: 'providers_set_default', id_value: p.id }, 'provdef');
        await loadProviders();
        const note = $('setNote');
        if (note) { note.className = 'snote ok'; note.textContent = '已设为默认，下一轮对话生效'; }
        loadUsage();
      }));
      actions.appendChild(mk('编辑', () => {
        $('provId').value = p.id; $('provName').value = p.name; $('provKind').value = p.kind;
        $('provModel').value = p.model || ''; $('provBaseUrl').value = p.base_url || '';
        $('provKeyEnv').value = p.key_env || ''; $('provKey').value = '';
      }));
      actions.appendChild(mk('删除', async () => {
        await wsRequest({ type: 'providers_delete', id_value: p.id }, 'provdel');
        await loadProviders();
      }));
      item.appendChild(actions);
      list.appendChild(item);
    }
  }

  async function saveProviderFromForm() {
    const payload = {
      id: $('provId').value.trim(),
      name: $('provName').value.trim(),
      kind: $('provKind').value,
      model: $('provModel').value.trim(),
      base_url: $('provBaseUrl').value.trim(),
      key_env: $('provKeyEnv').value.trim(),
      key: $('provKey').value.trim(),
    };
    const note = $('setNote');
    try {
      await wsRequest({ type: 'providers_save', provider: payload }, 'provsave');
      note.className = 'snote ok';
      note.textContent = '提供商已保存';
      $('provKey').value = '';
      await loadProviders();
    } catch (e) {
      note.className = 'snote err';
      note.textContent = '保存失败: ' + e.message;
    }
  }

  // —— 项目（工作区）——
  async function loadProjects() {
    const list = $('projectList');
    if (!list) return;
    try {
      const data = await wsRequest({ type: 'projects_list' }, 'projects');
      projectsCache = (data.data && data.data.projects) || [];
      activeProject = (data.data && data.data.active) || null;
    } catch (_) {
      try {
        const resp = await fetch('/api/projects');
        const data = await resp.json();
        projectsCache = data.projects || [];
        activeProject = data.active || null;
      } catch (__) { projectsCache = []; }
    }
    renderProjects();
  }

  function renderProjects() {
    const list = $('projectList');
    if (!list) return;
    list.innerHTML = '';
    if (!projectsCache.length) {
      const empty = document.createElement('div');
      empty.className = 'session-item';
      empty.style.cssText = 'font-size:12px;color:var(--label-tertiary);cursor:default';
      empty.textContent = '还没有项目 —— 点上面的 ＋ 添加';
      list.appendChild(empty);
      return;
    }
    for (const project of projectsCache) {
      const row = document.createElement('div');
      row.className = 'project-item' + (project.is_active ? ' active' : '');
      const ico = document.createElement('span');
      ico.className = 'p-ico';
      ico.textContent = '📁';
      const name = document.createElement('span');
      name.className = 'p-name';
      name.textContent = project.name || project.path;
      name.title = project.path + (project.exists ? '' : '（目录不存在）');
      const del = document.createElement('button');
      del.className = 'p-del';
      del.textContent = '✕';
      del.title = '从列表移除（不删文件）';
      del.onclick = async (ev) => {
        ev.stopPropagation();
        await wsRequest({ type: 'projects_remove', project_id: project.id }, 'projrm');
        await loadProjects();
      };
      row.appendChild(ico); row.appendChild(name); row.appendChild(del);
      row.onclick = async () => {
        await wsRequest({ type: 'projects_set_active', project_id: project.id }, 'projact');
        await loadProjects();
        await loadSessions();
        $('sessionScope').textContent = (project.name || '当前项目');
      };
      list.appendChild(row);
    }
  }

  async function addProjectByPath(path, name) {
    const note = $('projNote');
    try {
      await wsRequest({ type: 'projects_add', path, name: name || '' }, 'projadd');
      if (note) { note.className = 'snote ok'; note.textContent = '已添加：' + path; }
      await loadProjects();
      return true;
    } catch (e) {
      if (note) { note.className = 'snote err'; note.textContent = '添加失败: ' + e.message; }
      return false;
    }
  }

  async function pickFolder() {
    const api = window.clawdDesktop;
    if (api && typeof api.pickFolder === 'function') {
      try {
        const picked = await api.pickFolder();
        if (picked) await addProjectByPath(picked);
        return;
      } catch (_) { /* 落到手动输入 */ }
    }
    const input = $('projPathInput');
    if (input) { input.focus(); input.placeholder = '当前环境没有原生选择器，请粘贴路径'; }
  }

  async function cloneProject(url) {
    const note = $('projNote');
    if (!url) { if (note) { note.className = 'snote err'; note.textContent = '请先填仓库 URL'; } return; }
    if (note) { note.className = 'snote'; note.textContent = '克隆中…'; }
    try {
      await wsRequest({ type: 'projects_clone', url }, 'projclone');
      if (note) { note.className = 'snote ok'; note.textContent = '克隆完成'; }
      await loadProjects();
    } catch (e) {
      if (note) { note.className = 'snote err'; note.textContent = '克隆失败: ' + e.message; }
    }
  }

  // —— 模型选择器 ——
  async function loadModels() {
    try {
      const res = await wsRequest({ type: 'models_list' }, 'models');
      modelsCache = (res.data && res.data.models) || [];
      if (!selectedModel && modelsCache.length) selectedModel = modelsCache[0].id;
    } catch (_) {
      try {
        const resp = await fetch('/api/models');
        const data = await resp.json();
        modelsCache = data.models || [];
        if (!selectedModel && modelsCache.length) selectedModel = modelsCache[0].id;
      } catch (__) { modelsCache = []; }
    }
    renderModelList();
    updateModelButton();
  }

  function updateModelButton() {
    const label = $('modelBtnLabel');
    if (!label) return;
    const short = String(selectedModel || '').split('/').pop() || '模型';
    label.textContent = short + (fastMode ? ' · 快速' : '');
  }

  function renderModelList() {
    const list = $('modelList');
    if (!list) return;
    const keyword = ($('modelSearch').value || '').toLowerCase();
    list.innerHTML = '';
    const items = modelsCache.filter((m) =>
      !keyword || (m.id + ' ' + (m.label || '')).toLowerCase().includes(keyword));
    if (!items.length) {
      const empty = document.createElement('div');
      empty.className = 'usage-empty';
      empty.textContent = '没有可用模型 —— 先在设置里加一个 API 提供商';
      list.appendChild(empty);
      return;
    }
    for (const model of items) {
      const row = document.createElement('div');
      row.className = 'model-item' + (model.id === selectedModel ? ' active' : '');
      const idEl = document.createElement('span');
      idEl.className = 'm-id';
      idEl.textContent = model.id;
      const subEl = document.createElement('span');
      subEl.className = 'm-sub';
      subEl.textContent = (model.label || '')
        + (model.source === 'global' ? ' · 全局默认' : '')
        + (model.vision ? ' · 👁 可看图' : '');
      if (model.vision) subEl.title = '这个模型支持图像输入：粘贴的图片会以图像内容块发送';
      row.appendChild(idEl); row.appendChild(subEl);
      row.onclick = () => {
        selectedModel = model.id;
        renderModelList();
        updateModelButton();
        $('modelOverlay').classList.remove('show');
      };
      list.appendChild(row);
    }
  }

  function openModelPicker() {
    $('modelOverlay').classList.add('show');
    loadModels();
    $('modelSearch').value = '';
    setTimeout(() => $('modelSearch').focus(), 50);
  }

  // —— 会话计时 ——
  function startElapsed() {
    sessionStartedAt = Date.now();
    if (elapsedTimer) clearInterval(elapsedTimer);
    elapsedTimer = setInterval(() => {
      const el = $('sessionElapsed');
      if (!el) return;
      const sec = Math.floor((Date.now() - sessionStartedAt) / 1000);
      el.textContent = '工作了 ' + (sec >= 60 ? Math.floor(sec / 60) + 'm ' + (sec % 60) + 's' : sec + 's');
    }, 1000);
  }
  function stopElapsed() {
    if (elapsedTimer) { clearInterval(elapsedTimer); elapsedTimer = null; }
  }

  // —— 会话列表（侧栏"工作区"）：列历史会话，点开加载上下文 ——
  function fmtRel(ts) {
    const t = Number(ts || 0);
    if (!t) return '';
    const diff = Date.now() / 1000 - t;
    if (diff < 3600) return Math.max(1, Math.round(diff / 60)) + ' 分钟前';
    if (diff < 86400) return Math.round(diff / 3600) + ' 小时前';
    return Math.round(diff / 86400) + ' 天前';
  }

  // 会话按项目分组：workdir 相同的归一组，组标题用项目名，未关联的放最后
  function projectLabelFor(workdir) {
    if (!workdir) return '未关联项目';
    const norm = (v) => String(v || '').replace(/\\/g, '/').replace(/\/+$/, '').toLowerCase();
    const target = norm(workdir);
    const hit = (projectsCache || []).find((p) => norm(p.path) === target);
    if (hit && hit.name) return hit.name;
    const parts = String(workdir).replace(/\\/g, '/').split('/').filter(Boolean);
    return parts.length ? parts[parts.length - 1] : workdir;
  }

  async function loadSessions() {
    const list = $('sessionList');
    if (!list) return;
    try {
      const data = await fetchJsonRetry('/api/sessions', 2);
      const items = data.sessions || [];
      window.__sessionCount = items.length;
      list.innerHTML = '';
      if (!items.length) {
        const empty = document.createElement('div');
        empty.style.cssText = 'padding:8px 10px;font-size:12px;color:var(--label-tertiary)';
        empty.textContent = '还没有历史会话';
        list.appendChild(empty);
        return;
      }
      // 分组（保持最近的在前）
      const groups = new Map();
      for (const it of items) {
        const key = (it.workdir || '');
        if (!groups.has(key)) groups.set(key, []);
        groups.get(key).push(it);
      }
      const ordered = Array.from(groups.entries()).sort((a, b) => {
        const ta = Math.max(...a[1].map((x) => x.updated_at || 0));
        const tb = Math.max(...b[1].map((x) => x.updated_at || 0));
        if (!a[0] !== !b[0]) return a[0] ? -1 : 1; // 未关联项目沉底
        return tb - ta;
      });
      for (const [workdir, rows] of ordered) {
        const head = document.createElement('div');
        head.className = 'session-group';
        const name = document.createElement('span');
        name.className = 'session-group-name';
        name.textContent = projectLabelFor(workdir);
        const cnt = document.createElement('span');
        cnt.className = 'session-group-count';
        cnt.textContent = String(rows.length);
        head.appendChild(name);
        head.appendChild(cnt);
        if (workdir) head.title = workdir;
        list.appendChild(head);
        for (const it of rows) {
          const row = document.createElement('div');
          row.className = 'session-item';
          const ico = document.createElement('span');
          ico.textContent = '💬';
          const title = document.createElement('span');
          title.textContent = it.title || it.id;
          title.style.cssText = 'overflow:hidden;text-overflow:ellipsis;white-space:nowrap;max-width:170px';
          const time = document.createElement('span');
          time.className = 'time';
          time.textContent = fmtRel(it.updated_at);
          row.appendChild(ico); row.appendChild(title); row.appendChild(time);
          row.title = `${it.id} · ${it.status || ''} · ${it.messages || 0} 条消息`
            + (it.model ? ` · ${it.provider ? it.provider + '/' : ''}${it.model}` : '')
            + (workdir ? ` · ${workdir}` : '');
          row.onclick = () => openSession(it.id);
          list.appendChild(row);
        }
      }
    } catch (e) {
      list.innerHTML = '';
      const err = document.createElement('div');
      err.style.cssText = 'padding:8px 10px;font-size:12px;color:var(--label-tertiary)';
      err.textContent = '会话列表不可用: ' + e.message;
      list.appendChild(err);
    }
  }

  async function openSession(id) {
    try {
      const data = await fetchJsonRetry('/api/session?id=' + encodeURIComponent(id), 2);
      $chat.innerHTML = '';
      $('sessionTitle').textContent = data.title || id;
      loadedHistory = (data.messages || [])
        .filter((m) => m.role === 'user' || m.role === 'assistant')
        .map((m) => ({ role: m.role, content: String(m.content || '') }));
      const hintEl = $('sessionHint');
      if (hintEl) {
        hintEl.textContent = loadedHistory.length
          ? ('已载入该会话 ' + loadedHistory.length + ' 条历史，继续发消息会带上上下文')
          : '';
        hintEl.classList.toggle('show', loadedHistory.length > 0);
      }
      let lastRendered = null;
      for (const m of (data.messages || [])) {
        const content = String(m.content || '');
        if (m.role === 'user') {
          addUser(content);
          lastRendered = 'user:' + content;
        } else if (m.role === 'assistant') {
          // 历史会话里可能同时存了"步骤结果"和"最终回答"（旧版本落盘行为）——同内容只显示一次
          if (lastRendered === 'assistant:' + content.trim()) continue;
          addAssistant(content);
          lastRendered = 'assistant:' + content.trim();
        } else if (m.role === 'tool') {
          addToolRow(`✓ 工具完成: ${m.name || 'tool'}`, content.slice(0, 2000));
          lastRendered = null;
        }
      }
      scrollEnd(true);
    } catch (e) {
      showBanner('会话加载失败: ' + e.message);
    }
  }

  // —— 角色库（personas/*.md）：连上 Host 后拉一次，填进输入框左侧下拉 ——
  const personasPending = {};
  function loadPersonas() {
    if (!ws || ws.readyState !== 1) return;
    const id = 'personas-' + Date.now();
    personasPending[id] = true;
    ws.send(JSON.stringify({ type: 'personas', id }));
  }
  function applyPersonas(items) {
    const sel = $('persona');
    if (!sel) return;
    const current = sel.value;
    sel.innerHTML = '<option value="">默认角色</option>';
    for (const p of items || []) {
      const opt = document.createElement('option');
      opt.value = p.name;
      opt.textContent = p.title ? `${p.title}` : p.name;
      opt.title = (p.description || '') + '（' + p.name + '）';
      sel.appendChild(opt);
    }
    if (current) sel.value = current;
  }

  // —— 发送 ——
  function send() {
    const text = $input.value.trim();
    if (!text) return;
    if (!ws || ws.readyState !== 1 || !authenticated) {
      showBanner('未连接或未认证，消息未发送'); return;
    }
    addUser(text);
    turnCount++; updateStats();
    const persona = ($('persona') && $('persona').value) || '';
    const payload = {
      type: 'run', goal: text, stream: true, persona, id: 'run-' + Date.now(),
      model: selectedModel || undefined,
      reasoning_effort: reasoningEffort,
      fast_mode: fastMode,
      workdir: (activeProject && activeProject.path) || undefined,
    };
    if (loadedHistory.length) payload.prior_messages = loadedHistory.slice(-20);
    if (attachments.length) payload.images = attachments.map((a) => ({ data_url: a.dataUrl }));
    ws.send(JSON.stringify(payload));
    startElapsed();
    clearAttachments();
    $input.value = '';
    $send.disabled = true;
    hideBanner();
  }
  $send.onclick = send;
  $input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
  });
  $input.addEventListener('input', function () {
    this.style.height = 'auto';
    this.style.height = Math.min(this.scrollHeight, 160) + 'px';
  });

  // —— 新会话 ——
  $('newChat').onclick = () => {
    $chat.innerHTML = ''; $trace.innerHTML = '';
    turnCount = 0; callCount = 0; updateStats();
    $('sessionTitle').textContent = '新会话';
    loadedHistory = [];
    const hintReset = $('sessionHint');
    if (hintReset) { hintReset.textContent = ''; hintReset.classList.remove('show'); }
    hideBanner();
  };

  // —— 轨迹开关（会话栏上的轻量按钮，不再用一整行 tab）——
  let showingTrace = false;
  $('btnTrace').onclick = () => {
    showingTrace = !showingTrace;
    $('btnTrace').classList.toggle('active', showingTrace);
    $chat.style.display = showingTrace ? 'none' : '';
    $trace.style.display = showingTrace ? '' : 'none';
  };

  // —— 插件市场 ——
  let pluginsCache = [];
  async function openMarket() {
    $('marketOverlay').classList.add('show');
    await loadPlugins();
  }
  function closeMarket() { $('marketOverlay').classList.remove('show'); }
  $('btnMarket').onclick = openMarket;
  $('marketClose').onclick = closeMarket;
  $('marketOverlay').addEventListener('click', (e) => {
    if (e.target === $('marketOverlay')) closeMarket();
  });

  async function loadPlugins() {
    const grid = $('marketGrid');
    grid.innerHTML = '<div class="market-empty">加载中…</div>';
    try {
      const resp = await fetch('/api/plugins');
      const data = await resp.json();
      pluginsCache = data.plugins || [];
    } catch (_) {
      pluginsCache = [];
      grid.innerHTML = '<div class="market-empty">插件服务不可用（Host 未启用 /api/plugins）</div>';
      return;
    }
    renderPlugins();
  }
  function renderPlugins() {
    const grid = $('marketGrid');
    const q = ($('marketSearch').value || '').toLowerCase();
    const list = pluginsCache.filter((p) =>
      !q || (p.name + p.description).toLowerCase().includes(q));
    if (!list.length) {
      grid.innerHTML = '<div class="market-empty">暂无插件 —— 把插件放进 .clawd/plugins/ 目录即可出现在这里</div>';
      return;
    }
    grid.innerHTML = '';
    for (const p of list) {
      const card = document.createElement('div');
      card.className = 'market-card';
      card.innerHTML =
        '<div class="mc-top"><div class="mc-icon">⬢</div>' +
        '<div style="min-width:0"><div class="mc-name"></div>' +
        '<div class="mc-sub"></div></div></div>' +
        '<div class="mc-desc"></div>' +
        '<div class="mc-tags"></div>';
      card.querySelector('.mc-name').textContent = p.name;
      card.querySelector('.mc-sub').textContent = 'v' + (p.version || '0.0.0');
      card.querySelector('.mc-desc').textContent = p.description || '';
      const tags = card.querySelector('.mc-tags');
      for (const t of (p.capabilities || [])) {
        const s = document.createElement('span');
        s.className = 'mc-tag'; s.textContent = t;
        tags.appendChild(s);
      }
      const st = document.createElement('span');
      st.className = 'mc-status';
      st.textContent = p.status === 'loaded' ? '● 已启用' : p.status;
      tags.appendChild(st);
      grid.appendChild(card);
    }
  }
  $('marketSearch').addEventListener('input', renderPlugins);

  // —— 设置面板 ——
  const $setOverlay = $('settingsOverlay');
  function openSettings() { $setOverlay.classList.add('show'); loadSettings(); loadProviders(); }
  function closeSettings() { $setOverlay.classList.remove('show'); }
  $('btnSettings').onclick = openSettings;
  $('settingsClose').onclick = closeSettings;
  $setOverlay.addEventListener('click', (e) => {
    if (e.target === $setOverlay) closeSettings();
  });

  function fillSettings(d) {
    $('setVersion').textContent = 'v' + (d.version || '—');
    $('setPython').textContent = d.python || '—';
    $('setWorkdir').textContent = d.workdir || '—';
    $('setApiKey').textContent = d.api_key_set ? '已配置（不回显）' : '未配置';
    const ap = d.active_provider || {};
    const activeLine = $('activeProviderLine');
    if (activeLine) {
      activeLine.textContent = ap.configured
        ? ('provider 列表里的「' + ap.name + '」' + (ap.has_key ? '' : '（缺密钥，会回退全局）'))
        : '未选择 provider —— 走下面的全局配置';
    }
    const usageActive = $('usageActiveProvider');
    if (usageActive) usageActive.textContent = ap.configured ? ('生效: ' + ap.name) : '';
    $('setProvider').value = d.provider || '';
    $('setModel').value = d.model || '';
    $('setBaseUrl').value = d.base_url || '';
    $('setRag').checked = !!d.enable_rag;
    $('setNativeTools').checked = !!d.native_tools;
    if ($('verLine').textContent === 'v—' && d.version) {
      $('verLine').textContent = 'v' + d.version;
    }
  }

  async function loadSettings() {
    const note = $('setNote');
    note.className = 'snote';
    note.textContent = '读取中…';
    try {
      const res = await request('settings_get');
      fillSettings(res.data || {});
      note.textContent = '';
    } catch (e) {
      note.className = 'snote err';
      note.textContent = '读取失败: ' + e.message;
    }
  }

  async function saveSettings() {
    const note = $('setNote');
    const btn = $('setSave');
    btn.disabled = true;
    note.className = 'snote';
    note.textContent = '保存中…';
    try {
      const res = await request('settings_set', {
        settings: {
          provider: $('setProvider').value.trim(),
          model: $('setModel').value.trim(),
          base_url: $('setBaseUrl').value.trim(),
          enable_rag: $('setRag').checked,
          native_tools: $('setNativeTools').checked,
        },
      });
      fillSettings(res.data || {});
      note.className = 'snote ok';
      note.textContent = (res.data && res.data.restart_required)
        ? '已保存。provider/model/base_url 需重启 Host 生效。'
        : '已保存并立即生效。';
    } catch (e) {
      note.className = 'snote err';
      note.textContent = '保存失败: ' + e.message;
    } finally {
      btn.disabled = false;
    }
  }
  $('setSave').onclick = saveSettings;

  // 用量页 / 多 provider 绑定
  const usageBtn = $('btnUsage');
  if (usageBtn) usageBtn.onclick = openUsage;
  const usageClose = $('usageClose');
  if (usageClose) usageClose.onclick = closeUsage;
  const usageRangeBar = $('usageRangeBar');
  if (usageRangeBar) {
    usageRangeBar.querySelectorAll('.vb').forEach((b) => {
      b.onclick = () => {
        usageRangeBar.querySelectorAll('.vb').forEach((x) => x.classList.remove('active'));
        b.classList.add('active');
        usageRange = b.dataset.range || 'today';
        loadUsage();
      };
    });
  }
  const usageRefresh = $('usageRefresh');
  if (usageRefresh) usageRefresh.onclick = loadUsage;
  const usageOverlay = $('usageOverlay');
  if (usageOverlay) usageOverlay.addEventListener('click', (e) => { if (e.target === usageOverlay) closeUsage(); });
  const btnAddProject = $('btnAddProject');
  if (btnAddProject) btnAddProject.onclick = () => $('projectOverlay').classList.add('show');
  const projectClose = $('projectClose');
  if (projectClose) projectClose.onclick = () => $('projectOverlay').classList.remove('show');
  const projBrowse = $('projBrowse');
  if (projBrowse) projBrowse.onclick = pickFolder;
  const projPathSave = $('projPathSave');
  if (projPathSave) projPathSave.onclick = async () => {
    const value = ($('projPathInput').value || '').trim();
    if (value && await addProjectByPath(value)) {
      $('projPathInput').value = '';
      $('projectOverlay').classList.remove('show');
    }
  };
  const projCloneBtn = $('projCloneBtn');
  if (projCloneBtn) projCloneBtn.onclick = () => cloneProject(($('projCloneUrl').value || '').trim());

  const btnModel = $('btnModel');
  if (btnModel) btnModel.onclick = openModelPicker;
  const modelClose = $('modelClose');
  if (modelClose) modelClose.onclick = () => $('modelOverlay').classList.remove('show');
  const modelSearch = $('modelSearch');
  if (modelSearch) modelSearch.oninput = renderModelList;
  const modelEffort = $('modelEffort');
  if (modelEffort) {
    modelEffort.querySelectorAll('button').forEach((b) => {
      b.onclick = () => {
        modelEffort.querySelectorAll('button').forEach((x) => x.classList.remove('active'));
        b.classList.add('active');
        reasoningEffort = b.dataset.effort || '最大';
      };
    });
  }
  const modelFast = $('modelFast');
  if (modelFast) {
    modelFast.onclick = () => {
      fastMode = !fastMode;
      modelFast.setAttribute('aria-pressed', fastMode ? 'true' : 'false');
      updateModelButton();
    };
  }

  const ctxBtn = $('btnContext');
  if (ctxBtn) ctxBtn.onclick = openContext;
  const ctxClose = $('ctxClose');
  if (ctxClose) ctxClose.onclick = () => $('ctxOverlay').classList.remove('show');
  const ctxOverlay = $('ctxOverlay');
  if (ctxOverlay) ctxOverlay.addEventListener('click', (e) => { if (e.target === ctxOverlay) ctxOverlay.classList.remove('show'); });
  const provSave = $('provSave');
  if (provSave) provSave.onclick = saveProviderFromForm;
  const provReset = $('provReset');
  if (provReset) provReset.onclick = () => {
    ['provId', 'provName', 'provModel', 'provBaseUrl', 'provKeyEnv', 'provKey'].forEach((k) => { if ($(k)) $(k).value = ''; });
  };
  $('setReload').onclick = loadSettings;

  // —— 版本与更新 ——
  async function loadInfo() {
    try {
      const resp = await fetch('/api/info');
      const d = await resp.json();
      if (d.version) $('verLine').textContent = 'v' + d.version;
      const tag = $('modelTag');
      if (tag && d.model) tag.textContent = (d.provider ? d.provider + ' · ' : '') + d.model;
      if (d.version) fillSettings(d);
    } catch (_) { /* Host 未提供 /api/info 时保持占位 */ }
  }
  loadInfo();

  function setUpdateLine(text, cls) {
    const el = $('updateLine');
    if (!el) return;
    el.textContent = text;
    el.className = 'update-line' + (cls ? ' ' + cls : '');
  }

  // Electron preload 暴露的桥（浏览器直接访问时为 undefined）
  const bridge = (typeof window !== 'undefined' && window.clawdDesktop) || null;
  // 更新流程共用一条 toast：下载中不自动消失，就绪时原地换成"重启安装"
  let updateToast = null;
  function updateToastFor(status) {
    if (!updateToast) return null;
    if (status === 'checking' || status === 'downloading') {
      updateToast.update({
        kind: 'warn',
        icon: '⬇',
        title: status === 'checking' ? '正在检查更新…' : '发现新版本，后台下载中…',
        detail: status === 'checking' ? '' : '下载完成后会提示你安装，不影响当前使用。',
        timeout: 0,
        actions: [],
      });
    }
    return updateToast;
  }
  if (bridge && typeof bridge.onUpdateStatus === 'function') {
    bridge.onUpdateStatus((status, detail) => {
      // 设置页里那行文字保留（用户主动点"检查更新"时有就地反馈）
      if (status === 'checking') setUpdateLine('正在检查更新…', '');
      else if (status === 'downloading') setUpdateLine('发现新版本，后台下载中…', 'warn');
      else if (status === 'none') setUpdateLine('已是最新版本', 'ok');
      else if (status === 'ready') setUpdateLine('新版本已下载，退出后自动安装', 'ok');
      else if (status === 'error') setUpdateLine(detail || '更新检查失败', 'err');
      else if (status === 'unsupported') setUpdateLine(detail || '当前版本不支持自动更新', 'warn');

      // 右下角 toast：只有"有新进展"才弹，避免用户没点检查就被打扰
      if (status === 'downloading' || status === 'ready') {
        if (!updateToast) {
          updateToast = toast({ kind: 'warn', icon: '⬇', title: '检查更新…', timeout: 0 });
        }
        updateToastFor(status);
        if (status === 'ready') {
          updateToast.update({
            kind: 'ok',
            icon: '✔',
            title: '新版本已就绪',
            detail: '退出 Clawd 后会自动安装。想立刻生效可点"重启安装"。',
            timeout: 0,
            actions: [
              { label: '重启安装', primary: true, onClick: () => { if (typeof bridge.quitAndInstall === 'function') bridge.quitAndInstall(); } },
              { label: '稍后', onClick: () => { updateToast = null; } },
            ],
          });
        }
      } else if (status === 'none') {
        if (updateToast) { updateToast.update({ kind: 'ok', icon: '✔', title: '已是最新版本', detail: '', timeout: 3000, actions: [] }); updateToast = null; }
      } else if (status === 'error') {
        if (updateToast) { updateToast.update({ kind: 'err', icon: '✖', title: '更新检查失败', detail: detail || '', timeout: 5000, actions: [] }); updateToast = null; }
      }
    });
  }
  $('btnCheckUpdate').onclick = () => {
    if (bridge && typeof bridge.checkForUpdates === 'function') {
      setUpdateLine('正在检查更新…', '');
      if (!updateToast) updateToast = toast({ kind: 'warn', icon: '⟳', title: '正在检查更新…', timeout: 0 });
      else updateToastFor('checking');
      bridge.checkForUpdates();
    } else {
      setUpdateLine('浏览器访问模式无更新通道，请在桌面安装版中使用', 'warn');
      toast({ kind: 'warn', icon: 'ℹ', title: '浏览器访问模式无更新通道', detail: '自动更新只在桌面安装版里可用。', timeout: 4000 });
    }
  };

  // —— 启动 ——
  if (!TOKEN) showBanner('缺少 token：请通过 Host 入口访问（壳自动注入），不要直接打开文件。');
  connect();
})();
