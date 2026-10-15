import assert from 'node:assert/strict';
import {publicReadFailure,publicReadDetail,browserFallbackBlocked,explicitlyDenied} from '../federation/public-read-status.mjs';
import {websiteLookup} from '../federation/tool-autonomy.mjs';
const url='https://reader.example/page';
const policy={network_allowed:true,tools_enabled:true,services:{browser:{configured:true}}};
const lookup=websiteLookup('读取网页 '+url,policy);
const state=result=>({receipts:[{tool:'web_read',args:{url}}],observations:[{tool:'web_read',result}],allowed:['web_search','web_read','visual_browser']});
for(const http of [403,500]){
 const result={status:'unavailable',errors:[{error:`无法确认 robots.txt 访问许可（HTTP ${http}）`}]};
 assert.equal(publicReadFailure(result),'robots_check_failed');assert.equal(explicitlyDenied(result),false);
 assert.equal(browserFallbackBlocked(result),true);assert.equal(lookup.next(state(result)),null);
 assert.match(publicReadDetail(result),/尚未请求文章正文/);
}
for(const code of ['robots_blocked','robots_check_failed','access_restricted','article_http_error','rate_limited']){
 const result={status:'unavailable',errors:[{code,stage:code.startsWith('robots')?'robots':'article',http_status:503,attempts:3,error:'host diagnosis'}]};
 assert.equal(publicReadFailure(result),code);assert.equal(lookup.next(state(result)),null);assert.match(publicReadDetail(result),/HTTP 503，已尝试 3 次/);
}
const dynamic={status:'unavailable',errors:[{code:'no_readable_body',stage:'extract',error:'未提取到足够的可读正文'}]};
assert.equal(lookup.next(state(dynamic)).tool,'visual_browser');
assert.equal(lookup.next({...state(dynamic),allowed:['web_read']}),null);
assert.equal(websiteLookup('只用 web_read 读取 '+url,policy).next(state(dynamic)),null);
assert.equal(publicReadFailure({status:'completed',sources:[{excerpt:'robots.txt disallow HTTP 403'}]}),null);
assert.equal(publicReadFailure({status:'unavailable',sources:[{excerpt:'robots.txt disallow HTTP 403'}]}),null);
console.log('Reader status passed: stage-aware errors, permission limits and browser fallback only for eligible failures.');
