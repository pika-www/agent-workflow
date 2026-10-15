import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
export async function semanticSearch(root,question) {
 const config=process.env.FEDERATION_EMBEDDING_CONFIG, database=process.env.FEDERATION_VECTOR_DATABASE,scope=process.env.FEDERATION_SPACE_ID;
 if(!config||!database||!scope)return {matches:[],reason:'not_configured'};
 return new Promise(resolve=>{
  const child=spawn(process.env.FEDERATION_TOOL_PYTHON||'python3',['-m','federation.vector_index'],{cwd:fileURLToPath(new URL('..',import.meta.url)),stdio:['pipe','pipe','ignore']});
  let output='',done=false;
  const finish=value=>{if(done)return;done=true;clearTimeout(timer);resolve(value);};
  const timer=setTimeout(()=>{child.kill('SIGKILL');finish({matches:[],reason:'embedding_timeout'});},8000);
  child.stdout.on('data',chunk=>{output+=chunk;if(output.length>200000){child.kill();finish({matches:[],reason:'invalid_embedding_response'});}});
  child.on('error',()=>finish({matches:[],reason:'embedding_unavailable'}));
  child.on('close',()=>{try{finish(JSON.parse(output));}catch{finish({matches:[],reason:'embedding_unavailable'});}});
  child.stdin.on('error',()=>{});
  child.stdin.end(JSON.stringify({root,question,config,database,scope,update_max:2}));
 });
}
export function fuseRanks(keyword,semantic) {
 const merged=new Map();
 [...keyword].sort((a,b)=>b[1].score-a[1].score||a[0].localeCompare(b[0])).forEach(([path,item],i)=>merged.set(path,{...item,score:1/(60+i+1),methods:['keyword']}));
 semantic.forEach((item,i)=>{
  const old=merged.get(item.path);
  merged.set(item.path,{...(old||{terms:new Set(),offset:item.offset}),score:(old?.score||0)+1/(60+i+1),semantic_score:item.score,methods:[...(old?.methods||[]),'vector']});
 });
 return merged;
}
