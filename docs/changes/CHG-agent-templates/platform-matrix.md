# 平台验证矩阵

目标沿用应用后端现有 Web/Windows 开发环境及 Linux + PostgreSQL 部署契约。本次没有新文件路径、Shell 或原生能力。

| 平台 | 影响、失败语义 | 测试命令、真实运行环境 | 提交、证据 | 结果 | 阻塞、补验计划 |
| --- | --- | --- | --- | --- | --- |
| Windows | Python ORM/HTTP + React，无操作系统分支 | 目标 pytest，Python 3.13/SQLite | Change green 记录，同一工作树 | passed | 无 |
| Web Chromium/Edge | 卡片/列表、表单、网络失败、认证过期 | Playwright app + HTTP integration，1440×900/390×844 | 10 app + 2 integration；visual-report.md | passed | 移动是桌面浏览器视口模拟，不声称真机验收 |
| Linux / PostgreSQL | 新增独立 agent_templates 表 | 003_agent_templates.sql，现有生产 migration 方式 | SQL 自查，无真实数据库运行 | not_evaluated | 部署时运行 SQL 后做启动及读写冒烟；不声明发布门禁通过 |
