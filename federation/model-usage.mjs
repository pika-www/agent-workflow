/** Optional process-local receipts. No prompts, outputs or secrets are persisted. */
import {appendFileSync,lstatSync} from 'node:fs';
import {isAbsolute} from 'node:path';
import {randomUUID} from 'node:crypto';
const tracked=new WeakSet();
const count=v=>typeof v==='number'&&Number.isFinite(v)&&v>=0?v:null;
export function modelCounters(message) {
  const u=message?.usage_metadata || message?.response_metadata?.tokenUsage || message?.response_metadata?.usage || {};
  return {input_tokens:count(u.input_tokens ?? u.promptTokens ?? u.prompt_tokens),output_tokens:count(u.output_tokens ?? u.completionTokens ?? u.completion_tokens),cached_tokens:count(u.input_token_details?.cache_read ?? u.prompt_tokens_details?.cached_tokens)};
}
function write(file,record) {
  try {if(!isAbsolute(file))return;try{const s=lstatSync(file);if(!s.isFile()||s.isSymbolicLink())return;}catch(e){if(e.code!=='ENOENT')return;}appendFileSync(file,JSON.stringify(record)+'\n',{mode:0o600});}catch{/* Telemetry must not fail an answer. */}
}
export function startModelUsage(provider,modelId,file=process.env.FEDERATION_MODEL_USAGE_FILE) {
  const record={id:randomUUID(),provider,model:modelId,status:'started',calls:1,input_tokens:null,output_tokens:null,cached_tokens:null};
  if(file)write(file,record);
  return {finish(status,counters={}){const result={...record,...Object.fromEntries(['input_tokens','output_tokens','cached_tokens'].map(k=>[k,count(counters[k])])),status};if(file)write(file,result);return result;}};
}
export function trackModel(model,provider,modelId,file=process.env.FEDERATION_MODEL_USAGE_FILE) {
  if(!file || tracked.has(model))return model;
  const proxy=new Proxy(model,{get(target,key){
    if(key==='invoke')return async(...args)=>{
      const record={id:randomUUID(),provider,model:modelId,status:'started',calls:1,input_tokens:null,output_tokens:null,cached_tokens:null};write(file,record);
      try{const result=await target.invoke(...args);write(file,{...record,...modelCounters(result),status:'completed'});return result;}catch(e){write(file,{...record,status:'failed'});throw e;}
    };
    if(key==='stream')return async(...args)=>{
      const record={id:randomUUID(),provider,model:modelId,status:'started',calls:1,input_tokens:null,output_tokens:null,cached_tokens:null};write(file,record);
      let stream;try{stream=await target.stream(...args);}catch(e){write(file,{...record,status:'failed'});throw e;}
      return (async function*(){let complete=false,counters=modelCounters(null),deltas=false;try{for await(const chunk of stream){const next=modelCounters(chunk);if(chunk.usage_metadata)deltas=true;for(const k of Object.keys(next))if(next[k]!=null)counters[k]=chunk.usage_metadata?(counters[k]??0)+next[k]:deltas?counters[k]:next[k];yield chunk;}complete=true;}finally{write(file,{...record,...counters,status:complete?'completed':'interrupted'});}})();
    };
    const value=Reflect.get(target,key,target);return typeof value==='function'?value.bind(target):value;
  }});tracked.add(proxy);return proxy;
}
