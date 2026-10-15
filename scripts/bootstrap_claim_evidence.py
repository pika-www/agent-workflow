"""Register existing, hash-pinned AI-product archives as pending claim evidence.

No Wiki/published page is rewritten and no semantic approval is manufactured.
Run with --apply only when annotation/import work has been authorized.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from federation.core import FederationStore
from federation.knowledge_evidence import register_document,add_claim,record_check,observe_document

SPACE='branch-c7a9d975cf3a'
CASES=[
 ('ai-interaction-correction.md','Microsoft HAX 第 9 条准则指出 AI 可能只部分正确，应让用户容易编辑、修正和恢复。',
  [('microsoft-hax','Sometimes AI systems will be only partially correct.')]),
 ('ai-workflow-scenario.md','文章提示 Agent 系统通常涉及延迟、成本和任务表现的取舍；其中具体工具生态已有更新说明。',
  [('anthropic-workflows','When building applications with LLMs, we recommend finding the simplest solution possible')]),
 ('ai-evaluation.md','文章建议早期从 20 至 50 个真实失败任务起步，并区分能力提升评估与回归评估。',
  [('anthropic-evals','We see teams delay building evals because they think they need hundreds of tasks.'),('anthropic-evals','**Regression evals** ask')]),
 ('github-copilot.md','GitHub Copilot cloud agent 可以研究仓库、生成计划、在分支上改代码，在临时开发环境中执行测试等操作；用户能够查看差异、迭代并创建 PR。',
  [('github-copilot','When you delegate tasks to Copilot cloud agent')]),
 ('khanmigo-learning.md','Khan Academy 介绍 Khanmigo 时强调通过问题引导学习者，并描述家教和教师助手的不同用途；文章也承认语言模型在数学上存在局限。',
  [('khanmigo-2023','It can guide students as they progress through courses'),('khanmigo-2023','To be clear, there is a long way to go.')]),
 ('metr-productivity.md','METR 于 2026 年 2 月说明，后续实验受到参与者选择、任务选择和计时等因素影响，不能可靠估计当前工具的生产力效果。',
  [('metr-2026','Given participant feedback and surveys')]),
]

def excerpt(text,needle):
    position=text.lower().find(needle.lower())
    if position<0:raise ValueError('原文中缺少预期片段：'+needle)
    start=text.rfind('\n\n',0,position)+2
    end=text.find('\n\n',position)
    if end<0:end=len(text)
    # Keep two paragraphs for definitions and caveats; still match actual bytes.
    next_end=text.find('\n\n',end+2)
    return text[start:next_end if next_end>=0 else end].strip()

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--apply',action='store_true');args=parser.parse_args()
    store=FederationStore(ROOT/'openwiki-federation',project_root=ROOT)
    archive=store._safe(store._home(SPACE),'evidence/20261005-first-batch')
    manifest=json.loads((archive/'manifest.json').read_text())
    sources={}
    for item in manifest:
        if item.get('status')!='read' or not item.get('text_path'):continue
        path=Path(item['text_path'])
        # Accept only the pre-existing branch archive, never an arbitrary path
        # suggested by a source document or prompt.
        if path.parent.resolve()!=archive.resolve() or path.is_symlink():raise ValueError('原文路径越过归档范围')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['text_sha256']:raise ValueError('已有原文与采集清单哈希不一致：'+item['id'])
        sources[item['id']]={**item,'text':raw.decode().strip()}
    report={'scope':'pending_annotations_only','wiki_rewritten':False,'semantic_approved':False,'documents':[],'claims':[]}
    # Validate every annotation before the first write, including changed pages.
    for filename,text,refs in CASES:
        if text not in store.page(SPACE,'topics/'+filename)['body']:
            raise ValueError('已有知识页内容变化，请人工重新标注：'+filename)
        if text not in store.page('central','ai-product-thinking/topics/'+filename)['body']:
            raise ValueError('中央页与结论不一致，请人工重新标注：'+filename)
        for identifier,needle in refs:excerpt(sources[identifier]['text'],needle)
    required=sorted({identifier for _,_,refs in CASES for identifier,_ in refs})
    for identifier in required:
        source=sources[identifier]
        doc=register_document(store,SPACE,source['title'],source['text'],source['url']) if args.apply else {'id':identifier}
        if args.apply:
            record_check(store,SPACE,doc['id'],doc['version'],observe_document(store,SPACE,doc['id'],doc['version']))
        report['documents'].append({'archive_id':identifier,'document_id':doc['id'],'original_archive_sha256':source['text_sha256'],'check_scope':'local_only'})
        source['document']=doc
    for filename,text,refs in CASES:
        page=store.page(SPACE,'topics/'+filename)
        if text not in page['body']:raise ValueError('已有知识页内容变化，请人工重新标注：'+filename)
        references=[]
        for identifier,needle in refs:
            source=sources[identifier];quote=excerpt(source['text'],needle)
            references.append({'document_id':source['document']['id'],'version':source['document'].get('version'),'quote':quote})
        claim=add_claim(store,SPACE,page['path'],page['sha256'],text,references) if args.apply else {'id':'dry-run'}
        report['claims'].append({'id':claim['id'],'path':page['path'],'semantic_review':'pending'})
    # Pin separate central annotations to the actual central page version. Do
    # not copy branch IDs or pretend a generated central page has identical bytes.
    central_docs={}
    for identifier in required:
        source=sources[identifier]
        doc=register_document(store,'central',source['title'],source['text'],source['url']) if args.apply else {'id':identifier}
        if args.apply:record_check(store,'central',doc['id'],doc['version'],observe_document(store,'central',doc['id'],doc['version']))
        central_docs[identifier]=doc
        report['documents'].append({'space':'central','archive_id':identifier,'document_id':doc['id'],'check_scope':'local_only'})
    for filename,text,refs in CASES:
        page=store.page('central','ai-product-thinking/topics/'+filename)
        references=[{'document_id':central_docs[identifier]['id'],'version':central_docs[identifier].get('version'),
                     'quote':excerpt(sources[identifier]['text'],needle)} for identifier,needle in refs]
        claim=add_claim(store,'central',page['path'],page['sha256'],text,references) if args.apply else {'id':'dry-run'}
        report['claims'].append({'id':claim['id'],'space':'central','path':page['path'],'semantic_review':'pending'})
    output=ROOT/'outputs/knowledge-evidence-20261006/bootstrap.json';output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,ensure_ascii=False,indent=2))
    print(json.dumps({'applied':args.apply,'documents':len(report['documents']),'claims':len(report['claims']),'report':str(output)},ensure_ascii=False))

if __name__=='__main__':main()
