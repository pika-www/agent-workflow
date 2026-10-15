/** Bounded, extractive working context. Chat history and execution receipts stay intact. */
import {createHash} from 'node:crypto';
import {estimatedTokens} from './context-budget.mjs';
import {literalExcerpt} from './context-extract.mjs';
import {publicExcerpt} from './public-excerpt.mjs';
const hash=value=>createHash('sha256').update(value).digest('hex');
const materialPattern=()=>/\n<material kind="([^"<>]+)">\n([\s\S]*?)\n<\/material>/g;
const pinnedMaterial=/^(?:requirement_state|manual_correction|intent_clarifications|task_goal|project_memory|user_profile)$/;
const bodyKeys=new Set(['text','excerpt','content','summary','wiki','note','description','stdout','stderr','error']);
function excerpt(text,limit) {
 if(text.length<=limit)return text;
 const head=Math.floor(limit*.65),tail=Math.max(0,limit-head-35);
 return text.slice(0,head).replace(/[\uD800-\uDBFF]$/,'')+'\n[上下文摘录；省略部分保留在原记录]\n'+(tail?text.slice(-tail).replace(/^[\uDC00-\uDFFF]/,''):'');
}
function project(value,limit,question='') {
 if(Array.isArray(value))return value.map(item=>project(item,limit,question));
 if(!value||typeof value!=='object')return value;
 const out={...value};
 for(const [key,item] of Object.entries(value)) {
  if(typeof item==='string'&&bodyKeys.has(key)&&item.length>limit) {
   out[key]=literalExcerpt(item,limit,question);out.context_excerpt_truncated=true;
   if(key==='excerpt'){out.truncated=true;out.provided_excerpt_sha256=hash(out[key]);}
  } else if(item&&typeof item==='object')out[key]=project(item,limit,question);
 }
 return out;
}
/** Find the oldest prefix that fits in logarithmic full-request counts.
 * Each candidate starts from the same original; no repeated excerpting and no
 * changes to pinned material. Always verify the chosen request in full.
 */
function projectOldest(input,index,matches,replace,fits) {
 if(!matches.length||fits())return;
 const original=input[index].content;
 const replacements=matches.map(match=>replace(match));
 const apply=count=>{
  let cursor=0,content='';
  for(let i=0;i<count;i++){
   const match=matches[i];content+=original.slice(cursor,match.index)+replacements[i];cursor=match.index+match[0].length;
  }
  input[index].content=content+original.slice(cursor);
 };
 apply(matches.length);
 if(!fits())return;
 let low=1,high=matches.length;
 while(low<high){const mid=Math.floor((low+high)/2);apply(mid);if(fits())high=mid;else low=mid+1;}
 apply(low);
 // Token boundaries can be non-monotonic by a few tokens. Do not trust the
 // search to replace the exact capacity check before the provider request.
 while(!fits()&&low<matches.length)apply(++low);
}
export function retainedContextMaterials(input,index) {
 if(!Number.isInteger(index)||typeof input[index]?.content!=='string')return null;
 return [...input[index].content.matchAll(materialPattern())].filter(m=>/^(wiki|tools)(:|$)/.test(m[1]))
  .map(m=>({key:m[1],text:m[2],truncated:m[2].includes('context_excerpt_truncated'),sha256:hash(m[2])}));
}
export function nativeContextSize(input,tools=[],countTokens=null) {
 const encoded=JSON.stringify(input);
 return {tokens:countTokens?countTokens(encoded+JSON.stringify(tools)):estimatedTokens(encoded)+estimatedTokens(JSON.stringify(tools)),bytes:Buffer.byteLength(encoded)};
}
export function compactNativeContext(original,{maxTokens=30000,softTokens=maxTokens,tools=[],materialIndex=null,force=false,countTokens=null,question=''}={}) {
 // maxTokens already subtracts output reserve and protocol headroom. Keep the
 // complete working window below that limit, instead of compacting at 90%.
 const before=nativeContextSize(original,tools,countTokens),soft=Math.min(maxTokens,softTokens),target=Math.floor(soft*(force ? .6 : .78));
 if(!force&&before.tokens<=soft&&before.bytes<=450000)return {input:original,receipt:null};
 let input=structuredClone(original);
 const latestUser=input.findLastIndex(item=>item.role==='user');
 const fits=()=>{const n=nativeContextSize(input,tools,countTokens);return n.tokens<=target&&n.bytes<=400000;};
 const fitsHard=()=>{const n=nativeContextSize(input,tools,countTokens);return n.tokens<=maxTokens&&n.bytes<=400000;};
 // Current-turn public evidence outranks optional history and old retrievals.
 // Parse once and always excerpt from the original, never an earlier excerpt.
 const publicResults=new Map();
 for(let i=latestUser+1;i<input.length;i++){
  const item=input[i],key=item.type==='function_call_output'?'output':'content';
  if(!(item.type==='function_call_output'||item.role==='tool'||item.role==='system'&&item.content?.startsWith('宿主为本轮已授权的')))continue;
  const split=item.role==='system'?item[key].lastIndexOf('\n'):-1;
  try{
   const value=JSON.parse(item[key].slice(split+1)),result=value.result || value;
   if(result.sources?.some(s=>/^https?:\/\//.test(s.url||'')))publicResults.set(i,{item,key,prefix:item[key].slice(0,split+1),value,result});
  }catch{/* Preserve opaque provider data. */}
 }
 if(Number.isInteger(materialIndex)&&materialIndex!==latestUser&&typeof input[materialIndex]?.content==='string') {
  const dialogue=[...input[materialIndex].content.matchAll(materialPattern())].filter(m=>m[1].startsWith('conversation:'));
  // Work from oldest to newest; retain recent exchanges in full when possible.
  projectOldest(input,materialIndex,dialogue,match=>{
   try {
    const value=JSON.parse(match[2]);value.content=literalExcerpt(value.content,320,question);
    return `\n<material kind="${match[1]}">\n${JSON.stringify(value)}\n</material>`;
   }catch{return match[0];/* Never invent or repair invalid host material. */}
  },fits);
 }
 for(const limit of [1600,800,320,120]) {
  if(fits())break;
  for(let i=0;i<input.length;i++) {
   const item=input[i];
   if(publicResults.has(i))continue;
   // Opaque native reasoning and function calls are retained verbatim. Every
   // tool result keeps its original call_id, JSON structure and numeric values.
   if(item.type==='function_call_output'||item.role==='tool'||item.role==='system'&&item.content?.startsWith('宿主为本轮已授权的')) {
    const key=item.type==='function_call_output'?'output':'content';
    const split=item.role==='system'?item[key].lastIndexOf('\n'):-1;
    try {const raw=original[i];input[i]={...item,[key]:raw[key].slice(0,split+1)+JSON.stringify(project(JSON.parse(raw[key].slice(split+1)),limit,question))};}catch{/* Never corrupt non-JSON or native protocol data. */}
   } else if(i===materialIndex&&typeof item.content==='string') {
    input[i]={...item,content:item.content.replace(materialPattern(),(full,key,body)=>{
     if(pinnedMaterial.test(key)||key.startsWith('conversation:'))return full;
     let projected;try{projected=JSON.stringify(project(JSON.parse(body),limit,question));}catch{projected=literalExcerpt(body,limit,question);}
     return `\n<material kind="${key}">\n${projected}\n</material>`;
    })};
   } else if(i!==latestUser&&['user','assistant'].includes(item.role)&&!item.type&&!item.tool_calls&&typeof item.content==='string') {
    input[i]={...item,content:literalExcerpt(item.content,limit,question)};
   }
  }
  if(fits())break;
 }
 // If excerpts alone do not fit, omit optional evidence/old history. Confirmed
 // requirements, corrections, the latest user message and system rules are pinned.
 if(!fits()&&Number.isInteger(materialIndex)&&materialIndex!==latestUser) {
  const optional=[...input[materialIndex].content.matchAll(materialPattern())].filter(match=>!pinnedMaterial.test(match[1]));
  projectOldest(input,materialIndex,optional,()=>'',fits);
 }
 // Do not sacrifice fresh evidence merely to hit the soft 78% target. Only
 // project it if the actual model limit still requires it, with a body floor.
 for(const limit of [8000,4000,2400,1600]){
  if(fitsHard())break;
  for(const [i,{item,key,prefix,value,result}] of publicResults){
   const sources=result.sources.map(source=>{
    if(typeof source.excerpt!=='string')return source;
    const snippet=source.read_method==='search_result_snippet';
    let text=publicExcerpt(source.excerpt,snippet?Math.min(limit,600):limit,question);
    // A relevance selector can find only a few short blocks. Keep those blocks
    // plus literal surrounding material instead of falling below the floor.
    if(!snippet&&text.length<Math.min(1600,source.excerpt.length))text=(text+'\n\n'+source.excerpt).slice(0,limit);
    return text===source.excerpt?source:{...source,excerpt:text,truncated:true,context_excerpt_truncated:true,provided_excerpt_sha256:hash(text)};
   });
   const projected={...result,sources,context_excerpt_truncated:sources.some(s=>s.context_excerpt_truncated)};
   input[i]={...item,[key]:prefix+JSON.stringify(value.result?{...value,result:projected}:projected)};
  }
 }
 const after=nativeContextSize(input,tools,countTokens),changed=JSON.stringify(input)!==JSON.stringify(original);
 if(after.tokens>maxTokens||after.bytes>500000)throw new Error('自动压缩后，当前问题、必要规则与本轮证据仍超过模型可用上下文；完整记录已保留，不再把本轮正文压缩成无法核对的短句。');
 return {input,receipt:changed?{method:'extractive',stage:'runtime',before_tokens:before.tokens,after_tokens:after.tokens,budget_tokens:maxTokens,
  before_sha256:hash(JSON.stringify(original)),after_sha256:hash(JSON.stringify(input)),history_preserved:true}:null};
}
