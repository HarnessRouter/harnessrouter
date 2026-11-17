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
