# 本地测试操作手册（docker-compose 文件夹）

本文件夹存放本地测试用的启动脚本和说明。仓库根目录下的三个 compose 文件是正式部署入口：

| 文件 | 部署形态 | 容器 |
|---|---|---|
| [docker-compose.yml](../docker-compose.yml) | 一体化 | 1 个容器（gateway + runner 同进程） |
| [docker-compose.split.yml](../docker-compose.split.yml) | 分离 | runner + gateway，共享一个数据卷 |
| [docker-compose.cluster.yml](../docker-compose.cluster.yml) | 集群 | 2 个 runner + session-router + gateway，各自独立数据卷 |

## 前置条件

- Docker Desktop（Windows，WSL2 后端）
- provider key 可以不写进 `.env`——启动后登录 console（`http://localhost:3000`），在 Integrations 页面添加即可；`.env` 里的 `HR_SECRET_GLOBAL_HARNESS_CONN_*` 是给脚本化部署用的另一条路，二者选一。

## 快速开始（推荐：分离部署）

```powershell
cd D:\work\Github\harnessrouter
cp .env.example .env        # 编辑 .env 填入 provider key
.\docker-compose\start-local.ps1 -Mode split
# 打开 http://localhost:3000
```

`start-local.ps1` 的四种模式：

```powershell
.\docker-compose\start-local.ps1 -Mode split      # 分离部署，本地构建（默认）
.\docker-compose\start-local.ps1 -Mode allinone   # 一体化，从 Docker Hub 拉镜像
.\docker-compose\start-local.ps1 -Mode cluster    # 集群（要求 .env 里有 HARNESS_INTERNAL_KEY）
.\docker-compose\start-local.ps1 -Mode down       # 停止全部（数据卷保留）
```

## 常用命令

```powershell
# 看日志（分离部署）
docker compose -f docker-compose.split.yml logs -f runner
docker compose -f docker-compose.split.yml logs -f gateway

# runner 首次启动会按 HR_BACKENDS 安装 agent CLI，耗时较长；
# 就绪标志：日志里出现 "backends available:"

# 只重建 runner
docker compose -f docker-compose.split.yml up -d --build runner

# 彻底清理（含数据卷，慎用）
docker compose -f docker-compose.split.yml down -v
```

## 本次本地定制的后端集合

`docker/entrypoint.sh` 中已把 `HR_BACKENDS` 默认值收窄为 7 个：

```
claude,codex,hermes,pi,dsh,opencode,gemini
```

- 这只影响「不设 `HR_BACKENDS` 时装哪些 CLI」。安装逻辑本身没动——`backend_bin` 里其它后端的分支仍在，想临时启用某个后端不需要改回代码，直接在 `.env` 里加一行即可，例如 `HR_BACKENDS=claude,codex,qoder`。
- 集群部署（cluster.yml）也读同一个 entrypoint，同样生效。

## 数据与存储

- 所有持久状态（SQLite 数据库、blob、secret store）都在数据卷里，runner 和 gateway 之间没有共享数据库——gateway 的库归 gateway，runner 的工作区/工具归 runner，二者只通过 HTTP + 共享卷交换文件。
- 想换成 PostgreSQL：不需要。自托管形态的存储就是 SQLite + 文件（见 `.env.example` 第 38 行注释），compose 里没有 PG 服务，也没有 PG 连接配置项。gateway 里出现的 postgres 字样只是「用户自带数据库连接」功能支持连到外部 PG，不是本产品的存储引擎。

## 安全注意

- 只有 console 的 3000 端口对外发布，runner 的 8081、gateway 的 8080 都只在 compose 网络内，**不要**在 compose 文件里 publish 它们。
- cluster 模式两个 runner 数据卷分开，必须设置 `HARNESS_INTERNAL_KEY`，否则 runner 对所有请求返回 401。
