"""Keep reference turns with their topic; the reply model interprets their meaning."""
import json
import re
from pathlib import Path

PATTERNS = {key: re.compile(value) for key, value in
            json.loads(Path(__file__).with_name('conversation-patterns.json').read_text()).items()}


def conversational_followup(question):
    text = re.sub(r'[\s，。！？!?,.]', '', str(question))
    return bool(len(text) < 150 and not PATTERNS['reset'].search(text) and not PATTERNS['standalone_temporal_public'].search(text) and
                (PATTERNS['followup'].search(text) or PATTERNS['rephrase'].search(text)))


def latest_dialogue(messages):
    """Bootstrap a legacy chat from its latest user topic, never an older match."""
    start = None
    for index in range(len(messages) - 1, -1, -1):
        message = messages[index]
        if message.get('role') != 'user':
            continue
        if message.get('phase') == 'confirmation' or message.get('content', '').startswith('/'):
            break
        start = index
        if not conversational_followup(message['content']):
            break
    return messages[start:] if start is not None else []
