/** Reading workspace: filtering, ordering, safe content and selection boundaries. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import {createRequire} from 'node:module';
const require=createRequire(new URL('../openwiki-upstream/package.json',import.meta.url));
const {JSDOM}=require('jsdom');
const html=fs.readFileSync(new URL('../federation/web/workspace.html',import.meta.url),'utf8');
const source=fs.readFileSync(new URL('../federation/web/workspace.js',import.meta.url),'utf8');
const dom=new JSDOM(html,{url:'http://127.0.0.1:18732/'}),{document}=dom.window;
const ids=[...document.querySelectorAll('[id]')].map(node=>node.id);
assert.equal(ids.length,new Set(ids).size,'DOM IDs must stay unique when panels move');
const state={hotKey:'fixture',category:'all',query:'',sort:'latest',hotspotSources:[{id:'ai',name:'AI 来源',group:'ai',status:'ready',fetched_at:'2026-10-09T12:00:00Z'}],hotspotItems:[
 {id:'a',title:'Agent 产品更新',summary:'企业工作流',source:'AI 来源',source_id:'ai',group:'ai',url:'https://example.com/a',rank:2,published_at:'2026-10-09T10:00:00Z'},
 {id:'b',title:'开源工具',source:'开发者',group:'tech',url:'https://example.com/b',rank:1,published_at:'2026-10-08T10:00:00Z'},
 {id:'c',title:'<img src=x onerror=alert(1)>',source:'综合',group:'general',url:'https://example.com/c',rank:3,published_at:'2026-10-07T10:00:00Z'},
 {id:'bad',title:'不安全链接',group:'ai',url:'javascript:alert(1)'}]};
const opened=[];
const context=vm.createContext({document,window:dom.window,URL,Date,state,openHotspot:item=>opened.push(item.id)});
const helpers=source.slice(source.indexOf('  const $ ='),source.indexOf('  const state ='));
const listFunctions=source.slice(source.indexOf('  function publicUrl('),source.indexOf('  function renderHotspots('));
vm.runInContext(helpers+listFunctions,context);
const rows=()=>[...document.querySelectorAll('.ws-news-item')];
context.renderNewsList();assert.deepEqual(rows().map(n=>n.dataset.hotspotId),['a','b','c']);
assert.equal(document.querySelectorAll('#ws-news-list img').length,0);
assert.match(rows()[2].textContent,/<img src=x/);
state.category='ai';context.renderNewsList();assert.equal(rows().length,1);
state.category='business';context.renderNewsList();assert.deepEqual(rows().map(n=>n.dataset.hotspotId),['a']);
state.category='tech';context.renderNewsList();assert.deepEqual(rows().map(n=>n.dataset.hotspotId),['b']);
state.category='all';state.query='ai 来源';context.renderNewsList();assert.equal(rows().length,1);
state.query='不存在';context.renderNewsList();assert.equal(rows().length,0);assert.match(document.querySelector('#ws-news-list').textContent,/没有找到/);
state.query='';state.sort='rank';state.selectedHotspot=state.hotspotItems[0];context.renderNewsList();assert.deepEqual(rows().map(n=>n.dataset.hotspotId),['b','a','c']);
assert.equal(rows()[1].getAttribute('aria-pressed'),'true');
document.body.classList.add('ws-news-drawer');rows()[1].click();assert.deepEqual(opened,['a']);assert.equal(document.body.classList.contains('ws-news-drawer'),false);
state.sort='latest';state.hotspotItems[0].published_at='invalid';context.renderNewsList();assert.match(context.newsTime(state.hotspotItems[0]),/时间未提供/);
assert.equal(document.querySelector('#ws-hot-reader').closest('#ws-chat-host')?.id,'ws-chat-host','Reader must overlay the conversation, leaving the news list available');
assert.equal(document.querySelector('#ws-actions').closest('dialog')?.id,'ws-task-dialog','Actual task records remain accessible');
vm.runInContext(source.split('\n').find(line=>line.includes('window.openWikiHotspots =')),context);
state.hotOpen=true;state.selectedHotspot=null;assert.equal(Object.keys(dom.window.openWikiHotspots.context()).length,0,'The default reading layout must not add unrelated news to ordinary chat');
state.selectedHotspot=state.hotspotItems[0];assert.equal(dom.window.openWikiHotspots.context().hotspot_id,'a');
state.hotOpen=false;assert.equal(Object.keys(dom.window.openWikiHotspots.context()).length,0,'Switching to chat stops attaching the selected story');
dom.window.close();console.log('Reading workspace: category/search/sort, empty state, selected source, mobile drawer, safe text and panel placement passed.');
