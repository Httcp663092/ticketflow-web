# ECS 生产运行说明

应用入口为 `https://8.159.144.194/ticketflow/`。前端需以 `--base=/ticketflow/` 构建到发布目录的 `public/ticketflow/`。API 仅绑定宿主机 `127.0.0.1:18080`，数据库不发布宿主机端口。现有 Nginx HTTPS server 通过独立 include 添加路径，原有根路径与 Pulse 路由保留。

## 首次安装

发布目录为 `/opt/ticketflow/releases/<release>`，`first-install.sh` 仅用于全新安装。发现配置、当前版本、项目容器、数据卷或端口占用时拒绝覆盖。脚本会在服务器生成密钥与初始管理员密码，保存于 `/opt/ticketflow/shared/`，权限 0600；禁止提交到仓库。首次安装会对全新数据库执行升级、降级、再升级验证，**禁止将该流程用于有业务数据的升级**。

容器总内存上限 448 MiB（API 256、PostgreSQL 192），单 API worker。密码哈希串行执行以限制小内存主机的瞬时占用。当前设置适合小团队起步，扩大用户量前需压测与扩容。

`activate-proxy.py` 检查原配置与备份逐字一致，再添加独立配置；执行 Nginx 检查、平滑重载和 HTTPS 健康验证，失败恢复原配置。`rollback-first-install.sh` 检查配置后恢复原入口并停止本项目，保留数据卷。

## 镜像与离线构建

默认使用 Amazon ECR 的 Docker Official Images：`public.ecr.aws/docker/library/python:3.12-slim` 与 `public.ecr.aws/docker/library/postgres:16-alpine`。可用 `TICKETFLOW_PYTHON_BASE` / `TICKETFLOW_POSTGRES_IMAGE` 指定经过核实的源；不修改 Docker 全局镜像配置。

PyPI 网络不稳定时，将目标平台 CPython 3.12 Linux x86_64 的 wheel 放入 `deploy/wheels/`，附 `SHA256SUMS`，设置 `TICKETFLOW_API_DOCKERFILE=deploy/Dockerfile.api.offline`。Docker 构建逐一校验文件，并以 `--no-index` 安装；wheel 不入库。跨平台下载不会自动转换所有环境标记，需额外下载 SQLAlchemy 在 Linux 下使用的 `greenlet`，并在真实容器验证。

## 备份与恢复

`backup.sh` 使用独立锁，备份 PostgreSQL 自定义格式 dump、附件和版本路径，写入 `/opt/ticketflow/backups/backup-<UTC>` 并生成校验和。首次上线手动执行并验证可恢复后，安装 `ticketflow-backup.service` 与 timer，每日 UTC 02:15（北京时间10:15，随机延迟最多5分钟）执行。保留策略暂为人工管理，需关注磁盘空间；同机备份不能防止整台服务器故障，后续需配置异地副本。

恢复前先停止本项目写入并制作当前快照；数据库先还原到本项目独立验证数据库核验，不直接覆盖生产库。附件与数据库须取自同一次备份。运行环境密钥需独立安全保管。禁止执行 `docker compose down -v` 或清理其他服务的数据卷。

## 运维检查

使用 `docker compose --env-file /opt/ticketflow/shared/runtime.env -f /opt/ticketflow/current/deploy/compose.prod.yaml ps` 查看状态。健康入口 `/ticketflow/api/health`。日志每容器最多3个10MiB文件。服务器已有 IP 证书续期 timer，由现有服务管理，TicketFlow 不替换证书或续期任务。

当前版本包含账号申请与审批、团队、工单流转、评论与附件、基础看板和权限隔离。SLA、通知、知识库、导出、完整管理审计和找回密码仍需后续实现；上线当前版本不代表 P0+P1 全部完成。
