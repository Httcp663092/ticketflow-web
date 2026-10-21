"""First deployment only: guarded additive route plus tested reload, with rollback."""

from pathlib import Path
import hashlib
import subprocess

root = Path("/opt/ticketflow")
source = Path("/etc/nginx/sites-enabled/pulse-public").resolve()
before = (root / "shared/nginx-pulse-public.before").read_bytes()
if source.read_bytes() != before:
    raise SystemExit(
        "Existing Nginx config changed since snapshot; refusing modification"
    )
text = before.decode()
if text.count("server {") != 1 or "listen 443 ssl" not in text or "ticketflow" in text:
    raise SystemExit("Unexpected Nginx layout; review required")
snippet = Path("/etc/nginx/snippets/ticketflow.conf")
if snippet.exists():
    raise SystemExit("TicketFlow Nginx snippet already exists")
if not (root / "current/public/ticketflow/index.html").is_file():
    raise SystemExit("Static release unavailable")
subprocess.run(
    ["curl", "--fail", "--silent", "http://127.0.0.1:18080/api/health"], check=True
)
snippet.write_bytes((root / "current/deploy/nginx-ticketflow.conf").read_bytes())
snippet.chmod(0o644)
try:
    source.write_text(
        text.replace(
            "server {", "server {\n    include /etc/nginx/snippets/ticketflow.conf;", 1
        )
    )
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    subprocess.run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "https://8.159.144.194/ticketflow/api/health",
        ],
        check=True,
    )
    subprocess.run(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "https://8.159.144.194/",
            "-o",
            str(root / "shared/existing-root.after"),
        ],
        check=True,
    )
except BaseException:
    source.write_bytes(before)
    snippet.unlink(missing_ok=True)
    subprocess.run(["nginx", "-t"], check=True)
    subprocess.run(["systemctl", "reload", "nginx"], check=True)
    raise
print("HTTPS_ROUTE_ACTIVE: original root kept, /ticketflow/ added")
