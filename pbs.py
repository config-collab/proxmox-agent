"""
Proxmox Backup Server (PBS) deep-check module.
SSHes into the PBS node (CT 107, 192.168.0.244) and collects:
  - Datastore list with usage and GC stats
  - Per-guest snapshot history with verification status
  - Recent task log (verify, gc, prune)
  - Disk health
"""
from dataclasses import dataclass, field
from datetime import datetime, timezone
import json
import config
from ssh_client import SSHClient


PBS_HOST     = "192.168.0.244"
PBS_USER     = "root"
PBS_KEY_FILE = "pbs_id_ed25519"


def _pbs_ssh() -> SSHClient:
    return SSHClient(
        host=PBS_HOST,
        user=PBS_USER,
        key_path=config.ssh_key_path(PBS_KEY_FILE),
    )


def _run_json(ssh: SSHClient, cmd: str) -> list | dict | None:
    out, _, rc = ssh.run(cmd, check=False, timeout=60)
    if rc != 0 or not out:
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class PBSSnapshot:
    datastore: str
    backup_type: str   # ct | vm | host
    backup_id: str     # e.g. "101"
    backup_time: int   # unix timestamp
    size_gb: float
    verified: bool | None   # True/False/None=unknown
    verify_time: int | None

    @property
    def age_hours(self) -> float:
        return (datetime.now(timezone.utc).timestamp() - self.backup_time) / 3600

    @property
    def age_str(self) -> str:
        h = self.age_hours
        if h < 48:
            return f"{h:.1f}h ago"
        return f"{h/24:.1f}d ago"

    @property
    def ctime_iso(self) -> str:
        return datetime.fromtimestamp(self.backup_time, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


@dataclass
class PBSDatastore:
    name: str
    path: str
    total_gb: float
    used_gb: float
    avail_gb: float
    pct_used: float
    snapshot_count: int
    last_gc: str        # ISO string or "never"
    last_verify: str
    snapshots: list[PBSSnapshot] = field(default_factory=list)


@dataclass
class PBSReport:
    reachable: bool
    pbs_version: str = ""
    datastores: list[PBSDatastore] = field(default_factory=list)
    recent_tasks: list[dict] = field(default_factory=list)
    disk_usage: str = ""
    error: str = ""


# ── Collection ─────────────────────────────────────────────────────────────────

def _collect_datastores(ssh: SSHClient) -> list[dict]:
    data = _run_json(ssh, "proxmox-backup-manager datastore list --output-format json 2>/dev/null")
    return data if isinstance(data, list) else []


def _collect_snapshots(ssh: SSHClient, datastore: str) -> list[PBSSnapshot]:
    data = _run_json(
        ssh,
        f"proxmox-backup-manager snapshot list {datastore} --output-format json 2>/dev/null",
    )
    if not isinstance(data, list):
        return []

    snaps: list[PBSSnapshot] = []
    for s in data:
        raw_size  = s.get("size") or 0
        size_gb   = round(raw_size / 1024 / 1024 / 1024, 2) if raw_size else 0
        verify    = s.get("verification")
        verified  = None
        vtime     = None
        if isinstance(verify, dict):
            verified = verify.get("state") == "ok"
            vtime    = verify.get("upid_time")

        snaps.append(PBSSnapshot(
            datastore=datastore,
            backup_type=s.get("backup-type", "?"),
            backup_id=str(s.get("backup-id", "?")),
            backup_time=int(s.get("backup-time", 0)),
            size_gb=size_gb,
            verified=verified,
            verify_time=vtime,
        ))

    return sorted(snaps, key=lambda s: s.backup_time, reverse=True)


def _collect_tasks(ssh: SSHClient) -> list[dict]:
    """Last 50 tasks — filters to gc, verify, prune."""
    data = _run_json(
        ssh,
        "proxmox-backup-manager task list --output-format json --limit 100 2>/dev/null",
    )
    if not isinstance(data, list):
        return []
    relevant = [t for t in data if t.get("worker_type", "") in ("gc", "verify", "prune", "backup")]
    return relevant[:50]


def _collect_df(ssh: SSHClient) -> str:
    out, _, _ = ssh.run("df -h --output=source,size,used,avail,pcent,target 2>/dev/null | grep -v tmpfs | grep -v udev", check=False)
    return out


def _last_task_time(tasks: list[dict], task_type: str, store: str) -> str:
    for t in tasks:
        if t.get("worker_type") == task_type and store in t.get("worker_id", ""):
            ts = t.get("starttime")
            if ts:
                return datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return "never"


# ── Public entry point ─────────────────────────────────────────────────────────

def collect() -> PBSReport:
    report = PBSReport(reachable=False)
    try:
        ssh = _pbs_ssh()
        ssh.connect()
        report.reachable = True

        # PBS version
        ver_out, _, _ = ssh.run("proxmox-backup-manager version 2>/dev/null", check=False)
        report.pbs_version = ver_out.split("\n")[0] if ver_out else "unknown"

        # Disk usage
        report.disk_usage = _collect_df(ssh)

        # Tasks (collected once, shared across all datastores)
        tasks = _collect_tasks(ssh)
        report.recent_tasks = tasks

        # Datastores
        raw_stores = _collect_datastores(ssh)
        for rs in raw_stores:
            name   = rs.get("store", rs.get("name", "?"))
            path   = rs.get("path", "?")

            # Get usage from df output if not in API response
            total  = rs.get("total",     0)
            used   = rs.get("used",      0)
            avail  = rs.get("avail",     total - used)
            pct    = round(used / total * 100, 1) if total else 0
            total_gb = round(total / 1024**3, 1)
            used_gb  = round(used  / 1024**3, 1)
            avail_gb = round(avail / 1024**3, 1)

            snaps  = _collect_snapshots(ssh, name)
            ds = PBSDatastore(
                name=name,
                path=path,
                total_gb=total_gb,
                used_gb=used_gb,
                avail_gb=avail_gb,
                pct_used=pct,
                snapshot_count=len(snaps),
                last_gc=_last_task_time(tasks, "gc", name),
                last_verify=_last_task_time(tasks, "verify", name),
                snapshots=snaps,
            )
            report.datastores.append(ds)

        ssh.close()
    except Exception as exc:
        report.error = str(exc)

    return report


# ── Render ─────────────────────────────────────────────────────────────────────

def render(report: PBSReport) -> str:
    lines = ["## PBS deep-check report\n"]

    if not report.reachable:
        lines.append(f"PBS at {PBS_HOST} is unreachable: {report.error}")
        return "\n".join(lines)

    lines.append(f"**PBS version:** {report.pbs_version}  |  **Host:** {PBS_HOST}\n")

    if report.disk_usage:
        lines.append("### Disk usage")
        lines.append(f"```\n{report.disk_usage}\n```\n")

    for ds in report.datastores:
        warn = " ⚠" if ds.pct_used >= config.STORAGE_WARN_PCT else ""
        lines.append(f"### Datastore `{ds.name}` ({ds.path}){warn}")
        lines.append(
            f"**{ds.used_gb} GB used / {ds.total_gb} GB total ({ds.pct_used}%)** — "
            f"{ds.snapshot_count} snapshots  |  "
            f"Last GC: {ds.last_gc}  |  Last verify: {ds.last_verify}\n"
        )

        if not ds.snapshots:
            lines.append("No snapshots found.\n")
            continue

        # Per-guest summary: latest snapshot + verification
        by_guest: dict[str, list[PBSSnapshot]] = {}
        for s in ds.snapshots:
            key = f"{s.backup_type}/{s.backup_id}"
            by_guest.setdefault(key, []).append(s)

        lines.append("| Guest | Type | Snapshots | Latest | Age | Size GB | Verified |")
        lines.append("|---|---|---|---|---|---|---|")
        for key, snaps in sorted(by_guest.items()):
            latest   = snaps[0]
            ver_icon = {True: "yes", False: "**FAILED**", None: "—"}.get(latest.verified, "—")
            lines.append(
                f"| {latest.backup_id} | {latest.backup_type} | {len(snaps)} "
                f"| {latest.ctime_iso} | {latest.age_str} "
                f"| {latest.size_gb} | {ver_icon} |"
            )

        # Flag any unverified snapshots
        unverified = [s for s in ds.snapshots if s.verified is False]
        failed_verify = [s for s in ds.snapshots[:20] if s.verified is None and s.age_hours > 48]
        if unverified:
            lines.append(f"\n> **[HIGH]** {len(unverified)} snapshot(s) failed verification — restore may be unreliable")
        if failed_verify:
            lines.append(f"\n> **[MEDIUM]** {len(failed_verify)} recent snapshot(s) have not been verified (run a verify job)")
        lines.append("")

    # Recent task log
    if report.recent_tasks:
        lines.append("### Recent task log (gc / verify / prune / backup)")
        lines.append("| Time | Type | Store | Status |")
        lines.append("|---|---|---|---|")
        for t in report.recent_tasks[:20]:
            ts      = t.get("starttime", 0)
            tstr    = datetime.fromtimestamp(int(ts), tz=timezone.utc).strftime("%Y-%m-%d %H:%M") if ts else "?"
            ttype   = t.get("worker_type", "?")
            store   = t.get("worker_id", "?")
            status  = t.get("status", "?")
            ok_icon = "ok" if status == "OK" else f"**{status}**"
            lines.append(f"| {tstr} | {ttype} | {store} | {ok_icon} |")

    return "\n".join(lines)
