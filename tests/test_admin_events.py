import re

from tests.support import csrf_from, sign_in

TOKEN_PATTERN = re.compile(r"/e/([A-Z0-9]{10})\b")
EVENT_ID_PATTERN = re.compile(r'href="/admin/events/(\d+)"')


def create_event(client, **fields):
    data = {
        "csrf_token": csrf_from(client, "/admin/events/new"),
        "title": "年終聚餐",
        "description": "一起吃頓飯。",
        "location": "台北市大安區",
        "starts_at": "2026-12-31T18:30",
        "registration_deadline_at": "2026-12-24T23:59",
    }
    data.update(fields)
    return client.post("/admin/events/new", data=data, follow_redirects=False)


def only_event_id(html):
    match = EVENT_ID_PATTERN.search(html)
    assert match is not None
    return int(match.group(1))


def only_event_token(html):
    match = TOKEN_PATTERN.search(html)
    assert match is not None
    return match.group(1)


def test_creating_an_event_lists_it_with_status_and_public_link(client):
    sign_in(client)

    response = create_event(client)
    assert response.status_code == 303
    assert response.headers["location"] == "/admin/events"

    page = client.get("/admin/events")
    text = page.text

    assert "年終聚餐" in text
    assert "草稿" in text
    assert "報名數：0" in text
    assert "2026-12-24 23:59" in text

    token = only_event_token(text)
    assert len(token) == 10
    assert not (set(token) & set("01OI"))
    assert f"/e/{token}" in text
    assert 'readonly' in text


def test_created_event_details_show_fixed_attendance_group(client):
    sign_in(client)
    create_event(client)
    event_id = only_event_id(client.get("/admin/events").text)

    detail = client.get(f"/admin/events/{event_id}")

    assert detail.status_code == 200
    assert "年終聚餐" in detail.text
    assert "是否出席" in detail.text
    assert "出席" in detail.text
    assert "不出席" in detail.text


def test_public_link_for_a_draft_says_the_event_is_not_open_yet(client):
    sign_in(client)
    create_event(client)
    token = only_event_token(client.get("/admin/events").text)

    response = client.get(f"/e/{token}")

    assert response.status_code == 200
    assert "活動尚未開放" in response.text
    assert "年終聚餐" in response.text


def test_unknown_event_token_returns_404(client):
    response = client.get("/e/ABCDEFGHJK")

    assert response.status_code == 404
    assert "找不到活動" in response.text


def test_empty_title_is_an_error_and_keeps_other_input(client):
    sign_in(client)

    response = create_event(client, title="")

    assert response.status_code == 200
    assert "請輸入活動標題" in response.text
    assert "一起吃頓飯。" in response.text
    assert 'value="台北市大安區"' in response.text
    assert 'value="2026-12-31T18:30"' in response.text


def test_event_fields_are_validated_against_the_spec_limits(client):
    sign_in(client)

    assert "100" in create_event(client, title="長" * 101).text
    assert "2000" in create_event(client, description="字" * 2001).text
    assert "200" in create_event(client, location="址" * 201).text


def test_malformed_times_are_rejected_and_kept_for_editing(client):
    sign_in(client)

    response = create_event(client, starts_at="下週三晚上")

    assert response.status_code == 200
    assert "活動時間格式不正確" in response.text
    assert 'value="下週三晚上"' in response.text


def test_regenerating_the_token_invalidates_the_old_link(client):
    sign_in(client)
    create_event(client)
    list_text = client.get("/admin/events").text
    old_token = only_event_token(list_text)
    event_id = only_event_id(list_text)

    response = client.post(
        f"/admin/events/{event_id}/rotate-token",
        data={"csrf_token": csrf_from(client, "/admin/events")},
        follow_redirects=False,
    )

    assert response.status_code == 303
    new_token = only_event_token(client.get("/admin/events").text)
    assert new_token != old_token
    assert client.get(f"/e/{old_token}").status_code == 404
    assert client.get(f"/e/{new_token}").status_code == 200


def test_rotating_a_token_requires_csrf(client):
    sign_in(client)
    create_event(client)
    event_id = only_event_id(client.get("/admin/events").text)

    response = client.post(f"/admin/events/{event_id}/rotate-token")

    assert response.status_code == 400


def test_admin_event_pages_carry_csrf_tokens(client):
    sign_in(client)

    for path in ("/admin/events", "/admin/events/new"):
        assert 'name="csrf_token"' in client.get(path).text


def test_creating_an_event_without_csrf_is_rejected(client):
    sign_in(client)

    response = client.post(
        "/admin/events/new",
        data={"title": "年終聚餐"},
        follow_redirects=False,
    )

    assert response.status_code == 400
    assert client.get("/admin/events").text.count("/e/") == 0


def test_title_at_the_length_limit_is_accepted(client):
    sign_in(client)

    response = create_event(client, title="長" * 100)

    assert response.status_code == 303


def test_event_text_is_escaped_in_admin_and_public_pages(client):
    sign_in(client)
    create_event(client, title="<script>alert(1)</script>")

    token = only_event_token(client.get("/admin/events").text)
    for html in (client.get("/admin/events").text, client.get(f"/e/{token}").text):
        assert "<script>alert(1)</script>" not in html
        assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html


def test_optional_times_may_be_left_empty(client):
    sign_in(client)

    response = create_event(client, starts_at="", registration_deadline_at="")

    assert response.status_code == 303
    assert "報名截止：—" in client.get("/admin/events").text
