# Hexa 全栈 E2E 套件

## 目标

用真实浏览器、真实 Vite 开发服务和真实 `hexa-api` 进程覆盖 Hexa 的主要用户流程。测试只依赖一次性 SQLite 数据库和一次性 HTTP Gateway 夹具，不读写开发或生产数据，不恢复 Hexa Cloud 能力。

## 运行入口

```powershell
cd client
npm run test:e2e -- --workers=1
```

配置 `playwright.e2e.config.ts` 自动启动：

| 组件 | 地址 | 说明 |
| --- | --- | --- |
| Vite | `http://127.0.0.1:4020` | 只代理 `/api/hexa` |
| Gateway 夹具 | `http://127.0.0.1:4021` | 需要服务端 Bearer Key，模拟 Agent/模型/工作区/文件/SSE |
| Hexa App API | `http://127.0.0.1:4022` | 真实 FastAPI、`hexa_session` HttpOnly Cookie、SQLite 临时库 |

夹具支持按提示词注入行为：`E2E_OUT:` 固定输出、`E2E_MARKDOWN` 输出 GFM、`E2E_FAIL:<scope>` 首次失败、`E2E_SLOW:<秒>` 延迟、`E2E_RUNNING` 长驻直到取消。任务节点输出会回传实际消费的 `refs`，用于验证 `deps` 与 `inputRefs` 的分离。

## 验收场景

| ID | 入口 | 操作 | 预期结果 |
| --- | --- | --- | --- |
| E2E-1 | `/` 登录 | 错误密码、正确密码、清 Cookie 后重登、退出 | 错误提示可见；`hexa_session` 为 HttpOnly 且不可被脚本读取；草稿在刷新和会话恢复后保留；退出后回到登录页 |
| E2E-2 | 工作区菜单 | 新建、切换、重命名工作区，深链访问其他工作区任务 | 工作区隔离任务/模板/运行；跨区任务不可见并显示错误；重命名刷新后保留 |
| E2E-3 | 对话页 | 选择 Agent/模型、上传附件、两轮对话、刷新、预览/下载产物、取消生成 | SSE 输出与追问持久化；`hexa_session` Cookie 可用且服务端不暴露 Gateway Key；产物经 hexa-api 代理下载；取消后不再处于生成态 |
| E2E-4 | 对话页 | 返回 GFM Markdown | 标题、表格、代码块高亮与复制按钮可用；深色模式与 390px 无横向溢出 |
| E2E-5 | 智能体页 | 打开详情并切换五个层级 | Instructions、运行时/模型、Skills/MCP/Plugins、Memory、环境变量与限制来自 Gateway；密钥值不渲染 |
| E2E-6 | 智能体页 | 另存 Gateway 模板、创建 Agent、删除 Agent、删除模板 | 数据经真实 App API 持久化；刷新后仍存在；删除后 API 不再返回 |
| E2E-7 | 任务页 | 空白建任务、编辑并保存三节点流程、运行、人工选择、产物下载、采用结果、保存为模板、用模板建任务 | 保存产生 v2；运行固定 v2 快照并完成；产物可下载且不暴露 Gateway 文件 ID；模板任务记录来源模板与版本 |
| E2E-8 | 任务页 | 五个并行节点 + 人工门控 | Run 进入 `waiting_human`；只把勾选的两个结果写入 `inputRefs`；继续后完成；活动 Run 锁定语义编辑；暂停/继续/取消语义正确 |
| E2E-9 | 任务页 | 同一任务先后运行工作流 v2、v3 | 两个 Run 各自展示绑定版本与输入；运行记录可返回所属任务；拖动节点、缩放与重放不产生写请求，刷新恢复默认布局 |
| E2E-10 | 模板管理 | 保存模板 v1、编辑为 v2、用 v2 建任务、再向原模板追加任务版本 | 旧任务与旧模板版本不被改写；`save-as-template` 默认新建模板，显式选择目标才追加版本 |
| E2E-11 | 任务页 | 节点失败、重新打开并保存新版本再次运行 | 失败 Run 保留；重开后可保存新 WorkflowRevision；新 Run 成功且两条历史并存 |
| E2E-12 | 运行记录 | 归档/取消归档、失败节点新建重跑 Run、中断 SSE | 归档状态持久化；重跑生成新 Run 且旧 Run 不变；SSE 中断后以只读轮询恢复完成 |
| E2E-13 | 390×844 视口 | 任务工作台与对话 | 单列布局、详情抽屉不超屏、触控目标与输入字号满足移动端下限 |
| E2E-14 | Microsoft Edge | 对话 Markdown 与任务运行 | 与 Chromium 相同路径通过，无运行时错误与横向溢出 |

## 边界

- 不验证真实 BYOK 模型回答质量、真实 Gateway 权限或生产 PostgreSQL 迁移。
- Artifact 只保存 Gateway 文件引用；夹具返回固定内容，真实远端清理不在本套件范围。
- 夹具仅用于测试进程，不是产品服务。
