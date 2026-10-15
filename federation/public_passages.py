"""Select literal passages locally; keep whole fetched pages in the archive."""
import math
import re

_STOP = {'the', 'and', 'with', 'from', 'for', 'that', 'this', 'what', 'how', 'please', 'official', 'docs', 'documentation', 'http', 'https', 'www', 'com'}


def relevant_excerpt(text, limit, question=''):
    if len(text) <= limit or not question:
        return text[:limit]
    terms = {s.lower()[:-1] if s.lower().endswith('s') and not s.lower().endswith('ss') and len(s)>3 else s.lower() for s in re.findall(r'[A-Za-z][A-Za-z0-9_+-]{2,}', question)
             if s.lower() not in _STOP}
    # Chinese page text also benefits, without translating or inventing facts.
    for word in re.findall(r'[\u4e00-\u9fff]{2,}', question):
        terms.update(word[i:i+2] for i in range(len(word)-1))
    terms = {s for s in terms if s not in {'查找', '说明', '官方', '文档', '句话', '两句', '请问', '告诉', '一下'}}
    if not terms:
        return text[:limit]
    blocks = [m.group(0) for m in re.finditer(r'[^\n]+(?:\n(?!\s*\n)[^\n]+)*', text)]
    hits = [{t for t in terms if (re.search(r'\b'+re.escape(t)+r's?\b', b, re.I) if t.isascii() else t in b)} for b in blocks]
    frequency = {t:sum(t in h for h in hits) for t in terms}
    if not any(hits):
        return text[:limit]
    selected = []; covered = set(); remaining = limit
    # Preserve page orientation while reserving most space for the question.
    if blocks and len(blocks[0]) < 240:
        selected.append((0, blocks[0])); remaining -= len(blocks[0])+2; covered.update(hits[0])
    candidates = {i for i,h in enumerate(hits) if h and i not in {s[0] for s in selected}}
    while candidates and remaining > 80:
        def score(i):
            value = sum((3 if t not in covered else 1)/math.sqrt(frequency[t]) for t in hits[i])
            # Navigation/link lists must not crowd out the explanatory prose.
            code_penalty = 0.15 if blocks[i].startswith('```') and not re.search(r'代码|示例|例子|语法|\b(?:code|example|syntax)\b', question, re.I) else 1
            return value * (0.2 if blocks[i].count('](')>3 else 1) * code_penalty, -i
        index = max(candidates, key=score); candidates.remove(index)
        piece = blocks[index][:min(remaining, max(700, limit//3))]
        selected.append((index,piece)); covered.update(hits[index]); remaining -= len(piece)+2
    return '\n\n'.join(piece for _,piece in sorted(selected))[:limit]
