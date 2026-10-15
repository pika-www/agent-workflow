/** Estimate the next request with a tokenizer, calibrated to provider receipts. */
import {createRequire} from 'node:module';
import {createHash} from 'node:crypto';
import {estimatedTokens} from './context-budget.mjs';
const require=createRequire(new URL('../openwiki-upstream/package.json',import.meta.url));
let encoder;
export function contextTokenCounter(runtime,receipts=[],shortText=null) {
 const key=createHash('sha256').update(JSON.stringify([runtime.provider,runtime.model,runtime.base_url,runtime.protocol])).digest('hex');
 // A tiny, tool-free request can use a conservative UTF-8 byte bound without
 // initializing the large tokenizer. This is never a measured token count.
 // Larger/custom workspaces and ordinary turns retain the exact tokenizer.
 if(typeof shortText==='string' && Buffer.byteLength(shortText)<=6000) {
  const local=text=>Buffer.byteLength(text)+256;
  const last=receipts.find(r=>r.counting_model_key===key&&r.context_counting==='utf8_byte_upper_bound'&&Number.isFinite(r.input_tokens)&&Number.isFinite(r.local_input_tokens_estimated));
  const overhead=last?Math.max(0,last.input_tokens-last.local_input_tokens_estimated):0;
  return {local,count:text=>local(text)+overhead,key,method:'utf8_byte_upper_bound'};
 }
 if(!/^gpt-|^o[134](?:-|$)/i.test(runtime.model))return {count:estimatedTokens,local:estimatedTokens,key,method:'estimated_han_utf8_with_15pct_margin'};
 encoder ??= createRequire(require.resolve('@langchain/core'))('js-tiktoken').getEncoding('o200k_base');
 // One request is counted by the capacity guard and again for its usage
 // receipt. Keep a small per-turn cache; never tokenize identical input twice.
 const cache=new Map();
 const local=text=>{
  if(cache.has(text))return cache.get(text);
  const tokens=encoder.encode(text,[],[]).length;
  if(cache.size>=4)cache.delete(cache.keys().next().value);
  cache.set(text,tokens);return tokens;
 };
 const last=receipts.find(r=>r.counting_model_key===key&&r.context_counting!=='utf8_byte_upper_bound'&&Number.isFinite(r.input_tokens)&&Number.isFinite(r.local_input_tokens_estimated));
 // Count the whole request once; a provider may add a private system prelude.
 // Apply only observed positive overhead and refresh it after each reply.
 const overhead=last?Math.max(0,last.input_tokens-last.local_input_tokens_estimated):0;
 return {local,count:text=>local(text)+overhead,key,
  method:last?'o200k_base_with_provider_receipt':'o200k_base_estimate'};
}
