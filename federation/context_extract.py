"""Literal relevance excerpts. Original messages remain the source of truth."""
import re
import json
import math
from pathlib import Path

MARKER = '\n[上下文摘录；省略部分保留在原记录]\n'
IMPORTANT = re.compile(r'必须|不能|不要|保留|更正|改为|取消|预算|截止|失败|风险|证据|https?://|\d+(?:\.\d+)?[%元天秒]')
ALIASES=json.loads(Path(__file__).with_name('memory-aliases.json').read_text())


def query_terms(question):
    words = set(re.findall(r'[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}', question.lower()))
    terms={part for word in words for part in ([word] if word.isascii() else [word[i:i+2] for i in range(len(word)-1)])} - {'什么','怎么','如何','现在','之前','我们','这个','项目','一下','的是','是否','需要','前的','要求'}
    for key,aliases in ALIASES.items():
        if any(alias.lower() in question.lower() for alias in aliases):terms.add('alias-'+key)
    return terms


def relevance_score(text, question):
    return len(query_terms(text)&query_terms(question))


def rank_originals(messages,question,k=3):
    """A lengthy assistant answer is not evidence of the user's requirements."""
    user_requirements=bool(re.search(r'之前.*(?:要求|首版)|(?:我的|用户).*(?:要求|偏好|约定)|教学要求|偏好|约定',question))
    ranked=[]
    for position,message in enumerate(messages):
        if user_requirements and message['role']!='user':continue
        score=relevance_score(message['content'],question)
        if score<2:continue
        score=score/(1+math.log1p(len(message['content'])/400))
        if message['role']=='user':score*=1.25
        ranked.append((score,position,message['id']))
    ranked.sort(reverse=True)
    # A compound question must not spend every slot on the dominant project.
    # These anchors are explicit user requirements, not assistant summaries.
    from .memory_requirements import requirement_ledger
    ledger = requirement_ledger(messages)
    anchor_ids = {source for item in ledger['active']
                  if item.get('subject') and item['subject'] in question
                  for source in item['source_ids']}
    anchors = [row for row in ranked if row[2] in anchor_ids]
    selected = anchors[:k]
    selected_ids = {row[2] for row in selected}
    for row in ranked:
        if len(selected) == k: break
        if row[2] not in selected_ids and row[0]>=ranked[0][0]*.6:
            selected.append(row);selected_ids.add(row[2])
    # Do not fill K with weak matches just because slots are available.
    return selected


def literal_excerpt(text, limit, question=''):
    if len(text) <= limit:
        return text
    # Sentence/chunk boundaries include middle constraints, not just the ends.
    blocks = [(m.start(), m.group()) for m in re.finditer(r'[^\n。！？]{1,240}[\n。！？]?', text)]
    ranked = sorted(blocks, key=lambda p: (-(relevance_score(p[1],question)*4 + bool(IMPORTANT.search(p[1]))*2), p[0]))
    selected = []
    remaining = max(0, limit-len(MARKER)*2)
    for start, block in ranked:
        if remaining < 16 or len(selected) == 3:
            break
        piece = block[:remaining]
        selected.append((start,piece))
        remaining -= len(piece)
    return MARKER.join(piece for _,piece in sorted(selected))


def is_literal_projection(before, after):
    pieces = after.split(MARKER)
    if not pieces or any(not piece for piece in pieces):
        return False
    cursor = 0
    for piece in pieces:
        at = before.find(piece,cursor)
        if at < 0:
            return False
        cursor = at+len(piece)
    return True
