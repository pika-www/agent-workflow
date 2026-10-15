import pytest
from federation.vector_index import VectorIndex, LocalEmbedder, load_documents, expand_query


def test_recovery_concepts_do_not_change_unrelated_memory_or_negative_queries():
    assert '备份' in expand_query('历史资料丢了，怎样找回旧版本？')
    for q in ['早先说的话还能找回来吗？','买完不想要了，钱怎么拿回来？','明天会下雨吗？']:
        assert expand_query(q)==q


def embedding(texts):
    # Controlled vectors test ranking/storage, not real semantic model quality.
    return [[1,0] if 'refund' in t or '退款' in t else [0,1] for t in texts]


def test_persistent_scope_versions_deletion_and_model_change(tmp_path):
    path=tmp_path/'vectors.sqlite3'
    index=VectorIndex(path,embedding,'fixture-v1')
    docs={'/a.md':'退款规则','/b.md':'机器维护'}
    assert index.update('a',docs)==2
    assert index.update('a',docs)==0
    index.update('b',{'/secret.md':'退款秘密'})
    assert [m['path'] for m in index.search('a',docs,'refund')['matches']]==['/a.md']
    assert index.search('a',{'/a.md':'已改为机器维护'},'refund')['matches']==[]
    assert index.search('a',{},'refund')['matches']==[]
    index.close()
    reopened=VectorIndex(path,embedding,'fixture-v1')
    assert reopened.search('a',docs,'refund')['complete']
    reopened.close()
    changed=VectorIndex(path,embedding,'fixture-v2')
    assert changed.search('a',docs,'refund')['matches']==[]
    changed.close()


def test_rejects_invalid_vectors_and_external_endpoint(tmp_path):
    with pytest.raises(ValueError):LocalEmbedder({'url':'https://example.com','model':'x','digest':'x'})
    index=VectorIndex(tmp_path/'v.sqlite',lambda _: [[float('nan')]],'bad')
    with pytest.raises(ValueError):index.update('a',{'/a.md':'a'})
    index.close()


def test_source_scan_skips_symlinks_and_task_artifacts(tmp_path):
    (tmp_path/'ok.md').write_text('ok')
    (tmp_path/'link.md').symlink_to(tmp_path/'ok.md')
    (tmp_path/'_delegation_results').mkdir()
    (tmp_path/'_delegation_results/a.md').write_text('task data')
    assert load_documents(tmp_path)=={'/ok.md':'ok'}
