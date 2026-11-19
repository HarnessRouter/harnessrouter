import json
import pathlib
import sys
import time

import unittest
from contextlib import redirect_stdout
from io import StringIO
from unittest.mock import patch

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import server


def check_turn_logs(crash):
    secret = 'canary-log-secret-123456'
    rec = {'identifier': 'hsess-test', 'backend': 'claude', 'model': secret, 'events': [],
           'status': 'running', 'started': time.time(), 'prompt': secret}
    def execute(turn_id):
        rec['events'].append({'text': secret})
        time.sleep(0.04)
        if crash:
            raise RuntimeError(secret)
        rec.update(status='completed', done=True)
    stream = StringIO()
    with patch.dict(server._turns, {'turn-test': rec}), patch.object(server, '_TURN_LOG_INTERVAL_S', 0.01, create=True), redirect_stdout(stream):
        wrapped = server._routes_end_with_turn(execute, [])
        if crash:
            with unittest.TestCase().assertRaises(RuntimeError):
                wrapped('turn-test')
        else:
            wrapped('turn-test')
    output = stream.getvalue()
    assert secret not in output
    logs = [json.loads(line.removeprefix('[turn] ')) for line in output.splitlines() if line.startswith('[turn] ')]
    assert logs[0]['event'] == 'started'
    assert any(row['event'] == 'progress' and row['events'] == 1 for row in logs)
    assert logs[-1]['event'] == 'finished'
    assert logs[-1]['status'] == ('failed' if crash else 'completed')
    assert all(row['session_id'] == 'hsess-test' and row['turn_id'] == 'turn-test' for row in logs)


class ExecutionLoggingTests(unittest.TestCase):
    def test_completed(self):
        check_turn_logs(False)

    def test_crashed(self):
        check_turn_logs(True)
