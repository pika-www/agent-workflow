"""Operator-controlled, bounded native model execution time."""
import os


def native_timeout_seconds(analysis=False, environment=None, *, wait_for_model=False):
    # The host only opts tool-free remote greetings into user-controlled waiting.
    if wait_for_model and not analysis:
        return None
    environment = os.environ if environment is None else environment
    key = 'WEIMING_ANALYSIS_TIMEOUT_SECONDS' if analysis else 'WEIMING_CHAT_TIMEOUT_SECONDS'
    default = 1200 if analysis else 600
    value = environment.get(key)
    if value is None:
        return default
    try:
        seconds = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(key + ' must be an integer between 60 and 3600') from exc
    if not 60 <= seconds <= 3600:
        raise ValueError(key + ' must be between 60 and 3600')
    return seconds
