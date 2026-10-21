# TicketFlow ERP 运维提单系统

当前为开发中的基础版本，尚未完成标准版 P0+P1。实施正文已按用户授权重新设计，见 docs/implementation-v1.md；功能将逐条实现和验收。

## 已实现
Vue 3 / TypeScript / Vite / Element Plus 工作台；FastAPI / SQLAlchemy 后端；Argon2 密码、8 小时 JWT、申请人/处理人/管理员权限；工单创建、分页搜索、详情、状态流转、管理员指派、评论与处理记录；Alembic 初始迁移；PostgreSQL Docker Compose 开发配置；CI。

申请人只能读取自己的工单；处理人可读取自己创建及所属处理组的工单；管理员可查看全部并指派。同组处理人才能被指派，管理员不受组限制。管理员可在工作台创建处理组和账号、启停非管理员账号；停用立即阻断已有令牌。当前没有公开注册入口。工单状态和指派操作必须提交最新 version，过期或并发写入返回409。新处理记录保存UTC时间，界面按上海时区显示；旧记录时间未知时保留为空。

## 本地开发
1. 复制 `.env.example` 为 `.env`，设置随机 SECRET_KEY（至少32字符）并同步修改数据库密码与连接串。
2. `docker compose up --build`（仅开发环境）。前端 http://127.0.0.1:15173，API 文档 http://127.0.0.1:18000/docs。数据库无宿主机端口。
3. `docker compose exec backend python -m app.create_user admin --role admin`，按提示输入密码；可用同一命令建立 agent/requester。
4. 访问前端登录并创建工单。

独立后端：Python 3.12，安装 backend/requirements.txt；在 backend 中设置 DATABASE_URL 和 SECRET_KEY，执行 `alembic upgrade head`、`uvicorn app.main:app`。
独立前端：Node 22，在 frontend 中执行 `npm ci`、`npm run dev`。
测试：backend 中 `python -m pytest -q`；frontend 中 `npm run build`。CI 额外在 PostgreSQL 上验证迁移往返。

## 上线限制
禁止将开发 Compose 直接用于生产。尚缺生产 TLS/反向代理、登录限流、密码找回、监控、备份恢复演练及完整验收。JWT 当前存于页面内存，刷新需重新登录。SLA/通知/统计/知识库/导出等仍按实施设计待开发。账号归组当前在创建时指定，既有账号调整组别的管理功能待补齐。
ECS 检查脚本 `scripts/inspect-ecs.sh` 仅查看资源、服务及端口，需用户提供明确主机。不得修改现有容器、Nginx、防火墙或运行中的服务。生产部署需用户再次确认。

实施基线见 docs/implementation-v1.md。开发任务和V1.0里程碑已在GitHub创建。


## 协作功能（开发中）
- 已增加附件、内部备注、退回处理、关闭后重开及管理员取消；退回、重开、取消必须填写原因，状态修改仍需最新版本。
- 附件仅对当前工单有访问权的账号开放，列表/下载均鉴权。所有附件均为工单内公开附件，内部备注不附带私有文件。
- 支持PNG/JPEG/PDF及UTF-8 TXT/CSV，单文件10MiB、单工单最多20个。图片/PDF检查文件头，文本完整校验UTF-8；这不是病毒扫描。下载强制作为附件返回，不在页面执行上传内容。
- 使用 ATTACHMENT_DIR 指定持久存储目录，未设置时为 backend/attachments；Compose已新增独立附件卷。备份/恢复需同时覆盖数据库与附件目录。不可将该目录暴露成无需鉴权的静态文件服务。
- 新事件区分系统记录和评论，避免用户评论伪装成状态变更；历史记录类型为legacy，不推断原始类型。历史缺失时间仍保留未知。
- 当前附件尚无删除/回收、病毒扫描或OSS集成。取消后的工单不可直接重开；已关闭工单可由有权限的申请人或处理人员填写原因重开。
- 本地测试现有11项，覆盖附件越权/类型/大小/路径/失败清理、内部备注隔离、退回/重开/取消和旧数据迁移。PostgreSQL迁移和Docker联调仍需单独验证。
