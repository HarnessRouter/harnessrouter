# 实施方案

- 行为、边界与验收依据：同目录 `spec.md`。
- 执行记录位置：同目录 `change-record.yaml`。

## 方案与依赖

- 先以路由、常量和 UI 依赖搜索确定 Cloud 产品边界；删除 Gateway 的 Cloud upload 及 HarnessRouter hosted provider 专属逻辑；再删除 Console 入口、死 CSS、测试和文档。
- 保留普通 provider catalog、UHP/Runner、浏览器运行时和安全网络检查；保留与其相关的通用测试。
- 使用新增的 no-cloud 回归测试验证入口不存在，并运行受影响的 Gateway 与 Console 测试。

## 实施与验证

| 步骤 | 改动与依赖 | 对应验收及验证方式 |
| --- | --- | --- |
| 1 | 建立 Cloud 删除契约和变更记录，冻结范围 | 记录文件审阅 |
| 2 | 删除 Gateway Cloud upload、目标持久化、HarnessRouter hosted provider 账号/余额/握手链路 | no-cloud、OpenAPI、普通 integrations 测试 |
| 3 | 删除 Console Cloud 入口、上传组件、BYOK hosted provider 操作和死样式 | TypeScript、相关 Jest |
| 4 | 更新 README、自托管指南和验证记录 | 文档搜索与 diff 审阅 |
| 5 | 如当前运行集群可复用，则重建并验证部署；否则明确记录源码与运行时状态差异 | compose 健康检查与 HTTP 探针 |

## 恢复与收尾

- 源码回滚使用本变更的 Git diff；运行时回滚使用此前镜像/compose 配置。执行证据和未完成项写入 `change-record.yaml`。
