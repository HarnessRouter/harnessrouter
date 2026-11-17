from app.db.models import AuthSession


def test_login_sets_httponly_cookie_and_session_stores_only_hash(client, app):
    response = client.post("/api/hexa/auth/login", json={"username": "admin", "password": "correct-password"})

    assert response.status_code == 200
    assert response.json() == {"authenticated": True, "username": "admin"}
    cookie = response.cookies.get("hexa_session")
    assert cookie
    set_cookie = response.headers["set-cookie"].lower()
    assert "httponly" in set_cookie
    assert "samesite=lax" in set_cookie
    assert "server-only-gateway-key" not in response.text

    with app.state.session_factory() as session:
        record = session.query(AuthSession).one()
        assert record.token_hash != cookie
        assert len(record.token_hash) == 64
        from app.auth.service import _token_hash
        assert record.token_hash == _token_hash(cookie, app.state.settings.session_secret)
        assert record.token_hash not in response.text


def test_invalid_login_and_missing_session_are_rejected(client):
    wrong = client.post("/api/hexa/auth/login", json={"username": "admin", "password": "wrong"})
    missing = client.get("/api/hexa/auth/session")

    assert wrong.status_code == 401
    assert missing.status_code == 401
    assert "server-only-gateway-key" not in wrong.text


def test_authenticated_session_can_be_read_and_logout_revokes_cookie(client):
    login = client.post("/api/hexa/auth/login", json={"username": "admin", "password": "correct-password"})
    assert login.status_code == 200

    current = client.get("/api/hexa/auth/session")
    assert current.status_code == 200
    assert current.json() == {"authenticated": True, "username": "admin"}

    logout = client.post("/api/hexa/auth/logout")
    assert logout.status_code == 200
    assert client.get("/api/hexa/auth/session").status_code == 401


def test_cross_origin_mutations_and_validation_errors_do_not_expose_secrets(client):
    response = client.post('/api/hexa/auth/login', headers={'origin': 'https://attacker.test'}, json={'username': 'admin', 'password': 'correct-password'})
    assert response.status_code == 403
    malformed = client.post('/api/hexa/auth/login', json={'password': 'private-password'})
    assert malformed.status_code == 422
    assert 'private-password' not in malformed.text


def test_expired_forged_and_revoked_session_are_denied(client, app):
    from datetime import datetime, timedelta, timezone
    client.cookies.set('hexa_session', 'forged')
    assert client.get('/api/hexa/auth/session').status_code == 401
    client.cookies.clear()
    client.post('/api/hexa/auth/login', json={'username': 'admin', 'password': 'correct-password'})
    with app.state.session_factory() as db:
        record = db.query(AuthSession).one()
        record.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        db.commit()
    assert client.get('/api/hexa/auth/session').status_code == 401
