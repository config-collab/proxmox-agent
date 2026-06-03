/* ============================================================
   Proxmox Assistant — front-end logic
   Talks to the FastAPI backend at /api/*
   Chat:     POST /api/chat  -> SSE event stream
   Status:   GET  /api/status
   Settings: GET/POST /api/settings
   Audit:    GET  /api/audit
   ============================================================ */

const $  = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => [...r.querySelectorAll(s)];
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

const AUTONOMY_LEVELS = [
  { key:'observe',  label:'Observe',  glyph:'⊘', desc:'Read-only. Zero writes, zero SSH changes. Query and report only. Maximum trust — the agent literally cannot break anything.' },
  { key:'suggest',  label:'Suggest',  glyph:'⋯', desc:'Write operations are drafted and shown but never auto-executed. Every action needs your explicit click. (Default)' },
  { key:'maintain', label:'Maintain', glyph:'⚙', desc:'Auto-applies patches, restarts failed services, triggers backups. Destructive ops (delete, network changes) still ask first.' },
  { key:'full',     label:'Full',     glyph:'⚡', desc:'Full autonomy. The agent can create/delete containers and modify config without asking. Only for advanced users on dev nodes.' },
];

const state = { provider:'claude', busy:false, started:false, calls:0, autonomy:1, pveProtection:'strict' };
let STATUS   = null;
let SETTINGS = null;

/* ─── DOM refs ───────────────────────────────────────────────────────────────── */
let stream, consoleEl, consoleBody, consoleCnt, ta, sendBtn;

/* ─── Boot ───────────────────────────────────────────────────────────────────── */

document.addEventListener('DOMContentLoaded', async () => {
  stream      = $('#stream');
  consoleEl   = $('#console');
  consoleBody = $('#consoleBody');
  consoleCnt  = $('#consoleCnt');
  ta          = $('#ta');
  sendBtn     = $('#sendBtn');

  _restoreHistory();
  await loadStatus();
  _prefetchInventory();   // background — result ready by the time user clicks
  wireComposer();
  wireConsole();
  wireWelcome();

  $('#gear').addEventListener('click',        openSettings);
  $('#themeBtn').addEventListener('click',    toggleTheme);
  _initTheme();
  $('#closeSheet').addEventListener('click',  closeSettings);
  $('#newChat').addEventListener('click',     resetChat);
  $('#auditBtn').addEventListener('click',    openAuditDrawer);
  $('#closeAudit').addEventListener('click',  closeAuditDrawer);
  $('#scrim').addEventListener('click',       _closeTopDrawer);
  $('#closeDrawer').addEventListener('click', closeDrawer);
});

/* ─── Status + chips ─────────────────────────────────────────────────────────── */

async function loadStatus() {
  try {
    const r = await fetch('/api/status');
    STATUS = await r.json();
  } catch(_) {
    STATUS = {
      node:'?', pbs:'', agent:'', provider:'claude', generated:'', autonomy:1,
      summary: {
        inventory: {value:'—', status:'warn', note:'offline'},
        backups:   {value:'—', status:'warn', note:'offline'},
        patches:   {value:'—', status:'warn', note:'offline'},
        security:  {value:'—', status:'warn', note:'offline'},
      }
    };
  }
  state.provider = STATUS.provider || 'claude';
  state.autonomy = STATUS.autonomy ?? 1;
  $('#aiProvider').textContent = _provLabel(STATUS.provider);
  $('#brandSub').textContent   = `node ${STATUS.node} · agent .134`;
  const wn = $('#welcomeNode');
  if(wn) wn.textContent = STATUS.node;
  _renderAutonomyBadge();
  renderChips();
}

function _provLabel(p) {
  return {claude:'Claude', openai:'OpenAI', ollama:'Ollama'}[p] || 'Claude';
}

function _renderAutonomyBadge() {
  const lvl  = AUTONOMY_LEVELS[state.autonomy] || AUTONOMY_LEVELS[1];
  const gear = $('#gear');
  if(!gear) return;
  gear.className = `iconbtn ${lvl.key}`;
  gear.title     = `Settings · security: ${lvl.label}`;
  // Update sub-line to show current node + level
  const sub = $('#brandSub');
  if(sub) sub.textContent = `node ${STATUS?.node||'?'} · ${lvl.glyph} ${lvl.label.toLowerCase()}`;
}

function _updateChipFromResult(kind, data, summary) {
  if(!STATUS?.summary) return;
  if(kind === 'inventory') {
    const r = data || {};
    const run = r.running ?? 0, tot = r.total ?? 0;
    STATUS.summary.inventory = {value:`${tot} guests`, status: run===tot?'ok':'warn', note:`${run} running`};
  } else if(kind === 'patches') {
    const d = data || {};
    const tot = d.total ?? 0, sec = d.security ?? 0;
    STATUS.summary.patches = {value: tot?`${tot} pending`:'up to date', status: tot?'warn':'ok', note:`${sec} security`};
  } else if(kind === 'security') {
    const d = data || {};
    const crits = (d.findings||[]).filter(f=>f.sev==='critical').length;
    const highs = (d.findings||[]).filter(f=>f.sev==='high').length;
    STATUS.summary.security = {value: d.score||'?', status: crits?'bad':highs?'warn':'ok', note:`${crits} critical`};
  } else if(kind === 'backups') {
    STATUS.summary.backups = {value: summary||'checked', status:'ok', note:'just checked'};
  }
  renderChips();
}

function renderChips() {
  if(!STATUS) return;
  const s = STATUS.summary;
  const map = [
    ['inventory','Inventory', s.inventory],
    ['backups',  'Backups',   s.backups],
    ['patches',  'Patches',   s.patches],
    ['security', 'Security',  s.security],
  ];
  $('#chips').innerHTML = map.map(([k,label,o]) => `
    <button class="stat" data-tool="${k}">
      <span class="k"><span class="dot ${o.status}"></span>${label}</span>
      <span class="v">${o.value}</span>
      <span class="n">${o.note}</span>
    </button>`).join('');
  $$('#chips .stat').forEach(b =>
    b.addEventListener('click', () => { if(!state.busy) routeAndRun(b.dataset.tool); }));
}

/* ─── Composer ───────────────────────────────────────────────────────────────── */

function wireComposer() {
  const sync = () => {
    ta.style.height = 'auto';
    ta.style.height = Math.min(ta.scrollHeight, 120) + 'px';
    sendBtn.disabled = !ta.value.trim() || state.busy;
  };
  ta.addEventListener('input', sync);
  ta.addEventListener('keydown', e => {
    if(e.key === 'Enter' && !e.shiftKey){ e.preventDefault(); submit(); }
  });
  sendBtn.addEventListener('click', submit);
  sync();
}

function submit() {
  const v = ta.value.trim();
  if(!v || state.busy) return;
  ta.value = ''; ta.style.height = 'auto'; sendBtn.disabled = true;
  handleUser(v);
}

/* ─── Console ────────────────────────────────────────────────────────────────── */

function wireConsole() {
  $('#consoleHead').addEventListener('click', () => consoleEl.classList.toggle('collapsed'));
}

function pushConsole(html, count=false) {
  const idle = $('.idle', consoleBody);
  if(idle) idle.remove();
  const div = document.createElement('div');
  div.innerHTML = html;
  consoleBody.appendChild(div);
  consoleBody.scrollTop = consoleBody.scrollHeight;
  if(count) {
    state.calls++;
    consoleCnt.textContent = state.calls + (state.calls===1?' call':' calls');
  }
}

function nowTs() { return new Date().toTimeString().slice(0,8); }

/* ─── Theme toggle ───────────────────────────────────────────────────────────── */

function _initTheme() {
  const saved = localStorage.getItem('pve-theme') || 'dark';
  document.documentElement.dataset.theme = saved;
  _updateThemeBtn(saved);
}

function toggleTheme() {
  const cur  = document.documentElement.dataset.theme || 'dark';
  const next = cur === 'dark' ? 'light' : 'dark';
  document.documentElement.dataset.theme = next;
  localStorage.setItem('pve-theme', next);
  _updateThemeBtn(next);
}

function _updateThemeBtn(theme) {
  const btn = $('#themeBtn');
  if(btn) btn.textContent = theme === 'dark' ? '☀' : '🌙';
}

/* ─── Speculative prefetch ───────────────────────────────────────────────────── */

const _prefetchCache = {};

async function _prefetchInventory() {
  try {
    const r = await fetch('/api/prefetch/inventory');
    if(!r.ok) return;
    _prefetchCache.inventory = await r.json();
  } catch(_) {}
}

/* ─── localStorage history ───────────────────────────────────────────────────── */

const HISTORY_KEY = 'pve-agent-history';

function _saveHistory() {
  try {
    const msgs = [];
    $$('.msg', stream).forEach(el => {
      if(el.classList.contains('me')) msgs.push({type:'user', text:el.textContent});
      else if(el.classList.contains('ai-line')) msgs.push({type:'ai', html:$('.ai-body',el)?.innerHTML||''});
    });
    localStorage.setItem(HISTORY_KEY, JSON.stringify(msgs.slice(-30)));
  } catch(_) {}
}

function _restoreHistory() {
  try {
    const saved = JSON.parse(localStorage.getItem(HISTORY_KEY)||'[]');
    if(!saved.length) return;
    const welcome = $('#welcome');
    if(welcome) welcome.remove();
    state.started = true;
    saved.forEach(m => {
      if(m.type === 'user') {
        const el = document.createElement('div');
        el.className = 'msg bubble me';
        el.textContent = m.text;
        stream.appendChild(el);
      } else {
        const el = document.createElement('div');
        el.className = 'msg ai-line';
        el.innerHTML = `<div class="ai-av">AI</div><div class="ai-body">${m.html}</div>`;
        stream.appendChild(el);
      }
    });
    toBottom();
  } catch(_) {}
}

/* ─── Stream helpers ──────────────────────────────────────────────────────────── */

function clearWelcome() {
  const w = $('#welcome');
  if(w) { w.remove(); state.started = true; }
}

function addUser(text) {
  clearWelcome();
  const m = document.createElement('div');
  m.className = 'msg bubble me';
  m.textContent = text;
  stream.appendChild(m);
  toBottom();
}

function addAi() {
  const m = document.createElement('div');
  m.className = 'msg ai-line';
  m.innerHTML = `<div class="ai-av">AI</div><div class="ai-body"></div>`;
  stream.appendChild(m);
  toBottom();
  return $('.ai-body', m);
}

function toBottom() { requestAnimationFrame(() => { stream.scrollTop = stream.scrollHeight; }); }

/* ─── Routing ────────────────────────────────────────────────────────────────── */

function handleUser(text) { addUser(text); runChat(text); }

function routeAndRun(tool) {
  const labels = {
    inventory: "What's running right now?",
    patches:   "Any patches I should worry about?",
    backups:   "Are my backups healthy?",
    security:  "Run a security audit.",
    checkup:   "Run a full health check of the cluster.",
    helpers:   "Find community helper scripts",
    community: "What's the community saying about this?",
    reasoning: "Show me your reasoning for that recommendation.",
  };
  addUser(labels[tool] || tool);
  runChat(labels[tool] || tool);
}

/* ─── Chat (SSE) ──────────────────────────────────────────────────────────────── */

async function runChat(message) {
  // Speculative prefetch: if we have a cached inventory result, show it immediately
  const isInventoryMsg = /inventory|running|vm|guest|what.?s.up/i.test(message);
  if(isInventoryMsg && _prefetchCache.inventory?.data?.guests?.length) {
    const prefetchBody = addAi();
    const card = _invCard(_prefetchCache.inventory.data);
    if(card) {
      prefetchBody.appendChild(card);
      const note = document.createElement('div');
      note.className = 'ai-text';
      note.innerHTML = `<span style="color:var(--faint);font-size:11px;font-family:var(--mono)">cached result — refreshing in background</span>`;
      prefetchBody.appendChild(note);
      toBottom();
      _prefetchCache.inventory = null; // invalidate
      _prefetchInventory();            // start fresh fetch for next time
      state.busy = false; sendBtn.disabled = !ta.value.trim();
      return;
    }
  }

  state.busy = true; sendBtn.disabled = true;
  const body = addAi();

  const think = document.createElement('div');
  think.className = 'thinking';
  think.innerHTML = `<i></i><i></i><i></i> reading env_profile…`;
  body.appendChild(think);
  toBottom();

  let toolLogBody = null;
  let planCard    = null;
  let planSteps   = [];
  let planResults = {};
  let thinkRemoved = false;

  function rmThink() {
    if(!thinkRemoved) { think.remove(); thinkRemoved = true; }
  }

  try {
    const resp = await fetch('/api/chat', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({message, autonomy: state.autonomy}),
    });
    if(!resp.ok) throw new Error(`HTTP ${resp.status}`);

    const reader  = resp.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';

    while(true) {
      const {done, value} = await reader.read();
      if(done) break;
      buf += decoder.decode(value, {stream:true});

      let boundary;
      while((boundary = buf.indexOf('\n\n')) !== -1) {
        const chunk = buf.slice(0, boundary);
        buf = buf.slice(boundary + 2);
        let event = 'message', data = null;
        for(const line of chunk.split('\n')) {
          if(line.startsWith('event: '))     event = line.slice(7).trim();
          else if(line.startsWith('data: ')) { try { data = JSON.parse(line.slice(6)); } catch(_) {} }
        }
        if(!data) continue;
        rmThink();

        switch(event) {
          case 'tool_start': {
            toolLogBody = _startToolLog(body, data.name, data.sig);
            pushConsole(`<span class="ts">${nowTs()}</span> <span class="t">[tool]</span> ${esc(data.sig)}`, true);
            break;
          }
          case 'tool_line': {
            if(toolLogBody) {
              const row = document.createElement('div');
              row.innerHTML = `<span class="${data.cls||'mut'}">${esc(data.text)}</span>`;
              toolLogBody.appendChild(row);
              pushConsole(`<span class="ts">${nowTs()}</span> <span class="${data.cls||'mut'}">${esc(data.text)}</span>`);
            }
            toBottom();
            break;
          }
          case 'tool_end': {
            if(toolLogBody) {
              const tl = toolLogBody.closest('.toollog');
              const tsEl = tl?.querySelector('.tl-head .ts');
              if(tsEl) tsEl.textContent = 'done';
              tl?.querySelector('.tl-head .dot')?.classList.remove('pulse');
            }
            toolLogBody = null;
            break;
          }
          case 'tool_result': {
            const card = _renderCard(data.kind, data.data, data.summary);
            if(card) { body.appendChild(card); toBottom(); }
            planResults[data.name] = data;
            if(data.kind === 'backups' || data.kind === 'pbs') _updateDrawer(planResults);
            _updateChipFromResult(data.kind, data.data, data.summary);
            break;
          }
          case 'ai_text': {
            const p = document.createElement('div');
            p.className = 'ai-text';
            p.innerHTML = data.html || '';
            body.appendChild(p); toBottom();
            break;
          }
          case 'judge_result': {
            const score = data.score || 3;
            const color = score >= 4 ? 'var(--ok)' : score === 3 ? 'var(--warn)' : 'var(--crit)';
            const icon  = score >= 4 ? '✓' : score === 3 ? '⚠' : '✗';
            const p = document.createElement('div');
            p.className = 'ai-text';
            p.innerHTML = `<span style="color:${color};font-family:var(--mono)">${icon} Safety ${score}/5 · ${esc(data.verdict||'')}</span>`;
            body.appendChild(p); toBottom();
            break;
          }

          case 'blocked': {
            const p = document.createElement('div');
            p.className = 'ai-text';
            p.innerHTML = `<span style="color:var(--warn)">⚠ ${esc(data.message)}</span>`;
            body.appendChild(p); toBottom();
            break;
          }
          case 'plan_start': {
            planSteps = data.steps || [];
            planCard  = _makePlanCard(planSteps);
            body.appendChild(planCard);
            consoleEl.classList.remove('collapsed');
            toBottom();
            break;
          }
          case 'plan_step_active': {
            if(planCard) _planStepState(planCard, data.index, 'active', '', 'ok');
            showAgentBar(`Agent running · ${planSteps[data.index]}() · step ${data.index+1}/${planSteps.length}`);
            break;
          }
          case 'plan_step_done': {
            if(planCard) _planStepState(planCard, data.index, 'done', data.meta||'', data.status||'ok');
            const pr = planCard?.querySelector('#apPr');
            if(pr) pr.textContent = `${data.index+1} / ${planSteps.length}`;
            break;
          }
          case 'plan_done': {
            hideAgentBar();
            const sum = _checkupSummary(planResults);
            if(sum) { body.appendChild(sum); toBottom(); }
            break;
          }
          case 'error': {
            const p = document.createElement('div');
            p.className = 'ai-text';
            p.innerHTML = `<span style="color:var(--crit)">Error: ${esc(data.message||'unknown')}</span>`;
            body.appendChild(p); toBottom();
            break;
          }
        }
      }
    }
  } catch(err) {
    rmThink();
    const p = document.createElement('div');
    p.className = 'ai-text';
    p.innerHTML = `<span style="color:var(--crit)">Connection error: ${esc(err.message)}</span>`;
    body.appendChild(p); toBottom();
  }

  _saveHistory();
  state.busy = false;
  sendBtn.disabled = !ta.value.trim();
  toBottom();
}

/* ─── Tool log block ──────────────────────────────────────────────────────────── */

function _startToolLog(parent, name, sig) {
  const wrap = document.createElement('div');
  wrap.className = 'toollog';
  wrap.innerHTML = `
    <div class="tl-head">
      <span class="dot acc pulse"></span>
      <span>[tool]</span><span class="nm">${esc(name)}</span>
      <span class="sp"></span><span class="ts">running</span>
    </div>
    <div class="tl-body"></div>`;
  parent.appendChild(wrap);
  toBottom();
  return $('.tl-body', wrap);
}

/* ─── Card renderer dispatch ──────────────────────────────────────────────────── */

function _renderCard(kind, data, summary) {
  switch(kind) {
    case 'inventory':  return _invCard(data);
    case 'patches':    return _patchCard(data);
    case 'security':   return _secCard(data);
    case 'backups':    return _backupCard(data, summary);
    case 'helpers':    return _helpersCard(data, summary);
    case 'metrics':    return _metricsCard(data);
    case 'community':  return _communityCard(data, summary);
    case 'reasoning':  return _reasoningCard(data);
    case 'pbs':        return null;
    default:           return null;
  }
}

/* ─── Community card ─────────────────────────────────────────────────────────── */

function _communityCard(d, summary) {
  if(!d?.results?.length) return null;
  const card = document.createElement('div');
  card.className = 'card';
  const rows = d.results.slice(0, 8).map(r => `
    <tr>
      <td style="flex:1">
        <a href="${esc(r.url)}" target="_blank" style="color:var(--info);text-decoration:none;font-weight:500">
          ${esc(r.title.slice(0,60))}
        </a>
        <div style="font-size:10px;color:var(--muted);margin-top:3px">
          ↑${r.score} by u/${esc(r.author)} · ${r.comments} comments · ${r.created}
        </div>
      </td>
    </tr>`).join('');
  card.innerHTML = `
    <div class="card-head">
      <span class="kicker">ask_community</span>
      <span class="ti" style="margin-left:4px">r/Proxmox discussions</span>
      <span class="sp"></span>
      <span class="pill ok"><span class="dot ok"></span>${d.results.length} results</span>
    </div>
    <div class="card-body"><table class="tbl" style="width:100%">
      <tbody>${rows}</tbody>
    </table></div>
    <div class="card-foot" style="color:var(--faint);font-size:11px">
      👥 Real community feedback · click links to read full threads · upvotes show what works
    </div>`;
  return card;
}

/* ─── Reasoning card ──────────────────────────────────────────────────────────── */

function _reasoningCard(d) {
  if(!d?.reasoning) return null;
  const card = document.createElement('div');
  card.className = 'card';
  const sections = (d.reasoning || '').split('\n###').map((s, i) => {
    if(i === 0) return s;
    return s.split('\n')[0] + ' ' + s.split('\n').slice(1).join(' ').slice(0, 200);
  });
  card.innerHTML = `
    <div class="card-head">
      <span class="kicker">show_reasoning</span>
      <span class="ti" style="margin-left:4px">Agent thinking</span>
      <span class="sp"></span>
      <span class="pill info">transparency</span>
    </div>
    <div class="card-body" style="font-size:13px;line-height:1.6;color:var(--text-2)">
      <pre style="overflow-x:auto;white-space:pre-wrap;word-break:break-word;margin:0">${esc(d.reasoning || 'No reasoning available')}</pre>
    </div>
    <div class="card-foot">
      <button class="btn sm ghost" onclick="toast('Exported reasoning — check audit log for full trace')">Export chain-of-thought</button>
    </div>`;
  return card;
}

/* ─── Metrics card ────────────────────────────────────────────────────────────── */

function _metricsCard(d) {
  if(!d?.raw) return null;
  const card = document.createElement('div');
  card.className = 'card';
  // Convert the sparkline markdown to styled monospace blocks
  const html = d.raw
    .replace(/\*\*(.+?)\*\*/g, '<b>$1</b>')
    .replace(/`([^`]+)`/g, '<span class="mono" style="color:var(--accent);letter-spacing:-1px">$1</span>')
    .replace(/\n/g, '<br>');
  card.innerHTML = `
    <div class="card-head">
      <span class="kicker">get_metrics</span>
      <span class="ti" style="margin-left:4px">${esc(d.name||'metrics')} · ${esc(d.timeframe||'hour')}</span>
    </div>
    <div class="card-body" style="padding:11px 13px;font-size:12.5px;line-height:1.8">
      ${html}
    </div>`;
  return card;
}

/* ─── Helper scripts card ─────────────────────────────────────────────────────── */

function _helpersCard(d, summary) {
  const scripts = d.scripts || d.list || [];
  if(!scripts.length) return null;
  const card = document.createElement('div');
  card.className = 'card';
  const rows = scripts.map(s => `
    <tr>
      <td><b style="color:var(--text)">${esc(s.label||s.name)}</b>
          <span style="color:var(--faint);font-size:10.5px;margin-left:6px">${esc(s.category||s.dir||'')}</span></td>
      <td class="mono" style="font-size:10px;color:var(--muted);max-width:200px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap"
          title="${esc(s.run_cmd||'')}">${esc((s.run_cmd||'').slice(0,60))}…</td>
      <td><button class="btn sm ghost" data-cmd="${esc(s.run_cmd||'')}" data-label="${esc(s.label||s.name)}">Run ▸</button></td>
    </tr>`).join('');
  card.innerHTML = `
    <div class="card-head">
      <span class="kicker">community scripts</span>
      <span class="ti" style="margin-left:4px">Helper scripts</span>
      <span class="sp"></span>
      <span class="pill ok"><span class="dot ok"></span>${scripts.length} found</span>
    </div>
    <div class="card-body"><table class="tbl">
      <thead><tr><th>Script</th><th>Command</th><th></th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <div class="card-foot" style="color:var(--faint);font-size:11px;font-family:var(--mono)">
      Source: community-scripts.github.io/ProxmoxVE · runs on Proxmox host
    </div>`;
  $$('button[data-cmd]', card).forEach(btn => {
    btn.addEventListener('click', () => _confirmRunScript(btn.dataset.cmd, btn.dataset.label));
  });
  return card;
}

async function _confirmRunScript(cmd, label) {
  if(state.autonomy < 2) {
    toast(`Blocked: raise Security level to Maintain or Full to run scripts.`); return;
  }
  if(!confirm(`Run "${label}" on the Proxmox host?\n\n${cmd}\n\nThis will execute on 192.168.${STATUS?.node?.split('.').slice(-2).join('.')||'?'}.`)) return;
  toast(`Running ${label}…`);
  try {
    const r = await fetch('/api/run-script', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({run_cmd: cmd}),
    });
    const result = await r.json();
    const body = addAi();
    const p = document.createElement('div');
    p.className = 'ai-text';
    if(result.ok) {
      p.innerHTML = `<span style="color:var(--ok)">✓ ${esc(label)} installed.</span>`;
    } else {
      p.innerHTML = `<span style="color:var(--crit)">Script failed: ${esc(result.error||result.output?.slice(0,200)||'unknown')}</span>`;
    }
    body.appendChild(p); toBottom();
  } catch(e) { toast('Run failed: ' + e.message); }
}

/* ─── Inventory card ──────────────────────────────────────────────────────────── */

function _invCard(d) {
  const rows    = d.guests || [];
  const total   = d.total   ?? rows.length;
  const running = d.running ?? rows.filter(r => r.state==='running').length;
  const card = document.createElement('div');
  card.className = 'card';
  const renderRows = n => rows.slice(0,n).map(v => {
    const sshLink = v.ip ? `<a href="ssh://root@${esc(v.ip)}" title="SSH to ${esc(v.name)}" style="color:var(--faint);font-family:var(--mono);font-size:10px;text-decoration:none;margin-left:4px">⌨</a>` : '';
    return `<tr class="${v.state==='stopped'?'dim':''}">
      <td class="mono">${v.id}</td>
      <td>${esc(v.name)}${sshLink}</td>
      <td class="mono">${esc(v.node||'pve')}</td>
      <td><span class="state"><span class="dot ${v.state==='running'?'ok':'warn'}"></span>${v.state}</span></td>
      <td class="mono">${esc(v.mem||'—')}</td><td class="mono">${esc(v.load||'—')}</td>
    </tr>`;
  }).join('');
  card.innerHTML = `
    <div class="card-head">
      <span class="kicker">get_inventory</span>
      <span class="ti" style="margin-left:4px">Cluster inventory</span>
      <span class="sp"></span>
      <span class="pill ok"><span class="dot ok"></span>${running} up</span>
    </div>
    <div class="card-body"><table class="tbl">
      <thead><tr><th>VMID</th><th>Name</th><th>Node</th><th>State</th><th>Mem</th><th>Load</th></tr></thead>
      <tbody>${renderRows(6)}</tbody>
    </table></div>
    <div class="card-foot">
      <button class="btn sm ghost" id="invMore">Show all ${total} ▾</button>
    </div>`;
  let open = false;
  card.querySelector('#invMore').addEventListener('click', e => {
    open = !open;
    card.querySelector('tbody').innerHTML = renderRows(open ? rows.length : 6);
    e.target.textContent = open ? 'Show less ▴' : `Show all ${total} ▾`;
    toBottom();
  });
  return card;
}

/* ─── Patch card ──────────────────────────────────────────────────────────────── */

function _patchCard(d) {
  const list  = d.list || [];
  const total = d.total ?? list.length;
  const sec   = d.security ?? list.filter(p => p.type==='security').length;
  const ok    = total === 0;
  const card  = document.createElement('div');
  card.className = 'card';
  const blocked = state.autonomy === 0;
  const rows = list.map(p => `
    <tr>
      <td class="mono">${esc(p.pkg)}</td>
      <td class="mono">${esc(p.to||'—')}</td>
      <td>${p.type==='security'
        ? '<span class="sevtag high">security</span>'
        : '<span class="state" style="color:var(--faint)">routine</span>'}</td>
    </tr>`).join('');
  card.innerHTML = `
    <div class="card-head">
      <span class="kicker">check_patches</span>
      <span class="ti" style="margin-left:4px">Patch report · ${esc(d.host||'pve')}</span>
      <span class="sp"></span>
      <span class="pill ${ok?'ok':'warn'}"><span class="dot ${ok?'ok':'warn'}"></span>${ok?'up to date':`${total} pending`}</span>
    </div>
    <div class="card-body"><table class="tbl">
      <thead><tr><th>Package</th><th>→ Version</th><th>Type</th></tr></thead>
      <tbody>${rows||'<tr><td colspan="3" style="color:var(--faint);text-align:center;padding:16px">All up to date</td></tr>'}</tbody>
    </table></div>
    <div class="card-foot">
      ${blocked ? '<span style="color:var(--faint);font-size:11.5px;font-family:var(--mono)">⚠ Observe mode — writes blocked</span>' : `
        ${sec>0 ? `<button class="btn primary sm" id="apSec">Apply security (${sec})</button>` : ''}
        ${total>0 ? `<button class="btn ghost sm" id="apAll">Apply all (${total})</button>` : ''}
        ${total>0 ? `<button class="btn ghost sm" id="dryRun">Dry run</button>` : ''}
      `}
    </div>`;
  if(!blocked) {
    card.querySelector('#apSec')?.addEventListener('click',  () => toast('Queued apply_patches(security) — agent will confirm before running.'));
    card.querySelector('#apAll')?.addEventListener('click',  () => toast('Queued apply_patches(all) — agent will confirm before running.'));
    card.querySelector('#dryRun')?.addEventListener('click', () => toast('Queued dry run — will show what would change without applying.'));
  }
  return card;
}

/* ─── Backup card ─────────────────────────────────────────────────────────────── */

function _backupCard(d, summary) {
  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML = `
    <div class="card-head">
      <span class="kicker">backup health</span>
      <span class="ti" style="margin-left:4px">${esc(summary||'Backup status')}</span>
      <span class="sp"></span>
      <button class="btn sm" id="openBak">Open report ▸</button>
    </div>`;
  card.querySelector('#openBak').addEventListener('click', () => openDrawer(d));
  return card;
}

/* ─── Security card ───────────────────────────────────────────────────────────── */

const SEV_RANK = {critical:0, high:1, medium:2, low:3};

function _secCard(d) {
  const findings = [...(d.findings||[])].sort((a,b) =>
    (SEV_RANK[a.sev]??9) - (SEV_RANK[b.sev]??9));
  const scoreOk = (d.score||'').startsWith('A');
  const card = document.createElement('div');
  card.className = 'card';
  card.innerHTML = `
    <div class="card-head">
      <span class="kicker">security_audit</span>
      <span class="ti" style="margin-left:4px">Findings</span>
      <span class="sp"></span>
      <span class="pill ${scoreOk?'ok':'bad'}">score ${esc(d.score||'?')}</span>
    </div>
    <div class="findings">${findings.map(x => `
      <div class="finding">
        <div class="glyph g-${x.sev}">${x.glyph||'◆'}</div>
        <div class="f-body">
          <div class="f-top">
            <span class="sevtag ${x.sev}">${x.sev}</span>
            <span class="f-title">${esc(x.title||'')}</span>
          </div>
          <div class="f-where">${esc(x.where||'')}</div>
          <div class="f-detail">${esc(x.detail||'')}</div>
          <div class="f-fix">
            <button class="btn sm f-fix-btn" data-action="fix">Ask agent to fix ▸</button>
            <button class="btn sm ghost f-exp-btn" data-action="explain">Explain ▸</button>
          </div>
        </div>
      </div>`).join('')}
    </div>`;
  $$('.f-fix-btn', card).forEach(b => b.addEventListener('click', () =>
    toast('Queued — agent will draft the fix and ask before applying.')));
  $$('.f-exp-btn', card).forEach((b, idx) => b.addEventListener('click', () => {
    const f = findings[idx];
    if(!f) return;
    handleUser(`Explain this finding in detail: ${f.title}. Location: ${f.where}. ${f.detail}`);
  }));
  return card;
}

/* ─── Agentic plan card ───────────────────────────────────────────────────────── */

function _makePlanCard(steps) {
  const card = document.createElement('div');
  card.className = 'agentplan';
  card.innerHTML = `
    <div class="ap-head">
      <span class="ic">◆</span>
      <span class="ti">Agent plan · full health check</span>
      <span class="sp"></span>
      <span class="pr" id="apPr">0 / ${steps.length}</span>
    </div>
    <div class="ap-steps">${steps.map((s,i) => `
      <div class="ap-step" data-i="${i}">
        <span class="box">${i+1}</span>
        <span class="nm">${esc(s)}()</span>
        <span class="meta"></span>
      </div>`).join('')}
    </div>`;
  return card;
}

function _planStepState(card, index, st, meta, statusCls) {
  const row = card.querySelector(`.ap-step[data-i="${index}"]`);
  if(!row) return;
  row.className = `ap-step ${st}`;
  row.querySelector('.box').textContent = st==='done' ? '✓' : '';
  if(meta) row.querySelector('.meta').innerHTML =
    `<span class="dot ${statusCls}" style="margin-right:5px"></span>${esc(meta)}`;
}

/* ─── Checkup summary card ────────────────────────────────────────────────────── */

function _checkupSummary(results) {
  const actions = [];
  const sec = results['security_audit']?.data;
  const pat = results['check_patches']?.data;

  if(sec?.findings?.length > 0) {
    const crit = sec.findings.find(f => f.sev==='critical');
    if(crit) actions.push({sev:'critical', glyph:'▲', title:crit.title, where:crit.where, act:'fix'});
    const hi = sec.findings.find(f => f.sev==='high');
    if(hi && !actions.find(a => a.title===hi.title)) actions.push({sev:'high', glyph:'●', title:hi.title, where:hi.where, act:'fix'});
  }
  if(pat?.security > 0 && actions.length < 3)
    actions.push({sev:'high', glyph:'●', title:`${pat.security} security patches pending`,
                  where:pat.host||'pve', act:'patch'});

  const card = document.createElement('div');
  card.className = 'card';
  if(actions.length === 0) {
    card.innerHTML = `
      <div class="card-head">
        <span class="kicker">agent summary</span>
        <span class="ti" style="margin-left:4px">All clear</span>
        <span class="sp"></span>
        <span class="pill ok"><span class="dot ok"></span>no issues</span>
      </div>`;
    return card;
  }
  card.innerHTML = `
    <div class="card-head">
      <span class="kicker">agent summary</span>
      <span class="ti" style="margin-left:4px">Recommended actions</span>
      <span class="sp"></span>
      <span class="pill bad">${actions.length} to fix</span>
    </div>
    <div class="findings">${actions.map(a => `
      <div class="finding">
        <div class="glyph g-${a.sev}">${a.glyph}</div>
        <div class="f-body">
          <div class="f-top"><span class="sevtag ${a.sev}">${a.sev}</span>
            <span class="f-title">${esc(a.title)}</span></div>
          <div class="f-where">${esc(a.where||'')}</div>
        </div>
        <button class="btn sm" data-act="${a.act}" style="align-self:center">
          ${a.act==='patch'?'Apply':'Fix'}
        </button>
      </div>`).join('')}
    </div>`;
  $$('button[data-act]', card).forEach(b => b.addEventListener('click', () => {
    const a = b.dataset.act;
    if(a==='patch') toast('Drafting apply_patches(security) — will confirm before running.');
    else toast('Drafting fix — agent will show exact change before applying.');
  }));
  return card;
}

/* ─── Agent working bar ───────────────────────────────────────────────────────── */

function showAgentBar(text) {
  let bar = document.getElementById('agentbar');
  if(!bar) {
    bar = document.createElement('div');
    bar.id = 'agentbar'; bar.className = 'agentbar';
    bar.innerHTML = `<span class="dot acc pulse"></span><span class="lbl" id="agentbarLbl"></span>
      <span class="sp"></span><span class="stop">working…</span>`;
    document.querySelector('.dock').insertBefore(bar, document.querySelector('.dock').firstChild);
  }
  document.getElementById('agentbarLbl').textContent = text;
}
function hideAgentBar() { document.getElementById('agentbar')?.remove(); }

/* ─── Backup drawer ───────────────────────────────────────────────────────────── */

function _updateDrawer(results) {
  const bak = results['check_backups']?.data;
  const pbs = results['check_pbs']?.data;
  const raw = [bak?.raw, pbs?.raw].filter(Boolean).join('\n\n---\n\n');
  if(raw) {
    $('#drawerBody').innerHTML = `
      <div class="card">
        <div class="card-body" style="padding:8px">
          <pre style="font-size:11px;font-family:var(--mono);color:var(--text-2);
               white-space:pre-wrap;word-break:break-word;margin:0">${esc(raw)}</pre>
        </div>
      </div>`;
  }
}

function openDrawer(data) {
  if(data?.raw) {
    $('#drawerBody').innerHTML = `
      <div class="card">
        <div class="card-body" style="padding:8px">
          <pre style="font-size:11px;font-family:var(--mono);color:var(--text-2);
               white-space:pre-wrap;word-break:break-word;margin:0">${esc(data.raw)}</pre>
        </div>
      </div>`;
  } else {
    $('#drawerBody').innerHTML = `
      <div class="ai-text" style="color:var(--muted);padding:12px">
        No backup data loaded yet — run "Are my backups healthy?" first.
      </div>`;
  }
  _openDrawerEl($('#drawer'));
}

function closeDrawer() { _closeDrawerEl($('#drawer')); }

/* ─── Audit log drawer ────────────────────────────────────────────────────────── */

let _lastAuditRaw = [];

async function openAuditDrawer() {
  _openDrawerEl($('#auditDrawer'));
  try {
    const r = await fetch('/api/audit');
    const entries = await r.json();
    _lastAuditRaw = entries;
    _renderAudit(entries);
  } catch(e) {
    $('#auditBody').innerHTML = `<div class="ai-text" style="color:var(--crit)">Failed to load audit log: ${esc(e.message)}</div>`;
  }
  $('#auditDownload').onclick = () => {
    const blob = new Blob([_lastAuditRaw.map(e => JSON.stringify(e)).join('\n')], {type:'application/json'});
    const a = document.createElement('a'); a.href = URL.createObjectURL(blob);
    a.download = `audit-${Date.now()}.jsonl`; a.click();
  };
}

function _renderAudit(entries) {
  if(!entries.length) {
    $('#auditBody').innerHTML = `<div class="ai-text" style="color:var(--muted);padding:12px">No audit entries yet.</div>`;
    return;
  }
  const html = [...entries].reverse().map(e => {
    const irr = !e.reversible ? `<span class="ae-irr">irreversible</span>` : '';
    const ts  = (e.timestamp||'').replace('T',' ').slice(0,19);
    return `<div class="audit-entry">
      <div><span class="ae-op">${esc(e.operation||'')}</span>${irr}</div>
      <div class="ae-target">${esc(e.target||'')}</div>
      <div class="ae-meta">${ts} · ${esc(e.outcome||'')} ${e.agent?'· '+esc(e.agent):''}</div>
    </div>`;
  }).join('');
  $('#auditBody').innerHTML = `<div style="padding:0 2px">${html}</div>`;
}

function closeAuditDrawer() { _closeDrawerEl($('#auditDrawer')); }

/* ─── Drawer helpers ──────────────────────────────────────────────────────────── */

function _openDrawerEl(el) {
  if(!el) return;
  $('#scrim').classList.add('open');
  el.classList.add('open');
}
function _closeDrawerEl(el) {
  if(!el) return;
  el.classList.remove('open');
  // Only close scrim if no other drawer is open
  if(!$$('.drawer.open').length) $('#scrim').classList.remove('open');
}
function _closeTopDrawer() {
  // Close whichever drawer is open
  $$('.drawer.open').forEach(d => d.classList.remove('open'));
  $('#scrim').classList.remove('open');
}

/* ─── Settings sheet ──────────────────────────────────────────────────────────── */

async function openSettings() {
  if(!SETTINGS) {
    try {
      const r = await fetch('/api/settings');
      SETTINGS = await r.json();
    } catch(_) {
      SETTINGS = {
        provider:'claude', proxmox_host:'', ssh_user:'root', pbs_host:'', agent:'',
        autonomy: 1, ntfy_url: '',
        providers: {
          claude: {label:'Claude', model:'claude-sonnet-4-6', kind:'cloud', key:'ANTHROPIC_API_KEY', masked:''},
          openai: {label:'OpenAI', model:'gpt-4o',           kind:'cloud', key:'OPENAI_API_KEY',    masked:''},
          ollama: {label:'Ollama', model:'llama3:8b',         kind:'local', key:'OLLAMA_HOST', masked:'http://localhost:11434/v1'},
        }
      };
    }
  }
  state.provider        = SETTINGS.provider        || 'claude';
  state.autonomy        = SETTINGS.autonomy        ?? 1;
  state.preChangeBkp    = SETTINGS.pre_change_backup || 'snapshot';
  _renderSettings();
  $('#sheet').classList.add('open');
}

function closeSettings() { $('#sheet').classList.remove('open'); }

function _renderSettings() {
  // Render security badge in header
  const auton = AUTONOMY_LEVELS[state.autonomy]?.label || 'Default';
  const prot = (state.pveProtection || 'strict').charAt(0).toUpperCase() + (state.pveProtection || 'strict').slice(1);
  $('#securityBadge').textContent = `${auton} · ${prot}`;

  // Autonomy segmented control
  $('#segAutonomy').innerHTML = AUTONOMY_LEVELS.map((l, i) => `
    <button data-lvl="${i}" class="${i===state.autonomy?'on':''}">
      ${l.glyph} ${l.label}<small>${['Read-only','Default','Auto-patch','Autonomous'][i]}</small>
    </button>`).join('');
  $$('#segAutonomy button').forEach(b =>
    b.addEventListener('click', () => _setAutonomy(+b.dataset.lvl)));
  _renderAutonomyDesc();

  // Pre-change protection
  const PCB_LEVELS = [
    { key:'none',     label:'None',      sub:'Disabled',         desc:'No backup taken before changes. Fastest, least safe.' },
    { key:'snapshot', label:'Snapshot',  sub:'Instant (default)', desc:'VM/LXC snapshot before every write. Rollback in seconds. No storage overhead.' },
    { key:'pbs',      label:'PBS Backup',sub:'Incremental',       desc:'Full incremental PBS backup before changes. Off-node copy. Takes 2–5 min but survives hardware failure.' },
  ];
  $('#segProtection').innerHTML = PCB_LEVELS.map(l => `
    <button data-pcb="${l.key}" class="${l.key===state.preChangeBkp?'on':''}">
      ${l.label}<small>${l.sub}</small>
    </button>`).join('');
  $$('#segProtection button').forEach(b => b.addEventListener('click', () => {
    state.preChangeBkp = b.dataset.pcb;
    $$('#segProtection button').forEach(x => x.classList.toggle('on', x.dataset.pcb===b.dataset.pcb));
    $('#protectionDesc').textContent = PCB_LEVELS.find(l => l.key===b.dataset.pcb)?.desc || '';
  }));
  $('#protectionDesc').textContent = PCB_LEVELS.find(l => l.key===state.preChangeBkp)?.desc || '';

  // PVE host protection
  const PVE_MODES = [
    { key:'strict', label:'🔒 Strict', desc:'Block all writes to Proxmox host. Safest — cannot accidentally break PVE.' },
    { key:'warn',   label:'⚠️ Warn',  desc:'Allow host changes with pre-flight backup + confirmation. For experienced users.' },
    { key:'off',    label:'🟢 Off',   desc:'No protection. Use ONLY on dev/test nodes. Production risk.' },
  ];
  $('#segPveProtection').innerHTML = PVE_MODES.map(m => `
    <button data-pve="${m.key}" class="${m.key===state.pveProtection?'on':''}">
      ${m.label}
    </button>`).join('');
  $$('#segPveProtection button').forEach(b => b.addEventListener('click', () => {
    state.pveProtection = b.dataset.pve;
    $$('#segPveProtection button').forEach(x => x.classList.toggle('on', x.dataset.pve===b.dataset.pve));
    $('#pveProtectionDesc').textContent = PVE_MODES.find(m => m.key===b.dataset.pve)?.desc || '';
    _updateSecurityBadge();
  }));
  $('#pveProtectionDesc').textContent = PVE_MODES.find(m => m.key===state.pveProtection)?.desc || '';

  // LLM provider
  const p = SETTINGS.providers;
  $('#segProvider').innerHTML = Object.entries(p).map(([k,v]) => `
    <button data-prov="${k}" class="${k===state.provider?'on':''}">
      ${v.label}<small>${v.model}</small>
    </button>`).join('');
  $$('#segProvider button').forEach(b =>
    b.addEventListener('click', () => _setProvider(b.dataset.prov)));
  _renderProvFields();

  // Connection
  const n  = esc(SETTINGS.proxmox_host||'');
  const su = esc(SETTINGS.ssh_user||'root');
  const ph = esc(SETTINGS.pbs_host||'');
  const ag = esc(SETTINGS.agent||STATUS?.agent||'');
  $('#connFields').innerHTML = `
    <div class="row"><label>PROXMOX_HOST</label><input id="sHost"    value="${n}"></div>
    <div class="row"><label>API TOKEN</label>   <input id="sPveToken" type="password" placeholder="user@realm!id=secret (recommended)"></div>
    <div class="row"><label>—or PASS—</label>   <input id="sPvePass"  type="password" placeholder="root password (fallback)"></div>
    <div class="row"><label>SSH_USER</label>    <input id="sSshUser" value="${su}"></div>
    <div class="row"><label>PBS_HOST</label>    <input id="sPbsHost" value="${ph}"></div>
    <div class="row"><label>AGENT_BIND</label>  <input id="sAgent"   value="${ag}"></div>`;

  // Alerts
  const ntfy = esc(SETTINGS.ntfy_url||'');
  $('#alertFields').innerHTML = `
    <div class="row"><label>NTFY_URL</label><input id="sNtfy" value="${ntfy}" placeholder="https://ntfy.sh/your-topic"></div>
    <div class="ntfy-hint">Headless cron sends a push notification here when it finds critical/high findings.<br>
    Free tier at ntfy.sh — or self-host. Format: https://ntfy.sh/&lt;topic&gt;</div>`;

  $('#saveSettings').onclick = _saveSettings;
}

function _renderAutonomyDesc() {
  const lvl = AUTONOMY_LEVELS[state.autonomy] || AUTONOMY_LEVELS[1];
  $('#autonomyDesc').textContent = lvl.desc;
}

function _updateSecurityBadge() {
  const auton = AUTONOMY_LEVELS[state.autonomy]?.label || 'Default';
  const prot = (state.pveProtection || 'strict').charAt(0).toUpperCase() + (state.pveProtection || 'strict').slice(1);
  $('#securityBadge').textContent = `${auton} · ${prot}`;
}

function _renderProvFields() {
  const v = SETTINGS.providers[state.provider];
  if(!v) return;
  $('#provFields').innerHTML = `
    <div class="row"><label>${v.key}</label>
      <input id="sApiKey" type="password" placeholder="${esc(v.masked||'enter key…')}"></div>
    <div class="row"><label>MODEL</label>
      <input id="sModel" value="${esc(v.model)}"></div>
    <div class="row"><label>${v.kind==='local'?'CONTEXT':'MAX_TOKENS'}</label>
      <input value="${v.kind==='local'?'8192':'4096'}"></div>`;
  _renderEnvPreview();
}

function _renderEnvPreview() {
  const v = SETTINGS.providers[state.provider];
  if(!v) return;
  const node = $('#sHost')?.value || SETTINGS.proxmox_host || '';
  const lvl  = AUTONOMY_LEVELS[state.autonomy]?.key || 'suggest';
  $('#envPreview').innerHTML =
    `<span class="k">LLM_PROVIDER=</span><span class="v">${state.provider}</span>\n` +
    `<span class="k">${v.key}=</span><span class="v">${esc(v.masked||'…')}</span>\n` +
    `<span class="k">MODEL=</span><span class="v">${esc(v.model)}</span>\n` +
    `<span class="k">PROXMOX_HOST=</span><span class="v">${esc(node)}</span>\n` +
    `<span class="k">AGENT_AUTONOMY=</span><span class="v">${state.autonomy} # ${lvl}</span>`;
}

function _setAutonomy(n) {
  state.autonomy = n;
  $$('#segAutonomy button').forEach(b => b.classList.toggle('on', +b.dataset.lvl===n));
  _renderAutonomyDesc();
  _renderAutonomyBadge();
  _updateSecurityBadge();
  _renderEnvPreview();
}

function _setProvider(k) {
  state.provider = k;
  $$('#segProvider button').forEach(b => b.classList.toggle('on', b.dataset.prov===k));
  $('#aiProvider').textContent = SETTINGS.providers[k]?.label || k;
  _renderProvFields();
}

async function _saveSettings() {
  const payload = {
    provider:           state.provider,
    autonomy:           state.autonomy,
    pre_change_backup:  state.preChangeBkp || 'snapshot',
    pve_protection:     state.pveProtection || 'strict',
    proxmox_host:  $('#sHost')?.value     || '',
    proxmox_token: $('#sPveToken')?.value || '',
    proxmox_pass:  $('#sPvePass')?.value  || '',
    ssh_user:      $('#sSshUser')?.value  || '',
    pbs_host:      $('#sPbsHost')?.value  || '',
    ntfy_url:      $('#sNtfy')?.value     || '',
    api_key:       $('#sApiKey')?.value   || '',
  };
  try {
    const r = await fetch('/api/settings', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    if(!r.ok) throw new Error(`HTTP ${r.status}`);
    SETTINGS = null;
    STATUS   = null;
    await loadStatus();
    closeSettings();
    toast('Saved · agent reloaded env');
  } catch(e) {
    toast('Save failed: ' + e.message);
  }
}

/* ─── Misc ────────────────────────────────────────────────────────────────────── */

function resetChat() {
  localStorage.removeItem(HISTORY_KEY);
  stream.innerHTML = _welcomeHTML();
  state.started = false;
  wireWelcome();
  closeDrawer();
}

function _welcomeHTML() {
  const node = STATUS?.node || '?';
  return `<div class="welcome" id="welcome">
    <div class="big-mark">◈</div>
    <h1>How can I help with your homelab?</h1>
    <p>I'm watching node <b id="welcomeNode" style="color:var(--text-2)">${esc(node)}</b> from the Pi. Ask in plain English — I'll run the tools.</p>
    <div class="suggest">
      <button class="sug go"  data-tool="checkup"><span class="g">◆</span>Run a full health check<span class="ar">→</span></button>
      <button class="sug"     data-tool="inventory"><span class="g">▤</span>What's running right now?<span class="ar">→</span></button>
      <button class="sug"     data-tool="patches"><span class="g">⬇</span>Any patches I should worry about?<span class="ar">→</span></button>
      <button class="sug"     data-tool="backups"><span class="g">⛛</span>Are my backups healthy?<span class="ar">→</span></button>
      <button class="sug"     data-tool="security"><span class="g">⚿</span>Run a security audit<span class="ar">→</span></button>
      <button class="sug"     data-tool="helpers"><span class="g">◆</span>Find &amp; install a community script<span class="ar">→</span></button>
    </div>
    <div class="trust-strip">
      <span>● every command logged</span>
      <span>● read-only by default</span>
      <span>● keys never leave the Pi</span>
      <span>● Ollama = fully local</span>
    </div>
    <div style="margin-top:20px;padding:12px 14px;background:rgba(91,156,240,.08);border-left:3px solid var(--info);border-radius:6px;font-size:13px;color:var(--text-2)">
      <strong style="color:var(--info)">🔍 Transparency First</strong><br>
      Not an "AI agent"—a decision-support tool. Before any change:<br>
      • Ask the community: <button class="btn xs ghost" onclick="routeAndRun('community')">ask_community()</button>
      • See my reasoning: <button class="btn xs ghost" onclick="routeAndRun('reasoning')">show_reasoning()</button>
      • Check the audit: <button class="btn xs ghost" onclick="openAuditDrawer()">audit log</button><br>
      You decide. I just provide data and options.
    </div></div>`;
}

function wireWelcome() {
  $$('#welcome .sug').forEach(b =>
    b.addEventListener('click', () => { if(!state.busy) routeAndRun(b.dataset.tool); }));
}

let toastT;
function toast(msg) {
  const t = $('#toast');
  t.innerHTML = `<span class="dot ok"></span>${esc(msg)}`;
  t.classList.add('show');
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.remove('show'), 2600);
}

/* Expose globals for inline HTML onclick */
window.closeDrawer      = closeDrawer;
window.closeAuditDrawer = closeAuditDrawer;
window.toast            = toast;
