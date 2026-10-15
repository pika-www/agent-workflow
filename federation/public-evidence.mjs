/** Readable evidence from the exact public tool payload retained by the model. */
import {publicExcerpt} from './public-excerpt.mjs';
import {createHash} from 'node:crypto';
const hash=s=>createHash('sha256').update(s).digest('hex');
const publicTools=new Set(['web_search','web_read','visual_browser']);
const safeUrl=value=>{try{const u=new URL(value);return /^https?:$/.test(u.protocol)&&!u.username&&!u.password?u.href:null;}catch{return null;}};
export function publicToolInputs(observations=[]) {
 const inputs=[];
 observations.forEach((o,index)=>{
  if(!publicTools.has(o?.tool)||!['completed','partial'].includes(o.result?.status))return;
  (o.result.sources || []).forEach((s,n)=>{
   const url=safeUrl(s.url),excerpt=s.excerpt?.trim();
   if(!url||!excerpt)return;
   const snippet=o.tool==='web_search'||s.read_method==='search_result_snippet';
   const title=String(s.title || new URL(url).hostname).replace(/[\n\r]/g,' ').slice(0,180);
   // Do not mix JSON syntax, URLs and neighbouring sites into an evidence quote.
   const body=excerpt.slice(0,4000);
   const assessmentText=body.split('\n').flatMap(line=>line.match(/.{1,850}/gu) || []).join('\n');
   const text=[`来源标题：${title}`,`来源链接： ${url}`,snippet?'依据范围：搜索摘要，未读取网页正文。':'依据范围：实际读取的网页摘录，不代表独立核实或功能实测。',
    assessmentText].join('\n');
   inputs.push({path:`tool-receipt:${index}:source:${n}`,origin:'host_tool',text,claims:[],preserve_lines:true,
    source_url:url,source_title:title,source_excerpt:body,assessment_text:assessmentText,search_snippet:snippet,
    citation_label:`来源：<${url}>`,truncated:Boolean(s.truncated||excerpt.length>body.length),provided_sha256:hash(text)});
  });
 });
 // Body evidence must not be crowded out by search snippets of the same pages.
 const readUrls=new Set(inputs.filter(i=>!i.search_snippet).map(i=>i.source_url));
 return inputs.filter(i=>!i.search_snippet||!readUrls.has(i.source_url)).sort((a,b)=>Number(a.search_snippet)-Number(b.search_snippet));
}
export function hasAnswerBody(answer) {
 // A promise ending in a colon is not the promised deliverable. In particular,
 // evidence withdrawal must not leave "here is the report:" as a complete reply.
 const plain=answer.trim().replace(/\*\*|__/g,'');
 if(plain.length<260 && !plain.includes('\n') && /[：:]$/.test(plain)
   && /(?:以下|下面|如下|先给|给你|这是|这里是|here (?:is|are)|(?:report|example|table) below)/iu.test(plain))return false;
 return Boolean(answer.replace(/```[\s\S]*?```/g,' code example ')
  .replace(/\[[^\]\n]*\]\(https?:\/\/[^\s)]+\)/gu,'').replace(/<?https?:\/\/[^\s<>]+>?/gu,'')
  .replace(/\[Wiki:[^\]]*\]/gu,'').replace(/(?:来源|参考(?:资料|链接)?|Sources?|References?|链接)\s*[:：]?/giu,'')
  .replace(/[\s\p{P}\p{S}\d]/gu,''));
}
export function publicEvidenceFallback(inputs,{failed=false,question='',language='zh'}={}) {
 const english=language==='en';
 const choices=[],seen=new Set();
 const terms=[...(question.match(/[a-z][\w-]{2,}|[\u4e00-\u9fff]{2,}/giu)||[])].flatMap(t=>/^[a-z]/i.test(t)?[t.toLowerCase()]:[...t].slice(0,-1).map((_,i)=>t.slice(i,i+2)));
 for(const input of inputs){
  if(!input.source_url||seen.has(input.source_url))continue;
  seen.add(input.source_url);
  // Prefer task-related prose over a site's menu/footer, without inventing a summary.
  const lines=publicExcerpt(input.source_excerpt,800,question).split(/\n+/u).map(s=>s.trim()).filter(s=>s.length>=8);
  const score=s=>terms.reduce((n,t)=>n+Number(s.toLowerCase().includes(t)),0)-(/copyright|备案|版权所有|cookie|隐私政策|免责声明/iu.test(s)?8:0);
  const quote=lines.map((text,i)=>({text,i,score:score(text)})).sort((a,b)=>b.score-a.score||a.i-b.i).slice(0,2).sort((a,b)=>a.i-b.i).map(x=>x.text).join('\n');
  if(!quote)continue;
  const readable=quote.replace(/\[([^\]]+)\]\(https?:\/\/[^\s)]+\)/gu,'$1 ').replace(/\[[^\n]*$/u,'').slice(0,400);
  choices.push(english?`${input.source_title} (${input.search_snippet?'search snippet only':'page excerpt'}):\n\n> ${readable.replace(/\n/g,'\n> ')}\n\nSource: <${input.source_url}>`:`${input.source_title}（${input.search_snippet?'仅搜索摘要':'网页摘录'}）：\n\n> ${readable.replace(/\n/g,'\n> ')}\n\n${input.citation_label}`);
  if(choices.length===3)break;
 }
 if(!choices.length)return null;
 if(english)return (failed?'The automatic evidence check did not finish, so a reliable complete conclusion is not yet available.':'The available material does not support a complete conclusion.')
  +' These are excerpts retrieved during this turn:\n\n'+choices.join('\n\n')
  +'\n\nThese excerpts reflect statements on the pages or search snippets; unread feature details, real-world performance and publication times remain unconfirmed.';
 return (failed?'这次答复的自动核对没有完成，暂时无法给出可靠的完整结论。':'现有资料还不足以形成完整结论。')
  +'以下是本轮实际取得的原文片段，可先了解各来源提到的内容：\n\n'+choices.join('\n\n')
  +'\n\n这些摘录只代表页面或搜索摘要中的表述；未读到的功能细节、实际使用效果和发布时间仍无法确认。';
}
