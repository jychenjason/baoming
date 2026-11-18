def test_home_page_offers_entry_to_admin(client):
    response = client.get("/")

    assert response.status_code == 200
    assert "報名" in response.text
    assert 'href="/admin/login"' in response.text
