# 行为说明

- 已有需求、设计或契约引用：用户契约（2026-11-13）：“hexa版本就是要移除cloud相关功能”。
- 实施方案：同目录 `plan.md`。

## 目标行为

- Hexa 自托管版本不再提供 HarnessRouter Cloud 的部署、上传、目标工作区、云端账号余额、Get a key / Reconnect 及 hosted provider 专属入口。
- 被移除的 HTTP 路由不再出现在公共 OpenAPI，也不再执行到云端的出站请求。
- 普通外部模型服务商、浏览器运行时、UHP 连接与 Runner 管理继续可用；它们属于 Hexa 的本地编排能力或用户自有服务商连接。

## 边界与非目标

- 本次不删除泛指 hosted/cloud 的历史实现注释、协议兼容说明或第三方服务商名称，除非它们形成 Hexa 用户可访问的 HarnessRouter Cloud 产品入口。
- 本次不删除普通 BYOK 服务商，也不删除浏览器和 UHP/Runner 功能。
- 已有工作树中的其他功能改动不属于本变更范围，验证时保留并区分。

## 验收

- 公共 API：Cloud 上传、目标管理和连接握手路由不存在；OpenAPI 不暴露这些路径；现有 harness、UHP 和普通 integrations 路由仍可访问。
- Gateway：不再声明或持久化 Cloud upload 记录，不再暴露 HarnessRouter hosted provider 专属连接/余额逻辑。
- Console：设置、工作区、BYOK 页面不显示 Cloud 部署/上传/云端账号操作，也不调用对应接口。
- 文档：README 和自托管指南不再把 Cloud 作为 Hexa 的部署路径。
