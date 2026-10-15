/** Report credentials live outside Agent .env files and never enter prompts. */
import {open} from 'node:fs/promises';
import {constants} from 'node:fs';
import path from 'node:path';

const fields={
  'openai-compatible':['OPENAI_COMPATIBLE_API_KEY','OPENAI_COMPATIBLE_BASE_URL'],
  openai:['OPENAI_API_KEY','OPENAI_BASE_URL'],
  anthropic:['ANTHROPIC_API_KEY','ANTHROPIC_BASE_URL'],
  gemini:['GEMINI_API_KEY',null],
};

export async function reportRuntime(configured, filename) {
  if(!path.isAbsolute(filename))throw new Error('报告模型配置路径必须为绝对路径');
  const handle=await open(filename,constants.O_RDONLY|constants.O_NOFOLLOW);
  let config;
  try {
    const info=await handle.stat();
    if(!info.isFile() || info.size>16000 || (info.mode&0o077))throw new Error('报告模型配置必须为 600 权限的私有文件');
    try {config=JSON.parse(await handle.readFile('utf8'));}
    catch {throw new Error('报告模型配置不是有效 JSON，请在本机检查');}
  } finally {await handle.close();}
  if(!config || Array.isArray(config) || Object.keys(config).some(key=>!['provider','model','base_url','api_key','responses_api','reasoning_effort','simple_chat_fallback_model'].includes(key)) || !Object.hasOwn(fields,config.provider)
      || !/^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$/.test(config.model || '')
      || typeof config.api_key!=='string' || !config.api_key.trim() || config.api_key.length>4096 || /[\s\0-\x1f]/.test(config.api_key))
    throw new Error('深度报告模型配置无效');
  if(config.simple_chat_fallback_model!==undefined && !/^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$/.test(config.simple_chat_fallback_model))throw new Error('备用问候模型名无效');
  if(config.responses_api!==undefined && typeof config.responses_api!=='boolean')throw new Error('报告接口协议配置无效');
  if(config.reasoning_effort!==undefined && !['none','low','medium','high','xhigh','max'].includes(config.reasoning_effort))throw new Error('报告推理强度配置无效');
  if(config.base_url){
    if(config.provider==='gemini' || typeof config.base_url!=='string' || config.base_url.length>2000 || /[\s\0-\x1f]/.test(config.base_url))throw new Error('深度报告接口地址无效');
    let url;
    try {url=new URL(config.base_url);} catch {throw new Error('深度报告接口地址无效');}
    if(!['http:','https:'].includes(url.protocol)||url.username||url.password||url.search||url.hash
       ||(url.protocol==='http:'&&!['localhost','127.0.0.1','[::1]'].includes(url.hostname)))throw new Error('深度报告接口地址无效');
  } else if(config.provider==='openai-compatible')throw new Error('兼容服务缺少报告接口地址');
  const [keyField,urlField]=fields[config.provider];
  const changes={OPENWIKI_PROVIDER:config.provider,OPENWIKI_MODEL_ID:config.model,[keyField]:config.api_key,
    OPENWIKI_REASONING_EFFORT:config.reasoning_effort,
    OPENWIKI_OPENAI_COMPATIBLE_REASONING_EFFORT_SUPPORTED:String(config.reasoning_effort!==undefined),
    OPENWIKI_OPENAI_COMPATIBLE_USE_RESPONSES_API:String(config.responses_api===true),
    OPENWIKI_OPENAI_COMPATIBLE_STREAMING:'true',OPENWIKI_OPENAI_COMPATIBLE_STREAM_MESSAGES:'true'};
  if(urlField)changes[urlField]=config.base_url || undefined;
  return {provider:config.provider,modelId:config.model,
    publicConfig:{scope:'product_analysis',provider:config.provider,model:config.model,base_url:config.base_url || '',fallback:'disabled'},
    sanitizeError(error){return new Error(String(error?.message || '报告模型调用失败').split(config.api_key).join('[REDACTED]').slice(0,1000));},
    runtime:{...configured,
    async createNativeAgent({shortChat=false,alternate=false}={}){
      if(!shortChat&&!config.responses_api)return null;
      if(alternate&&!config.simple_chat_fallback_model)return null;
      return (await import('./native-agent.mjs')).nativeAgentRuntime(alternate?{...config,model:config.simple_chat_fallback_model,responses_api:!config.responses_api}:config,{shortChat});
    },createModel(provider,model,retries,maxTokens){
      // Each analysis runs in its own Node child. Restore environment immediately
      // after construction, so prefetch and any ordinary model stay unchanged.
      const saved=new Map(Object.keys(changes).map(key=>[key,process.env[key]]));
      try {
        for(const [key,value] of Object.entries(changes)){if(value===undefined)delete process.env[key];else process.env[key]=value;}
        return configured.createModel(provider,model,retries,maxTokens);
      } finally {for(const [key,value] of saved){if(value===undefined)delete process.env[key];else process.env[key]=value;}}
    }}};
}
