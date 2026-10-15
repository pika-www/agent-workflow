from federation.memory_requirements import requirement_ledger, filter_summary
from federation.memory_read import memory_read_answer


def messages(*texts):
    return [{'id': str(i), 'role': 'user', 'content': text} for i, text in enumerate(texts)]


def fixture():
    return messages('岚桥项目预算上限23800元，交付日2026年12月2日；',
                    '南岬项目的预算是99000元，仅适用于南岬，与岚桥无关。',
                    '纠正：岚桥预算上限改为21700元，交付日改为2026年12月5日。')


def test_real_browser_fixture_does_not_supersede_other_project():
    ledger = requirement_ledger(fixture())
    assert not ledger['conflicts']
    assert {(r['subject'], r['value']) for r in ledger['active'] if r['slot']=='budget'} == {('岚桥','21700元'),('南岬','99000元')}
    old = next(r for r in ledger['records'] if r['value']=='23800元')
    assert old['status']=='superseded'


def test_unnamed_multi_project_correction_never_overwrites_both():
    data=fixture()+[{'id':'new','role':'user','content':'纠正：预算改为20300元。'}]
    ledger=requirement_ledger(data)
    assert {(r.get('subject'),r['value']) for r in ledger['active'] if r['slot']=='budget'} == {('岚桥','21700元'),('南岬','99000元')}
    assert any(r.get('reason')=='ambiguous_project_subject' for r in ledger['conflicts'])


def test_unnamed_single_project_correction_still_works():
    ledger=requirement_ledger(messages('岚桥项目预算是23800元。','纠正：预算改为20300元。'))
    assert [(r['subject'],r['value']) for r in ledger['active']] == [('岚桥','20300元')]


def test_summary_filter_keeps_other_project_and_removes_stale_value():
    ledger=requirement_ledger(fixture())
    summary={'constraints':[{'text':t} for t in ['岚桥项目预算是23800元。','岚桥项目预算是21700元。','南岬项目预算是99000元。']]}
    assert [r['text'] for r in filter_summary(summary,ledger)['constraints']]==['岚桥项目预算是21700元。','南岬项目预算是99000元。']


def test_resolution_only_changes_same_project_candidates():
    data=messages('岚桥项目预算是23800元。','南岬项目预算是99000元。','岚桥预算是21700元。','南岬预算是88000元。')
    initial=requirement_ledger(data)
    candidates=[r for r in initial['conflicts'] if r['subject']=='岚桥']
    selected=next(r for r in candidates if r['value']=='21700元')
    ledger=requirement_ledger(data,{'budget':[{'selected_id':selected['id'],'candidate_ids':[r['id'] for r in candidates]}]})
    assert [r['value'] for r in ledger['active']]==['21700元']
    assert {r['subject'] for r in ledger['conflicts']}=={'南岬'}


def test_assistant_cannot_invent_a_project_scope():
    data=messages('预算是23800元。','纠正：预算是20300元。')
    data.insert(1,{'id':'assistant','role':'assistant','content':'岚桥项目预算是23800元。'})
    assert all('subject' not in r for r in requirement_ledger(data)['records'])


def test_multi_project_read_defers_to_contextual_route():
    ledger=requirement_ledger(fixture())
    assert memory_read_answer('查看当前预算',{'requirement_state':ledger}) is None
