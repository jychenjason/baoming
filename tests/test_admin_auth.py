from datetime import datetime, timedelta, timezone

from tests.support import ADMIN_PASSWORD, csrf_from, sign_in, submit_login


def test_login_form_asks_for_password(client):
    response = client.get("/admin/login")

    assert response.status_code == 200
    assert 'name="password"' in response.text
    assert 'name="csrf_token"' in response.text


def test_admin_can_sign_in_with_configured_password(client):
    response = sign_in(client)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/events"
    assert client.get("/admin/events").status_code == 200


def test_wrong_password_shows_error_without_granting_access(client):
    response = submit_login(client, "wrong-password")

    assert response.status_code == 401
    assert "密碼錯誤" in response.text
    assert "wrong-password" not in response.text
    assert client.get("/admin/events", follow_redirects=False).status_code == 303


def test_login_without_csrf_token_is_rejected(client):
    response = client.post("/admin/login", data={"password": ADMIN_PASSWORD})

    assert response.status_code == 400
    assert client.get("/admin/events", follow_redirects=False).status_code == 303


def test_admin_routes_redirect_to_login_when_signed_out(client):
    response = client.get("/admin/events", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_every_admin_post_requires_signing_in(client):
    response = client.post("/admin/events/new", follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"


def test_logout_requires_signing_in_again(client):
    sign_in(client)
    csrf = csrf_from(client, "/admin/events")

    response = client.post(
        "/admin/logout", data={"csrf_token": csrf}, follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/admin/login"
    assert client.get("/admin/events", follow_redirects=False).status_code == 303


def test_admin_session_expires_after_twelve_hours(app, client):
    start = datetime(2026, 1, 1, 9, 0, tzinfo=timezone.utc)
    app.state.clock = lambda: start
    sign_in(client)

    app.state.clock = lambda: start + timedelta(hours=11, minutes=59)
    assert client.get("/admin/events", follow_redirects=False).status_code == 200

    app.state.clock = lambda: start + timedelta(hours=12, minutes=1)
    assert client.get("/admin/events", follow_redirects=False).status_code == 303


def test_login_failures_from_one_address_are_rate_limited(client):
    csrf = csrf_from(client, "/admin/login")
    data = {"password": "wrong-password", "csrf_token": csrf}

    for _ in range(5):
        assert client.post("/admin/login", data=data).status_code == 401

    response = client.post("/admin/login", data=data)

    assert response.status_code == 429
    assert "請求過於頻繁" in response.text


def test_spoofed_forwarded_for_header_does_not_reset_the_login_limit(client):
    csrf = csrf_from(client, "/admin/login")
    data = {"password": "wrong-password", "csrf_token": csrf}

    for index in range(5):
        client.post(
            "/admin/login", data=data, headers={"X-Forwarded-For": f"10.0.0.{index}"}
        )

    response = client.post(
        "/admin/login", data=data, headers={"X-Forwarded-For": "10.0.0.99"}
    )

    assert response.status_code == 429


def test_session_cookie_is_httponly_and_samesite_lax(client):
    response = client.get("/admin/login")
    cookies = response.headers.get_list("set-cookie")

    assert cookies
    assert "HttpOnly" in cookies[0]
    assert "samesite=lax" in cookies[0].lower()
    assert "; secure" not in cookies[0].lower()


def test_session_cookie_is_secure_when_the_request_uses_https(client):
    response = client.get("https://testserver/admin/login")
    cookies = response.headers.get_list("set-cookie")

    assert cookies
    assert "Secure" in cookies[0]
