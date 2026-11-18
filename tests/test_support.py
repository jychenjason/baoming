import pytest

from tests.support import extract_csrf


def test_extracts_csrf_token_from_hidden_input():
    html = '<form><input type="hidden" name="csrf_token" value="abc123"></form>'

    assert extract_csrf(html) == "abc123"


def test_raises_when_csrf_token_is_missing():
    with pytest.raises(AssertionError):
        extract_csrf("<form></form>")
