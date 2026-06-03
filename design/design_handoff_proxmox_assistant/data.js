/* ============================================================
   Placeholder env_profile + tool outputs.
   Mirrors what the Pi-side agent would write to env_profile.json
   and what each of the 6 tools returns. Swap with real values.
   ============================================================ */

const DATA = {
  node: "192.168.0.91",
  pbs: "192.168.0.91:8007",
  agent: "192.168.0.134:8080",
  provider: "claude",            // claude | openai | ollama
  generated: "2026-05-31 09:41",

  summary: {
    inventory: { value: "3 nodes · 11 VMs", status: "ok",   note: "10 running · 1 stopped" },
    backups:   { value: "9 / 11 fresh",     status: "warn", note: "2 stale · oldest 3d" },
    patches:   { value: "14 pending",       status: "warn", note: "3 security" },
    security:  { value: "B+",               status: "bad",  note: "1 critical finding" }
  },

  // ---- get_inventory ----
  inventory: [
    { id:101, name:"web",            node:"pve-1", state:"running", cpu:"4c", mem:"2.1G", load:"12%" },
    { id:102, name:"db",             node:"pve-1", state:"running", cpu:"8c", mem:"6.4G", load:"41%" },
    { id:106, name:"nextcloud",      node:"pve-1", state:"running", cpu:"4c", mem:"4.0G", load:"31%" },
    { id:109, name:"wireguard",      node:"pve-1", state:"running", cpu:"1c", mem:"256M", load:"2%"  },
    { id:103, name:"dns",            node:"pve-2", state:"running", cpu:"1c", mem:"512M", load:"3%"  },
    { id:104, name:"media",          node:"pve-2", state:"running", cpu:"4c", mem:"3.0G", load:"22%" },
    { id:105, name:"home-assistant", node:"pve-2", state:"running", cpu:"2c", mem:"1.2G", load:"9%"  },
    { id:111, name:"test",           node:"pve-2", state:"running", cpu:"2c", mem:"800M", load:"5%"  },
    { id:107, name:"vault",          node:"pve-3", state:"running", cpu:"2c", mem:"1.0G", load:"6%"  },
    { id:108, name:"grafana",        node:"pve-3", state:"running", cpu:"2c", mem:"1.5G", load:"14%" },
    { id:110, name:"bak",            node:"pve-3", state:"stopped", cpu:"—",  mem:"—",    load:"—"   }
  ],

  // ---- check_patches ----
  patches: {
    host: "pve-1",
    total: 14,
    security: 3,
    list: [
      { pkg:"openssl",      to:"3.0.14-1", type:"security" },
      { pkg:"libssl3",      to:"3.0.14-1", type:"security" },
      { pkg:"sudo",         to:"1.9.15p5", type:"security" },
      { pkg:"curl",         to:"8.5.0-2",  type:"routine"  },
      { pkg:"vim",          to:"9.1.0016", type:"routine"  },
      { pkg:"pve-manager",  to:"8.2.4",    type:"routine"  },
      { pkg:"htop",         to:"3.3.0-1",  type:"routine"  }
    ]
  },

  // ---- check_backups + check_pbs ----
  backups: {
    coverage: "9 / 11",
    stale: 2,
    pbs: { used: "61%", gc: "ok", verify: "passed", store: "pbs-main" },
    list: [
      { id:101, name:"web",        last:"2h ago",  size:"2.1G", status:"fresh"   },
      { id:102, name:"db",         last:"2h ago",  size:"6.0G", status:"fresh"   },
      { id:106, name:"nextcloud",  last:"5h ago",  size:"3.8G", status:"fresh"   },
      { id:103, name:"dns",        last:"6h ago",  size:"0.4G", status:"fresh"   },
      { id:110, name:"bak",        last:"19h ago", size:"—",    status:"stale"   },
      { id:109, name:"wireguard",  last:"3d ago",  size:"0.2G", status:"overdue" }
    ]
  },

  // ---- security_audit ----
  security: {
    score: "B+",
    findings: [
      { sev:"critical", glyph:"▲", title:"Root SSH login enabled",      where:"pve-1 · /etc/ssh/sshd_config", detail:"PermitRootLogin yes — disable or restrict to keys." },
      { sev:"high",     glyph:"●", title:"3 security patches unapplied", where:"pve-1 · openssl, libssl3, sudo", detail:"Known CVEs pending. Apply via check/apply_patches." },
      { sev:"medium",   glyph:"◆", title:"Firewall disabled on 2 VMs",  where:"104 media · 111 test",          detail:"No pve-firewall ruleset bound; default-allow." },
      { sev:"low",      glyph:"○", title:"SSH password auth enabled",   where:"all nodes",                     detail:"PasswordAuthentication yes alongside keys." },
      { sev:"low",      glyph:"○", title:"No 2FA on web UI",            where:"datacenter realm",              detail:"TOTP available but not enforced for root@pam." }
    ]
  },

  providers: {
    claude:  { label:"Claude",  model:"claude-sonnet-4", kind:"cloud", key:"ANTHROPIC_API_KEY", masked:"sk-ant-••••4a2" },
    openai:  { label:"OpenAI",  model:"gpt-4o",          kind:"cloud", key:"OPENAI_API_KEY",    masked:"sk-••••9f1"   },
    ollama:  { label:"Ollama",  model:"llama3:8b",       kind:"local", key:"OLLAMA_HOST",       masked:"127.0.0.1:11434" }
  }
};

const SEV_RANK = { critical:0, high:1, medium:2, low:3 };
