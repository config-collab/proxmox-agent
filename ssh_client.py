"""
Thin SSH wrapper around paramiko — key-based auth.
"""
import sys
import paramiko
import config


class SSHClient:
    def __init__(self, host=None, port=None, user=None, key_path=None):
        self.host     = host     or config.SSH_HOST
        self.port     = port     or config.SSH_PORT
        self.user     = user     or config.SSH_USER
        self.key_path = key_path or config.pve_key_path()
        self._ssh     = None

    def connect(self):
        pkey = paramiko.Ed25519Key.from_private_key_file(self.key_path)
        client = paramiko.SSHClient()
        client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        client.connect(
            self.host,
            port=self.port,
            username=self.user,
            pkey=pkey,
            timeout=15,
        )
        self._ssh = client
        return self

    def run(self, cmd, check=True, timeout=60):
        """Run a command, return (stdout, stderr, exit_code)."""
        _, stdout, stderr = self._ssh.exec_command(cmd, get_pty=False, timeout=timeout)
        rc  = stdout.channel.recv_exit_status()
        out = stdout.read().decode(errors="replace").strip()
        err = stderr.read().decode(errors="replace").strip()
        if check and rc != 0:
            print(f"[ssh error] cmd={cmd!r} rc={rc} stderr={err!r}", file=sys.stderr)
        return out, err, rc

    def close(self):
        if self._ssh:
            self._ssh.close()
            self._ssh = None

    def __enter__(self):
        return self.connect()

    def __exit__(self, *_):
        self.close()


def guest_ssh(name: str) -> "SSHClient":
    """Return a ready-to-connect SSHClient for a named guest."""
    conns = config.guest_connections()
    if name not in conns:
        raise KeyError(f"No connection info for guest {name!r} — check .env GUEST_IP_/GUEST_KEY_ vars")
    g = conns[name]
    return SSHClient(host=g["ip"], user=g["user"], key_path=g["key_path"])
