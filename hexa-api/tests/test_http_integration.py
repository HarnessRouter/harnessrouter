"""Real HTTP adapter boundary; the fake HTTP Gateway does not prove Provider success."""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from tests.test_conversations import login
from app.gateway.client import GatewayClient


def test_real_http_gateway_continuation_progress_and_app_restart(client, app, caplog):
    requests = []
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            assert self.headers['Authorization'] == 'Bearer server-only-gateway-key'
            requests.append(body)
            self.send_response(200); self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
            events = [
                {'type': 'response.created', 'response': {'id': f'r{len(requests)}'}},
                {'type': 'response.output_text.delta', 'delta': '真实 HTTP 边界'},
                {'type': 'response.completed', 'response': {'id': f'r{len(requests)}', 'status': 'completed'}},
            ]
            for event in events:
                self.wfile.write(f'data: {json.dumps(event)}\n\n'.encode()); self.wfile.flush()
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True); worker.start()
    try:
        app.state.gateway = GatewayClient(f'http://127.0.0.1:{server.server_port}', 'server-only-gateway-key')
        login(client)
        cid = client.post('/api/hexa/conversations', json={'agent_id': 'a1', 'model': 'm1'}).json()['id']
        for key in ['first', 'next']:
            result = client.post(f'/api/hexa/conversations/{cid}/messages', headers={'Idempotency-Key': key}, json={'text': key})
            assert result.status_code == 202
            assert result.json()['assistant']['id'] is not None
        assert 'previous_response_id' not in requests[0]
        assert requests[1]['previous_response_id'] == 'r1'
        assert requests[0]['metadata']['harness_id'] == 'a1'
        assert 'server-only-gateway-key' not in result.text
        assert 'server-only-gateway-key' not in caplog.text
        # A second app instance reads the same persisted session and conversation.
        from app.main import create_app
        from fastapi.testclient import TestClient
        with TestClient(create_app(app.state.settings, app.state.gateway)) as restarted:
            restarted.cookies.update(client.cookies)
            snapshot = restarted.get(f'/api/hexa/conversations/{cid}').json()
            assert len(snapshot['messages']) == 4
            assert snapshot['previous_response_id'] == 'r2'
    finally:
        server.shutdown(); server.server_close(); worker.join(timeout=2)


def test_http_chained_fanout_loop_keeps_rounds_and_history_after_restart(client, app):
    import time
    from tests.test_task_workflows import authenticated, node
    from app.main import create_app
    from fastapi.testclient import TestClient

    contexts = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            context = json.loads(body['input'][0]['content'])
            contexts.append(context)
            rid = f'composition-{len(contexts)}'
            output = 'done' if context.get('loop_previous') else 'again'
            annotations = [{'type': 'container_file_citation', 'file_id': rid,
                            'container_id': 'composition', 'filename': 'result.txt'}]
            events = [
                {'type': 'response.created', 'response': {'id': rid}},
                {'type': 'response.output_text.delta', 'delta': output},
                {'type': 'response.completed', 'response': {
                    'id': rid, 'status': 'completed', 'output': [{'type': 'message', 'content': [
                        {'type': 'output_text', 'text': output, 'annotations': annotations},
                    ]}],
                }},
            ]
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            for event in events:
                self.wfile.write(f'data: {json.dumps(event)}\n\n'.encode())
                self.wfile.flush()

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    try:
        # Agent inventory stays controlled; execution uses the real HTTP adapter.
        app.state.task_executor.gateway = GatewayClient(f'http://127.0.0.1:{server.server_port}', 'local-fixture-key')
        authenticated(client)
        created = client.post('/api/hexa/tasks', json={'workflow': {'max_concurrency': 2, 'nodes': [
            node('source'),
            node('outer', deps=['source'], inputRefs=['source'], foreach={
                'source': 'source', 'path': 'artifacts', 'max_items': 2, 'mode': 'parallel',
            }),
            node('inner', deps=['outer'], inputRefs=['outer'], foreach={
                'source': 'outer', 'path': 'items', 'max_items': 2,
            }),
            node('check', deps=['inner'], inputRefs=['inner'], loop={
                'body': ['outer', 'inner', 'check'], 'max_iterations': 2,
                'until': {'source': 'check', 'path': 'text', 'op': 'eq', 'value': 'done'},
            }, final_report=True),
        ]}})
        assert created.status_code == 201
        task = created.json()
        started = client.post(f"/api/hexa/tasks/{task['id']}/runs", headers={'Idempotency-Key': 'http-composition'})
        assert started.status_code == 202
        run_id = started.json()['id']
        for _ in range(400):
            result = client.get(f'/api/hexa/runs/{run_id}').json()
            if result['status'] in ('completed', 'failed'):
                break
            time.sleep(0.025)
        assert result['status'] == 'completed', result['nodes']
        assert len(contexts) == 7
        inner = next(row for row in result['nodes'] if row['node_id'] == 'inner')
        assert inner['iteration'] == 2
        assert inner['output']['items'][0]['text'] == 'done'
        history = client.get(f"/api/hexa/node-runs/{inner['id']}").json()['attempts']
        aggregates = [row for row in history if row['execution_kind'] == 'foreach_aggregate']
        assert [row['iteration'] for row in aggregates] == [1, 2]
        assert aggregates[0]['output']['items'][0]['text'] == 'again'
        with TestClient(create_app(app.state.settings, app.state.gateway)) as restarted:
            restarted.cookies.update(client.cookies)
            assert restarted.get(f'/api/hexa/runs/{run_id}').json() == result
            first = restarted.get(f"/api/hexa/node-runs/{inner['id']}?offset=0&limit=2").json()
            second = restarted.get(f"/api/hexa/node-runs/{inner['id']}?offset=2&limit=10").json()
            assert first['attempts'] + second['attempts'] == history
        assert len(contexts) == 7
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
