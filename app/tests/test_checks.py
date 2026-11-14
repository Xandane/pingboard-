from pingboard.checks import check_url


def test_unresolvable_domain_is_down():
    # Домен в зоне .invalid гарантированно не резолвится (RFC 2606).
    result = check_url("http://pingboard-test.invalid", timeout=2)
    assert result["dns_ok"] is False
    assert result["up"] is False
    assert result["error"].startswith("dns:")
