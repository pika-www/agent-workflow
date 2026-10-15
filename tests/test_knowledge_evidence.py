"""Evidence lifecycle with actual scoped files; HTTP/model remain controlled."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient
from federation.app import create_app
from federation.knowledge import knowledge_health
from federation.knowledge_evidence import (register_document, document_text, add_claim, claim_snapshot,
    review_claim, observe_document, record_check, evidence_overview, adopt_observation, save_revision, supersede_claim)


class EvidenceTest(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.app=create_app(base=Path(self.tmp.name)/'data')
        self.store=self.app.state.store
        self.app.state.hotspots.fetcher=lambda source: []
        self.client_context=TestClient(self.app)
        self.client=self.client_context.__enter__()
        self.space='software-frontend'
        self.page=self.store._wiki(self.space)/'guide.md'
        self.page.write_text('# 纠错\n允许编辑和撤销。\n这是整理者的推断。\n')
        self.source='Make it easy to edit, refine, or recover when the AI system is wrong.\n'

    def tearDown(self):
        self.client_context.__exit__(None,None,None)
        self.tmp.cleanup()

    def setup_claim(self,kind='fact'):
        doc=register_document(self.store,self.space,'原文',self.source,'https://example.org/correction')
        page=self.store.page(self.space,'guide.md')
        claim=add_claim(self.store,self.space,'guide.md',page['sha256'],'允许编辑和撤销。',
          [{'document_id':doc['id'],'version':doc['version'],'quote':'edit, refine, or recover'}],kind)
        return doc,claim

    def test_read_only_empty_snapshot_does_not_create_evidence_records(self):
        result=self.client.get('/api/spaces/'+self.space+'/evidence')
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['summary']['claims'],0)
        self.assertFalse((self.store.base/'metadata/claim-evidence').exists())

    def test_exact_match_is_pending_not_semantic_approval(self):
        before=self.page.read_bytes();doc,claim=self.setup_claim()
        self.assertEqual(claim['semantic_review'],'pending')
        self.assertEqual(claim['references'][0]['start_line'],1)
        self.assertEqual(self.page.read_bytes(),before)
        view=claim_snapshot(self.store,self.space)[0]
        self.assertEqual(view['status'],'review_due')
        self.assertEqual(view['references'][0]['freshness'],'unknown')
        self.assertEqual(document_text(self.store,self.space,doc['id'])['text'],self.source)
        self.assertEqual(knowledge_health(self.store,self.space)['pages'][0]['claims'][0]['id'],claim['id'])

    def test_fabricated_quote_claim_and_cross_space_references_are_rejected(self):
        doc,claim=self.setup_claim();page=self.store.page(self.space,'guide.md')
        for text,refs in [('不在知识页里',[{'document_id':doc['id'],'version':doc['version'],'quote':'edit'}]),
                          ('允许编辑和撤销。',[{'document_id':doc['id'],'version':doc['version'],'quote':'invented evidence'}])]:
            with self.assertRaises(ValueError):add_claim(self.store,self.space,'guide.md',page['sha256'],text,refs)
        other=register_document(self.store,'software-app','别库','别库原文')
        with self.assertRaises(ValueError):add_claim(self.store,self.space,'guide.md',page['sha256'],'允许编辑和撤销。',[{'document_id':other['id'],'version':other['version'],'quote':'别库'}])
        self.assertEqual(len(claim_snapshot(self.store,self.space)),1)

    def test_expected_versions_and_inference_kind_survive_review(self):
        doc,claim=self.setup_claim('inference')
        with self.assertRaises(ValueError):add_claim(self.store,self.space,'guide.md','0'*64,'允许编辑和撤销。',claim['references'])
        view=claim_snapshot(self.store,self.space)[0]
        review_claim(self.store,self.space,claim['id'],view['review_token'],'approved')
        updated=claim_snapshot(self.store,self.space)[0]
        self.assertEqual(updated['semantic_review'],'approved')
        self.assertEqual(updated['kind'],'inference')
        self.assertEqual(updated['status'],'review_due')

    def test_local_check_never_claims_online_freshness(self):
        doc,_=self.setup_claim()
        observation=observe_document(self.store,self.space,doc['id'],doc['version'])
        result=record_check(self.store,self.space,doc['id'],doc['version'],observation)
        self.assertEqual(result['scope'],'local')
        self.assertEqual(result['affected_pages'],['guide.md'])
        view=claim_snapshot(self.store,self.space)[0]
        self.assertEqual(view['references'][0]['freshness'],'local_only')
        self.assertEqual(view['semantic_review'],'pending')

    def test_navigation_and_work_templates_cannot_be_revised_or_annotated(self):
        doc,_=self.setup_claim()
        for path in ['index.md','topics/index.md','_agent_templates/check.md','INSTRUCTIONS.md']:
            target=self.store._wiki(self.space)/path
            target.parent.mkdir(parents=True,exist_ok=True)
            target.write_text('# 配置\n允许编辑和撤销。\n')
            page=self.store.page(self.space,path)
            with self.assertRaises(ValueError):
                add_claim(self.store,self.space,path,page['sha256'],'允许编辑和撤销。',
                          [{'document_id':doc['id'],'version':doc['version'],'quote':'edit'}])
            with self.assertRaises(ValueError):
                save_revision(self.store,self.space,path,page['sha256'],'# 变化\n')
            self.assertEqual(target.read_text(),page['body'])

    def test_replacement_requires_review_and_preserves_old_claim_history(self):
        doc,old=self.setup_claim()
        record_check(self.store,self.space,doc['id'],doc['version'],observe_document(self.store,self.space,doc['id'],doc['version']))
        self.page.write_text('# 修订\n允许编辑和撤销。\n允许编辑。\n')
        page=self.store.page(self.space,'guide.md')
        new=add_claim(self.store,self.space,'guide.md',page['sha256'],'允许编辑。',
          [{'document_id':doc['id'],'version':doc['version'],'quote':'edit'}])
        views={c['id']:c for c in claim_snapshot(self.store,self.space)}
        with self.assertRaises(ValueError):supersede_claim(self.store,self.space,old['id'],views[old['id']]['review_token'],new['id'],views[new['id']]['review_token'])
        review_claim(self.store,self.space,new['id'],views[new['id']]['review_token'],'approved')
        current={c['id']:c for c in claim_snapshot(self.store,self.space)}
        with self.assertRaises(ValueError):supersede_claim(self.store,self.space,old['id'],current[old['id']]['review_token'],new['id'],views[new['id']]['review_token'])
        endpoint='/api/spaces/'+self.space+'/evidence/claims/'+old['id']+'/supersede'
        response=self.client.post(endpoint,json={'token':current[old['id']]['review_token'],
          'replacement_id':new['id'],'replacement_token':current[new['id']]['review_token']})
        self.assertEqual(response.status_code,200,response.text)
        state=evidence_overview(self.store,self.space)
        self.assertEqual(state['summary']['pending'],0)
        self.assertEqual(len(state['claims']),2)
        self.assertEqual(state['claims'][0]['text'],'允许编辑和撤销。')
        self.assertEqual(state['claims'][0]['superseded_by'],new['id'])
        self.assertEqual(state['claims'][0]['semantic_review'],'pending')
        self.page.write_text('# 再变化\n允许编辑。\n')
        self.assertEqual(evidence_overview(self.store,self.space)['summary']['pending'],1)

    def test_local_check_and_failed_fetch_cannot_erase_known_web_change(self):
        doc,_=self.setup_claim();text='Updated rule from the web.'
        changed=record_check(self.store,self.space,doc['id'],doc['version'],{'status':'changed','scope':'online',
          'observed_version':hashlib.sha256(text.encode()).hexdigest(),'text':text,'diff':'body changed'})
        record_check(self.store,self.space,doc['id'],doc['version'],observe_document(self.store,self.space,doc['id'],doc['version']))
        self.assertEqual(claim_snapshot(self.store,self.space)[0]['status'],'stale')
        record_check(self.store,self.space,doc['id'],doc['version'],{'status':'unavailable','scope':'online','error':'controlled failure'})
        self.assertEqual(claim_snapshot(self.store,self.space)[0]['status'],'stale')
        self.assertEqual(evidence_overview(self.store,self.space)['documents'][0]['pending_change']['id'],changed['id'])
        adopted=adopt_observation(self.store,self.space,doc['id'],doc['version'],changed['id'])
        self.assertNotIn('pending_change',adopted)

    def test_reannotation_archives_previous_review_and_resets_new_version(self):
        doc,old=self.setup_claim()
        view=claim_snapshot(self.store,self.space)[0]
        review_claim(self.store,self.space,old['id'],view['review_token'],'approved')
        self.page.write_text(self.page.read_text()+'\n新增上下文。\n')
        page=self.store.page(self.space,'guide.md')
        new=add_claim(self.store,self.space,'guide.md',page['sha256'],old['text'],old['references'])
        self.assertEqual(new['semantic_review'],'pending')
        data=json.loads((self.store.base/'metadata/claim-evidence'/f'{self.space}.json').read_text())
        archived=next(h['previous'] for h in data['history'] if h['action']=='archive_claim_version')
        self.assertEqual(archived['page_version'],old['page_version'])
        self.assertEqual(archived['semantic_review'],'approved')
        self.assertEqual(archived['references'],old['references'])

    def test_changed_online_source_preserves_old_text_and_invalidates_review(self):
        doc,claim=self.setup_claim();old=self.page.read_bytes()
        view=claim_snapshot(self.store,self.space)[0]
        review_claim(self.store,self.space,claim['id'],view['review_token'],'approved')
        text='Updated rule. Editing is no longer mentioned.'
        result=record_check(self.store,self.space,doc['id'],doc['version'],{'scope':'online','status':'changed','observed_version':hashlib.sha256(text.encode()).hexdigest(),'text':text,'diff':'old -> new'})
        self.assertEqual(document_text(self.store,self.space,doc['id'])['text'],self.source)
        view=claim_snapshot(self.store,self.space)[0]
        self.assertEqual(view['status'],'stale')
        with self.assertRaises(ValueError):review_claim(self.store,self.space,claim['id'],view['review_token'],'approved')
        with self.assertRaises(ValueError):adopt_observation(self.store,self.space,doc['id'],doc['version'],'old-check')
        adopted=adopt_observation(self.store,self.space,doc['id'],doc['version'],result['id'])
        self.assertNotEqual(adopted['version'],doc['version'])
        self.assertEqual(document_text(self.store,self.space,doc['id'])['text'],text)
        self.assertEqual(self.page.read_bytes(),old)
        self.assertEqual(claim_snapshot(self.store,self.space)[0]['status'],'stale')
        self.assertEqual(len(adopted['versions']),2)

    def test_failed_online_read_is_visible_without_replacing_source(self):
        doc,_=self.setup_claim()
        class Broken:
            def fetch(self,*args,**kwargs):raise ValueError('page unavailable')
        observed=observe_document(self.store,self.space,doc['id'],doc['version'],True,Broken())
        self.assertEqual(observed['status'],'unavailable')
        record_check(self.store,self.space,doc['id'],doc['version'],observed)
        self.assertEqual(document_text(self.store,self.space,doc['id'])['text'],self.source)
        self.assertEqual(claim_snapshot(self.store,self.space)[0]['status'],'review_due')

    def test_online_unchanged_uses_real_extracted_body_and_no_semantic_claim(self):
        doc,_=self.setup_claim()
        source=(self.source+'Additional original material. '*6).strip()
        doc=register_document(self.store,self.space,'原文',source,'https://example.org/correction',doc['version'])
        class Reader:
            def fetch(self,url):return {'url':url,'headers':{'content-type':'text/plain'},'body':source.encode()}
        observed=observe_document(self.store,self.space,doc['id'],doc['version'],True,Reader())
        self.assertEqual(observed['status'],'unchanged')
        record_check(self.store,self.space,doc['id'],doc['version'],observed)
        self.assertEqual(evidence_overview(self.store,self.space)['documents'][0]['freshness'],'online_checked')

    def test_archive_tampering_and_path_escape_are_rejected(self):
        doc,claim=self.setup_claim()
        archive=self.store.base/'metadata/evidence-text'/self.space/(doc['version']+'.md')
        archive.write_text('tampered')
        with self.assertRaises(ValueError):document_text(self.store,self.space,doc['id'])
        self.assertEqual(claim_snapshot(self.store,self.space)[0]['status'],'stale')
        for path in ['../escape.md','/absolute.md']:
            with self.assertRaises(ValueError):save_revision(self.store,self.space,path,'0'*64,'new')

    def test_revision_backups_protect_concurrent_edits_and_published_snapshots(self):
        doc,claim=self.setup_claim();old=self.page.read_bytes()
        review=self.store.review(self.space);self.store.publish(self.space,review['token'])
        version=hashlib.sha256(old).hexdigest()
        save_revision(self.store,self.space,'guide.md',version,'# 纠错\n新增修订稿。\n')
        backups=list((self.store.base/'metadata/page-revisions'/self.space).rglob('*.md'))
        self.assertEqual(backups[0].read_bytes(),old)
        self.assertEqual((self.store.base/'published'/self.space/'guide.md').read_bytes(),old)
        self.assertEqual(claim_snapshot(self.store,self.space)[0]['status'],'stale')
        with self.assertRaises(ValueError):save_revision(self.store,self.space,'guide.md',version,'lost edit')
        with self.assertRaises(ValueError):save_revision(self.store,'central','index.md','0'*64,'central edit')

    def test_api_flow_rejects_cross_origin_and_preserves_review_separation(self):
        route='/api/spaces/'+self.space+'/evidence'
        response=self.client.post(route+'/documents',json={'title':'Local','text':self.source})
        self.assertEqual(response.status_code,200,response.text);doc=response.json()
        payload={'path':'guide.md','page_version':self.store.page(self.space,'guide.md')['sha256'],'text':'允许编辑和撤销。','references':[{'document_id':doc['id'],'version':doc['version'],'quote':'edit, refine, or recover'}]}
        response=self.client.post(route+'/claims',json=payload)
        self.assertEqual(response.status_code,200,response.text)
        claim=self.client.get(route).json()['claims'][0]
        rejected=self.client.post(route+'/claims/'+claim['id']+'/review',json={'token':'obsolete','decision':'approved'})
        self.assertEqual(rejected.status_code,400)
        response=self.client.post(route+'/claims/'+claim['id']+'/review',json={'token':claim['review_token'],'decision':'rejected'})
        self.assertEqual(response.status_code,200)
        response=self.client.post(route+'/documents/'+doc['id']+'/check',json={'expected_version':doc['version']},headers={'Origin':'https://evil.invalid'})
        self.assertEqual(response.status_code,403)
        self.assertEqual(self.client.get('/evidence').status_code,200)


if __name__=='__main__':unittest.main()
