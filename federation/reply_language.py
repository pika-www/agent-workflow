"""Shared with the JavaScript generation and answer-repair paths."""
import json
from pathlib import Path

REPLY_LANGUAGE_POLICY = json.loads(Path(__file__).with_name('reply-language.json').read_text())['reply']
