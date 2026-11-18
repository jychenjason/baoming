import io
import json
import logging

from app.logging import JsonFormatter


def test_request_log_is_structured_json_without_client_ip(client):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())
    logger = logging.getLogger("app")
    logger.addHandler(handler)
    try:
        response = client.get("/")
    finally:
        logger.removeHandler(handler)

    payloads = [
        json.loads(line) for line in stream.getvalue().splitlines() if line.strip()
    ]
    request_logs = [item for item in payloads if item.get("event") == "request"]

    assert len(request_logs) == 1
    payload = request_logs[0]
    assert payload["method"] == "GET"
    assert payload["path"] == "/"
    assert payload["status"] == response.status_code
    assert payload["duration_ms"] >= 0
    assert "client_ip" not in payload
