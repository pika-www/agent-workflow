"""Golden user utterances shared with the actual Node parser."""
import json
import subprocess
import pytest
from federation.memory_requirements import claims, requirement_ledger, filter_summary, summary_grounding_error

CASES=[
 ('预算为500元。', [('budget','500元')]),
 ('预算上限改为17200元。', [('budget','17200元')]),
 ('交付日2026年11月7日。', [('deadline','2026-11-07')]),
 ('交付日改为2026年11月9日。', [('deadline','2026-11-09')]),
 ('预算从500元改到300元。',[('budget','300元')]),
 ('预算不超过300美元。',[('budget','300美元')]),
 ('预算为500,000元。',[('budget','500,000元')]),
 ('预算为300万元。',[]),
 ('预算为500元/月。',[('budget','500元/月')]),
 ('截止日期为2026-10-250。',[]),
 ('目标平台为AndroidX。',[]),
 ('交付格式为HTML5。',[]),
 ('截止日期改为2026年10月20日。',[('deadline','2026-10-20')]),
 ('截止日期：2026/2/29。',[]),
 ('截止日期：2028/2/29。',[('deadline','2028-02-29')]),
 ('只做 Android，iOS 暂缓。',[('platform','android')]),
 ('目标平台：iOS和Android。',[('platform','android/ios')]),
 ('交付格式改为PDF和Markdown。',[('deliverable','markdown/pdf')]),
 ('目标版本：Vue 3.5。',[('version','vue 3.5')]),
 ('验收标准改为首字在500毫秒内出现。',[('acceptance','首字在500毫秒内出现')]),
 ('预算改为300元好吗？',[]),('如果预算为300元。',[]),
 ('不要使用Vue，不要清空历史，不再保留历史。',[]),
 ('不能删除历史，不联网。',[('history','preserve'),('network','local_only')]),
 ('不得联网。',[('network','local_only')]),
 ('不是使用Vue，而是使用React。',[('framework','react')]),
 ('预算为500元。交付格式为PDF。',[('budget','500元'),('deliverable','pdf')]),
]

@pytest.mark.parametrize('text,expected',CASES)
def test_golden_utterance(text,expected):
 assert sorted((slot,value) for slot,value,_ in claims(text))==sorted(expected)

def test_python_node_rule_parity():
 source="import {requirementClaims} from './federation/requirement-claims.mjs';let raw='';for await(const c of process.stdin)raw+=c;console.log(JSON.stringify(JSON.parse(raw).map(requirementClaims)));"
 result=subprocess.run(['node','--input-type=module','-e',source],input=json.dumps([c[0] for c in CASES]),text=True,capture_output=True,check=True)
 assert json.loads(result.stdout)==[[list(c) for c in claims(text)] for text,_ in CASES]

def test_correction_conflict_and_stale_summary():
 messages=[{'id':'a','role':'user','content':'预算为500元。交付格式为PDF。'}, {'id':'b','role':'user','content':'预算改为300元。交付格式改为Markdown。'}]
 state=requirement_ledger(messages)
 assert {(r['slot'],r['value']) for r in state['active']}=={('budget','300元'),('deliverable','markdown')}
 old={'constraints':[{'text':'预算为500元。','source_ids':['a']}],'decisions':[]}
 assert not filter_summary(old,state)['constraints']
 assert summary_grounding_error({'constraints':[{'text':'预算为200元。','source_ids':['b']}],'decisions':[],'progress':[],'open_questions':[]},{},messages)=='unsupported_requirement'
 state=requirement_ledger(messages+[{'id':'c','role':'user','content':'预算为200元。'}])
 assert {r['value'] for r in state['conflicts']}=={'300元','200元'}


def test_change_of_budget_cannot_silently_resolve_framework_conflict():
 state=requirement_ledger([{'id':'a','role':'user','content':'使用Vue。预算为500元。'}, {'id':'b','role':'user','content':'使用React，预算改为300元。'}])
 assert {r['value'] for r in state['conflicts']}=={'vue','react'}
 assert {(r['slot'],r['value']) for r in state['active']}=={('budget','300元')}
 assert [(s,v) for s,v,_ in claims('使用Vue，改用React。')]==[('framework','react')]


def test_long_dialogue_budget_and_delivery_correction():
 messages=[{'id':'old','role':'user','content':'预算上限18500元，交付日2026年11月7日，禁止上传到云端；验收口令是竹影-47。'},
           {'id':'new','role':'user','content':'纠正旧要求：预算上限改为17200元，交付日改为2026年11月9日；禁止上传到云端仍然有效，验收口令竹影-47不变。18500元和11月7日已经作废。'}]
 state=requirement_ledger(messages)
 assert {(r['slot'],r['value']) for r in state['active']}=={('budget','17200元'),('deadline','2026-11-09')}
 assert not state['conflicts']
 assert all(r['status']=='superseded' for r in state['records'] if r['source_ids']==['old'])
