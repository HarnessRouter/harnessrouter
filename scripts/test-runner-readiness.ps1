param([string]$Image = 'harnessrouter/runner:latest')

$ErrorActionPreference = 'Stop'
$runnerSource = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../runner')).Path

# Mount current sources read-only and use disposable storage. The test dependencies
# are installed in this temporary container, leaving running services untouched.
docker run --rm --entrypoint sh `
    --mount "type=bind,source=$runnerSource,target=/workspace/runner,readonly" `
    -w /workspace `
    -e HARNESS_WORKSPACE=/tmp/hexa-test-workspaces `
    -e HR_DATA_DIR=/tmp/hexa-test-data `
    $Image -lc 'python -m pip install --quiet pytest pytest-asyncio && python -m pytest runner/tests/test_readiness.py -q -p no:cacheprovider'
exit $LASTEXITCODE
