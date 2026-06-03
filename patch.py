"""
Patch agent — OS detection, pending update enumeration, classification, and apply.
Supports: Debian/Ubuntu (apt), Alpine (apk), RHEL/CentOS (yum/dnf), Arch (pacman).
"""
from dataclasses import dataclass, field
from ssh_client import SSHClient


# ── Data types ─────────────────────────────────────────────────────────────────

@dataclass
class PendingUpdate:
    package: str
    current: str
    available: str
    category: str   # "security" | "kernel" | "routine"
    repo: str = ""


@dataclass
class GuestPatchState:
    guest_id: int
    guest_name: str
    ip: str
    os_name: str       # e.g. "Debian GNU/Linux 12"
    os_family: str     # "debian" | "alpine" | "rhel" | "arch" | "unknown"
    reachable: bool
    updates: list[PendingUpdate] = field(default_factory=list)
    error: str = ""

    @property
    def security_count(self) -> int:
        return sum(1 for u in self.updates if u.category == "security")

    @property
    def kernel_count(self) -> int:
        return sum(1 for u in self.updates if u.category == "kernel")

    @property
    def routine_count(self) -> int:
        return sum(1 for u in self.updates if u.category == "routine")


# ── OS detection ───────────────────────────────────────────────────────────────

def detect_os(ssh: SSHClient) -> tuple[str, str]:
    """Return (os_name, os_family). os_family is the key used to pick the right commands."""
    out, _, rc = ssh.run("cat /etc/os-release 2>/dev/null", check=False)
    if rc != 0:
        return "unknown", "unknown"

    fields: dict[str, str] = {}
    for line in out.splitlines():
        k, _, v = line.partition("=")
        fields[k.strip()] = v.strip().strip('"')

    name   = fields.get("PRETTY_NAME", fields.get("NAME", "unknown"))
    id_val = fields.get("ID", "").lower()
    id_like = fields.get("ID_LIKE", "").lower()

    if id_val in ("debian", "ubuntu") or "debian" in id_like or "ubuntu" in id_like:
        return name, "debian"
    if id_val == "alpine":
        return name, "alpine"
    if id_val in ("rhel", "centos", "fedora", "rocky", "almalinux") or "rhel" in id_like:
        return name, "rhel"
    if id_val == "arch" or "arch" in id_like:
        return name, "arch"
    return name, "unknown"


# ── Per-family update checks ───────────────────────────────────────────────────

def _check_debian(ssh: SSHClient) -> list[PendingUpdate]:
    updates: list[PendingUpdate] = []

    # Refresh package index (quiet)
    ssh.run("apt-get update -qq 2>/dev/null", check=False, timeout=120)

    # List upgradable packages
    out, _, rc = ssh.run("apt list --upgradable 2>/dev/null", check=False, timeout=60)
    if rc != 0 or not out:
        return updates

    # Identify packages from security repositories
    security_pkgs: set[str] = set()
    sec_out, _, _ = ssh.run(
        "apt-get --just-print dist-upgrade 2>/dev/null "
        "| grep '^Inst' | grep -i security | awk '{print $2}'",
        check=False, timeout=60,
    )
    for line in sec_out.splitlines():
        security_pkgs.add(line.strip())

    for line in out.splitlines():
        # Format: package/repo version [upgradable from: old_version]
        if not line or line.startswith("Listing"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        pkg_repo = parts[0]                        # e.g. "curl/bookworm-security"
        pkg  = pkg_repo.split("/")[0]
        repo = pkg_repo.partition("/")[2]
        avail = parts[1]
        current = ""
        if "upgradable from:" in line:
            current = line.split("upgradable from:")[-1].strip().rstrip("]")

        if "linux-image" in pkg or "linux-headers" in pkg:
            cat = "kernel"
        elif pkg in security_pkgs or "security" in repo:
            cat = "security"
        else:
            cat = "routine"

        updates.append(PendingUpdate(
            package=pkg, current=current, available=avail,
            category=cat, repo=repo,
        ))

    return updates


def _check_alpine(ssh: SSHClient) -> list[PendingUpdate]:
    updates: list[PendingUpdate] = []
    out, _, rc = ssh.run("apk list --upgrades 2>/dev/null", check=False, timeout=60)
    if rc != 0:
        return updates
    for line in out.splitlines():
        # Format: package-version [repo] {provider} (license) [upgradable from version]
        pkg = line.split()[0] if line else ""
        if not pkg:
            continue
        cat = "kernel" if "linux" in pkg else "routine"
        updates.append(PendingUpdate(package=pkg, current="", available="", category=cat))
    return updates


def _check_rhel(ssh: SSHClient) -> list[PendingUpdate]:
    updates: list[PendingUpdate] = []
    # Try dnf first, fall back to yum
    out, _, rc = ssh.run(
        "dnf check-update --quiet 2>/dev/null || yum check-update --quiet 2>/dev/null",
        check=False, timeout=120,
    )
    # Exit code 100 = updates available (normal for yum/dnf)
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2 or line.startswith(" "):
            continue
        pkg   = parts[0]
        avail = parts[1] if len(parts) > 1 else ""
        cat   = "kernel" if "kernel" in pkg else "routine"
        updates.append(PendingUpdate(package=pkg, current="", available=avail, category=cat))
    return updates


def _check_arch(ssh: SSHClient) -> list[PendingUpdate]:
    updates: list[PendingUpdate] = []
    out, _, rc = ssh.run("pacman -Qu 2>/dev/null", check=False, timeout=120)
    if rc != 0:
        return updates
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        pkg = parts[0]
        cat = "kernel" if "linux" in pkg else "routine"
        updates.append(PendingUpdate(package=pkg, current="", available="", category=cat))
    return updates


_CHECKERS = {
    "debian": _check_debian,
    "alpine": _check_alpine,
    "rhel":   _check_rhel,
    "arch":   _check_arch,
}


# ── Public: check one guest ────────────────────────────────────────────────────

def check_guest(guest_id: int, guest_name: str, ip: str, key_path: str, user: str = "root") -> GuestPatchState:
    state = GuestPatchState(
        guest_id=guest_id, guest_name=guest_name,
        ip=ip, os_name="", os_family="", reachable=False,
    )
    try:
        ssh = SSHClient(host=ip, user=user, key_path=key_path)
        ssh.connect()
        state.reachable = True
        state.os_name, state.os_family = detect_os(ssh)
        checker = _CHECKERS.get(state.os_family)
        if checker:
            state.updates = checker(ssh)
        else:
            state.error = f"unsupported OS family: {state.os_family}"
        ssh.close()
    except Exception as exc:
        state.error = str(exc)
    return state


# ── Apply patches ──────────────────────────────────────────────────────────────

APPLY_COMMANDS = {
    "debian": "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y 2>&1",
    "alpine": "apk upgrade 2>&1",
    "rhel":   "dnf upgrade -y 2>&1 || yum upgrade -y 2>&1",
    "arch":   "pacman -Syu --noconfirm 2>&1",
}

SECURITY_ONLY_COMMANDS = {
    "debian": (
        "DEBIAN_FRONTEND=noninteractive apt-get install "
        "$(apt-get --just-print dist-upgrade 2>/dev/null "
        "| grep '^Inst' | grep -i security | awk '{print $2}' | tr '\\n' ' ') -y 2>&1"
    ),
}


def apply_guest(
    guest_id: int, guest_name: str, ip: str,
    key_path: str, user: str = "root",
    security_only: bool = False,
    dry_run: bool = True,
) -> str:
    """
    Apply pending updates on a guest. Returns a log string.
    dry_run=True (default) — shows what WOULD run without executing.
    """
    try:
        ssh = SSHClient(host=ip, user=user, key_path=key_path)
        ssh.connect()
        _, os_family = detect_os(ssh)

        if security_only and os_family in SECURITY_ONLY_COMMANDS:
            cmd = SECURITY_ONLY_COMMANDS[os_family]
        elif os_family in APPLY_COMMANDS:
            cmd = APPLY_COMMANDS[os_family]
        else:
            ssh.close()
            return f"[{guest_name}] unsupported OS family: {os_family}"

        if dry_run:
            ssh.close()
            return (
                f"[DRY RUN] Would run on {guest_name} ({ip}):\n"
                f"  $ {cmd}\n"
                f"Pass dry_run=false to execute."
            )

        out, err, rc = ssh.run(cmd, check=False, timeout=300)
        ssh.close()
        result = out + ("\n" + err if err else "")
        status = "ok" if rc == 0 else f"exit {rc}"
        return f"[{guest_name}] patch apply — {status}\n{result[-3000:]}"

    except Exception as exc:
        return f"[{guest_name}] error: {exc}"


# ── Render patch report ────────────────────────────────────────────────────────

def render_patch_report(states: list[GuestPatchState]) -> str:
    lines = ["## Patch report\n"]

    total_security = sum(s.security_count for s in states)
    total_kernel   = sum(s.kernel_count   for s in states)
    total_routine  = sum(s.routine_count  for s in states)
    lines.append(
        f"**Summary:** {total_security} security · {total_kernel} kernel · {total_routine} routine"
        f" across {len(states)} guests\n"
    )

    # Priority order: security first, then kernel, then routine, then up-to-date
    def sort_key(s):
        return (-s.security_count, -s.kernel_count, -s.routine_count)

    for s in sorted(states, key=sort_key):
        if not s.reachable:
            lines.append(f"### `{s.guest_id}` {s.guest_name} — unreachable ({s.error})")
            continue
        if s.error and not s.updates:
            lines.append(f"### `{s.guest_id}` {s.guest_name} — error: {s.error}")
            continue

        total = len(s.updates)
        badge = ""
        if s.security_count:
            badge += f" **[SECURITY: {s.security_count}]**"
        if s.kernel_count:
            badge += f" [kernel: {s.kernel_count}]"

        lines.append(f"### `{s.guest_id}` {s.guest_name} ({s.os_name}){badge}")

        if total == 0:
            lines.append("Up to date.\n")
            continue

        lines.append(f"{total} pending update(s):\n")
        lines.append("| Package | Category | Available |")
        lines.append("|---|---|---|")
        for u in sorted(s.updates, key=lambda u: (u.category != "security", u.category != "kernel")):
            lines.append(f"| `{u.package}` | {u.category} | {u.available} |")
        lines.append("")

        if s.security_count:
            lines.append(f"> Apply security updates: `apply_patches(guest_name=\"{s.guest_name}\", security_only=True)`")
        if s.kernel_count:
            lines.append(f"> Kernel update requires a reboot after apply.")
        lines.append("")

    return "\n".join(lines)
