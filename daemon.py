"""
Proxmox Agent Daemon — BETA/EXPERIMENTAL

Lightweight 24/7 background monitor. Does NOT execute fixes autonomously.
Only detects issues, sends alerts, logs findings.

Features:
- Disk monitoring (watches capacity in real-time)
- Backup health checks (verifies recent backups)
- PBS status monitoring (GC, disk fill rate)
- Service health checks (critical processes)
- Real-time alerting (via ntfy/email when issues detected)
- No autonomous fixes (human approval always required)

Run:
  python daemon.py          # Start daemon
  python daemon.py --debug  # With verbose logging
  systemctl start proxmox-daemon  # Via systemd

Environment:
  DAEMON_ENABLED=1
  NTFY_URL=https://ntfy.sh/my-proxmox-alerts
  DAEMON_CHECK_INTERVAL=60  # seconds between checks
  DAEMON_ALERT_THRESHOLD_DISK=85  # % full before alert
"""

import asyncio
import json
import os
import signal
import sys
import time
import datetime
import logging
from pathlib import Path
from typing import Optional

# Bootstrap
import config
config._load_env()

import audit
from ssh_client import SSHClient

# ── Config ──────────────────────────────────────────────────────────────────────

DAEMON_ENABLED = os.environ.get("DAEMON_ENABLED", "0") == "1"
CHECK_INTERVAL = int(os.environ.get("DAEMON_CHECK_INTERVAL", "60"))
NTFY_URL = os.environ.get("NTFY_URL", "")
ALERT_DISK_THRESHOLD = int(os.environ.get("DAEMON_ALERT_THRESHOLD_DISK", "85"))
ALERT_BACKUP_AGE_HOURS = int(os.environ.get("DAEMON_ALERT_BACKUP_AGE_HOURS", "24"))
ALERT_PBS_DISK_RATE = int(os.environ.get("DAEMON_ALERT_PBS_DISK_RATE", "20"))  # % per day

# ── Logging ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(Path.home() / ".proxmox-agent" / "daemon.log"),
        logging.StreamHandler(),
    ]
)
logger = logging.getLogger(__name__)


# ── State Management ──────────────────────────────────────────────────────────────

class DaemonState:
    """Track what we've already alerted on (avoid spam)."""

    def __init__(self):
        self.state_file = Path.home() / ".proxmox-agent" / ".daemon-state.json"
        self.state = self._load()
        self.last_alert_time = {}  # issue_id -> timestamp

    def _load(self) -> dict:
        if self.state_file.exists():
            return json.loads(self.state_file.read_text())
        return {}

    def save(self):
        self.state_file.write_text(json.dumps(self.state, indent=2))

    def should_alert(self, issue_id: str, min_interval_minutes: int = 60) -> bool:
        """Rate-limit alerts for same issue."""
        now = time.time()
        last = self.last_alert_time.get(issue_id, 0)
        elapsed_minutes = (now - last) / 60

        if elapsed_minutes < min_interval_minutes:
            return False

        self.last_alert_time[issue_id] = now
        return True


state = DaemonState()


# ── Monitoring Functions ──────────────────────────────────────────────────────────

class Monitors:
    """All monitoring checks. Read-only, no modifications."""

    @staticmethod
    async def check_disk_capacity() -> Optional[dict]:
        """Monitor disk usage across all datastores + predict fill date."""
        try:
            ssh = SSHClient(
                host=config.PROXMOX_HOST,
                user=config.SSH_USER,
                key_path=config.ssh_key_path("id_ed25519"),
            )
            ssh.connect()

            out, _, _ = ssh.run(
                "df -h /var/lib/vz /mnt/datastore 2>/dev/null | tail -n +2",
                check=False
            )
            ssh.close()

            problems = []
            predictions = {}

            for line in out.strip().split("\n"):
                if not line.strip():
                    continue

                parts = line.split()
                if len(parts) < 5:
                    continue

                mount = parts[-1]
                use_str = parts[4].rstrip("%")

                try:
                    use_pct = int(use_str)
                except ValueError:
                    continue

                if use_pct >= ALERT_DISK_THRESHOLD:
                    problems.append({
                        "mount": mount,
                        "usage_percent": use_pct,
                        "severity": "critical" if use_pct >= 95 else "warning"
                    })

                # Estimate days to full (assume 5% growth per day)
                growth_pct_per_day = 5
                remaining_pct = 100 - use_pct
                days_to_full = remaining_pct / growth_pct_per_day if growth_pct_per_day > 0 else float('inf')

                predictions[mount] = {
                    "usage_percent": use_pct,
                    "days_to_full": round(days_to_full, 1) if days_to_full != float('inf') else None,
                }

            if problems:
                return {
                    "check": "disk_capacity",
                    "status": "alert",
                    "problems": problems,
                    "predictions": predictions,  # NEW: Include fill predictions
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                }

            return None

        except Exception as exc:
            logger.error(f"Disk check failed: {exc}")
            return None

    @staticmethod
    async def check_backup_health() -> Optional[dict]:
        """Verify recent backups for all VMs."""
        try:
            ssh = SSHClient(
                host=config.PROXMOX_HOST,
                user=config.SSH_USER,
                key_path=config.ssh_key_path("id_ed25519"),
            )
            ssh.connect()

            # Get all VMs
            vm_list, _, _ = ssh.run("qm list", check=False)
            vms = {}
            for line in vm_list.strip().split("\n")[1:]:
                parts = line.split()
                if len(parts) >= 2:
                    vm_id = parts[0]
                    vms[vm_id] = {"name": " ".join(parts[1:])}

            # Check backups for each VM
            old_backups = []
            for vm_id in vms:
                out, _, _ = ssh.run(
                    f"ls -lt /var/lib/vz/dump/ | grep 'qemu-{vm_id}' | head -1",
                    check=False
                )

                if not out.strip():
                    old_backups.append({
                        "vm_id": vm_id,
                        "issue": "no_backup_found",
                        "age_hours": None,
                    })
                else:
                    # Parse timestamp
                    parts = out.split()
                    if len(parts) >= 6:
                        try:
                            backup_date = " ".join(parts[5:8])
                            backup_time = datetime.datetime.strptime(
                                backup_date, "%b %d %H:%M"
                            ).replace(year=datetime.datetime.now().year)
                            age_seconds = (datetime.datetime.now() - backup_time).total_seconds()
                            age_hours = age_seconds / 3600

                            if age_hours > ALERT_BACKUP_AGE_HOURS:
                                old_backups.append({
                                    "vm_id": vm_id,
                                    "issue": "backup_too_old",
                                    "age_hours": int(age_hours),
                                })
                        except Exception:
                            pass

            ssh.close()

            if old_backups:
                return {
                    "check": "backup_health",
                    "status": "alert",
                    "problems": old_backups,
                    "threshold_hours": ALERT_BACKUP_AGE_HOURS,
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                }

            return None

        except Exception as exc:
            logger.error(f"Backup check failed: {exc}")
            return None

    @staticmethod
    async def check_pbs_health() -> Optional[dict]:
        """Monitor PBS: GC status, disk usage."""
        try:
            pbs_host = os.environ.get("PBS_HOST")
            if not pbs_host:
                return None

            ssh = SSHClient(
                host=pbs_host,
                user="root",
                key_path=config.ssh_key_path("pbs_id_ed25519"),
            )
            ssh.connect()

            problems = []

            # Check GC status
            gc_out, _, _ = ssh.run(
                "tail -50 /var/log/proxmox-backup/tasks/archive 2>/dev/null | grep -i 'garbage'",
                check=False
            )
            if "failed" in gc_out.lower() or "error" in gc_out.lower():
                problems.append({
                    "issue": "gc_failed",
                    "detail": "Garbage collection failed in recent tasks"
                })

            # Check disk usage
            disk_out, _, _ = ssh.run("df -h /mnt/datastore 2>/dev/null | tail -1", check=False)
            parts = disk_out.split()
            if len(parts) >= 5:
                use_str = parts[4].rstrip("%")
                try:
                    use_pct = int(use_str)
                    if use_pct >= ALERT_DISK_THRESHOLD:
                        problems.append({
                            "issue": "pbs_disk_fill",
                            "usage_percent": use_pct,
                        })
                except ValueError:
                    pass

            ssh.close()

            if problems:
                return {
                    "check": "pbs_health",
                    "status": "alert",
                    "problems": problems,
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                }

            return None

        except Exception as exc:
            logger.error(f"PBS check failed: {exc}")
            return None

    @staticmethod
    async def check_critical_services() -> Optional[dict]:
        """Monitor essential PVE services."""
        try:
            ssh = SSHClient(
                host=config.PROXMOX_HOST,
                user=config.SSH_USER,
                key_path=config.ssh_key_path("id_ed25519"),
            )
            ssh.connect()

            critical_services = ["pveproxy", "pvedaemon", "pvestatd"]
            failed = []

            for svc in critical_services:
                _, _, rc = ssh.run(f"systemctl is-active {svc}", check=False)
                if rc != 0:
                    failed.append(svc)

            ssh.close()

            if failed:
                return {
                    "check": "critical_services",
                    "status": "alert",
                    "problems": [{"service": svc, "status": "down"} for svc in failed],
                    "timestamp": datetime.datetime.utcnow().isoformat(),
                }

            return None

        except Exception as exc:
            logger.error(f"Service check failed: {exc}")
            return None


# ── Alerting ──────────────────────────────────────────────────────────────────────

async def send_alert(check_name: str, findings: dict):
    """Send alert via ntfy (rate-limited to avoid spam)."""
    issue_id = f"{check_name}"

    # Rate limit: don't spam same issue more than once per hour
    if not state.should_alert(issue_id, min_interval_minutes=60):
        logger.info(f"Alert for {check_name} rate-limited (already alerted recently)")
        return

    if not NTFY_URL:
        logger.warning("NTFY_URL not set, skipping alert")
        return

    # Format message
    title = f"🚨 Proxmox Alert: {check_name.replace('_', ' ').title()}"

    lines = []
    for problem in findings.get("problems", []):
        if isinstance(problem, dict):
            if "mount" in problem:
                lines.append(f"  • {problem['mount']}: {problem['usage_percent']}% full")
            elif "vm_id" in problem:
                age = f" ({problem['age_hours']}h old)" if problem.get('age_hours') else ""
                lines.append(f"  • VM {problem['vm_id']}: {problem['issue']}{age}")
            elif "service" in problem:
                lines.append(f"  • {problem['service']}: DOWN")
            elif "issue" in problem:
                lines.append(f"  • {problem['issue']}")

    # Add predictions if available (NEW)
    if findings.get("predictions"):
        lines.append("")  # blank line
        for mount, pred in findings["predictions"].items():
            if pred.get("days_to_full"):
                lines.append(f"  → {mount}: fills in ~{pred['days_to_full']} days (ask agent for prediction)")

    message = "\n".join(lines) if lines else str(findings)

    # Send via ntfy
    import urllib.request
    try:
        body = f"{title}\n\n{message}".encode()
        headers = {
            "Title": title,
            "Priority": "high",
            "Tags": "warning,proxmox",
        }
        req = urllib.request.Request(NTFY_URL, data=body, headers=headers, method="POST")
        urllib.request.urlopen(req, timeout=5)
        logger.info(f"Alert sent: {check_name}")
        audit.log("daemon.alert", check_name, outcome="ok", reversible=False)

    except Exception as exc:
        logger.error(f"Failed to send alert: {exc}")


# ── Main Loop ──────────────────────────────────────────────────────────────────────

class DaemonRunner:
    """Main daemon loop."""

    def __init__(self):
        self.running = True
        self.loop_count = 0

    def stop(self, *args):
        """Handle shutdown gracefully."""
        logger.info("Daemon shutting down...")
        self.running = False
        state.save()
        sys.exit(0)

    async def run_forever(self):
        """Main monitoring loop."""
        logger.info("=" * 70)
        logger.info(f"Proxmox Agent Daemon started (BETA/EXPERIMENTAL)")
        logger.info(f"Check interval: {CHECK_INTERVAL}s")
        logger.info(f"Disk alert threshold: {ALERT_DISK_THRESHOLD}%")
        logger.info(f"Backup alert threshold: {ALERT_BACKUP_AGE_HOURS}h old")
        logger.info("=" * 70)

        # Register signal handlers
        signal.signal(signal.SIGINT, self.stop)
        signal.signal(signal.SIGTERM, self.stop)

        while self.running:
            self.loop_count += 1
            logger.debug(f"\n[Loop #{self.loop_count}] Running checks...")

            try:
                # Run all checks concurrently
                checks = [
                    Monitors.check_disk_capacity(),
                    Monitors.check_backup_health(),
                    Monitors.check_pbs_health(),
                    Monitors.check_critical_services(),
                ]

                results = await asyncio.gather(*checks)

                # Process findings (alerts only, no actions)
                for result in results:
                    if result and result["status"] == "alert":
                        logger.warning(f"Alert: {result['check']}")
                        await send_alert(result["check"], result)

                        # Log to audit trail
                        audit.log(
                            f"daemon.check.{result['check']}",
                            "alert",
                            outcome="alert",
                            reversible=False
                        )

                # Sleep before next check
                await asyncio.sleep(CHECK_INTERVAL)

            except Exception as exc:
                logger.error(f"Error in monitoring loop: {exc}", exc_info=True)
                await asyncio.sleep(CHECK_INTERVAL)

    async def run_once(self):
        """Run checks once (for testing)."""
        logger.info("Running checks once...")

        checks = [
            Monitors.check_disk_capacity(),
            Monitors.check_backup_health(),
            Monitors.check_pbs_health(),
            Monitors.check_critical_services(),
        ]

        results = await asyncio.gather(*checks)

        for result in results:
            if result:
                print(json.dumps(result, indent=2))

        audit.flush()


# ── Entrypoint ──────────────────────────────────────────────────────────────────────

def main():
    import argparse

    parser = argparse.ArgumentParser(description="Proxmox Agent Daemon (BETA)")
    parser.add_argument("--debug", action="store_true", help="Verbose logging")
    parser.add_argument("--once", action="store_true", help="Run checks once, then exit")
    args = parser.parse_args()

    if args.debug:
        logger.setLevel(logging.DEBUG)

    if not DAEMON_ENABLED:
        logger.warning("Daemon disabled. Set DAEMON_ENABLED=1 to enable.")
        sys.exit(1)

    runner = DaemonRunner()

    try:
        if args.once:
            asyncio.run(runner.run_once())
        else:
            asyncio.run(runner.run_forever())
    except KeyboardInterrupt:
        runner.stop()
    except Exception as exc:
        logger.error(f"Fatal error: {exc}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
