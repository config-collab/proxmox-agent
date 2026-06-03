/* ============================================================
   Proxmox Assistant — front-end logic (vanilla, no build step)
   Mirrors the shippable stack: plain JS talking to a streaming
   backend. Here the "stream" is simulated from DATA.
   ============================================================ */

const $  = (s, r=document) => r.querySelector(s);
const $$ = (s, r=document) => [...r.querySelectorAll(s)];
const sleep = ms => new Promise(r => setTimeout(r, ms));
const esc = s => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));

const state = { provider: DATA.provider, busy: false, started: false, calls: 0 };

/* fake clock for plausible timestamps */
let clock = new Date(2026, 4, 31, 9, 41, 0);
function stamp(adv = 2){ clock = new Date(clock.getTime() + adv*1000);
  return clock.toTimeString().slice(0,8); }

/* ---- refs ---- */
let stream, dock, consoleEl, consoleBody, consoleCnt, ta, sendBtn;

document.addEventListener('DOMContentLoaded', () => {
  stream      = $('#stream');
  consoleEl   = $('#console');
  consoleBody = $('#consoleBody');
  consoleCnt  = $('#consoleCnt');
  ta          = $('#ta');
  sendBtn     = $('#sendBtn');

  renderChips();
  buildSettings();
  wireComposer();
  wireConsole();

  $('#gear').addEventListener('click', () => toggleSheet(true));
  $('#closeSheet').addEventListener('click', () => toggleSheet(false));
  $('#newChat').addEventListener('click', resetChat);
  $('#scrim').addEventListener('click', closeDrawer);
  $('#closeDrawer').addEventListener('click', closeDrawer);
});

/* ============================================================ CHIPS */
function renderChips(){
  const s = DATA.summary;
  const map = [
    ['inventory','Inventory', s.inventory],
    ['backups','Backups',     s.backups],
    ['patches','Patches',     s.patches],
    ['security','Security',   s.security],
  ];
  $('#chips').innerHTML = map.map(([k,label,o]) => `
    <button class="stat" data-tool="${k}">
      <span class="k"><span class="dot ${o.status}"></span>${label}</span>
      <span class="v">${o.value}</span>
      <span class="n">${o.note}</span>
    </button>`).join('');
  $$('#chips .stat').forEach(b =>
    b.addEventListener('click', () => { if(!state.busy) routeAndRun(b.dataset.tool, true); }));
}

/* ============================================================ COMPOSER */
function wireComposer(){
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
function submit(){
  const v = ta.value.trim();
  if(!v || state.busy) return;
  ta.value = ''; ta.style.height = 'auto'; sendBtn.disabled = true;
  handleUser(v);
}

/* ============================================================ CONSOLE */
function wireConsole(){
  $('#consoleHead').addEventListener('click', () => consoleEl.classList.toggle('collapsed'));
}
function pushConsole(html, count = false){
  const idle = $('.idle', consoleBody);
  if(idle) idle.remove();
  const div = document.createElement('div');
  div.innerHTML = html;
  consoleBody.appendChild(div);
  consoleBody.scrollTop = consoleBody.scrollHeight;
  if(count){ state.calls++; consoleCnt.textContent = state.calls + (state.calls===1?' call':' calls'); }
}

/* ============================================================ STREAM HELPERS */
function clearWelcome(){
  const w = $('#welcome');
  if(w){ w.remove(); state.started = true; }
}
function addUser(text){
  clearWelcome();
  const m = document.createElement('div');
  m.className = 'msg bubble me';
  m.textContent = text;
  stream.appendChild(m);
  toBottom();
}
function addAi(){
  const m = document.createElement('div');
  m.className = 'msg ai-line';
  m.innerHTML = `<div class="ai-av">AI</div><div class="ai-body"></div>`;
  stream.appendChild(m);
  toBottom();
  return $('.ai-body', m);
}
function toBottom(){ requestAnimationFrame(() => { stream.scrollTop = stream.scrollHeight; }); }

/* ============================================================ ROUTING */
function handleUser(text){
  addUser(text);
  const tool = classify(text);
  runPlan(tool);
}
function routeAndRun(tool, fromChip){
  const labels = { inventory:'What\'s running right now?', patches:'Any patches I should worry about?',
    backups:'Are my backups healthy?', security:'Run a security audit.',
    checkup:'Run a full health check of the cluster.' };
  addUser(labels[tool] || tool);
  runPlan(tool);
}
function classify(t){
  t = t.toLowerCase();
  if(/(full|everything|all of|health ?check|check ?up|status report|overall|rundown|once.?over|sweep|look around|how.?s everything)/.test(t)) return 'checkup';
  if(/(patch|updat|upgrad|apt|cve)/.test(t)) return 'patches';
  if(/(backup|pbs|snapshot|restore|datastore)/.test(t)) return 'backups';
  if(/(inventory|running|vms?|nodes?|guests?|what.?s up|cluster)/.test(t)) return 'inventory';
  if(/(secur|audit|harden|vuln|firewall|ssh|2fa)/.test(t)) return 'security';
  return 'fallback';
}

/* ============================================================ PLANS */
async function runPlan(tool){
  state.busy = true; sendBtn.disabled = true;
  const body = addAi();
  const think = document.createElement('div');
  think.className = 'thinking';
  think.innerHTML = `<i></i><i></i><i></i> reading env_profile…`;
  body.appendChild(think);
  await sleep(550);
  think.remove();

  const plans = { inventory:planInventory, patches:planPatches, backups:planBackups,
    security:planSecurity, checkup:planCheckup, fallback:planFallback };
  await plans[tool](body);

  state.busy = false;
  sendBtn.disabled = !ta.value.trim();
  toBottom();
}

/* streamed tool-log block: returns the body el for appending result */
async function streamLog(parent, name, lines){
  const wrap = document.createElement('div');
  wrap.className = 'toollog';
  wrap.innerHTML = `<div class="tl-head"><span class="dot acc pulse"></span>
    <span>[tool]</span><span class="nm">${esc(name)}</span><span class="sp"></span>
    <span class="ts">running</span></div><div class="tl-body"></div>`;
  parent.appendChild(wrap);
  const tbody = $('.tl-body', wrap);
  pushConsole(`<span class="ts">${stamp()}</span> <span class="t">[tool]</span> ${esc(name)}`, true);
  toBottom();

  for(const ln of lines){
    await sleep(ln.d || 480);
    const row = document.createElement('div');
    row.innerHTML = ln.html;
    tbody.appendChild(row);
    if(ln.console) pushConsole(`<span class="ts">${stamp()}</span> ${ln.console}`);
    toBottom();
  }
  $('.tl-head .ts', wrap).textContent = 'done';
  $('.tl-head .dot', wrap).classList.remove('pulse');
  await sleep(260);
}

async function aiText(parent, html){
  const p = document.createElement('div');
  p.className = 'ai-text';
  p.innerHTML = html;
  parent.appendChild(p);
  toBottom();
  await sleep(120);
}

/* ---------- INVENTORY ---------- */
async function planInventory(body){
  await streamLog(body, 'get_inventory()', [
    { html:`<span class="mut">› ssh pvesh get /cluster/resources --type vm</span>`, d:420 },
    { html:`<span class="ok">✓ 3 nodes · 11 VMs · 10 running</span>`, console:`<span class="ok">✓ 11 VMs · 10 running</span>`, d:520 },
  ]);
  body.appendChild(invCard());
  await aiText(body, `Everything's reachable — <b>10 of 11</b> VMs are running. The only one down is <span class="em">110 bak</span>, your backup target, which is fine to leave stopped.`);
}
function invCard(){
  const rows = DATA.inventory;
  const card = document.createElement('div');
  card.className = 'card';
  const render = (n) => rows.slice(0,n).map(v => `
    <tr class="${v.state==='stopped'?'dim':''}">
      <td class="mono">${v.id}</td><td>${esc(v.name)}</td><td class="mono">${v.node}</td>
      <td><span class="state"><span class="dot ${v.state==='running'?'ok':'warn'}"></span>${v.state}</span></td>
      <td class="mono">${v.mem}</td><td class="mono">${v.load}</td>
    </tr>`).join('');
  card.innerHTML = `
    <div class="card-head"><span class="kicker">get_inventory</span><span class="ti" style="margin-left:4px">Cluster inventory</span>
      <span class="sp"></span><span class="pill ok"><span class="dot ok"></span>10 up</span></div>
    <div class="card-body"><table class="tbl">
      <thead><tr><th>VMID</th><th>Name</th><th>Node</th><th>State</th><th>Mem</th><th>Load</th></tr></thead>
      <tbody>${render(6)}</tbody></table></div>
    <div class="card-foot"><button class="btn sm ghost" id="invMore">Show all 11 ▾</button>
      <button class="btn sm ghost">Copy markdown</button></div>`;
  let open = false;
  card.querySelector('#invMore').addEventListener('click', e => {
    open = !open;
    card.querySelector('tbody').innerHTML = render(open ? rows.length : 6);
    e.target.textContent = open ? 'Show less ▴' : 'Show all 11 ▾';
    toBottom();
  });
  return card;
}

/* ---------- PATCHES ---------- */
async function planPatches(body){
  await streamLog(body, `check_patches(host="pve-1")`, [
    { html:`<span class="mut">› ssh apt-get update -q</span>`, d:430 },
    { html:`<span class="mut">› apt list --upgradable</span>`, d:430 },
    { html:`<span class="ok">✓ 14 upgradable · 3 security</span>`, console:`<span class="ok">✓ 14 upgradable · 3 sec</span>`, d:480 },
  ]);
  body.appendChild(patchCard());
  await aiText(body, `<b>14 packages</b> pending on pve-1. <span class="em">3 are security</span> — openssl, libssl3, sudo. I'd apply those now and schedule the rest. Want me to?`);
}
function patchCard(){
  const card = document.createElement('div');
  card.className = 'card';
  const rows = DATA.patches.list.map(p => `
    <tr><td class="mono">${esc(p.pkg)}</td><td class="mono">${esc(p.to)}</td>
    <td>${p.type==='security'
      ? '<span class="sevtag high">security</span>'
      : '<span class="state" style="color:var(--faint)">routine</span>'}</td></tr>`).join('');
  card.innerHTML = `
    <div class="card-head"><span class="kicker">check_patches</span><span class="ti" style="margin-left:4px">Patch report · pve-1</span>
      <span class="sp"></span><span class="pill warn"><span class="dot warn"></span>14 pending</span></div>
    <div class="card-body"><table class="tbl">
      <thead><tr><th>Package</th><th>→ Version</th><th>Type</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
    <div class="card-foot">
      <button class="btn primary sm" id="applySec">Apply security (3)</button>
      <button class="btn ghost sm" id="applyAll">Apply all (14)</button>
      <button class="btn ghost sm">Dry run</button></div>`;
  card.querySelector('#applySec').addEventListener('click', () => applyPatches(card, 'security', 3));
  card.querySelector('#applyAll').addEventListener('click', () => applyPatches(card, 'all', 14));
  return card;
}
async function applyPatches(card, scope, n){
  if(state.busy) return;
  state.busy = true;
  const foot = card.querySelector('.card-foot');
  foot.innerHTML = `<span class="thinking"><i></i><i></i><i></i> applying ${scope} (${n})…</span>`;
  consoleEl.classList.remove('collapsed');
  pushConsole(`<span class="ts">${stamp()}</span> <span class="t">[tool]</span> apply_patches(${scope})`, true);
  const pkgs = scope==='security' ? ['openssl','libssl3','sudo'] : ['openssl','libssl3','sudo','curl','vim','…'];
  for(const p of pkgs){
    await sleep(420);
    pushConsole(`<span class="ts">${stamp()}</span> <span class="ok">✓</span> ${p} <span class="mut">unpacked & configured</span>`);
  }
  await sleep(380);
  pushConsole(`<span class="ts">${stamp()}</span> <span class="ok">✓ done</span> <span class="mut">no reboot required</span>`);
  card.querySelector('.card-head .pill').outerHTML = `<span class="pill ok"><span class="dot ok"></span>applied</span>`;
  foot.innerHTML = `<span class="pill ok"><span class="dot ok"></span>${n} packages applied · no reboot</span>`;
  // refresh summary chip
  DATA.summary.patches = { value:'up to date', status:'ok', note:'applied just now' };
  renderChips();
  state.busy = false; sendBtn.disabled = !ta.value.trim();
  toBottom();
}

/* ---------- BACKUPS (drawer = direction B) ---------- */
async function planBackups(body){
  await streamLog(body, 'check_backups()', [
    { html:`<span class="ok">✓ 9/11 fresh · 2 stale</span>`, console:`<span class="ok">✓ 9/11 fresh</span>`, d:460 },
  ]);
  await streamLog(body, `check_pbs(store="pbs-main")`, [
    { html:`<span class="mut">› proxmox-backup-manager datastore status</span>`, d:400 },
    { html:`<span class="ok">✓ 61% used · GC ok · verify passed</span>`, console:`<span class="ok">✓ PBS 61% · verified</span>`, d:480 },
  ]);
  const note = document.createElement('div');
  note.className = 'card';
  note.innerHTML = `<div class="card-head"><span class="kicker">backup health</span>
    <span class="ti" style="margin-left:4px">9 / 11 fresh</span><span class="sp"></span>
    <button class="btn sm" id="openBak">Open report ▸</button></div>`;
  body.appendChild(note);
  note.querySelector('#openBak').addEventListener('click', openDrawer);
  await aiText(body, `<b>9 of 11</b> backed up in the last 24h. Two are behind — <span class="em">110 bak</span> (19h) and <span class="em">wireguard</span> (3 days overdue). I opened the full report.`);
  await sleep(250);
  openDrawer();
}
function openDrawer(){
  const b = DATA.backups;
  $('#drawerBody').innerHTML = `
    <div class="minicards">
      <div class="mini"><div class="k">Coverage</div><div class="v">${b.coverage}</div>
        <span class="pill warn"><span class="dot warn"></span>${b.stale} stale</span></div>
      <div class="mini"><div class="k">PBS · ${b.pbs.store}</div><div class="v">${b.pbs.used}</div>
        <div class="bar"><i style="width:${b.pbs.used}"></i></div>
        <span class="pill ok" style="margin-top:8px"><span class="dot ok"></span>GC ${b.pbs.gc} · ${b.pbs.verify}</span></div>
    </div>
    <div class="card"><div class="card-body" style="padding:4px"><table class="tbl">
      <thead><tr><th>VMID</th><th>Name</th><th>Last backup</th><th>Size</th><th>Status</th></tr></thead>
      <tbody>${b.list.map(v => {
        const st = v.status==='fresh' ? ['ok','fresh'] : v.status==='stale' ? ['warn','stale'] : ['bad','overdue'];
        return `<tr><td class="mono">${v.id}</td><td>${esc(v.name)}</td><td>${v.last}</td>
          <td class="mono">${v.size}</td><td><span class="state"><span class="dot ${st[0]}"></span>${st[1]}</span></td></tr>`;
      }).join('')}</tbody></table></div></div>`;
  $('#scrim').classList.add('open');
  $('#drawer').classList.add('open');
}
function closeDrawer(){ $('#scrim').classList.remove('open'); $('#drawer').classList.remove('open'); }

/* ---------- SECURITY ---------- */
async function planSecurity(body){
  await streamLog(body, 'security_audit()', [
    { html:`<span class="mut">› sshd_config · pve-firewall · realm 2fa · apt cves</span>`, d:520 },
    { html:`<span class="ok">✓ score B+ · 5 findings · 1 critical</span>`, console:`<span class="ok">✓ B+ · 1 critical</span>`, d:520 },
  ]);
  body.appendChild(secCard());
  await aiText(body, `Posture is <b>B+</b>. The one that matters: <span class="em">root SSH login is enabled</span> on pve-1 — fix that first, then the 3 security patches.`);
}
function secCard(){
  const card = document.createElement('div');
  card.className = 'card';
  const f = [...DATA.security.findings].sort((a,b)=>SEV_RANK[a.sev]-SEV_RANK[b.sev]);
  card.innerHTML = `
    <div class="card-head"><span class="kicker">security_audit</span><span class="ti" style="margin-left:4px">Findings</span>
      <span class="sp"></span><span class="pill bad">score ${DATA.security.score}</span></div>
    <div class="findings">${f.map(x => `
      <div class="finding">
        <div class="glyph g-${x.sev}">${x.glyph}</div>
        <div class="f-body">
          <div class="f-top"><span class="sevtag ${x.sev}">${x.sev}</span>
            <span class="f-title">${esc(x.title)}</span></div>
          <div class="f-where">${esc(x.where)}</div>
          <div class="f-detail">${esc(x.detail)}</div>
          <div class="f-fix"><button class="btn sm">Ask agent to fix ▸</button></div>
        </div>
      </div>`).join('')}</div>`;
  $$('.f-fix .btn', card).forEach(b => b.addEventListener('click', () =>
    toast('Queued — the agent will draft the fix and ask before applying.')));
  return card;
}

/* ---------- AGENTIC: full health check (autonomous multi-tool loop) ---------- */
function showAgentBar(text){
  let bar = document.getElementById('agentbar');
  if(!bar){
    bar = document.createElement('div');
    bar.id = 'agentbar'; bar.className = 'agentbar';
    bar.innerHTML = `<span class="dot acc pulse"></span><span class="lbl" id="agentbarLbl"></span>
      <span class="sp"></span><span class="stop">working…</span>`;
    const dock = document.querySelector('.dock');
    dock.insertBefore(bar, dock.firstChild);
  }
  document.getElementById('agentbarLbl').textContent = text;
}
function hideAgentBar(){ const b = document.getElementById('agentbar'); if(b) b.remove(); }

const STEP_DEFS = {
  get_inventory:   { cmd:'pvesh get /cluster/resources --type vm', ok:'11 VMs · 10 running', meta:'10/11 up',   status:'ok'   },
  check_patches:   { cmd:'apt-get update -q && apt list --upgradable', ok:'14 upgradable · 3 security', meta:'14 · 3 sec', status:'warn' },
  check_backups:   { cmd:'proxmox-backup-manager datastore status', ok:'9/11 fresh · PBS 61% verified', meta:'2 stale',  status:'warn' },
  security_audit:  { cmd:'sshd · firewall · realm 2fa · apt cves', ok:'score B+ · 1 critical', meta:'B+ · 1 crit', status:'bad' },
};

async function runStepTool(tool){
  const d = STEP_DEFS[tool];
  pushConsole(`<span class="ts">${stamp()}</span> <span class="t">[tool]</span> ${tool}()`, true);
  await sleep(540);
  pushConsole(`<span class="ts">${stamp()}</span> <span class="mut">› ${esc(d.cmd)}</span>`);
  await sleep(620);
  pushConsole(`<span class="ts">${stamp()}</span> <span class="ok">✓ ${esc(d.ok)}</span>`);
  await sleep(320);
  return d;
}

async function planCheckup(body){
  const steps = ['get_inventory','check_patches','check_backups','security_audit'];
  await aiText(body, `On it — I'll run all four checks autonomously and report back, worst-first. <span class="em">Read-only</span>, no changes made.`);

  const plan = document.createElement('div');
  plan.className = 'agentplan';
  plan.innerHTML = `
    <div class="ap-head"><span class="ic">◆</span><span class="ti">Agent plan · full health check</span>
      <span class="sp"></span><span class="pr" id="apPr">0 / ${steps.length}</span></div>
    <div class="ap-steps">${steps.map((s,i)=>`
      <div class="ap-step" data-i="${i}"><span class="box">${i+1}</span>
      <span class="nm">${s}()</span><span class="meta"></span></div>`).join('')}</div>`;
  body.appendChild(plan);
  consoleEl.classList.remove('collapsed');
  toBottom();

  for(let i=0;i<steps.length;i++){
    const row = plan.querySelector(`.ap-step[data-i="${i}"]`);
    row.classList.add('active'); row.querySelector('.box').textContent = '';
    showAgentBar(`Agent running · ${steps[i]}()  ·  step ${i+1}/${steps.length}`);
    const r = await runStepTool(steps[i]);
    row.classList.remove('active'); row.classList.add('done');
    row.querySelector('.box').textContent = '✓';
    const m = row.querySelector('.meta');
    m.innerHTML = `<span class="dot ${r.status}" style="margin-right:5px"></span>${r.meta}`;
    plan.querySelector('#apPr').textContent = `${i+1} / ${steps.length}`;
    toBottom();
  }
  hideAgentBar();
  await sleep(280);

  body.appendChild(checkupSummary());
  await aiText(body, `Bottom line: the cluster is <b>healthy and running</b>, but there's <span class="em">one critical security gap</span> and a couple of housekeeping items. Fix the root SSH login first — I can walk you through any of these.`);
}

function checkupSummary(){
  const card = document.createElement('div');
  card.className = 'card';
  const actions = [
    { sev:'critical', glyph:'▲', title:'Root SSH login enabled', where:'pve-1 · sshd_config', btn:'Fix', act:'fix' },
    { sev:'high',     glyph:'●', title:'3 security patches unapplied', where:'openssl · libssl3 · sudo', btn:'Apply', act:'patch' },
    { sev:'medium',   glyph:'◆', title:'2 backups stale', where:'110 bak · wireguard', btn:'Back up', act:'backup' },
  ];
  card.innerHTML = `
    <div class="card-head"><span class="kicker">agent summary</span>
      <span class="ti" style="margin-left:4px">Recommended actions</span>
      <span class="sp"></span><span class="pill bad">3 to fix</span></div>
    <div class="findings">${actions.map(a=>`
      <div class="finding">
        <div class="glyph g-${a.sev}">${a.glyph}</div>
        <div class="f-body"><div class="f-top"><span class="sevtag ${a.sev}">${a.sev}</span>
          <span class="f-title">${esc(a.title)}</span></div>
          <div class="f-where">${esc(a.where)}</div></div>
        <button class="btn sm" data-act="${a.act}" style="align-self:center">${a.btn}</button>
      </div>`).join('')}</div>
    <div class="card-foot" style="color:var(--muted);font-size:12px">
      <span class="pill ok"><span class="dot ok"></span>10/11 VMs healthy</span>
      <span class="pill ok"><span class="dot ok"></span>PBS verified</span></div>`;
  $$('button[data-act]', card).forEach(b => b.addEventListener('click', () => {
    const a = b.dataset.act;
    if(a==='backup'){ openDrawer(); }
    else if(a==='patch'){ toast('Drafting apply_patches(security) — will confirm before running.'); }
    else { toast('Drafting fix: set PermitRootLogin prohibit-password on pve-1.'); }
  }));
  return card;
}

/* ---------- FALLBACK ---------- */
async function planFallback(body){
  await aiText(body, `I can pull live status from your node at <span class="em">${DATA.node}</span>. Try one of these:`);
  const row = document.createElement('div');
  row.style.cssText = 'display:flex;gap:8px;flex-wrap:wrap';
  row.innerHTML = ['checkup','inventory','patches','backups','security']
    .map(k => `<button class="btn sm" data-tool="${k}">${k==='checkup'?'full check':k}</button>`).join('');
  body.appendChild(row);
  $$('button', row).forEach(b => b.addEventListener('click', () => { if(!state.busy) routeAndRun(b.dataset.tool); }));
}

/* ============================================================ SETTINGS */
function buildSettings(){
  const p = DATA.providers;
  $('#segProvider').innerHTML = Object.entries(p).map(([k,v]) => `
    <button data-prov="${k}" class="${k===state.provider?'on':''}">
      ${v.label}<small>${v.model}</small></button>`).join('');
  $$('#segProvider button').forEach(b => b.addEventListener('click', () => setProvider(b.dataset.prov)));
  renderProviderFields();

  $('#connFields').innerHTML = `
    <div class="row"><label>PROXMOX_HOST</label><input value="${DATA.node}"></div>
    <div class="row"><label>SSH_USER</label><input value="root"></div>
    <div class="row"><label>PBS_HOST</label><input value="${DATA.pbs}"></div>
    <div class="row"><label>AGENT_BIND</label><input value="${DATA.agent}"></div>`;

  $('#saveSettings').addEventListener('click', () => { renderChips(); toggleSheet(false); toast('Saved · agent reloaded env_profile'); });
}
function renderProviderFields(){
  const v = DATA.providers[state.provider];
  $('#provFields').innerHTML = `
    <div class="row"><label>${v.key}</label><input type="password" value="${v.masked}"></div>
    <div class="row"><label>MODEL</label><input value="${v.model}"></div>
    <div class="row"><label>${v.kind==='local'?'CONTEXT':'MAX_TOKENS'}</label><input value="${v.kind==='local'?'8192':'4096'}"></div>`;
  $('#envPreview').innerHTML =
    `<span class="k">PROVIDER=</span><span class="v">${state.provider}</span>\n` +
    `<span class="k">${v.key}=</span><span class="v">${v.masked}</span>\n` +
    `<span class="k">MODEL=</span><span class="v">${v.model}</span>\n` +
    `<span class="k">PROXMOX_HOST=</span><span class="v">${DATA.node}</span>\n` +
    `<span class="k">AGENT_BIND=</span><span class="v">${DATA.agent}</span>\n` +
    `<span class="k">LOG_LEVEL=</span><span class="v">info</span>`;
}
function setProvider(k){
  state.provider = k;
  $$('#segProvider button').forEach(b => b.classList.toggle('on', b.dataset.prov===k));
  $('#aiProvider').textContent = DATA.providers[k].label;
  renderProviderFields();
}
function toggleSheet(open){ $('#sheet').classList.toggle('open', open); }

/* ============================================================ MISC */
function resetChat(){
  stream.innerHTML = welcomeHTML();
  state.started = false;
  wireWelcome();
  closeDrawer();
}
function welcomeHTML(){
  return `<div class="welcome" id="welcome">
    <div class="big-mark">◈</div>
    <h1>How can I help with your homelab?</h1>
    <p>I'm watching node <b style="color:var(--text-2)">${DATA.node}</b> from the Pi. Ask in plain English — I'll run the tools.</p>
    <div class="suggest">
      <button class="sug go" data-tool="checkup"><span class="g">◆</span>Run a full health check<span class="ar">→</span></button>
      <button class="sug" data-tool="inventory"><span class="g">▤</span>What's running right now?<span class="ar">→</span></button>
      <button class="sug" data-tool="patches"><span class="g">⬇</span>Any patches I should worry about?<span class="ar">→</span></button>
      <button class="sug" data-tool="backups"><span class="g">⛁</span>Are my backups healthy?<span class="ar">→</span></button>
      <button class="sug" data-tool="security"><span class="g">⚿</span>Run a security audit<span class="ar">→</span></button>
    </div></div>`;
}
function wireWelcome(){
  $$('#welcome .sug').forEach(b => b.addEventListener('click', () => { if(!state.busy) routeAndRun(b.dataset.tool); }));
}

let toastT;
function toast(msg){
  const t = $('#toast');
  t.innerHTML = `<span class="dot ok"></span>${esc(msg)}`;
  t.classList.add('show');
  clearTimeout(toastT);
  toastT = setTimeout(() => t.classList.remove('show'), 2600);
}

/* boot welcome once DOM ready (stream filled by HTML, just wire it) */
document.addEventListener('DOMContentLoaded', wireWelcome);
