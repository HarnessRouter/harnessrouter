from tests.test_conversations import login


def test_upload_file_is_owned_and_used_as_response_content(client, app):
    class FileGateway:
        async def upload_file(self, name, content, media_type):
            assert content == b'hello'
            return {'id': 'file-one', 'filename': name, 'bytes': len(content)}
        async def create_response(self, text, previous, key, **kwargs):
            assert kwargs['content'] == [{'type': 'input_text', 'text': 'read'}, {'type': 'input_file', 'file_id': 'file-one'}]
            return {'response_id': 'r1', 'text': 'read hello', 'status': 'completed'}
        async def delete_file(self, file_id):
            assert file_id == 'file-one'
    app.state.gateway = FileGateway()
    login(client)
    upload = client.post('/api/hexa/files', files={'file': ('note.txt', b'hello', 'text/plain')})
    assert upload.status_code == 201
    fid = upload.json()['id']
    cid = client.post('/api/hexa/conversations', json={}).json()['id']
    assert client.post(f'/api/hexa/conversations/{cid}/messages', headers={'Idempotency-Key': 'file-task'}, json={'text': 'read', 'file_ids': [fid]}).status_code == 202
    assert client.delete(f'/api/hexa/files/{fid}').status_code == 409
    assert client.delete('/api/hexa/files/99999').status_code == 404


def test_file_ids_cannot_be_injected_directly_to_gateway(client):
    login(client)
    cid = client.post('/api/hexa/conversations', json={}).json()['id']
    response = client.post(f'/api/hexa/conversations/{cid}/messages', headers={'Idempotency-Key': 'injection'}, json={'text': 'read', 'file_ids': [99999]})
    assert response.status_code == 404


def test_generated_file_download_is_proxied_as_attachment_without_executing_html(client, app):
    class OutputGateway:
        async def create_response(self, *args, **kwargs):
            return {'response_id': 'r1', 'text': 'done', 'status': 'completed', 'files': [{'file_id': 'out', 'container_id': 'session-1', 'filename': '<img onerror=alert(1)>.html', 'media_type': 'text/html'}]}
        async def file_content(self, container_id, file_id):
            assert (container_id, file_id) == ('session-1', 'out')
            return b'<script>alert(1)</script>'
    app.state.gateway = OutputGateway()
    login(client)
    cid = client.post('/api/hexa/conversations', json={}).json()['id']
    assert client.post(f'/api/hexa/conversations/{cid}/messages', headers={'Idempotency-Key': 'out'}, json={'text': 'generate'}).status_code == 202
    files = client.get(f'/api/hexa/conversations/{cid}/files').json()['files']
    assert len(files) == 1
    download = client.get(f"/api/hexa/files/{files[0]['id']}/content")
    assert download.status_code == 200
    assert download.headers['content-type'] == 'application/octet-stream'
    assert download.headers['content-disposition'].startswith('attachment;')
    assert download.headers['x-content-type-options'] == 'nosniff'
