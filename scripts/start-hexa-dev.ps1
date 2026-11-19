param(
  [string]$DatabasePath = "$PSScriptRoot\..\.artifacts\hexa-api\dev.db",
  [int]$Port = 4010
)

$ErrorActionPreference = 'Stop'
$repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$configPath = Join-Path $repo '.env.hexa-dev'
$database = (Resolve-Path $DatabasePath -ErrorAction Stop).Path

function Read-Config {
  $values = @{}
  if (Test-Path $configPath) {
    foreach ($line in Get-Content $configPath) {
      if ($line -match '^([^#=]+)=(.*)$') { $values[$Matches[1]] = $Matches[2] }
    }
  }
  return $values
}

$config = Read-Config
if (-not $config.HEXA_ADMIN_PASSWORD_HASH) {
  $adminPassword = Read-Host '设置 Hexa 管理员密码' -AsSecureString
  $passwordBstr = [Runtime.InteropServices.Marshal]::SecureStringToBSTR($adminPassword)
  $password = [Runtime.InteropServices.Marshal]::PtrToStringBSTR($passwordBstr)
  [Runtime.InteropServices.Marshal]::ZeroFreeBSTR($passwordBstr)
  $hash = $password | python -c "import sys; sys.path.insert(0, 'hexa-api'); from app.auth.passwords import hash_password; print(hash_password(sys.stdin.read().rstrip('\n')))"
  if ($LASTEXITCODE -ne 0 -or -not $hash) { throw '管理员密码哈希生成失败。' }
  $config.HEXA_ADMIN_PASSWORD_HASH = $hash.Trim()
}
if (-not $config.HEXA_SESSION_SECRET) {
  $config.HEXA_SESSION_SECRET = python -c "import secrets; print(secrets.token_urlsafe(48))"
}
if (-not $config.HEXA_GATEWAY_API_KEY) {
  $config.HEXA_GATEWAY_API_KEY = Read-Host '输入 Gateway API Key'
}
if (-not $config.HEXA_GATEWAY_URL) { $config.HEXA_GATEWAY_URL = 'http://127.0.0.1:3000/api/harness' }
if (-not $config.HEXA_ADMIN_USERNAME) { $config.HEXA_ADMIN_USERNAME = 'admin' }

@(
  "HEXA_DATABASE_URL=sqlite:///$($database.Replace('\','/'))"
  "HEXA_ADMIN_USERNAME=$($config.HEXA_ADMIN_USERNAME)"
  "HEXA_ADMIN_PASSWORD_HASH=$($config.HEXA_ADMIN_PASSWORD_HASH)"
  "HEXA_SESSION_SECRET=$($config.HEXA_SESSION_SECRET)"
  "HEXA_GATEWAY_URL=$($config.HEXA_GATEWAY_URL)"
  "HEXA_GATEWAY_API_KEY=$($config.HEXA_GATEWAY_API_KEY)"
  'HEXA_COOKIE_SECURE=false'
  'HEXA_SESSION_TTL_SECONDS=1209600'
) | Set-Content -LiteralPath $configPath -Encoding utf8

Get-Content $configPath | ForEach-Object {
  if ($_ -match '^([^#=]+)=(.*)$') { [Environment]::SetEnvironmentVariable($Matches[1], $Matches[2], 'Process') }
}

Write-Host "Hexa API 使用数据库：$database"
Write-Host "启动地址：http://127.0.0.1:$Port"
python -m uvicorn app.main:app --app-dir (Join-Path $repo 'hexa-api') --host 127.0.0.1 --port $Port --reload
