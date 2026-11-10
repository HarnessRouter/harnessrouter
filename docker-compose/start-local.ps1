# HarnessRouter 本地测试启动脚本（Windows / Docker Desktop）
#
# 用法：
#   .\start-local.ps1 -Mode split        # 默认：分离部署（runner + gateway），本地构建
#   .\start-local.ps1 -Mode allinone     # 一体化镜像（从 Docker Hub 拉取，需要先 cp .env）
#   .\start-local.ps1 -Mode cluster      # 集群部署（2 runner + session-router + gateway）
#   .\start-local.ps1 -Mode down         # 停止并删除容器（数据卷保留）
#
# 首次运行前请先把 .env.example 复制为 .env，并填入自己的 provider key。
param(
    [ValidateSet('split', 'allinone', 'cluster', 'down')]
    [string]$Mode = 'split'
)

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path | Split-Path -Parent

Push-Location $Root
try {
    if (-not (Test-Path "$Root\.env")) {
        Write-Host "未找到 .env，从 .env.example 复制..." -ForegroundColor Yellow
        Copy-Item "$Root\.env.example" "$Root\.env"
        Write-Host ".env 已创建。provider key 可以稍后在 console 的 Integrations 页面配置。" -ForegroundColor Yellow
    }

    switch ($Mode) {
        'allinone' {
            docker compose up -d
            Write-Host "一体化部署已启动：http://localhost:3000" -ForegroundColor Green
        }
        'split' {
            docker compose -f docker-compose.split.yml up -d --build
            Write-Host "分离部署已启动（构建可能需要几分钟，runner 首次启动会安装各 agent CLI）：http://localhost:3000" -ForegroundColor Green
        }
        'cluster' {
            if (-not (Select-String -Path "$Root\.env" -Pattern '^HARNESS_INTERNAL_KEY=' -Quiet)) {
                Write-Host "cluster 模式需要 .env 中设置 HARNESS_INTERNAL_KEY。" -ForegroundColor Red
                Write-Host '生成：python -c "import secrets; print(secrets.token_hex(32))"'
                exit 1
            }
            docker compose -f docker-compose.cluster.yml up -d --build
            Write-Host "集群部署已启动：http://localhost:3000" -ForegroundColor Green
        }
        'down' {
            docker compose down
            docker compose -f docker-compose.split.yml down
            docker compose -f docker-compose.cluster.yml down
            Write-Host "已停止（数据卷保留；加 -v 才会删除）。" -ForegroundColor Green
        }
    }
}
finally {
    Pop-Location
}
