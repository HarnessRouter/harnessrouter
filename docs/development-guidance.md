# Hexa 后续开发指南

本文是 Hexa 后续开发、测试和评审的入口清单。它把现有产品契约和 WisHarness 规范转化为可执行步骤；产品行为的唯一正文仍由下列文档定义：

- [Cloud 能力移除契约](changes/CHG-hexa-remove-cloud-contract/spec.md)
- [任务模块设计规范：版本关系与保存边界](changes/CHG-task-centric-workflow/spec.md#版本关系与保存边界)
- [任务模块完整验收](changes/CHG-task-centric-workflow/spec.md#验收)
- [当前开发验证记录](development-verification.md)

## 一、开发前入口检查

`.wisharness/config.json` 当前启用 WisHarness，已选择团队协作、UI 视觉验收、跨平台兼容和 Git 分支协作能力。开始分析、修改代码、编写测试或评审前，按任务类型完成以下检查：

1. 读取 `.wisharness/config.json`，确认总开关和能力配置。
2. 所有开发任务读取 `.wisharness/rules/core.md`。
3. 行为变化、跨模块修改、并行协作或跨会话交接，读取 `.wisharness/rules/team-collaboration.md`。
4. UI 修改读取 `.wisharness/rules/ui-visual-contract.md`，同时查找对应的设计稿、截图、原型和现有视觉契约。
5. 涉及路径、进程、权限、Shell、原生模块、Runner 或平台 API，读取 `.wisharness/rules/cross-platform.md`，并更新对应平台矩阵。
6. 涉及分支、提交、评审、合并、回滚或热修复，读取 `.wisharness/rules/git-collaboration.md`。
7. 修改 WisHarness 配置前读取 `.wisharness/rules/config-reference.md`。
8. 复杂功能、接口调整或迁移，在生产代码前复用或建立 `spec.md`、`plan.md`；命中共享变更条件时同时维护 `change-record.yaml`。

完成后，交付记录必须说明实际读取的规范、匹配的验收范围、执行过的测试，以及未执行项和补验方式。

## 二、产品边界：先判断是否触碰 Cloud 契约

Hexa 自托管版本不得重新提供 HarnessRouter Cloud 的以下入口：

- 部署和上传
- 目标工作区
- 云端账号、余额和 hosted account
- Get a key、Reconnect 或密钥握手
- hosted provider 专属连接和调用路径

同步上游或重构时，不能只检查页面。应同时检查菜单和路由、公共 API/OpenAPI、服务端代理、provider 注册、配置项、数据库字段、错误文案、README、部署脚本和测试夹具。

以下能力继续属于产品范围，不能因为移除 Cloud 能力而误删：

- 普通 BYOK 服务商，包括 Azure OpenAI、AWS 兼容服务和其他 OpenAI-compatible 服务
- 第三方 Agent 运行时
- 浏览器运行时
- UHP 连接
- Runner 管理
- 自托管 Gateway 的本地编排能力

每个涉及 provider、Gateway、连接或设置页面的变更，都应同时添加或复用正向和负向验收：被移除入口不存在，保留能力仍然可用。

## 三、任务模块的唯一数据边界

任务模块必须遵循以下关系：

```text
Template → TemplateVersion
                └── 显式使用模板创建 Task
Task → WorkflowRevision
          ├── Run A → NodeRun / Artifact
          └── Run B → NodeRun / Artifact
```

职责边界固定如下：

| 模块 | 权威职责 |
| --- | --- |
| `client` | 编辑草稿、提交 API、展示保存和运行状态、展示错误和恢复信息 |
| `hexa-api` | 认证、权限、Task/Workflow/Template/Run/NodeRun/Artifact 持久化、状态转换、调度和脱敏 |
| Gateway | 接收应用后端发起的 Agent 执行请求，返回执行结果 |
| 数据库 | 保存任务定义、不可变版本、运行快照、节点尝试、结果引用和审计信息 |

开发时必须保持以下不变量：

- `WorkflowRevision` 和 `TemplateVersion` 创建后不可修改。
- 草稿修改不会改变模板、旧版本或既有 Run。
- 只有服务端返回的 `WorkflowRevision` 才是 `saved` 状态。
- Run 只能绑定已保存版本，不能绑定本地草稿。
- 每个 Run 保存绑定的工作流版本、执行配置和实际输入的快照。
- 模板新增版本不会升级旧任务；任务修改也不会自动写回来源模板。
- 保存任务流程、保存为模板、保存模板新版本、运行和重放必须是不同的用户操作。
- 重放只回看历史事件，不重新执行 Agent，也不创建 Run。
- 历史 Run 必须使用自己的快照展示流程图，不能用 Task 当前版本或模板最新版本重新拼装。
- 运行记录、NodeRun、结果引用和 Artifact 采用追加方式保存，不能被后续编辑覆盖。
- 运行中的语义修改必须先暂停或取消活动 Run，再保存新版本并创建新的 Run；拖动、平移和缩放等查看布局可以是临时视图状态。

## 四、建议的实施顺序

### 1. 先稳定领域模型和服务端边界

优先确认 Task、WorkflowRevision、Template、TemplateVersion、Run、NodeRun 和 Artifact 的字段、外键、状态转换及权限范围。API 应明确返回版本 ID、不可变版本号、来源模板版本和 Run 绑定版本，不用一个模糊的资源 ID 代替这些关系。

保存工作流时使用 `expected_revision` 并处理 409 冲突。创建 Run 时执行启动预检，固定 Agent、模型、提示词、工具和配置摘要；不保存 API Key、授权头或其他凭据。

### 2. 再实现可恢复的保存流程

前端允许保留本地草稿，但必须明确显示：未修改、本地修改、保存中、已保存、保存失败、版本冲突和内容过期。服务端确认持久化前不能显示成功。

保存失败时保留草稿和错误提示。刷新或重新打开任务时读取服务端数据，并清楚区分服务端已保存版本与浏览器本地草稿。

### 3. 再实现运行和历史

创建 Run 时固定 WorkflowRevision 和 `execution_snapshot`。`deps` 只决定执行依赖，`inputRefs` 只决定实际消费的结果；人工选择属于当前 Run 的追加数据，不修改工作流版本。

终态 Run 不重新打开。终态重跑创建新的 Run；活动 Run 的节点重试可以追加新的 NodeRun 尝试。历史输入、输出、错误、耗时、人工决定和配置摘要都必须可追溯且脱敏。

### 4. 最后扩展模板、画布和视觉体验

保存为模板必须是显式操作，并且只复制可复用工作流定义，不复制运行记录、结果、Artifact 内容或凭据。模板版本和任务版本互不覆盖。

画布验收按业务语义和查看状态分开：节点、依赖、输入声明和执行配置影响 WorkflowRevision；平移、缩放、拖动运行节点和重放只影响当前查看状态。

## 五、验收矩阵

每项任务按实际影响范围选择下列验收。已有场景优先复用，不在多个文档重复定义同一行为。

| 影响范围 | 必查场景 | 必须确认 |
| --- | --- | --- |
| Cloud 边界 | Cloud 入口移除、普通 provider/UHP/Runner 保留 | 路由、OpenAPI、服务端出站请求、页面入口和文档均符合契约 |
| 任务创建 | 空白创建、模板创建 | 进入统一任务详情；模板历史 Run、NodeRun、结果和 Artifact 不被复制 |
| 保存流程 | 编辑、保存、失败、冲突、刷新 | 只产生新的 WorkflowRevision；保存失败保留草稿；409 有明确反馈 |
| 模板 | 保存为新模板、追加现有模板版本 | 只有显式操作才写模板；旧版本和既有任务不改变 |
| 运行 | 同一任务多次运行、并行节点、人工门控 | 每次 Run 绑定正确版本和快照；依赖与输入引用语义正确 |
| 历史 | 打开旧 Run、重放、终态重跑 | 历史图和输入输出不被当前版本覆盖；重放不产生执行请求；重跑创建新 Run |
| 节点控制 | 重试、跳过、取消、采用结果 | 状态转换符合契约；旧尝试保留；过期结果显示为派生状态 |
| 安全 | 权限、脱敏、Artifact 代理 | 用户和工作区边界由服务端判断；凭据不进入数据库、日志或客户端响应 |
| UI | 加载、空态、保存失败、运行中、人工等待、恢复、移动视口 | 结构、可访问性、溢出和关键断点都可用；截图和交互证据可查 |
| 平台 | Windows、Linux、macOS 或 Web 的适用范围 | 路径、进程、权限、Shell、编码和原生能力按支持矩阵验证 |

## 六、测试执行规则

按变更实际影响范围选择测试，不默认用全仓测试代替分析。每个可测试行为必须有单元测试或复用已有完整覆盖；涉及模块协作、API 或数据边界时补集成测试；涉及完整用户路径时补 E2E。某一层不适用时，要记录结构性原因，环境缺失或运行失败不能写成“不适用”。

建议按以下顺序执行：

1. 先写最小目标测试并确认 Red，避免用 mock 生产实现或弱化断言制造失败。
2. 写最小实现，运行目标测试和受影响回归。
3. 需要时再重构，每次保持目标测试和回归 Green。
4. 对 UI 修改执行真实交互和关键视口检查，保存结构化报告、截图、平台、视口和测试命令。
5. 对平台能力更新 `.wisharness/templates/platform-matrix.md` 对应的项目矩阵或现有平台记录。
6. 对交付前变更检查实际 diff、调用方、消费者、权限边界、敏感数据流和错误恢复。

当前项目常用验证入口包括：

```powershell
npm run typecheck --prefix client
npm test --prefix client
npm run build --prefix client
python -m pytest hexa-api/tests gateway/tests
```

命令必须按本次变更的目录、用例和运行环境进行筛选。未执行的必需验证标记为 `not_evaluated`，写明原因、影响和补验命令；本地通过不能替代必需的真实平台、部署或 CI 验证。

## 七、交付前检查

交付前逐项回答：

- 是否触碰或重新暴露了被移除的 Cloud 能力？
- 是否保持了 Task、Template、WorkflowRevision、Run 和 NodeRun 的版本关系？
- 是否把本地草稿误当成服务端已保存版本？
- “保存成功”是否有服务端持久化证据？
- 每个 Run 是否固定了实际工作流、输入和执行配置快照？
- 历史 Run 是否能在当前任务版本改变后保持原样？
- 是否处理了保存失败、版本冲突、活动 Run 冲突、权限失败和重复请求？
- 是否验证了模板不携带运行态数据、结果、Artifact 内容和凭据？
- 是否按范围执行了单元、集成、E2E、UI 和平台验证？
- 是否记录了未执行项、阻塞项、证据位置和下一步？
- 是否保留了工作树中的他人改动，且提交范围只包含本次任务？

只有相关代码、必要测试和适用门禁全部通过，且没有未说明的失败或阻塞，才能声明本次开发完成。合入不等于发布；真实部署、生产形态和发布证据需要单独记录。

## 八、当前建议优先级

结合现有仓库结构，后续优先级建议如下：

1. 继续补齐 `hexa-api` 任务系统的真实持久化、版本冲突、幂等请求和运行快照测试。
2. 对 `client` 的任务工作台逐一补齐保存状态、失败恢复、运行历史和移动视口验收。
3. 将模板、任务和运行记录的跨对象验收固定到 API 集成测试和浏览器 E2E。
4. 维护 Cloud 负向回归，防止上游同步恢复已移除的入口，同时保持 UHP、Runner、浏览器和 BYOK 正向回归。
5. 对已记录的未评估项逐项补验，尤其是真实 PostgreSQL、真实普通 BYOK Provider、生产形态启动、跨浏览器和支持平台验证。
6. 交付前回读实际 diff、Change 状态、测试证据和剩余事项，再进行评审或合入。
