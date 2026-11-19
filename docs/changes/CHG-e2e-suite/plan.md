# 实施方案

- 行为、边界与验收依据：[spec.md](spec.md) 的 E2E-1 至 E2E-14。
- 执行记录位置：[change-record.yaml](change-record.yaml)。本方案于 2026-11-19 接手核查时事后补齐，不作为原实现已完成事前设计的证据。

## 方案与依赖

复用 Playwright、真实 Vite、FastAPI Cookie 会话、一次性 SQLite 和受控 HTTP Gateway。`client/playwright.e2e.config.ts` 管理隔离服务与清理，禁止连接开发或生产数据库。共享辅助函数负责登录、任务创建和流程保存；断言通过用户入口及公开 API 检查持久化、权限、版本与零写入重放。

依赖已有任务领域 API、工作区 API、文件代理、浏览器安装和本机 Python/Node 运行时。真实 BYOK、PostgreSQL 与生产部署不属于本套件的验收证据。

## 实施与验证

| 步骤 | 改动与依赖 | 对应验收及验证方式 |
| --- | --- | --- |
| 1 | 隔离 HTTP Gateway、临时数据库和可配置测试端口 | 启动健康检查，确认不读取真实凭据 |
| 2 | 登录、工作区、对话和智能体测试 | E2E-1 至 E2E-6；浏览器操作与公开 API 回读 |
| 3 | 任务、模板版本、Run 快照、人工门控、失败恢复和 Artifact 下载 | E2E-7 至 E2E-12；生命周期及恢复套件 |
| 4 | 桌面/390px 移动视口、Edge、按需分页和刷新恢复 | E2E-13、E2E-14；cross-browser、task-pagination 与任务生命周期套件 |
| 5 | 核对测试结果与实际范围 | 证据和未执行项只记录在 Change，不将受控 Gateway 结果称为真实模型验收 |

## 恢复与收尾

测试服务结束后由 runner 关闭，临时数据库由测试工厂清理。失败证据保存在已忽略的 `client/test-results/` 或 `client/.artifacts/`；共享记录保留命令、结果和适用基线。删除测试只影响验证能力，不修改业务数据库；无需业务数据回滚。后续选择器或 API 契约变更应同步维护测试。
