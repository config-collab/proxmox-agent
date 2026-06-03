"""
Backup agent — reads scheduled jobs, enumerates backup archives per guest,
detects gaps, and reports storage fill rate.

Data sources:
  PVE API  /cluster/backup          — scheduled vzdump jobs
  PVE API  /nodes/{n}/storage       — storage pools
  PVE API  /nodes/{n}/storage/{s}/content?content=backup  — archive list
  SSH      vzdump.conf              — fallback if API job list is sparse
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import config
from proxmox_api import ProxmoxAPI


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class BackupArchive:
    vmid: int
    volid: str
    storage: str
    ctime: int          # unix timestamp
    size_gb: float
    format: str         # pbs-vm, pbs-ct, vma, tar, etc.
    verified: bool | None = None   # None = unknown

    @property
    def age_hours(self) -> float:
        now = datetime.now(timezone.utc).timestamp()
        return (now - self.ctime) / 3600

    @property
    def age_str(self) -> str:
        h = self.age_hours
        if h < 1:
            return f"{int(h*60)}m ago"
        if h < 48:
            return f"{h:.1f}h ago"
        return f"{h/24:.1f}d ago"

    @property
    def ctime_iso(self) -> str:
        return datetime.fromtimestamp(self.ctime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


@dataclass
class GuestBackupState:
    vmid: int
    name: str
    guest_type: str     # "vm" | "lxc"
    has_job: bool       # covered by a scheduled backup job
    archives: list[BackupArchive] = field(default_factory=list)

    @property
    def latest(self) -> BackupArchive | None:
        return max(self.archives, key=lambda a: a.ctime) if self.archives else None

    @property
    def latest_age_hours(self) -> float | None:
        return self.latest.age_hours if self.latest else None

    @property
    def status(self) -> str:
        if not self.archives:
            return "NO BACKUP"
        age = self.latest_age_hours
        if age > config.BACKUP_MAX_AGE_H * 3:
            return "STALE"
        if age > config.BACKUP_MAX_AGE_H:
            return "OVERDUE"
        return "ok"


@dataclass
class StorageFill:
    name: str
    total_gb: float
    used_gb: float
    avail_gb: float
    pct_used: float
    backup_count: int


@dataclass
class BackupReport:
    guests: list[GuestBackupState] = field(default_factory=list)
    storage_fill: list[StorageFill] = field(default_factory=list)
    scheduled_jobs: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


# ── Collection ─────────────────────────────────────────────────────────────────

def _bytes_to_gb(b: int) -> float:
    return round(b / 1024 / 1024 / 1024, 2)


def _collect_scheduled_jobs(api: ProxmoxAPI) -> tuple[list[dict], set[int]]:
    """Return (job_list, set_of_covered_vmids)."""
    try:
        jobs = api.get("/cluster/backup") or []
    except Exception:
        jobs = []

    covered: set[int] = set()
    for job in jobs:
        vmids_str = job.get("vmid", "")
        if not vmids_str or vmids_str == "all":
            # Treat 'all' as covering everything — we'll handle it at render time
            return jobs, set()    # empty set = all covered
        for part in str(vmids_str).split(","):
            part = part.strip()
            if part.isdigit():
                covered.add(int(part))
    return jobs, covered


def _collect_backup_archives(api: ProxmoxAPI, node: str) -> dict[int, list[BackupArchive]]:
    """Return {vmid: [BackupArchive, ...]} for all backup-capable storages."""
    by_vmid: dict[int, list[BackupArchive]] = {}

    try:
        storages = api.storage(node) or []
    except Exception:
        return by_vmid

    for s in storages:
        sname  = s.get("storage", "")
        stypes = s.get("content", "")
        # Only query storages that hold backups and are active
        if "backup" not in stypes or s.get("status") != "available":
            continue

        try:
            contents = api.get(f"/nodes/{node}/storage/{sname}/content?content=backup") or []
        except Exception:
            continue

        for item in contents:
            vmid = item.get("vmid")
            if not vmid:
                continue
            vmid = int(vmid)
            arc = BackupArchive(
                vmid=vmid,
                volid=item.get("volid", ""),
                storage=sname,
                ctime=int(item.get("ctime", 0)),
                size_gb=_bytes_to_gb(item.get("size", 0)),
                format=item.get("format", ""),
                verified=item.get("verification", {}).get("state") == "ok"
                         if item.get("verification") else None,
            )
            by_vmid.setdefault(vmid, []).append(arc)

    return by_vmid


def _collect_storage_fill(api: ProxmoxAPI, node: str, by_vmid: dict) -> list[StorageFill]:
    fills = []
    try:
        storages = api.storage(node) or []
    except Exception:
        return fills

    # Count archives per storage
    arc_per_storage: dict[str, int] = {}
    for arcs in by_vmid.values():
        for a in arcs:
            arc_per_storage[a.storage] = arc_per_storage.get(a.storage, 0) + 1

    for s in storages:
        if "backup" not in s.get("content", ""):
            continue
        total = s.get("total", 0)
        avail = s.get("avail", 0)
        used  = total - avail
        pct   = round(used / total * 100, 1) if total else 0
        fills.append(StorageFill(
            name=s.get("storage", "?"),
            total_gb=_bytes_to_gb(total),
            used_gb=_bytes_to_gb(used),
            avail_gb=_bytes_to_gb(avail),
            pct_used=pct,
            backup_count=arc_per_storage.get(s.get("storage", ""), 0),
        ))
    return fills


def collect(api: ProxmoxAPI, node: str = "pve") -> BackupReport:
    report = BackupReport()

    # 1. Scheduled jobs
    jobs, covered_vmids = _collect_scheduled_jobs(api)
    report.scheduled_jobs = jobs
    all_covered = len(covered_vmids) == 0 and len(jobs) > 0  # job with vmid=all

    # 2. Backup archives
    by_vmid = _collect_backup_archives(api, node)
    report.storage_fill = _collect_storage_fill(api, node, by_vmid)

    # 3. Guest list from inventory
    try:
        vms = api.vms(node) or []
        cts = api.containers(node) or []
    except Exception as exc:
        report.warnings.append(f"Could not list guests: {exc}")
        return report

    for g in vms + cts:
        vmid      = int(g["vmid"])
        gtype     = "vm" if g in vms else "lxc"
        has_job   = all_covered or vmid in covered_vmids
        archives  = sorted(by_vmid.get(vmid, []), key=lambda a: a.ctime, reverse=True)
        report.guests.append(GuestBackupState(
            vmid=vmid,
            name=g.get("name", f"{gtype}-{vmid}"),
            guest_type=gtype,
            has_job=has_job,
            archives=archives,
        ))

    # 4. Storage warnings
    for sf in report.storage_fill:
        if sf.pct_used >= config.STORAGE_WARN_PCT:
            report.warnings.append(
                f"Backup storage '{sf.name}' is {sf.pct_used}% full "
                f"({sf.avail_gb} GB free)"
            )

    return report


# ── Render ─────────────────────────────────────────────────────────────────────

def render(report: BackupReport) -> str:
    lines = ["## Backup status report\n"]

    # ── Summary counts ─────────────────────────────────────────────────────────
    no_backup = [g for g in report.guests if not g.archives]
    overdue   = [g for g in report.guests if g.status in ("OVERDUE", "STALE")]
    no_job    = [g for g in report.guests if not g.has_job and g.archives]
    ok        = [g for g in report.guests if g.status == "ok"]

    lines.append(
        f"**{len(ok)} ok** · "
        f"**{len(overdue)} overdue** · "
        f"**{len(no_backup)} never backed up** · "
        f"**{len(no_job)} unscheduled**\n"
    )

    # ── Per-guest table ────────────────────────────────────────────────────────
    lines.append("| ID | Name | Type | Last backup | Age | Size GB | Scheduled | Status |")
    lines.append("|---|---|---|---|---|---|---|---|")

    def sort_key(g):
        order = {"NO BACKUP": 0, "STALE": 1, "OVERDUE": 2, "ok": 3}
        return (order.get(g.status, 9), g.vmid)

    for g in sorted(report.guests, key=sort_key):
        lat   = g.latest
        when  = lat.ctime_iso if lat else "—"
        age   = lat.age_str   if lat else "—"
        size  = f"{lat.size_gb}" if lat else "—"
        sched = "yes" if g.has_job else "no"
        badge = {
            "NO BACKUP": "**[NO BACKUP]**",
            "STALE":     "**[STALE]**",
            "OVERDUE":   "**[OVERDUE]**",
            "ok":        "ok",
        }.get(g.status, g.status)
        lines.append(f"| {g.vmid} | {g.name} | {g.guest_type} | {when} | {age} | {size} | {sched} | {badge} |")

    # ── Storage fill ───────────────────────────────────────────────────────────
    if report.storage_fill:
        lines.append("\n### Backup storage")
        lines.append("| Storage | Used GB | Total GB | % Used | Archives |")
        lines.append("|---|---|---|---|---|")
        for sf in report.storage_fill:
            warn = " ⚠" if sf.pct_used >= config.STORAGE_WARN_PCT else ""
            lines.append(
                f"| {sf.name} | {sf.used_gb} | {sf.total_gb} "
                f"| {sf.pct_used}%{warn} | {sf.backup_count} |"
            )

    # ── Scheduled jobs ─────────────────────────────────────────────────────────
    if report.scheduled_jobs:
        lines.append("\n### Scheduled backup jobs")
        lines.append("| ID | Schedule | Storage | VMs | Retention (daily/weekly/monthly) |")
        lines.append("|---|---|---|---|---|")
        for j in report.scheduled_jobs:
            vmids    = j.get("vmid", "all")
            storage  = j.get("storage", "?")
            schedule = j.get("schedule", j.get("starttime", "?"))
            daily    = j.get("prune-backups", {}).get("keep-daily",   "?")
            weekly   = j.get("prune-backups", {}).get("keep-weekly",  "?")
            monthly  = j.get("prune-backups", {}).get("keep-monthly", "?")
            lines.append(f"| {j.get('id', '?')} | {schedule} | {storage} | {vmids} | {daily}/{weekly}/{monthly} |")

    # ── Action items ───────────────────────────────────────────────────────────
    action_items = []
    for g in no_backup:
        action_items.append(f"[CRITICAL] {g.name} (vmid {g.vmid}) has never been backed up — add to a backup job immediately")
    for g in overdue:
        action_items.append(f"[HIGH] {g.name} last backup {g.latest.age_str if g.latest else '?'} — exceeds {config.BACKUP_MAX_AGE_H}h threshold")
    for g in no_job:
        action_items.append(f"[MEDIUM] {g.name} has backups but no scheduled job — manual only, risk of being forgotten")
    for w in report.warnings:
        action_items.append(f"[HIGH] {w}")

    if action_items:
        lines.append("\n### Action items")
        for item in action_items:
            lines.append(f"- {item}")

    return "\n".join(lines)
