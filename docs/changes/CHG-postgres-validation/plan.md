# 实施方案

- 行为、边界与验收依据：spec.md。
- 执行记录：change-record.yaml。

## 方案与依赖

复用 hexa-api/migrate.py、001–007 SQL、docker-compose.hexa-api.yml、现有 API 测试及应用工厂。测试增加显式 PostgreSQL 入口，并以唯一 schema 隔离每个测试，数据库连接和测试凭据只通过环境注入。先在现有实现上运行真实 PG 回归，发现缺陷后补充最小失败用例，再做修复。

依赖 Windows Docker Desktop 的 Linux 引擎、PostgreSQL 16 镜像和现有 Python/psycopg/pytest。Compose 使用独立项目和一次性环境；不读取当前服务凭据。

## 实施与验证

| 步骤 | 改动与依赖 | 对应验收及验证方式 |
| --- | --- | --- |
| 1 | 新增可选 PG 测试数据库入口；现有 SQLite 默认不变 | 真实迁移 + Cookie/API 集成，先运行现有目标测试记录失败 |
| 2 | 新建库、升级和重复迁移验收；修复发现的兼容问题 | CLI 集成、任务/模板/Run/Artifact/进度回归；相关逻辑单测 |
| 3 | 独立 Compose 构建和运行 | Linux API healthcheck、HTTP 登录保存读取、重启恢复 |
| 4 | 自查和证据整理 | 最终 diff、迁移顺序文档、平台及安全边界；保留其他 Change 未完成项 |

## 恢复与收尾

测试只删除自己创建的 UUID schema；Compose 仅关闭本次命名项目并移除其卷。不对生产数据库运行 DROP 或数据库回滚。修复补丁可单独撤回；新增过程列不删除。测试入口与使用说明保留，原始日志置于已忽略的 .artifacts/postgres/，本目录保留结论和限制。
