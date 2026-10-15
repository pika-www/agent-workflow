/** Prefer an A lookup for short remote chat; keep host/TLS and IPv6-only fallback. */
import {lookup} from 'node:dns';
import {createRequire} from 'node:module';
const require=createRequire(new URL('../openwiki-tools/package.json',import.meta.url));
const agents=new Map();
export function ipv4FirstLookup(hostname,options,callback,resolve=lookup) {
  const original=typeof options==='object'?options:{family:options || 0};
  resolve(hostname,{...original,family:4},(error,address,family)=>{
    if(!error)return callback(null,address,family);
    if(!['ENOTFOUND','ENODATA','EAI_AGAIN'].includes(error.code))return callback(error);
    resolve(hostname,original,callback);
  });
}
export function remoteChatOptions(baseURL) {
  let url;try{url=new URL(baseURL || 'https://api.openai.com/v1');}catch{return {};}
  if(url.protocol!=='https:')return {};
  const {Agent,fetch}=require('undici');
  if(!agents.has(url.origin))agents.set(url.origin,new Agent({connect:{lookup:ipv4FirstLookup,timeout:10000}}));
  const dispatcher=agents.get(url.origin);
  return {fetch(input,init) {
    const target=new URL(typeof input==='string'||input instanceof URL?input:input.url);
    if(target.origin!==url.origin||!target.pathname.startsWith(url.pathname.replace(/\/$/,'')+'/'))throw new Error('Remote model transport target mismatch');
    return fetch(input,{...init,dispatcher,redirect:'error'});
  }};
}
