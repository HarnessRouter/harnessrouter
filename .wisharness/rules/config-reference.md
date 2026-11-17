# 配置填写与使用说明

填写、修改或使用配置前读本文。实际值只存于 `.wisharness/config.json`；本文由 init / update 管理，不存参数副本，不直接修改。

## 从哪里开始

告知 Agent 调整目标，如“启用 UI 视觉验收，布局容差 2 px，单测命令 `npm run test:unit`”。Agent 核实项目脚本后用 update 预览、按已有授权应用；必要选择或授权缺失时等待用户明确答复。示例命令与数值均非默认值。

首次初始化固定启用基础规范，用户按编号选择四项专项规范；遗留测试补齐和 GitLab 工作流默认开启，不参与选择。不选专项规范时：

```json
{
  "enabled": true,
  "gitlab": { "requireIssueForMr": true },
  "workflows": { "backfill": true, "gitlab": true },
  "capabilities": {
    "selected": [],
    "routes": {},
    "settings": {}
  }
}
```

须用标准 JSON，无注释、尾随逗号或未列字段。手改也须遵守本文，并用 init / update 只读检查核对配置、入口与规则。

## 总开关与工作流

以下字段的值均为布尔值。`gitlab` 是 GitLab 行为策略对象，`workflows.gitlab` 是工作流开关。开关仅按用户明确要求调整，保留已有显式 `false`。

| 字段 | 初始/默认值 | 作用 |
| --- | --- | --- |
| `enabled` | `true` | 总开关；`false` 不激活规范或工作流。disable 同时清理入口，init 重新启用。 |
| `gitlab.requireIssueForMr` | `true`，省略也开启 | MR 创建是否强制关联同项目的打开 Issue；开启且缺少有效引用时自动创建并关联，不询问新建还是复用；`false` 关闭 Issue 关联门禁，允许不关联 Issue，不强制关联标记、自动关闭策略或 Issue 关联读回。仍保留 Git remote、私有正文文件、内置 launcher、目标分支和 MR 读回要求。 |
| `workflows.backfill` | `true` | 按任务补齐遗留测试；初始化不自动补测或运行测试。 |
| `workflows.gitlab` | `true` | 按任务操作 GitLab Issue、MR、流水线；执行前核实真实 Git remote，不自动授权远端写入、部署或通知。 |

工作流与专项规范独立：GitLab 工作流不启用 Git 分支协作规范，该规范也不授权 GitLab 操作。

关闭 MR 强关联时，在现有 JSON 的 `gitlab` 对象中设置 `"requireIssueForMr": false`，保留其他字段。省略 `gitlab` 或其中该字段时默认开启；`gitlab` 仅支持已列字段，不接受顶层 `requireIssueForMr`。仅接受布尔值，不接受字符串 `"false"` 或 `null`。init / update 保留显式值；`--reset` 恢复默认 `true`。该开关只控制本地关联策略，不修改 GitLab 服务端策略。

GitLab 技能仅从真实 Git remote 取仓库地址，通过前置检查判断是否支持（推荐 `wisgit.qihoo.net`）。多候选且目标不明时请用户选择；缺少合规 remote 时请用户本地配置后复查，不自动修改已有 remote，不阻止本地规范初始化。

不生成 `project`，不支持 `--gitlab-url`。旧 `project.gitlabUrl` 仅兼容读取，下次应用 init/update 时移除，保留其他有效配置；`--check` 只预览。

## wisTag 平台配置

wisTag 的能力开关、Review/Repair 设置与规则由平台管理；本配置不提供 wisTag 工作流或仓库、YAML 引用。查询或配置平台能力直接使用 `wistag` Skill，无需先初始化或启用 Harness。仓库从实际 Git remote 核实，CLI 管理服务地址与登录状态；项目 YAML 仅在用户要求保留草稿时维护。

## 云舟项目配置与本地凭据

可选顶层字段 `yunzhou` 只保存非秘密的默认空间；不添加默认值，也不启用新的 workflow：

```json
{
  "enabled": true,
  "workflows": { "backfill": true, "gitlab": true },
  "gitlab": { "requireIssueForMr": true },
  "capabilities": { "selected": [], "routes": {}, "settings": {} },
  "yunzhou": {
    "spaceId": "your-space-id"
  }
}
```

上例为最小完整配置，`your-space-id` 须替换为真实值；已有项目只合并 `yunzhou`，保留其他字段。`yunzhou` 可省略或为 `{}`；`spaceId` 必须是只含字母、数字、下划线、短横线的非空字符串，不能用数值，以免长 ID 丢失精度。未知字段及 AK/SK 不允许写入此对象。空间 ID 在[云舟空间设置](https://yy.qihoo.net/#/system-setting?tab=space)查看。

init/update 的 `--yunzhou-space-id <ID>` 可设置或更换空间；省略保留已有值，`--reset` 恢复为未配置。手工移除 `yunzhou` 可清除默认空间。配置云舟后，init/update 自动在根 `.gitignore` 补充 `/.wisharness/.env`，并在不存在时创建空白 `.wisharness/.env.example`；保留已有示例和真实 `.env`，不读取真实密钥文件，不将它纳入托管清单。`--check` 只预览；reset/disable 不删除凭据文件或忽略规则。

AK/SK 由用户在本机 `.wisharness/.env` 中配置，POSIX 权限必须设为 `600`；Git 项目必须忽略且未跟踪该文件。非空环境变量 `ZCS_AK` / `ZCS_SK` 优先，缺少的值由文件补齐。具体格式、密钥获取和项目绑定见云舟 Skill 的“环境与凭据”。不要在聊天、配置 JSON、预览或提交中显示密钥。

云舟查询无需先初始化项目；客户端在项目根目录自动读取默认空间和本地凭据，也支持 `--project-dir` 指定根目录。请求体显式 `spaceId` 覆盖默认值，不依赖 `enabled` 或工作流开关。无本地配置时继续支持原有环境变量及请求体传参。

## 选择专项规范：`capabilities.selected`

用户选编号，JSON 存对应 ID，不存编号、不重复；`core` 始终包含，不写入数组。四项独立，AI 不代选。

| 编号 | ID | 用途与参数 |
| --- | --- | --- |
| 1 | `team-collaboration` | 变更记录、评审、交接；无专属参数。 |
| 2 | `git-collaboration` | 分支、提交、合并、回滚；无专属参数。执行时按项目规范、实际分支及远端确认开发基线和合并目标，不预设分支策略或名称。 |
| 3 | `ui-visual-contract` | UI 设计与视觉验收；可填 `settings.ui`。 |
| 4 | `cross-platform` | 支持平台与实际平台验收；可填 `settings.platforms`。 |

`[]` 仅不选专项规范，基础规范与工作流默认值仍生效。取消能力移除其入口及未手改托管文件；参数可保留，但未启用能力的参数不得使用。

## 复用已有规范：`capabilities.routes`

通常填 `{}` 生成所选规范；复用时填“已选能力 ID → 项目根目录相对路径”，如 `"ui-visual-contract": "docs/design/acceptance.md"`。

- 仅替换已选专项入口，基础规范不可替换。目标须为已存在的普通文件，不经符号链接；复用后该能力正文和模板由项目维护，WisHarness 不再生成。
- 路径仅含英文字母、数字、下划线、短横线、空格、点及 `/`。禁止绝对路径、`..`、空路径段、Windows 保留文件名，或指向 `.wisharness/` 内文件及根目录 `AGENTS.md`、`CLAUDE.md`。
- 路由值存为字符串。删除路由或让 Agent 在 update 补丁中传 `null` 可恢复内置规范；空值不写入最终 routes。

## 项目参数：`capabilities.settings`

`settings` 可为 `{}`，仅支持 `ui`、`platforms`、`commands`。值应有用户上下文、项目契约、真实脚本或有依据的 Agent 判断支撑，不虚构事实；本次验收判断记录在视觉契约中，不自动写成项目永久配置。

| 字段 | 值与用途 |
| --- | --- |
| `ui.tolerancePx` | 非负有限数值，单位 px，如 `2`；未定可为 `null` 或省略。仅启用 UI 视觉验收时用于几何与布局容差，非截图像素差异百分比，不覆盖更严的项目要求。无值时由 Agent 按视觉规范制定有依据的验收方法，不强制询问数值、不套用固定值；通过仍须实际验证。 |
| `platforms` | 不重复数组，取值 `macos`、`windows`、`linux`、`web`、`ios`、`android`。仅启用跨平台兼容时使用，须与产品支持契约核对。`[]` 或省略仅表示未配置，先从产品契约、支持矩阵及项目证据确定范围；仍无法确定时才记未评估，非全部支持。范围已知或已配置均不等于验证通过。 |
| `commands` | 对象，键见下表，可省略；值为非空单行命令字符串或 `null`。供基础验证和按需工作流读取，不依赖专项选择；应引用项目已有脚本，不含密钥。 |

新增 UI 或平台参数须先选对应能力。以下示例须经用户明确选择 UI 和跨平台规范，容差及平台范围须有项目依据；数值和平台仅示范格式，命令未定，不因启用能力就要求用户填写容差：

```json
{
  "enabled": true,
  "workflows": { "backfill": true, "gitlab": true },
  "capabilities": {
    "selected": ["ui-visual-contract", "cross-platform"],
    "routes": {},
    "settings": {
      "ui": { "tolerancePx": 2 },
      "platforms": ["web", "windows"],
      "commands": {
        "unit": null,
        "integration": null,
        "e2e": null,
        "live": null,
        "build": null,
        "review": null
      }
    }
  },
  "gitlab": { "requireIssueForMr": true }
}
```

## 测试、构建与评审命令：`settings.commands`

用户可自行配置或通过 update 指定，保留已有值；初始化不主动询问、要求补填或保存推测命令。省略或 `null` 为未配置，Agent 在开发或验证任务中从项目脚本发现并核验，无法确定时再确认。

以下键相对 `capabilities.settings.commands`，须填项目实际入口：

| 键 | 验证目标与填写要求 |
| --- | --- |
| `unit` | 可测试的独立行为；如有 `test:unit` 脚本，可填 `npm run test:unit`。 |
| `integration` | 模块或服务边界协作，按本次场景决定是否执行。 |
| `e2e` | 完整用户路径，按本次用户场景决定是否执行。 |
| `live` | 真实环境、服务或平台行为；运行前核实环境、依赖、账号权限及操作授权。 |
| `build` | 构建与产物生成；如有 `build` 脚本，可填 `npm run build`。 |
| `review` | 项目规定的自动评审或检查；不为未自动化的人工评审虚构命令。 |

命令应能从项目根目录运行，子项目须注明工作目录；如确认 `frontend/package.json` 有对应脚本，可填 `npm --prefix frontend run test:unit`。不限定语言、包管理器或测试框架。

执行前核实脚本、目录、依赖及目标环境；命令字符串不代表可信结果或授权，init / update 不执行这些命令。可测试行为须严格单测，集成与 E2E 按真实用户场景选用，不强制三层齐备；不适用须说明原因，空命令不豁免必需验证，未执行标记 `not_evaluated`。

### 测试范围与命令选择

`settings.commands` 是可复用入口，不代表每次必须执行整套测试；按基础规范默认选目标用例与受影响回归，全量须先说明依据。

- 核实脚本展开内容、runner 的文件/模块/用例过滤及参数转发；可为本次调用加已核验筛选参数，不修改已保存的命令固化单次范围。
- 筛选须保留初始化、fixture、环境变量和清理，不能绕过原入口必需步骤。报告须发现并执行目标用例，零退出但未发现目标不算通过。
- 不支持过滤时先找已有更窄入口，否则用最小可用套件并记录限制；全仓须说明原因，耗时过长的必需验证用已有 CI 或分批完成，不跳过。
- 入口不决定所有用例均为本次必需验证；选择依据、未执行受影响项、全量原因和可复用证据记入现有任务记录或验证报告。

## 修改与检查

推荐告知 Agent 待改字段和值，由 update 同步配置、入口及托管文件。省略保留，唯有 `--reset` 丢弃旧设置重建。补丁的 `settings`、`ui`、`commands` 按字段合并，`platforms` 整体替换；已存命令或容差用 `null` 清空。

当前插件的 `scripts/init.mjs <项目目录> --check --configured` 只读核对已存配置与生成文件，不执行测试或构建；通过仅代表配置与路由一致，非业务验收通过。

配置变更应与 `AGENTS.md`、生成规范、`.wisharness/managed-files.json` 一起提交。清单摘要供重复初始化和更新判断覆盖、删除或冲突，不手改；自定义规则放项目自有目录，用 routes 引用。
