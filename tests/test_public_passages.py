from federation.public_passages import relevant_excerpt


def test_late_relevant_passages_survive_without_inventing_text():
    intro = '# Technical manual'
    paragraphs = [intro] + ['Unrelated installation notes. '*50 for _ in range(15)]
    paragraphs += ['Lists are mutable sequences and support item replacement.',
                   'Tuples are immutable sequences; individual items cannot be reassigned.']
    text = '\n\n'.join(paragraphs)
    excerpt = relevant_excerpt(text, 1000, '解释 list 和 tuple 的区别')
    assert len(excerpt) <= 1000
    assert 'Lists are mutable' in excerpt and 'Tuples are immutable' in excerpt
    assert all(piece in text for piece in excerpt.split('\n\n'))
    assert text.startswith(intro)


def test_unrelated_query_and_short_documents_keep_existing_behavior():
    text = '原始网页正文。'*1000
    assert relevant_excerpt(text, 300, '') == text[:300]
    assert relevant_excerpt(text, 300, 'different keyword') == text[:300]
    assert relevant_excerpt('短正文', 100, '文档') == '短正文'


def test_concept_explanation_prefers_prose_over_long_code():
    text = '# Guide\n\n' + '\n\n'.join('```\nlist(tuple(values))\n```' for _ in range(50))
    text += '\n\nLists are mutable sequences.\n\nTuples are immutable sequences.'
    excerpt = relevant_excerpt(text, 300, '说明 list 和 tuple 的区别')
    assert 'Lists are mutable' in excerpt and 'Tuples are immutable' in excerpt
