import re

CSRF_PATTERN = re.compile(r'name="csrf_token"\s+value="([^"]+)"')

ADMIN_PASSWORD = "admin-test-password"


def extract_csrf(html: str) -> str:
    match = CSRF_PATTERN.search(html)
    if match is None:
        raise AssertionError("no csrf_token found in page")
    return match.group(1)


def csrf_from(client, path: str) -> str:
    response = client.get(path)
    assert response.status_code == 200
    return extract_csrf(response.text)


def submit_login(client, password, csrf=None, follow_redirects=False):
    csrf = csrf or csrf_from(client, "/admin/login")
    return client.post(
        "/admin/login",
        data={"password": password, "csrf_token": csrf},
        follow_redirects=follow_redirects,
    )


def sign_in(client):
    response = submit_login(client, ADMIN_PASSWORD)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/events"
    return response
