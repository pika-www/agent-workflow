/** Same-turn presentation and real-DOM streaming; no model or recorded-room writes. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { fileURLToPath, pathToFileURL } from 'node:url';
const require = createRequire(new URL('../openwiki-upstream/package.json', import.meta.url));
const { JSDOM } = require('jsdom');
const marked = await import(pathToFileURL(require.resolve('marked')).href);
const pnpm = fileURLToPath(new URL('../openwiki-upstream/node_modules/.pnpm/', import.meta.url));
const purifyPath = fs.readdirSync(pnpm).filter(name => /^dompurify@\d/.test(name)).sort().reverse()
  .map(name => path.join(pnpm, name, 'node_modules/dompurify/dist/purify.cjs.js')).find(fs.existsSync);
assert.ok(purifyPath);
const source = fs.readFileSync(new URL('../federation/web/agent-chat.js', import.meta.url), 'utf8');
function extract(name) {
  const start = source.search(new RegExp(`  (?:async )?function ${name}\\(`));
  assert.ok(start >= 0, name);
  return source.slice(start, source.indexOf('\n  }', start) + 4);
}
const dom = new JSDOM('<!doctype html><body><div id="ag-feed"></div><p id="ag-turn-label"></p></body>', {
  url:'http://127.0.0.1/', runScripts:'outside-only',
});
const { window } = dom;
window.marked = marked; window.DOMPurify = require(purifyPath)(window);
const context = dom.getInternalVMContext();
vm.runInContext(`
  const state = {room:null,taskExpanded:new Map(),sending:new Set(),submissions:new Map(),unconfirmed:new Map(),feedSignature:''};
  const $ = id => document.getElementById('ag-'+id);
  const make = (tag, cls, text) => {const node=document.createElement(tag);if(cls)node.className=cls;if(text!==undefined)node.textContent=String(text);return node;};
  const active = status => ['queued','running'].includes(status);
  const date = String, agentName = id => id, depth = () => 1, agent = () => ({});
  const renderContextUsage=()=>null, renderTemplateReads=()=>null, renderSkillReads=()=>null, renderWikiReads=()=>null;
  const renderComposerContext=()=>{};
  const renderDelegations=()=>null;
  const resumeReply=()=>{}, persistView=()=>{};
  ${['publicSourceURL','markdownBody','rememberDetails','validInterimReplies','renderInterimReplies','mergeReplyMessages',
    'questionLanguage','turnLanguage','conversationMessages','operationTarget','operationReadFailure','operationFailureDetail','replyOperations','renderOperations','validReplyTimeline','replyTimeline','recordReplyTimeline','renderUnplacedOperations','processingLabel','replyStageLabel','isNativeReply','renderReplyLoading','contextAdjustment','renderReplyBody','renderReportCheck','renderReportArtifacts','messageDetails','renderReplyTiming','renderMessages','renderStreamNotice','renderLiveReply','renderNativeAgentEvent'].map(extract).join('\n')}
  window.testChat={state,markdownBody,mergeReplyMessages,conversationMessages,renderMessages,renderLiveReply,renderNativeAgentEvent,questionLanguage};
`,context);
const { state, mergeReplyMessages, conversationMessages, renderMessages, renderLiveReply } = window.testChat;
const feed = window.document.getElementById('ag-feed');
const articles = () => [...feed.querySelectorAll('article.ag-message:not(.ag-user)')];
const fileRoom = 'a'.repeat(32), fileId = 'b'.repeat(32);
state.room = {id:fileRoom};
const fileLinks = window.testChat.markdownBody([
  `[真实附件](/api/chat/rooms/${fileRoom}/files/${fileId})`,
  `[其他会话](/api/chat/rooms/${'c'.repeat(32)}/files/${fileId})`,
  `[任意接口](/api/skills)`,
  `[越界路径](/api/chat/rooms/${fileRoom}/files/../private)`,
  `[脚本](javascript:alert(1))`,
].join('\n\n'));
assert.equal(fileLinks.querySelectorAll('a').length,1,'Only exact file downloads in this room are permitted');
assert.equal(fileLinks.querySelector('a').getAttribute('href'),`/api/chat/rooms/${fileRoom}/files/${fileId}`);
assert.match(fileLinks.textContent,/其他会话.*任意接口.*越界路径.*脚本/s,'Rejected links retain readable labels');
const ack = {id:'ack',role:'assistant',agent_id:'central',round_id:'round',phase:'acknowledgement',content:'我先读资料。',created_at:'first'};
const final = {id:'final',role:'assistant',agent_id:'central',round_id:'round',phase:'consultation',status:'completed',content:'## 完整回答\n\n结论与依据。',created_at:'last',
  artifacts:[{format:'md',url:'/api/reports/'+'a'.repeat(32)+'/md'}]};
const raw = [{id:'user',role:'user',round_id:'round',content:'同一个问题'},ack,final];
const original = JSON.stringify(raw);
raw.forEach(Object.freeze);Object.freeze(raw);
renderMessages({id:'history',mode:'orchestrated',status:'idle',messages:raw},true);
assert.equal(articles().length,1,'The screenshot acknowledgement and final are one reply');
assert.equal(articles()[0].dataset.messageId,'final');
assert.equal(articles()[0].querySelector('time').textContent,'first');
assert.match(articles()[0].querySelector('.ag-message-text').textContent,/完整回答/);
assert.equal(articles()[0].querySelector('.ag-interim-history'),null,'Acceptance is transport metadata, not reply history');
assert.doesNotMatch(feed.textContent,/我先读资料|系统确认/);
assert.ok(articles()[0].querySelector('a.ag-report-download'));
assert.equal(JSON.stringify(raw),original,'Presentation never mutates recorded history');

const screenshotRoom='a'.repeat(32),screenshotId='b'.repeat(32);
state.roomId=screenshotRoom;
const browserCapture={id:screenshotId,room_id:screenshotRoom,kind:'image',generated:true,url:`/api/chat/rooms/${screenshotRoom}/files/${screenshotId}`,source_url:'https://example.com/',viewport:{width:390,height:844},scroll_y:675};
renderMessages({id:screenshotRoom,mode:'orchestrated',status:'idle',messages:[{...final,artifacts:[browserCapture,{...browserCapture,url:'https://tracking.invalid/image.png'},{...browserCapture,room_id:'c'.repeat(32)}],workflow:{receipts:[{tool:'visual_browser',status:'completed',args:{url:'https://example.com/page?token=private'},call_id:'browser-call'}]}}]},true);
assert.equal(feed.querySelectorAll('.ag-browser-capture').length,1,'Only host browser screenshots scoped to this room display');
assert.equal(feed.querySelector('.ag-browser-capture').open,false);
assert.equal(feed.querySelector('.ag-browser-image').getAttribute('src'),`/api/chat/rooms/${screenshotRoom}/files/${screenshotId}`);
assert.match(feed.textContent,/网页截图 · 手机/);
assert.match(feed.textContent,/浏览网页/);
assert.doesNotMatch(feed.textContent,/token=private|tracking.invalid/);
renderMessages({id:'history',mode:'orchestrated',status:'idle',messages:raw},true);


const pairs = [ack,final,{...ack,id:'ack2',round_id:'next'},{...final,id:'final2',round_id:'next'},
  {...ack,id:'member-ack',agent_id:'member'},{...final,id:'member-final',agent_id:'member'},
  {...ack,id:'task-ack',delegation_task_id:'task1'},{...final,id:'task-final',delegation_task_id:'task2'}];
assert.equal(mergeReplyMessages(pairs).length,5,'Rounds, Agents and delegated tasks do not merge');
assert.equal(mergeReplyMessages([final,{...final,id:'second-result'}]).length,2,'Distinct completed results stay intact');
assert.equal(mergeReplyMessages([ack,{role:'user',content:'another question'},final]).length,3,'A new question breaks a pending reply');
assert.equal(mergeReplyMessages([{...ack,round_id:undefined},{...final,round_id:undefined}]).length,2,'Missing round evidence never guesses association');
assert.equal(mergeReplyMessages([ack,{...final,agent_id:'member'}],{mode:'orchestrated'}).length,1,
  'The host acknowledgement belongs to the selected Agent in an ordinary question');
assert.equal(mergeReplyMessages([ack,{...final,agent_id:'member'}],{mode:'orchestrated',task_groups:[{round_id:'round'}]}).length,2,
  'Collaboration member answers do not absorb the main Agent acknowledgement');

const liveRoom = {id:'stream',mode:'orchestrated',status:'running',active_job_id:'round',messages:[{role:'user',round_id:'round',content:'问题'},ack],
  live_reply:{job_id:'round',agent_id:'central',turn_id:'turn',revision:0,text:'',updates:[],acknowledgement:{text:ack.content}}};
state.room=liveRoom;renderMessages(liveRoom,true);
const initialArticle=articles()[0];
assert.ok(initialArticle.querySelector('.ag-reply-loading[role="status"]'),'A running turn without prose shows loading');
assert.doesNotMatch(initialArticle.textContent,/我先读资料|系统确认/);
const first = {id:'first-answer',title:'先回应你',text:'有两项需要核对。',status:'streaming'};
renderLiveReply({...liveRoom.live_reply,revision:1,updates:[first]});
assert.equal(articles().length,1);assert.equal(articles()[0],initialArticle,'The loading reply updates in place');
assert.equal(initialArticle.querySelector('.ag-reply-loading'),null,'The first actual text replaces loading');
assert.equal(initialArticle.querySelector('.ag-reply-body > .ag-message-text:last-child').textContent.trim(),first.text);
assert.match(initialArticle.querySelector('.ag-response-stage').textContent,/正在写/);
renderLiveReply({...liveRoom.live_reply,revision:2,updates:[{...first,text:'有三项需要核对。',status:'completed'}]});
assert.match(initialArticle.querySelector('.ag-reply-body > .ag-message-text:last-child').textContent,/有三项/,'Same-length corrections replace the old text');
renderLiveReply({...liveRoom.live_reply,revision:1,text:'陈旧事件'});
renderLiveReply({...liveRoom.live_reply,job_id:'other-round',revision:100,text:'另一个问题'});
assert.doesNotMatch(feed.textContent,/陈旧事件|另一个问题/);

const beforeCheck={id:'draft-before-check',title:'先前回答（校对前）',text:'核对前的完整初稿。',status:'completed'};
renderLiveReply({...liveRoom.live_reply,revision:3,text:beforeCheck.text,updates:[{...first,status:'completed'},beforeCheck]});
assert.equal(articles().length,1);
assert.equal((feed.textContent.match(/核对前的完整初稿。/g)||[]).length,1,'An archived draft is displayed once');
assert.equal(initialArticle.querySelector('.ag-interim-history'),null,'Already visible interim text does not create a receipt-only history');
renderLiveReply({...liveRoom.live_reply,revision:4,text:'## 补充结果\n\n发现新的依据。',updates:[{...first,status:'completed'},beforeCheck]});
assert.equal(articles()[0],initialArticle);assert.equal(articles().length,1);
assert.match(initialArticle.querySelector('.ag-reply-body > .ag-message-text:last-child').textContent,/补充结果.*发现新的依据/s);
assert.match(initialArticle.querySelector('.ag-reply-body').textContent,/有两项.*发现新的依据/s,'Interim answer stays visible above the continuing stream');
renderLiveReply({...liveRoom.live_reply,revision:5,text:'<script>attack()</script> [恶意](javascript:attack())',updates:[]});
assert.equal(feed.querySelector('script'),null);assert.equal(feed.querySelector('a[href^="javascript:"]'),null);

const saved = {...final,stream_turn_id:'turn',interim_replies:[first,beforeCheck]};
renderMessages({...liveRoom,status:'idle',messages:[liveRoom.messages[0],ack,saved]},true);
assert.equal(articles().length,1);assert.equal(articles()[0].dataset.messageId,'final');
assert.equal(articles()[0].querySelector('.ag-interim-history'),null,'Post-processing archives stay out of the chat');
assert.doesNotMatch(articles()[0].textContent,/核对前的完整初稿/);
assert.equal(saved.interim_replies.length,2,'Presentation keeps the stored originals');
assert.equal(conversationMessages({...liveRoom,messages:[liveRoom.messages[0],ack,saved]}).length,2,
  'A saved turn suppresses its stale stream and interim copies');
const failed = {...final,status:'failed',recoverable_job_id:'b'.repeat(32),processing_stage:{detail:'正在核对原文'}};
renderMessages({...liveRoom,status:'failed',messages:[liveRoom.messages[0],ack,failed]},true);
assert.equal(articles().length,1);
assert.equal(articles()[0].querySelector('[data-resume-job-id]'),null,'Failure offers no reconnect button');
renderMessages({...liveRoom,status:'running',messages:[liveRoom.messages[0],ack,failed],live_reply:null},true);
assert.equal(articles()[0].querySelector('[data-resume-job-id]'),null);
state.sending.clear();
renderMessages({id:'failed',mode:'orchestrated',status:'failed',messages:[ack,failed]},true);
assert.equal(articles()[0].querySelector('[data-resume-job-id]'),null);
assert.match(feed.textContent,/未完成.*上次停在：正在核对原文/s);
assert.ok(articles()[0].querySelector('a.ag-report-download'));
const nativeRoom={id:'native',mode:'orchestrated',status:'running',active_job_id:'native-job',messages:[{role:'user',content:'核对计算'}],
  live_reply:{job_id:'native-job',agent_id:'central',turn_id:'native-turn',revision:0,text:'',updates:[],native_seq:0,native_protocol:'responses'}};
state.room=nativeRoom;renderMessages(nativeRoom,true);
const nativeEvent={job_id:'native-job',agent_id:'central',turn_id:'native-turn',protocol:'responses',origin:'provider',
  type:'response.output_text.delta',phase:'commentary',item_id:'native-message',update_id:'native-1',seq:1,revision:1,delta:'先核对'};
window.testChat.renderNativeAgentEvent(nativeEvent);
const nativeArticle=articles()[0];
window.testChat.renderNativeAgentEvent({...nativeEvent,seq:2,revision:2,delta:'利润。'});
assert.equal(articles()[0],nativeArticle);assert.match(feed.textContent,/先核对利润。/);
window.testChat.renderNativeAgentEvent(nativeEvent);
assert.equal((feed.textContent.match(/先核对利润。/g)||[]).length,1,'Replayed native seq never duplicates tokens');
renderLiveReply({...nativeRoom.live_reply,revision:3,native_seq:2,updates:[{id:'native-1',title:'Agent 中间回答',text:'先核对利润。',status:'completed'}]});
window.testChat.renderNativeAgentEvent({...nativeEvent,phase:'final_answer',update_id:'native-2',seq:3,revision:4,delta:'假设利润'});
window.testChat.renderNativeAgentEvent({...nativeEvent,phase:'final_answer',update_id:'native-2',seq:4,revision:5,delta:'1000。'});
assert.equal(articles().length,1);assert.equal(articles()[0],nativeArticle);
assert.match(feed.textContent,/先核对利润。.*假设利润1000。/s);
assert.equal(nativeArticle.querySelectorAll('.ag-reply-body > .ag-message-text').length,1,'Native message items continue in one text body');
assert.equal(nativeArticle.querySelector('.ag-interim-history'),null,'Native text never becomes a separate interim-history UI');
assert.equal(nativeArticle.querySelector('.ag-response-stage').hidden,true,'Protocol phase stays out of response badges');
assert.doesNotMatch(nativeArticle.textContent,/Agent 中间回答|继续补充|先给你这部分/);
renderLiveReply({...nativeRoom.live_reply,revision:6,native_seq:4,text:'假设利润1000。'});
window.testChat.renderNativeAgentEvent({...nativeEvent,phase:'final_answer',seq:4,revision:7,delta:'重复'});
assert.doesNotMatch(feed.textContent,/重复/);
window.testChat.renderNativeAgentEvent({...nativeEvent,job_id:'other',seq:100,revision:100,delta:'跨轮'});
assert.doesNotMatch(feed.textContent,/跨轮/);
const nativeSaved={...final,id:'native-saved',round_id:'native-job',native_stream:{protocol:'responses'},content:'校对后的结论。',
 interim_replies:[{id:'12345678-native-1',title:'Agent 中间回答',text:'先核对利润。',status:'completed'},
  {id:'12345678-before-check',title:'先前回答（校对前）',text:'已撤回的草稿。',status:'completed'}]};
const nativeRaw=JSON.stringify(nativeSaved);
renderMessages({...nativeRoom,status:'idle',live_reply:null,messages:[nativeRoom.messages[0],nativeSaved]},true);
assert.equal(articles().length,1);
assert.equal(articles()[0].querySelectorAll('.ag-reply-body > .ag-message-text').length,1);
assert.match(articles()[0].textContent,/先核对利润。.*校对后的结论。/s,'Completion retains the real Agent text in the same body');
assert.doesNotMatch(articles()[0].textContent,/Agent 中间回答|查看处理过程中|已撤回的草稿/);
assert.equal(JSON.stringify(nativeSaved),nativeRaw,'Saved native phases/receipts are not rewritten');
const corrected={...nativeSaved,id:'corrected-visible',answer_check:{status:'corrected_with_limits'},content:'这个问题目前还不能确定。'};
renderMessages({...nativeRoom,status:'idle',live_reply:null,messages:[nativeRoom.messages[0],corrected]},true);
assert.equal(articles()[0].querySelector('.ag-reply-body').textContent.trim(),'这个问题目前还不能确定。');
assert.doesNotMatch(articles()[0].querySelector('.ag-reply-body').textContent,/先核对利润|已撤回/,'Final corrections never reinsert the superseded draft');
const social={...nativeSaved,id:'social-visible',response_origin:'simple_chat_model',content:'你好，我叫主 Agent。'};
renderMessages({...nativeRoom,status:'idle',live_reply:null,messages:[nativeRoom.messages[0],social]},true);
assert.equal(articles()[0].querySelector('.ag-message-details'),null,'Ordinary social reply has no per-message technical footer');
renderMessages({...nativeRoom,status:'failed',live_reply:null,messages:[nativeRoom.messages[0],{...nativeSaved,status:'failed',content:'读取失败，未完成。'}]},true);
assert.match(articles()[0].textContent,/先核对利润。.*读取失败/s,'Failure keeps visible native text and the honest error');
const exhausted={...nativeSaved,status:'failed',transport_retry:{attempt:5,max_attempts:5,status:'exhausted'},content:'这次未能完成答复：自动重连 5 次仍失败，请稍后再试。'};
renderMessages({...nativeRoom,status:'failed',live_reply:null,messages:[nativeRoom.messages[0],exhausted]},true);
assert.equal((articles()[0].textContent.match(/自动重连 5 次仍失败/g)||[]).length,1,'The terminal failure appears once in the same reply');
assert.ok(articles()[0].querySelector('.ag-failure-text[role="alert"]'),'The recorded failure itself is the red alert');
assert.match(articles()[0].textContent,/先核对利润/,'Earlier completed model text remains visible');
assert.equal(articles()[0].querySelector('button'),null,'Exhaustion never offers a reconnect action');
const localSaved={...nativeSaved,native_stream:{protocol:'chat_completions'},content:'我叫主 Agent。',
 interim_replies:[{id:'12345678-native-1',title:'Agent 流式回答',text:'我叫主 Agent。',status:'completed'}]};
renderMessages({...nativeRoom,status:'idle',live_reply:null,messages:[nativeRoom.messages[0],localSaved]},true);
assert.equal((articles()[0].textContent.match(/我叫主 Agent。/g)||[]).length,1,'Native Chat final completion does not repeat streamed content');
const waitingRoom={id:'waiting',mode:'orchestrated',status:'idle',messages:[]};
state.submissions.set('waiting',{id:'send-1',content:'有没有更好听的名字？',created_at:'now'});state.sending.add('waiting');
renderMessages(waitingRoom,true);
assert.equal(feed.querySelectorAll('.ag-user').length,1,'Submission immediately shows the user message');
assert.match(feed.querySelector('.ag-reply-loading').textContent,/正在发送/);
state.submissions.clear();state.sending.clear();
const queuedRoom={...waitingRoom,status:'queued',active_job_id:'queue-1',messages:[{role:'user',round_id:'queue-1',content:'有没有更好听的名字？'}],
 live_reply:{job_id:'queue-1',revision:0,text:'',updates:[],acknowledgement:{text:'这条问题已收到。我先围绕你的问题给出解释。'}}};
state.room=queuedRoom;renderMessages(queuedRoom,true);
assert.match(feed.querySelector('.ag-reply-loading[role="status"]').textContent,/等待回复/);
assert.equal(feed.querySelectorAll('.ag-loading-dots > span').length,3);
assert.doesNotMatch(feed.textContent,/已收到|系统确认|围绕你的问题/);
renderMessages({...queuedRoom,status:'running',current_agent:'中央 Agent',live_reply:null},true);
assert.match(feed.querySelector('.ag-reply-loading').textContent,/正在回复/,'Reload without a stream snapshot still shows loading');
assert.equal(articles()[0].dataset.replyKey,JSON.stringify(['queue-1','central','']),'A display name never becomes the streaming Agent ID');
renderMessages({...queuedRoom,status:'failed',messages:[queuedRoom.messages[0],{role:'assistant',agent_id:'central',content:'这次回复未完成，可以重试。',status:'failed',round_id:'queue-1'}]},true);
assert.equal(feed.querySelector('.ag-reply-loading'),null,'A failed turn does not leave an endless loader');
renderMessages({...queuedRoom,status:'idle',messages:[queuedRoom.messages[0],{role:'assistant',agent_id:'central',content:'可以叫我未明。',status:'completed',round_id:'queue-1'}]},true);
assert.equal(feed.querySelector('.ag-reply-loading'),null,'Completion clears loading');
renderMessages(waitingRoom,true);
assert.equal(feed.querySelector('.ag-reply-loading'),null,'Failed submission cleanup leaves the idle room without loading');
window.close();
console.log('Single-reply UI passed: historical merge, separate rounds/Agents/tasks, frozen history, stream identity, same-length correction, stale events, expansion preservation, draft dedupe, completed persistence, safe Markdown, artifacts and recoverable failures.');

// The first real tool can appear before any model text, in the same later reply.
const toolRoom={id:'tools',mode:'orchestrated',status:'running',active_job_id:'tools-job',messages:[{role:'user',content:'读取资料并计算'}],
 live_reply:{job_id:'tools-job',agent_id:'central',turn_id:'tool-turn',revision:0,text:'',updates:[],native_protocol:'responses',native_seq:0}};
state.room=toolRoom;renderMessages(toolRoom,true);
assert.equal(articles().length,1,'Waiting uses a loading reply before actual activity');
assert.ok(articles()[0].querySelector('.ag-reply-loading[role="status"]'));
assert.equal(articles()[0].querySelector('.ag-message-text'),null,'Loading never fabricates model text');
const started={origin:'host_tool',protocol:'responses',type:'agent.tool.started',job_id:'tools-job',agent_id:'central',
 turn_id:'tool-turn',seq:1,revision:1,call_id:'call-read',name:'web_read',target:'https://example.com/article?token=SECRET#private'};
window.testChat.renderNativeAgentEvent(started);
const toolArticle=articles()[0];assert.ok(toolArticle);
assert.equal((toolArticle.querySelector('.ag-message-text')?.textContent || ''),'','A tool event never fabricates model text');
let toolLog=toolArticle.querySelector('.ag-operation-log');assert.ok(toolLog);toolLog.open=true;toolLog.dispatchEvent(new window.Event('toggle'));
assert.match(toolLog.textContent,/正在读取网页.*https:\/\/example.com\/article/s);
assert.doesNotMatch(toolLog.textContent,/SECRET|private/);
window.testChat.renderNativeAgentEvent({...started,seq:2,revision:2,type:'agent.tool.completed',status:'completed',elapsed_ms:1234});
assert.equal(toolArticle.querySelector('.ag-operation-log').open,true);
assert.match(toolArticle.textContent,/已读取网页.*1.2 秒/s);
window.testChat.renderNativeAgentEvent({...started,seq:3,revision:3});
assert.equal(toolArticle.querySelectorAll('.ag-operation-row').length,1,'Replayed call IDs do not duplicate operations or revert completion');
assert.equal(toolArticle.querySelector('.ag-operation-row').dataset.status,'completed');
window.testChat.renderNativeAgentEvent({...started,seq:4,revision:4,type:'response.output_text.delta',origin:'provider',phase:'final_answer',
 item_id:'message-result',delta:'取得资料后继续回答。'});
assert.equal(articles()[0],toolArticle);assert.match((toolArticle.querySelector('.ag-message-text')?.textContent || ''),/继续回答/);
renderLiveReply({...toolRoom.live_reply,revision:5,native_seq:4});
window.testChat.renderNativeAgentEvent({...started,seq:4,revision:6});
assert.equal(toolArticle.querySelectorAll('.ag-operation-row').length,1,'Canonical snapshot and SSE reconnect remain deduplicated');
const storedTool={...nativeSaved,id:'stored-tool',round_id:'tools-job',content:'完成本轮核对。',interim_replies:[],
 reply_timeline:toolRoom.live_reply.timeline,
 operations:[{call_id:'call-read',name:'web_read',status:'completed',target:'https://example.com/article',elapsed_ms:1234}],
 workflow:{receipts:[{call_id:'call-read',tool:'web_read',status:'completed',args:{url:'https://example.com/article?token=SECRET'}},
  {call_id:'call-search',tool:'web_search',status:'unavailable',args:{query:'<img src=x onerror=attack()> token=SECRET'}}]}};
const unchanged=JSON.stringify(storedTool);
renderMessages({...toolRoom,status:'idle',messages:[toolRoom.messages[0],storedTool]},true);
assert.equal(articles()[0].querySelectorAll('.ag-operation-row').length,2,'Historical real receipts fill missing operations without duplicates');
assert.equal(articles()[0].querySelector('[data-call-id="call-read"]').closest('details').open,true,'Open state follows the completed tool group, even when old receipts are prepended');
assert.match(articles()[0].textContent,/未取得结果/);
assert.equal(articles()[0].querySelector('img'),null,'Log targets are literal text');
assert.doesNotMatch(articles()[0].textContent,/SECRET/);
assert.equal(JSON.stringify(storedTool),unchanged,'Historical receipts are not rewritten');
renderMessages({...toolRoom,status:'failed',messages:[{...storedTool,status:'failed',operations:[{call_id:'call-read',name:'web_read',status:'running'}],workflow:undefined}]},true);
assert.match(articles()[0].textContent,/已中断：读取网页/);
renderMessages({id:'plain',status:'idle',messages:[{...final,artifacts:undefined}]},true);
assert.equal(feed.querySelector('.ag-operation-log'),null,'Plain model answers do not invent operations');
console.log('Operation log UI passed: live execution before prose, same article, replay dedupe, persistent expansion, final receipts, interruption, URL/query redaction and literal targets.');
renderMessages({id:'host-reads',status:'idle',messages:[{...final,artifacts:undefined,
 wiki_reads:[{path:'/index.md',sha256:'a'.repeat(64)}],
 template_reads:[{path:'/_agent_templates/manifest.json',sha256:'b'.repeat(64)},{path:'/unverified.md'}]}]},true);
assert.equal(feed.querySelectorAll('.ag-operation-row').length,0,'Host prefetch metadata does not become a conversation operation');
assert.doesNotMatch(feed.textContent,/资料预读|index.md|unverified.md|编辑文件|运行命令/);

// One assistant turn follows actual text -> operation -> text -> operation order.
const orderedRoom={id:'ordered',mode:'orchestrated',status:'running',active_job_id:'ordered-job',messages:[{role:'user',content:'查询后计算'}],
 live_reply:{job_id:'ordered-job',agent_id:'central',turn_id:'ordered-turn',revision:0,text:'',updates:[],operations:[],timeline:[],native_seq:0,native_protocol:'responses'}};
state.room=orderedRoom;renderMessages(orderedRoom,true);
let orderedSeq=0;
const sendOrdered=event=>window.testChat.renderNativeAgentEvent({job_id:'ordered-job',agent_id:'central',turn_id:'ordered-turn',
 protocol:'responses',origin:'provider',seq:++orderedSeq,revision:orderedSeq,...event});
sendOrdered({type:'response.output_text.delta',phase:'commentary',item_id:'one',update_id:'native-1',delta:'先读取网页。'});
sendOrdered({origin:'host_tool',type:'agent.tool.started',call_id:'web-1',name:'web_read',target:'https://example.com/page'});
const orderedArticle=articles()[0], opened=orderedArticle.querySelector('.ag-operation-inline');
opened.open=true;opened.dispatchEvent(new window.Event('toggle'));
sendOrdered({origin:'host_tool',type:'agent.tool.completed',call_id:'web-1',name:'web_read',status:'completed',elapsed_ms:90});
sendOrdered({type:'response.output_text.delta',phase:'commentary',item_id:'two',update_id:'native-2',delta:'网页已取得，接着核算数字。'});
sendOrdered({origin:'host_tool',type:'agent.tool.started',call_id:'calc-1',name:'profit_calculate'});
sendOrdered({origin:'host_tool',type:'agent.tool.completed',call_id:'calc-1',name:'profit_calculate',status:'completed',elapsed_ms:3});
sendOrdered({type:'response.output_text.delta',phase:'final_answer',item_id:'three',delta:'未校对的最终草稿。'});
assert.equal(articles().length,1);assert.equal(articles()[0],orderedArticle);
const order=()=>[...articles()[0].querySelector('.ag-reply-body').children].map(node=>node.classList.contains('ag-operation-log')?'tool':'text');
assert.deepEqual(order(),['text','tool','text','tool','text']);
assert.equal(orderedArticle.querySelector('.ag-operation-inline').open,true,'Earlier tool group stays expanded when later text arrives');
const orderedStored={id:'ordered-stored',role:'assistant',agent_id:'central',round_id:'ordered-job',status:'completed',
 content:'核对后的最终结论。',native_stream:{protocol:'responses'},interim_replies:orderedRoom.live_reply.updates,
 operations:orderedRoom.live_reply.operations,reply_timeline:orderedRoom.live_reply.timeline};
const storedOrderOriginal=JSON.stringify(orderedStored);
renderMessages({...orderedRoom,status:'idle',messages:[orderedRoom.messages[0],orderedStored]},true);
assert.deepEqual(order(),['text','tool','text','tool','text']);
assert.equal(articles()[0].querySelector('.ag-operation-inline').open,true);
assert.match(articles()[0].querySelector('.ag-reply-body').textContent,/先读取网页.*已读取网页.*网页已取得.*已计算收入.*核对后的最终结论/s);
assert.doesNotMatch(feed.textContent,/未校对的最终草稿/,'Timeline answer slot uses the checked canonical answer');
assert.equal(JSON.stringify(orderedStored),storedOrderOriginal);
const recordedOrdered={...orderedStored,reply_timeline:undefined,native_stream:{protocol:'responses',events:[
 {type:'response.output_text.delta',phase:'commentary',update_id:'native-1'},
 {type:'response.output_item.done',item_type:'function_call',call_id:'web-1',name:'web_read'},
 {type:'response.completed'},
 {type:'response.output_text.delta',phase:'commentary',update_id:'native-2'},
 {type:'response.output_item.done',item_type:'function_call',call_id:'calc-1',name:'profit_calculate'},
 {type:'response.completed'},
 {type:'response.output_text.delta',phase:'final_answer'}]}};
renderMessages({...orderedRoom,status:'idle',messages:[recordedOrdered]},true);
assert.deepEqual(order(),['text','tool','text','tool','text'],'Recorded provider order + actual receipts supports historical placement');
renderMessages({...orderedRoom,status:'idle',messages:[{...recordedOrdered,operations:[],workflow:undefined}]},true);
assert.equal(feed.querySelectorAll('.ag-operation-log').length,0,'A provider call with no execution receipt cannot become an operation');
renderMessages({...orderedRoom,status:'idle',messages:[{...orderedStored,reply_timeline:undefined,native_stream:{protocol:'responses'}}]},true);
assert.equal(articles()[0].querySelector('.ag-reply-body').firstElementChild.classList.contains('ag-operation-log'),true);
assert.equal(articles()[0].querySelector('.ag-message-details'),null);
assert.match(articles()[0].querySelector('.ag-operation-log').textContent,/工具操作/);
console.log('Ordered reply timeline passed: live text/tool interleaving, one article, canonical correction, snapshot continuity, historical evidence and unexecuted-call exclusion.');

const compactRoom={id:'auto-compact',mode:'orchestrated',status:'running',active_job_id:'compact-job',messages:[{role:'user',content:'继续当前问题'}],
 live_reply:{job_id:'compact-job',agent_id:'central',turn_id:'compact-turn',revision:0,text:'',updates:[],operations:[],timeline:[],native_seq:0,native_protocol:'responses'}};
state.room=compactRoom;renderMessages(compactRoom,true);
const compactEvent={origin:'host_context',protocol:'responses',type:'agent.context.compacted',job_id:'compact-job',agent_id:'central',turn_id:'compact-turn',
 seq:1,revision:1,stage:'runtime',before_tokens:20000,after_tokens:6000,budget_tokens:12000};
window.testChat.renderNativeAgentEvent(compactEvent);
assert.equal(feed.querySelectorAll('.ag-context-compacted').length,1);
assert.match(feed.textContent,/上下文已自动压缩/);
assert.equal(feed.querySelectorAll('.ag-operation-row').length,0,'Compaction is not a fabricated tool call');
window.testChat.renderNativeAgentEvent({...compactEvent,seq:2,revision:2,type:'response.output_text.delta',origin:'provider',phase:'final_answer',item_id:'compact-answer',delta:'继续回答当前问题。'});
assert.equal(feed.querySelectorAll('.ag-context-compacted').length,1);
assert.match(feed.textContent,/上下文已自动压缩.*继续回答当前问题/s);
const compactSaved={role:'assistant',agent_id:'central',id:'compact-saved',round_id:'compact-job',content:'继续回答当前问题。',workflow:{context_compactions:[{before_tokens:20000,after_tokens:6000}]}};
renderMessages({...compactRoom,status:'idle',messages:[compactRoom.messages[0],compactSaved]},true);
assert.equal(feed.querySelectorAll('.ag-context-compacted').length,1,'The lightweight notice survives final persistence');
console.log('Automatic compaction UI: one host notice, continuous answer, no fabricated tool or model text.');

// The screenshot: English user text, Chinese prior history, public-tool receipts.
const languageRoom={id:'language',mode:'orchestrated',status:'running',active_job_id:'en-round',messages:[
 {id:'zh-user',role:'user',round_id:'zh-round',content:'你好'},
 {id:'zh-reply',role:'assistant',agent_id:'central',round_id:'zh-round',content:'你好。',status:'completed'},
 {id:'en-user',role:'user',round_id:'en-round',content:'hello Do you know me？'}],
 live_reply:{job_id:'en-round',turn_id:'live',agent_id:'central',native_protocol:'responses',text:'',revision:1,
 operations:[{call_id:'search',name:'web_search',status:'completed',target:'hello Do you know me',elapsed_ms:1500},
 {call_id:'read',name:'web_read',status:'network_error',target:'https://example.com/page',elapsed_ms:10300}],
 context_compaction:{stage:'runtime',before_tokens:30000,after_tokens:20000}}};
const rawLanguageRoom=JSON.stringify(languageRoom);state.room=languageRoom;
renderMessages(languageRoom,true);
const englishReply=articles().at(-1);
assert.match(englishReply.textContent,/Main Agent.*Context automatically compacted.*Tool activity.*Searched public sources.*Page connection failed.*Replying/s);
assert.match(englishReply.textContent,/1.5 s.*10.3 s/s);
assert.doesNotMatch(englishReply.textContent,/工具操作|已搜索|网页连接失败|正在回复| 秒|上下文/);
assert.equal(englishReply.lang,'en');
assert.equal(articles()[0].lang,'zh-CN','A later English turn does not relabel older Chinese turns');
assert.equal(JSON.stringify(languageRoom),rawLanguageRoom,'UI translation never rewrites persisted receipts or history');
for(const [q,expected] of [['Hello!','en'],['hello Do you know me？','en'],['请解释 React hooks','zh'],['Please answer in Chinese: explain hooks.','zh'],['用英文解释闭包','en'],['Explain the name 吴锋','en']])assert.equal(window.testChat.questionLanguage(q),expected,q);
const restored={...languageRoom,status:'idle',active_job_id:null,live_reply:null,messages:[...languageRoom.messages,
 {id:'saved-en',role:'assistant',agent_id:'central',round_id:'en-round',status:'completed',content:'Yes, I know the background you shared.',operations:languageRoom.live_reply.operations}]};
renderMessages(restored,true);assert.match(articles().at(-1).textContent,/Searched public sources.*Page connection failed/s);
console.log('Per-turn language: English operations/loading/compaction, Chinese history, explicit language overrides and persisted readback passed.');

// Failed submissions remain readable beside a new draft; late server receipt
// removes the local duplicate without confusing an older identical message.
const unconfirmedRoom={id:'unconfirmed',mode:'orchestrated',status:'idle',messages:[{id:'old',role:'user',content:'原消息'}]};
state.unconfirmed.set(unconfirmedRoom.id,[{id:'local-1',content:'原消息',known_message_ids:['old'],created_at:'now'}]);
renderMessages(unconfirmedRoom,true);
assert.equal(feed.querySelectorAll('.ag-user').length,2);
assert.match(feed.textContent,/发送未确认/);
unconfirmedRoom.messages.push({id:'new',role:'user',content:'原消息'});
renderMessages(unconfirmedRoom,true);
assert.equal(feed.querySelectorAll('.ag-user').length,2);
assert.doesNotMatch(feed.textContent,/发送未确认/);
console.log('Unconfirmed send: original text retained safely and late acknowledgement reconciled.');

const checkingRoom={id:'checked-room',status:'running',active_job_id:'checked-round',messages:[{id:'checked-user',role:'user',round_id:'checked-round',content:'这个月失业人数是多少？'}],
 live_reply:{job_id:'checked-round',agent_id:'central',native_protocol:'responses',revision:1,text:'',updates:[],operations:[],processing_stage:{stage:'checking_evidence',detail:'正在核对依据'}}};
state.room=checkingRoom;renderMessages(checkingRoom);
assert.match(feed.textContent,/正在核对依据/);assert.doesNotMatch(feed.textContent,/99万人/);
renderLiveReply({...checkingRoom.live_reply,revision:2,processing_stage:{stage:'answer_ready'},text:'来源未提供当月失业人数，目前无法确认。'});
assert.equal(articles().length,1);assert.equal(feed.querySelector('.ag-reply-loading'),null);
assert.match(feed.textContent,/来源未提供当月失业人数/);
