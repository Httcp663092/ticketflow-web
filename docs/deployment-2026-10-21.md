# 2026-10-21 首次生产上线记录

用户已明确批准本次正式部署。当前发布 `r20261021T022230Z`，入口为 https://8.159.144.194/ticketflow/ 。这是当前已实现功能的上线，P0+P1 尚未全部完成。

## 隔离与访问

目标 ECS 为上海实例 ele，Ubuntu 24.04，2 核 2 GiB。应用使用独立 Compose 项目 ticketflow-prod，独立数据库和附件卷；API 仅监听 127.0.0.1:18080，数据库无宿主端口。复用原 HTTPS 证书，给现有 server 添加独立 /ticketflow/ include，原根路径与 /v1/stream 保留。原 private-memos 容器未重启或修改。

首次管理员 admin 由服务器生成随机密码，凭据文件另行私密交付，不入库。注册账号必须由管理员审核，首次管理员应登录后修改密码。未导入演示账号或演示数据库。保留一张已关闭的“上线验证工单（自动验收）”，含验收评论与一个文本附件。

## 验证证据

- 前端类型检查和 /ticketflow/ base 构建通过。
- 服务器容器执行 18 项回归测试全部通过，137.69 秒；测试 fixture 使用隔离内存 SQLite，不写生产表。
- 真实 PostgreSQL 全新数据库执行 Alembic upgrade → downgrade base → upgrade 成功；随后创建管理员。此回退验证仅在空数据库执行。
- 外网 HTTPS 验证证书、HTML、两个静态资源和健康接口通过。
- 外网管理员登录、资料查询、真实 PostgreSQL 创建工单、内部评论、附件上传下载字节比对、处理中→已解决→已关闭及事件记录通过，验收工单 ID=1。
- Nginx 配置检查和平滑重载通过；原根路径响应逐字匹配部署前备份。
- 数据库与附件备份 SHA256 校验通过；dump 还原到新建验证库成功，两库用户数=1、工单数=1，验证库随后移除，生产数据保留。
- 启用独立每日备份 timer，UTC 02:15（北京时间10:15，最多延后5分钟）；首次验证备份 `/opt/ticketflow/backups/backup-20261021T023950Z`。

## 网络问题与处理

服务器访问 Docker Hub 超时，改用 Amazon ECR 中 Docker Official Images，不修改全局 Docker 配置。服务器 PyPI 解析不稳定，使用本机从 PyPI 下载的 CPython 3.12 Linux x86_64 wheel，经 SHA256 校验后离线安装；Linux 专用 greenlet 另从 PyPI 下载并校验。

原始发布包 SHA256 为 `bf31b7c134f716244ad33a6e9d1e7cb94340aab56951286de6819f8cb865021a`。服务器随后应用可信镜像源与离线构建配置补丁；对应代码和运维脚本提交 `6cbd2093282e917f44a7efc9c5159b745ff41ddb`。运行环境增加 TICKETFLOW_API_DOCKERFILE=deploy/Dockerfile.api.offline。README 与独立 smoke.py 是仓库中的后续运维资料，生产验收通过等价外网请求执行。

## 后续工作

SLA、通知、知识库、导出、完整管理审计、找回密码仍待开发。备份目前存于同机，尚未配置异地备份与自动保留策略。小内存服务器需在扩大使用前进行容量评估和并发压测。现有 IP 证书由原 pulse-cert-renew.timer 管理，检查时上次运行成功，未改动续期配置。

升级时先备份，只执行正向迁移；禁止再次执行首次安装的空库回退步骤。运维与回滚入口见 deploy/README.md。

上线后资源抽查：API 60.62 MiB / 256 MiB，PostgreSQL 64.09 MiB / 192 MiB，整机 available 647 MiB；private-memos 持续运行7小时。定时备份首次计划为 2026-10-22 10:17:40 CST。Compose 最终配置另行校验通过。
