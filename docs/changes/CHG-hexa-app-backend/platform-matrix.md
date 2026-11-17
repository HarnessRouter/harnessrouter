# 平台矩阵

| 平台 | 实现影响 | 测试入口 | 环境 | 结果 |
| --- | --- | --- | --- | --- |
| Windows 11 开发机 | 使用 Python、FastAPI、SQLAlchemy 和标准 URL/路径 API；不依赖 Unix shell 或本机固定路径 | `python -X utf8 -m pytest -q hexa-api/tests`、`python -m compileall -q hexa-api/app` | Python 3.13.3、SQLite 测试库 | passed: 33 tests |
| Linux 容器 | 使用 PostgreSQL psycopg 驱动和 Uvicorn；数据库 URL、Gateway 地址和 Cookie Secure 均由环境变量提供 | Docker build 语法检查和容器启动冒烟 | PostgreSQL + Uvicorn 目标环境 | not_evaluated；本轮不部署 Docker |
| Chromium/移动视口 | app 模式登录、连续对话、文件、刷新恢复、右侧检查器、Agent 管理和无横向溢出已验证 | app/integration Playwright configs | Chromium + Vite + FastAPI fixture | passed；app 6、integration 2 |
| Edge | app 模式登录、连续对话、Agent 管理和移动布局已验证；集成文件/对话首测通过，第二个集成用例两次在创建浏览器上下文时由 Edge 进程退出 | app/integration Playwright configs | Edge desktop | partial；app 6、integration 1 passed，1 environment failure；需补验 |
