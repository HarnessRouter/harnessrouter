## Hexa 产品契约

Hexa 版本移除 HarnessRouter Cloud 的部署、上传、目标工作区、账号余额、密钥握手和 hosted provider 功能。后续同步上游或修复时，不得将这些能力恢复为 Hexa 产品入口。普通 BYOK 服务商（包括 Azure/AWS）、第三方运行时、浏览器、UHP 和 Runner 管理继续保留。行为边界见 `docs/changes/CHG-hexa-remove-cloud-contract/spec.md`。

## 任务、模板与运行记录开发契约

涉及任务、工作流、模板、运行记录或共享画布的开发、测试和评审，必须先阅读并遵守[任务模块设计规范：版本关系与保存边界](docs/changes/CHG-task-centric-workflow/spec.md#版本关系与保存边界)。该章节是关系和保存语义的唯一正文；客户端、应用后端和 UI 文案均应遵循，不得将当前演示实现或本地草稿视为已经完成真实持久化。

<!-- wisharness:start -->

## WisHarness

`.wisharness/config.json` 中 `enabled` 为 `true` 时，WisHarness 规范是每次开发任务的自动入口检查，不需要用户再次提醒。开始分析、修改代码、编写测试或评审前，必须按下列步骤执行：

1. 读取 `.wisharness/config.json`，确认 `enabled` 状态和当前项目能力配置。
2. `enabled` 为 `true` 时，先读取基础研发规范，再读取所有与当前任务匹配的专项规范；专项规范可以同时适用，不能只选择其中一项。
3. 根据任务内容匹配专项：行为变更、并行协作或跨会话交接读取团队协作规范；UI 修改读取 UI 视觉验收规范；影响路径、进程、权限、原生模块或平台能力读取跨平台规范；涉及分支、提交、评审、合并或热修复读取 Git 分支协作规范。
4. 将已读取规范中的要求转化为本次任务的实施步骤、验证项和完成标准，并在开发过程中持续执行，而不是只在任务结束时检查。
5. 规范引用的相对路径均以项目根目录为基准。必读规范缺失、路径失效或内容无法读取时，必须先报告阻塞并修复路径，不能跳过检查继续开发。
6. 完成修改后，按匹配规范执行必要的测试、视觉验收、跨平台检查和 Git 协作检查，并在结果中说明未执行项及原因。

- 所有开发任务：[基础研发规范](.wisharness/rules/core.md)
- 行为变更、并行协作或跨会话交接：[团队协作](.wisharness/rules/team-collaboration.md)
- UI 修改，尤其是有设计资料或对标产品时：[UI 视觉验收](.wisharness/rules/ui-visual-contract.md)
- 影响路径、进程、权限、原生模块或平台能力：[跨平台兼容](.wisharness/rules/cross-platform.md)
- 分支、提交、评审、合并或热修复：[Git 分支协作](.wisharness/rules/git-collaboration.md)

填写、修改或使用配置前读[配置说明](.wisharness/rules/config-reference.md)。

<!-- wisharness:end -->
