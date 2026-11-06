"""App-server framing must tolerate diagnostics and large native event payloads."""
import asyncio
import json
from types import SimpleNamespace
import pathlib
import sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from roder_driver import Rpc


def test_rpc_skips_noise_and_reads_items_larger_than_stream_limit():
    async def check():
        stream = asyncio.StreamReader(limit=64)
        rpc = Rpc(SimpleNamespace(stdout=stream))
        payload = {"method": "large", "params": {"text": "x" * (8 * 1024 * 1024 + 1)}}
        reader = asyncio.create_task(rpc.read())
        raw = b'diagnostic line\n[]\n' + json.dumps(payload).encode() + b'\n'
        for offset in range(0, len(raw), 65536):
            stream.feed_data(raw[offset:offset + 65536])
            await asyncio.sleep(0)
        stream.feed_eof()
        await reader
        assert await rpc.events.get() == payload
        assert await rpc.events.get() is None
    asyncio.run(check())


def test_approval_request_ends_noninteractive_turn(tmp_path):
    import os
    import subprocess
    binary = tmp_path / "app-server"
    binary.write_text("#!" + sys.executable + '\n' + '''
import json, sys
for line in sys.stdin:
    req = json.loads(line)
    method = req['method']
    results = {'tools/list': {'tools': []}, 'initialize': {},
               'workspace/create': {'workspace': {'id': 'ws'}},
               'thread/start': {'thread': {'id': 'thread'}},
               'turn/start': {'turnId': 'turn'}}
    print(json.dumps({'id': req['id'], 'result': results[method]}), flush=True)
    if method == 'turn/start':
        print(json.dumps({'method': 'thread/approvalRequested', 'params': {
            'threadId': 'thread', 'turnId': 'turn', 'approvalId': 'approval'}}), flush=True)
''')
    binary.chmod(0o755)
    (tmp_path / 'config.toml').write_text('')
    result = subprocess.run([sys.executable, str(pathlib.Path(__file__).resolve().parents[1] / 'roder_driver.py')],
        cwd=tmp_path, env={**os.environ, 'HR_RODER_BIN': str(binary),
            'RODER_CONFIG_DIR': str(tmp_path), 'HR_RODER_JOB': json.dumps({'model': 'gpt-6.1-sol', 'prompt': 'test'})},
        capture_output=True, text=True, timeout=10)
    events = [json.loads(line) for line in result.stdout.splitlines()]
    assert result.returncode == 1
    assert events[-1]['is_error']
    assert 'approval' in events[-1]['result']
