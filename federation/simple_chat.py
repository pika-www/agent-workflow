"""Exact social exchanges only; mixed requests retain normal intake rules."""
import json
import re
from pathlib import Path

_PATTERNS = {kind: re.compile(pattern) for kind, pattern in
             json.loads(Path(__file__).with_name('simple-chat-patterns.json').read_text()).items()}

def simple_chat_kinds(question):
    if not isinstance(question, str) or not question.strip() or len(question) > 160 or '\0' in question:
        return None
    def match(text):
        compact = re.sub(r'[\s，。！？、,.!?~～；;：:]+', '', text).lower()
        return next((kind for kind, pattern in _PATTERNS.items() if pattern.fullmatch(compact)), None)
    direct = match(question)
    if direct:
        return None if direct == 'style' else [direct]
    parts = [part.strip() for part in re.split(r'[，。！？、,.!?~～；;：:\n]+', question) if part.strip()]
    if not 2 <= len(parts) <= 4:
        return None
    kinds = [kind for part in parts if (kind := match(part)) != 'style']
    if not kinds or any(kind in {None, 'nickname'} for kind in kinds):
        return None
    return kinds


def simple_chat_kind(question):
    kinds = simple_chat_kinds(question)
    if not kinds:
        return None
    selected = next(kind for kind in ('identity', 'nickname_recall', 'nickname', 'social', 'courtesy', 'greeting') if kind in kinds)
    return 'nickname' if selected == 'nickname_recall' else selected
