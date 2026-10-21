# TicketFlow ERP 运维提单系统

当前为本地开发基础版本，尚未宣称完成标准版 P0+P1。原会话读取仅返回方案引用占位符，实施设计正文待补充；功能需逐条对照后验收。

## 已实现
Vue 3 / TypeScript / Vite / Element Plus 工作台；FastAPI / SQLAlchemy 后端；Argon2 密码、8 小时 JWT、申请人/处理人/管理员权限；工单创建、分页搜索、详情、状态流转、管理员指派、评论与处理记录；Alembic 初始迁移；PostgreSQL Docker Compose 开发配置；CI。

申请人只能读取自己工单；处理人可查看全部并推进状态；管理员可指派。此权限模型为基础实现，待与批准方案核对。当前没有公开注册入口。

## 本地开发
1. 复制 `.env.example` 为 `.env`，设置随机 SECRET_KEY（至少32字符）并同步修改数据库密码与连接串。
2. `docker compose up --build`（仅开发环境）。前端 http://127.0.0.1:15173，API 文档 http://127.0.0.1:18000/docs。数据库无宿主机端口。
3. `docker compose exec backend python -m app.create_user admin --role admin`，按提示输入密码；可用同一命令建立 agent/requester。
4. 访问前端登录并创建工单。

独立后端：Python 3.12，安装 backend/requirements.txt；在 backend 中设置 DATABASE_URL 和 SECRET_KEY，执行 `alembic upgrade head`、`uvicorn app.main:app`。
独立前端：Node 22，在 frontend 中执行 `npm ci`、`npm run dev`。
测试：backend 中 `python -m pytest -q`；frontend 中 `npm run build`。CI 额外在 PostgreSQL 上验证迁移往返。

## 上线限制
禁止将开发 Compose 直接用于生产。尚缺生产 TLS/反向代理、登录限流、密码找回、监控、备份恢复演练及完整验收。JWT 当前存于页面内存，刷新需重新登录。处理记录尚无时间戳，附件/SLA/通知/统计等范围待核对。
ECS 检查脚本 `scripts/inspect-ecs.sh` 仅查看资源、服务及端口，需用户提供明确主机。不得修改现有容器、Nginx、防火墙或运行中的服务。生产部署需用户再次确认。

开发任务清单位于 docs/tasks.json，远程 issues/milestones 未创建前不能视为已发布。
