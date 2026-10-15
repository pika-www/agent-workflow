"""Explicit text-only scope shared with Node; never broadens tool authority."""
import json
from pathlib import Path
import re

PATTERNS = {k: re.compile(v) for k, v in json.loads(Path(__file__).with_name('dialogue-scope.json').read_text()).items()}


def text_only_discussion(question):
    text = re.sub(r'\s+', '', question)
    return bool(PATTERNS['text_only'].search(text) and not PATTERNS['follow_on_action'].search(text))


def conversation_only_scope(question):
    text = re.sub(r'\s+', '', question)
    if not (text_only_discussion(text) or PATTERNS['conversation_only'].search(text)): return False
    positive = PATTERNS['negative_operations'].sub('', text)
    return not (PATTERNS['external_operations'].search(positive) or PATTERNS['follow_on_action'].search(positive))


def bounded_dialogue(question):
    """Priority only for explicitly self-contained, short-form replies."""
    return bool(len(question) <= 240 and conversation_only_scope(question)
                and not re.search(r'本会话|会话(?:原始|历史|记录)|上下文|长期|记忆|之前|上次|前文|最早|归档|原始记录', question)
                and re.search(r'一句话|两句话|简短|只回答', question))
