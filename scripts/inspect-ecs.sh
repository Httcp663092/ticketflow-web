#!/usr/bin/env sh
# Run only on the user-identified ECS host. Read-only; never use sudo automatically.
set -u
printf '\n== Host and resources ==\n'
uname -a
cat /etc/os-release
uptime
free -h
df -h
printf '\n== Listening sockets ==\n'
ss -lntup
printf '\n== Services ==\n'
systemctl list-units --type=service --state=running --no-pager
printf '\n== Containers ==\n'
if command -v docker >/dev/null 2>&1; then
 docker version --format '{{.Server.Version}}'
 docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'
 docker stats --no-stream --format 'table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}'
 docker network ls
 docker volume ls
else
 printf 'Docker unavailable\n'
fi
# Do not inspect container environment variables: they may contain secrets.
