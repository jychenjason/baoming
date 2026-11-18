import re

CSRF_PATTERN = re.compile(r'name="csrf_token"\s+value="([^"]+)"')


def extract_csrf(html: str) -> str:
    match = CSRF_PATTERN.search(html)
    if match is None:
        raise AssertionError("no csrf_token found in page")
    return match.group(1)
