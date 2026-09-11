"""Origin matching for the public chat endpoint.

CORS is a browser rule, not authentication: anything outside a browser can send
whatever Origin it likes. This is here to stop *someone else's page* from using a
bot's quota, not to keep determined callers out.
"""
import pytest

from graft.security.origins import normalize_origin, origin_allowed


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("https://example.test", "https://example.test"),
        ("https://Example.TEST", "https://example.test"),
        ("https://example.test/", "https://example.test"),
        ("http://localhost:3000", "http://localhost:3000"),
        ("https://example.test:443", "https://example.test"),
        ("http://example.test:80", "http://example.test"),
        ("https://example.test:8443", "https://example.test:8443"),
    ],
)
def test_normalize_keeps_scheme_host_and_meaningful_port(raw, expected):
    assert normalize_origin(raw) == expected


@pytest.mark.parametrize("raw", [None, "", "null", "  ", "example.test", "/path", "*"])
def test_unusable_origins_normalize_to_none(raw):
    assert normalize_origin(raw) is None


def test_an_exact_origin_matches():
    assert origin_allowed("https://example.test", ["https://example.test"])


def test_matching_is_case_insensitive_on_the_host_only():
    assert origin_allowed("HTTPS://Example.test", ["https://example.test"])


@pytest.mark.parametrize(
    "origin",
    [
        "http://example.test",          # scheme differs
        "https://sub.example.test",     # host differs
        "https://example.test:8443",    # port differs
        "https://example.test.evil.com",
    ],
)
def test_a_near_miss_is_not_a_match(origin):
    assert not origin_allowed(origin, ["https://example.test"])


@pytest.mark.parametrize("origin", [None, "", "null"])
def test_a_missing_or_opaque_origin_is_refused(origin):
    # A sandboxed iframe sends Origin: null. There is no bot that can be.
    assert not origin_allowed(origin, ["https://example.test"])


def test_a_wildcard_in_the_allowlist_is_not_honoured():
    # Never a wildcard: a bot's documents and its quota are not public goods.
    assert not origin_allowed("https://anything.test", ["*"])


def test_an_empty_allowlist_allows_nothing():
    assert not origin_allowed("https://example.test", [])


def test_the_allowlist_is_normalized_too():
    assert origin_allowed("https://example.test", ["HTTPS://Example.test/"])
