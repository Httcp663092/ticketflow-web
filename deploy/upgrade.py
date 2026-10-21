"""Root-only guarded release upgrade; never runs downgrade or recreates the DB."""

from pathlib import Path
import fcntl
import os
import shutil
import subprocess
import urllib.request
import json

root = Path("/opt/ticketflow")
release = Path(__file__).resolve().parent.parent
assert os.geteuid() == 0
assert release.parent == root / "releases"
previous = (root / "current").resolve(strict=True)
assert previous != release and previous.parent == root / "releases"
lock = (root / "shared/upgrade.lock").open("w")
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
env_path = root / "shared/runtime.env"
before = env_path.read_text()
values = dict(line.split("=", 1) for line in before.splitlines() if line)
assert values["TICKETFLOW_RELEASE"] == previous.name
assert values.get("TICKETFLOW_API_DOCKERFILE") == "deploy/Dockerfile.api.offline"
assert not (release / "deploy/wheels").exists()
shutil.copytree(previous / "deploy/wheels", release / "deploy/wheels")
env = os.environ.copy()
env.update(values)
env["TICKETFLOW_RELEASE"] = release.name
oldenv = os.environ.copy()
oldenv.update(values)


def dc(path, args, environment=env):
    return subprocess.run(
        [
            "docker",
            "compose",
            "--env-file",
            str(env_path),
            "-f",
            str(path / "deploy/compose.prod.yaml"),
        ]
        + args,
        env=environment,
        check=True,
    )


print("PHASE build isolated new API", flush=True)
dc(release, ["build", "api"])
print("PHASE regression tests (isolated fixtures)", flush=True)
dc(
    release,
    [
        "run",
        "--no-deps",
        "--rm",
        "-T",
        "-e",
        "SESSION_COOKIE_PATH=/api",
        "api",
        "python",
        "-m",
        "pytest",
        "-q",
        "-p",
        "no:cacheprovider",
    ],
)
print("PHASE pre-upgrade backup", flush=True)
subprocess.run(["bash", str(previous / "deploy/backup.sh")], env=oldenv, check=True)
snapshot = root / "shared" / ("runtime.before-" + release.name)
with snapshot.open("x") as f:
    f.write(before)
snapshot.chmod(0o600)
# Forward-only migration; current release adds no schema changes.
dc(release, ["run", "--no-deps", "--rm", "-T", "api", "alembic", "upgrade", "head"])
for path in [release, release / "public", release / "public/ticketflow"]:
    path.chmod(0o755)
for path in (release / "public").rglob("*"):
    path.chmod(0o755 if path.is_dir() else 0o644)
try:
    print("PHASE replace this API only; keep database and other services", flush=True)
    dc(release, ["up", "-d", "--no-deps", "--wait", "--wait-timeout", "120", "api"])
    schema = json.load(
        urllib.request.urlopen("http://127.0.0.1:18080/openapi.json", timeout=10)
    )
    assert (
        "/api/admin/analytics" in schema["paths"]
        and "/api/auth/logout" in schema["paths"]
    )
    assert (release / "public/ticketflow/index.html").is_file()
    temp = root / "current.next"
    assert not temp.exists()
    temp.symlink_to(release)
    os.replace(temp, root / "current")
    new_values = dict(values)
    new_values["TICKETFLOW_RELEASE"] = release.name
    temp_env = root / "shared/runtime.next"
    with temp_env.open("x") as f:
        f.write("".join(k + "=" + v + "\n" for k, v in new_values.items()))
    temp_env.chmod(0o600)
    os.replace(temp_env, env_path)
    assert json.load(
        urllib.request.urlopen(
            "https://8.159.144.194/ticketflow/api/health", timeout=10
        )
    ) == {"status": "ok"}
    assert (
        urllib.request.urlopen("https://8.159.144.194/").read()
        == (root / "shared/existing-root.before").read_bytes()
    )
    (root / "shared/installed-release").write_text(str(release) + "\n")
except BaseException:
    env_path.write_text(before)
    env_path.chmod(0o600)
    if (root / "current").resolve() == release:
        temp = root / "current.rollback"
        temp.symlink_to(previous)
        os.replace(temp, root / "current")
    dc(
        previous,
        ["up", "-d", "--no-deps", "--wait", "--wait-timeout", "120", "api"],
        oldenv,
    )
    raise
print("UPGRADE_HEALTHY " + release.name, flush=True)
