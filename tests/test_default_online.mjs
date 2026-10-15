import assert from 'node:assert/strict';
import {defaultOnlineLookup,hasPublicBody,publicSearchQuery} from '../federation/default-online.mjs';
const policy={default_online:true,network_allowed:true,services:{search:{enabled:true},browser:{configured:true}}};
const question='查阅 Playwright 官方文档，定位器每次操作都会重新查找元素吗？';
const flow=defaultOnlineLookup(question,policy,{reads:[]}),allowed=['web_search','web_read','visual_browser'];
assert.equal(flow.next({receipts:[],observations:[],allowed}).tool,'web_search');
const state={receipts:[{tool:'web_search',args:{query:'Playwright locators'}}],observations:[{tool:'web_search',result:{sources:[{url:'https://playwright.dev/docs/locators'}]}}],allowed};
assert.deepEqual(flow.next(state).args,{url:'https://playwright.dev/docs/locators'});
state.receipts.push({tool:'web_read',args:{url:'https://playwright.dev/docs/locators'}});state.observations.push({tool:'web_read',result:{status:'unavailable',sources:[]}});
assert.equal(flow.next(state).tool,'visual_browser');
state.receipts.push({tool:'visual_browser',args:{url:'https://playwright.dev/docs/locators'}});state.observations.push({tool:'visual_browser',result:{status:'completed',sources:[{excerpt:'actual body',read_method:'visual_browser_dom'}]}});
assert.equal(flow.next(state),null);
for(const q of ['你好','你是谁','不要联网，解释这个知识','离线回答','只根据知识库回答','我的密码：secret-123 帮我分析','邮件 a@example.com 是谁'])assert.equal(defaultOnlineLookup(q,policy),null,q);
assert.equal(defaultOnlineLookup(question,{...policy,has_attachments:true}),null);
assert.equal(defaultOnlineLookup(question,{...policy,network_allowed:false}),null);
assert.match(flow.instruction,/发布时间.*版本|发布日期.*版本/);
assert.equal(hasPublicBody({read_method:'http_text',excerpt:'免责声明：本页面信息可能来自第三方，仅供参考。'}),false);
assert.equal(hasPublicBody({read_method:'http_text',excerpt:'每次使用定位器时都会重新寻找元素。'}),true);
const deniedState={receipts:[state.receipts[0],state.receipts[1]],observations:[state.observations[0],{tool:'web_read',result:{status:'unavailable',errors:[{error:'该网页的 robots.txt 不允许自动采集'}]}}],allowed};
assert.equal(flow.next(deniedState),null,'Do not repeat a denied URL in a browser');
const dynamicState={...deniedState,observations:[state.observations[0],{tool:'web_read',result:{status:'unavailable',errors:[{error:'未提取到足够的可读正文；页面可能需要登录或执行脚本'}]}}]};
assert.equal(flow.next(dynamicState).tool,'visual_browser','An ambiguous static extraction failure must fall through to the browser');
const multipleCandidates=structuredClone(dynamicState);
multipleCandidates.observations[0].result.sources.push({url:'https://another.example/article'},{url:'https://third.example/article'});
assert.equal(flow.next(multipleCandidates).tool,'visual_browser','Fresh static results must not consume the budget before a pending dynamic read');
const browserFailure=structuredClone(multipleCandidates);
browserFailure.receipts.push({tool:'visual_browser',args:{url:'https://playwright.dev/docs/locators'}});
browserFailure.observations.push({tool:'visual_browser',result:{status:'unavailable',errors:[{error:'没有读到公开正文'}]}});
assert.equal(flow.next(browserFailure).args.url,'https://another.example/article','After one failed browser attempt, move to a different source');
assert.equal(defaultOnlineLookup(question,{...policy,services:{browser:{configured:false}}}).next(dynamicState),null);
assert.equal(defaultOnlineLookup('只用 web_read 解释 Locator 定位时机',policy).next(dynamicState),null);
const footerState={...deniedState,observations:[state.observations[0],{tool:'web_read',result:{status:'completed',sources:[{read_method:'http_text',excerpt:'免责声明：仅供参考。'}]}}]};
assert.equal(flow.next(footerState).tool,'visual_browser','A footer alone still needs actual rendered content');
console.log('Default online: no explicit search keyword, real body required, offline and private scopes retained.');

for(const q of ['这个月失业的人数有多少？','本月失业率是多少？','今年人口数据有多少？']) {
 const lookup=defaultOnlineLookup(q,policy,{}, {followup:true,question:'旧话题：最近有没有趣事？'});
 const next=lookup.next({receipts:[],observations:[],allowed});
 assert.equal(next.hostQueryReady,true,q);assert.equal(next.requireModelQuery,false);
 assert.doesNotMatch(next.args.query,/趣事/);
}
assert.equal(publicSearchQuery('这个月失业的人数有多少？',new Date('2026-10-01T00:01:00+08:00')),'2026-10失业的人数有多少');
for(const q of ['这个月失业了，很难受','失业了怎么办？','今年我想换工作'])assert.equal(defaultOnlineLookup(q,policy),null,q);

assert.match(defaultOnlineLookup('这个月中国失业的人数有多少？',policy).next({receipts:[],observations:[],allowed}).args.query,/site:stats\.gov\.cn/);
assert.doesNotMatch(defaultOnlineLookup('这个月美国失业人数多少？',policy).next({receipts:[],observations:[],allowed}).args.query,/stats\.gov\.cn/);
