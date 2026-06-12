from app.core.rate_limit import check_rate_limit, reset_rate_limits


def test_allows_up_to_max_requests():
    reset_rate_limits()
    assert all(check_rate_limit("k", 3, 60) for _ in range(3))
    assert check_rate_limit("k", 3, 60) is False


def test_keys_are_independent():
    reset_rate_limits()
    assert check_rate_limit("a", 1, 60) is True
    assert check_rate_limit("b", 1, 60) is True
    assert check_rate_limit("a", 1, 60) is False


def test_window_expires(monkeypatch):
    reset_rate_limits()
    import app.core.rate_limit as rl

    now = [1000.0]
    monkeypatch.setattr(rl.time, "monotonic", lambda: now[0])
    assert check_rate_limit("k", 1, 10) is True
    assert check_rate_limit("k", 1, 10) is False
    now[0] += 11
    assert check_rate_limit("k", 1, 10) is True
