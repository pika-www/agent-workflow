import pytest

from federation.native_timeout import native_timeout_seconds


def test_default_and_cpu_server_budgets_are_separate():
    assert native_timeout_seconds(environment={}) == 600
    assert native_timeout_seconds(True, {}) == 1200
    env = {'WEIMING_CHAT_TIMEOUT_SECONDS': '1800', 'WEIMING_ANALYSIS_TIMEOUT_SECONDS': '2400'}
    assert native_timeout_seconds(environment=env) == 1800
    assert native_timeout_seconds(True, env) == 2400


def test_remote_short_chat_waits_without_expiring_but_reports_keep_their_budget():
    assert native_timeout_seconds(environment={}, wait_for_model=True) is None
    assert native_timeout_seconds(environment={'WEIMING_CHAT_TIMEOUT_SECONDS':'60'}, wait_for_model=True) is None
    assert native_timeout_seconds(True, {}, wait_for_model=True) == 1200


@pytest.mark.parametrize('value', ['forever', '0', '-1', '3601', '30.5'])
def test_unbounded_or_invalid_budget_is_rejected(value):
    with pytest.raises(ValueError):
        native_timeout_seconds(environment={'WEIMING_CHAT_TIMEOUT_SECONDS': value})
