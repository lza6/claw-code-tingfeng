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
  let callCount = 0;

  const $ = (id) => document.getElementById(id);
  const $conn = $('conn'), $connText = $('connText'), $banner = $('banner');
  const $chat = $('chat'), $trace = $('trace'), $input = $('input'), $send = $('send');

  function setConn(ok, text) {
    $conn.className = 'conn' + (ok ? ' ok' : '');
    $connText.textContent = text;
  }
  function showBanner(t) { $banner.textContent = t; $banner.style.display = 'block'; }
  function hideBanner() { $banner.style.display = 'none'; }
  function updateStats() {
    $('stTurns').textContent = turnCount + ' 轮';
    $('stCalls').textContent = '工具 ' + callCount + ' 次';
  }

  // —— 消息渲染 ——
  function addUser(text) {
    const d = document.createElement('div');
    d.className = 'msg-user';
    d.textContent = text;
    $chat.appendChild(d);
    scrollEnd();
  }

  function addAssistant(text) {
    const wrap = document.createElement('div');
    wrap.className = 'msg-assistant';
    if (text.length > DEGRADE_THRESHOLD) wrap.classList.add('degraded');
    const who = document.createElement('div');
    who.className = 'who';
    who.textContent = 'Clawd';
    const body = document.createElement('div');
    body.textContent = text;
    const actions = document.createElement('div');
    actions.className = 'msg-actions';
    const copy = document.createElement('button');
    copy.textContent = '复制';
    copy.onclick = () => navigator.clipboard.writeText(text);
    actions.appendChild(copy);
    wrap.appendChild(who); wrap.appendChild(body); wrap.appendChild(actions);
    $chat.appendChild(wrap);
    scrollEnd();
  }

  function addError(text) {
    const d = document.createElement('div');
    d.className = 'msg-err';
    d.textContent = '⚠ ' + text;
    $chat.appendChild(d);
    scrollEnd();
  }

  function addToolRow(label, detail) {
    callCount++; updateStats();
    // 对话区：折叠单行
    const row = document.createElement('div');
    row.className = 'tool-row' + (detail && detail.length > DEGRADE_THRESHOLD ? ' degraded' : '');
    const ico = document.createElement('span'); ico.className = 't-ico'; ico.textContent = '⚙';
    const lab = document.createElement('span'); lab.className = 't-label'; lab.textContent = label;
    const det = document.createElement('div'); det.className = 't-detail'; det.textContent = detail || '(无输出)';
    row.appendChild(ico); row.appendChild(lab); row.appendChild(det);
    row.onclick = () => row.classList.toggle('open');
    $chat.appendChild(row);
    // 轨迹区：完整记录
    const tr = document.createElement('div');
    tr.className = 'tool-row open';
    tr.innerHTML = '<span class="t-label"></span>';
    tr.querySelector('.t-label').textContent = label;
    const td = document.createElement('div'); td.className = 't-detail'; td.textContent = detail || '';
    tr.appendChild(td);
    $trace.appendChild(tr);
    scrollEnd();
  }

  function scrollEnd() {
    const view = document.querySelector('.view');
    view.scrollTop = view.scrollHeight;
  }

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
    if (msg.type === 'response') {
      if (msg.id === 'auth') {
        // Host 响应: {id:'auth', type:'response', data:{status:'authenticated'}}
        const ok = msg.data?.status === 'authenticated' || msg.result;
        if (ok) {
          authenticated = true; reconnectDelay = 1000; everConnected = true;
          hideBanner(); setConn(true, '已连接 · 就绪');
        } else {
          setConn(false, '认证失败');
          showBanner('认证失败：token 无效。请通过 Host 入口访问。');
        }
        return;
      }
      // run 响应: {id, type:'response', data:{status, result, steps, elapsed_seconds}}
      const d = msg.data || msg.result || {};
      if (typeof d === 'object' && d.status === 'completed') {
        addAssistant(d.result || '(无输出)');
        const st = $('stTurns');
        st.textContent = `${turnCount} 轮`;
        if (d.elapsed_seconds) $('stCalls').textContent = `工具 ${callCount} 次 · ${d.elapsed_seconds}s · ${d.steps} 步`;
        $send.disabled = false;
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
      const [ico, fixedLabel] = LABELS[raw] || ['·', raw];
      let label;
      if (raw === 'AGENT_TOOL_EXEC_STARTED') {
        label = `工具调用: ${d.tool_name || '?'} ${JSON.stringify(d.tool_args || {}).slice(0, 80)}`;
      } else if (raw === 'AGENT_TOOL_EXEC_COMPLETED') {
        label = `工具完成: ${d.tool_name || '?'} ${d.success === false ? '(失败)' : ''}`;
      } else if (raw === 'AGENT_LLM_CALL_STARTED') {
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
      addToolRow(`${ico} ${label}`, detail);
      return;
    }
    addToolRow(msg.type || '?', JSON.stringify(msg, null, 2).slice(0, 4000));
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
    ws.send(JSON.stringify({ type: 'run', goal: text, id: 'run-' + Date.now() }));
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
    hideBanner();
  };

  // —— tab 切换 ——
  document.querySelectorAll('.tab').forEach((t) => {
    t.onclick = () => {
      document.querySelectorAll('.tab').forEach((x) => x.classList.remove('active'));
      t.classList.add('active');
      const isChat = t.dataset.tab === 'chat';
      $chat.style.display = isChat ? '' : 'none';
      $trace.style.display = isChat ? 'none' : '';
    };
  });

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

  // —— 设置（占位：后续接入 Host 配置面） ——
  $('btnSettings').onclick = () => addToolRow('设置', '设置面板将在后续版本提供。当前可通过 .clawd/ 目录配置 Host。');

  // —— 启动 ——
  if (!TOKEN) showBanner('缺少 token：请通过 Host 入口访问（壳自动注入），不要直接打开文件。');
  connect();
})();
