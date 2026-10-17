"""health_check 的告警去重测试。"""
import health_check


def test_same_unresolved_problem_is_not_repeated():
    problems = [("job:logs/options_whitelist.log", "whitelist stale")]

    assert health_check._new_problem_messages(problems, set()) == ["whitelist stale"]
    assert health_check._new_problem_messages(
        problems, {"job:logs/options_whitelist.log"}
    ) == []


def test_new_problem_is_alerted_while_existing_one_stays_quiet():
    problems = [
        ("job:logs/options_whitelist.log", "whitelist stale"),
        ("disk:system", "disk low"),
    ]

    assert health_check._new_problem_messages(
        problems, {"job:logs/options_whitelist.log"}
    ) == ["disk low"]


def test_whitelist_health_check_requires_a_success_heartbeat():
    watched = {path for path, _, _ in health_check.WATCHED}

    assert "logs/.options_whitelist_heartbeat" in watched
    assert "logs/options_whitelist.log" not in watched
