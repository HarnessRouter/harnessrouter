import httpx
import pytest

from app.gateway.client import GatewayClient


@pytest.mark.anyio
async def test_public_reasoning_and_tool_events_are_separate_from_reply(monkeypatch):
    import json
    events = [
        {'type': 'response.reasoning_summary_text.delta', 'delta': '先核对公开资料。'},
        {'type': 'response.output_item.added', 'item': {'id': 'call-1', 'type': 'function_call', 'name': 'web_search', 'status': 'in_progress', 'arguments': 'secret-input'}},
        {'type': 'response.output_item.done', 'item': {'id': 'call-1', 'type': 'function_call', 'name': 'web_search', 'status': 'completed'}},
        {'type': 'response.completed', 'response': {'id': 'trace-response', 'status': 'completed', 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '最终结果'}]}]}},
    ]
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=''.join(f'data: {json.dumps(event)}\n\n' for event in events)))
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=transport, **kwargs))
    result = await GatewayClient('http://gateway.test', 'test-key').create_response('hi', None, 'trace')
    assert result['text'] == '最终结果'
    assert result['execution']['reasoning'] == '先核对公开资料。'
    assert result['execution']['steps'] == [{'id': 'call-1', 'name': 'web_search', 'status': 'completed'}]
    assert 'secret-input' not in json.dumps(result)


@pytest.mark.anyio
@pytest.mark.parametrize('status,event_type', [('completed', 'response.completed'), ('incomplete', 'response.incomplete'), ('cancelled', 'response.failed')])
async def test_terminal_only_replay_keeps_output_and_cancellation(monkeypatch, status, event_type):
    import json
    event = {'type': event_type, 'response': {'id': 'resp-replay', 'status': status, 'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': '最终回答'}]}]}}
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text=f'data: {json.dumps(event)}\n\n'))
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=transport, **kwargs))
    result = await GatewayClient('http://gateway.test', 'test-key').create_response('hi', None, 'stable')
    assert result == {'response_id': 'resp-replay', 'text': '最终回答', 'status': status}


@pytest.mark.anyio
async def test_truncated_stream_retains_id_for_status_recovery(monkeypatch):
    from app.gateway.client import GatewayError
    original = httpx.AsyncClient
    transport = httpx.MockTransport(lambda request: httpx.Response(200, text='data: {"type":"response.created","response":{"id":"resp-recover"}}\n\n'))
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kwargs: original(transport=transport, **kwargs))
    with pytest.raises(GatewayError) as result:
        await GatewayClient('http://gateway.test', 'test-key').create_response('hi', None, 'stable')
    assert result.value.uncertain
    assert result.value.response_id == 'resp-recover'


@pytest.mark.anyio
async def test_gateway_sse_adapter_collects_utf8_delta_response_id_and_terminal_status():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer server-only-gateway-key"
        assert request.headers["idempotency-key"] == "message-1"
        assert request.url.path == "/api/harness/v1/responses"
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            content=(
                'data: {"type":"response.output_text.delta","delta":"你好"}\n\n'
                'data: {"type":"response.output_text.delta","delta":"，世界"}\n\n'
                'data: {"type":"response.completed","response":{"id":"resp-utf8","status":"completed"}}\n\n'
            ).encode("utf-8"),
        )

    transport = httpx.MockTransport(handler)
    gateway = GatewayClient("http://gateway.test/api/harness", "server-only-gateway-key")
    original = httpx.AsyncClient

    class Client(httpx.AsyncClient):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = transport
            super().__init__(*args, **kwargs)

    httpx.AsyncClient = Client
    try:
        result = await gateway.create_response("开始", None, "message-1")
    finally:
        httpx.AsyncClient = original

    assert result == {"response_id": "resp-utf8", "text": "你好，世界", "status": "completed"}
