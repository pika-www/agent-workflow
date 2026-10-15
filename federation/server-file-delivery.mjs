/** Bounded delivery of an explicit server-file selection to this same chat.
 * Resolve only user-authored, contiguous requests. Other questions use the Agent.
 * The host records actual tool receipts; no provider call is needed to copy files.
 */
import {createHash} from 'node:crypto';

const kinds={视频:'video',音频:'audio',图片:'image',文档:'document'};
const compact=text=>String(text || '').trim().replace(/[\s，。！？!?、,]+/gu,'');
const selection=text=>/^(?:所有的?|全部|都要|全部发给我|都发给我|全部发来|都发来)$/u.test(compact(text))?'all':
 /^(?:最新的?|最新一个|最新的一个|发最新的|最新的发给我)$/u.test(compact(text))?'latest':null;
const chase=text=>/^(?:[？?]+|继续|继续发送|接着发|发出来|还没收到|怎么没发|视频发不出来)$/u.test(String(text || '').trim());
function direct(text) {
 const match=compact(text).match(/^(?:请|帮我|请帮我)?(?:把|将)?(?:服务器|服务端)(?:上|里)?(?:的)?(?:(所有|全部|最新)(?:的)?)?(视频|音频|图片|文档)(?:文件)?(?:(全部|都))?(?:发给我|发我|发过来|发来|返回本聊天)$/u);
 return match?{kind:kinds[match[2]],label:match[2],selection:match[1]==='最新'?'latest':match[1] || match[3]?'all':null}:null;
}
export function serverFileDeliveryRequest(options={}) {
 const policy=options.toolPolicy,service=policy?.services?.server_files;
 if(options.analysis || options.researchContext || policy?.has_attachments || !policy?.tools_enabled
    || !service?.configured || service.runtime_location!=='server')return null;
 const question=options.currentQuestion,current=direct(question);
 if(current?.selection)return current;
 let chosen=selection(question);
 if(!chosen&&!chase(question))return null;
 const history=options.conversationWindow?.messages ?? options.contextMemory?.recent ?? [];
 // A completed host delivery contains real attachment links. A bare nudge
 // after that must not export the same set again.
 if(chase(question)) {
  const previous=history.findLast(m=>m.role==='assistant');
  if(/\/api\/chat\/rooms\/[a-f0-9]{32}\/files\/[a-f0-9]{32}/u.test(previous?.content || ''))return null;
 }
 const users=history.filter(m=>m.role==='user'&&!m.truncated&&typeof m.content==='string').slice(-6);
 if(users.at(-1)?.content===question)users.pop();
 for(const message of users.reverse()) {
  const request=direct(message.content);
  if(request)return chosen || request.selection?{...request,selection:chosen || request.selection}:null;
  const prior=selection(message.content);
  if(prior){chosen ||= prior;continue;}
  if(chase(message.content))continue;
  return null; // A topic change, cancellation or narrower target ends inheritance.
 }
 return null;
}

const hash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');
const label=text=>String(text).replace(/[\\\[\]`*_<>]/gu,'\\$&').replace(/[\r\n]/gu,' ');
const validArtifact=(a,room)=>a && /^[a-f0-9]{32}$/u.test(a.id || '') && /^[a-f0-9]{32}$/u.test(a.room_id || '')
 && (!room || a.room_id===room) && /^[a-f0-9]{64}$/u.test(a.sha256 || '') && typeof a.name==='string'
 && a.url===`/api/chat/rooms/${a.room_id}/files/${a.id}`;

export async function runServerFileDelivery(options={}) {
 const request=serverFileDeliveryRequest(options);
 if(!request || typeof options.executeTool!=='function')return null;
 const started=performance.now(),receipts=[],observations=[],artifacts=[],failures=[];
 const execute=async(action,parameters)=>{
  options.signal?.throwIfAborted();
  const args={action,parameters:JSON.stringify(parameters)},call_id='host-delivery-'+(receipts.length+1);
  const target=(action+(parameters.path?' '+parameters.path:'')).slice(0,180);
  // Reuse the supported stream envelope; origin remains host_tool and this
  // route has no native provider messages or model usage.
  await options.onAgentEvent?.({origin:'host_tool',protocol:'chat_completions',type:'agent.tool.started',call_id,name:'server_files',target});
  await options.onProgress?.({stage:'using_tool',detail:action==='find'?'正在查找服务器文件':`正在准备附件 ${artifacts.length+1}`});
  const before=performance.now();let result;
  try{result=await options.executeTool('server_files',args);}
  catch(error){options.signal?.throwIfAborted();result={status:'failed',error:String(error.message).slice(0,300)};}
  const receipt={call_id,tool:'server_files',args,origin:'host_workflow',status:result.status || 'completed',
   started_ms:Math.round(before-started),elapsed_ms:Math.round(performance.now()-before),output_sha256:hash(result)};
  receipts.push(receipt);observations.push({tool:'server_files',result});
  await options.onObservation?.('server_files',result);
  await options.onAgentEvent?.({origin:'host_tool',protocol:'chat_completions',type:'agent.tool.completed',call_id,name:'server_files',target,
   status:receipt.status,elapsed_ms:receipt.elapsed_ms,output_sha256:receipt.output_sha256});
  return result;
 };
 const found=await execute('find',{kind:request.kind});
 const entries=[...new Map((found.status==='completed'?found.entries || []:[])
  .filter(row=>row.kind==='file'&&typeof row.path==='string').map(row=>[row.path,row])).values()]
  .sort((a,b)=>(b.modified || 0)-(a.modified || 0)||a.path.localeCompare(b.path));
 const selected=request.selection==='latest'?entries.slice(0,1):entries;
 // Bound work and retained bytes independently of the model tool-call budget.
 let bytes=0,attempted=0;
 for(const entry of selected) {
  if(attempted>=31 || bytes+entry.bytes>200_000_000)break;
  attempted++;bytes+=Math.max(0,entry.bytes || 0);
  const result=await execute('attach',{path:entry.path});
  const delivered=(result.artifacts || []).filter(a=>validArtifact(a,options.conversationWindow?.room_id));
  if(result.status==='completed'&&delivered.length)artifacts.push(...delivered);
  else failures.push({path:entry.path,error:result.error || '未取得有效附件回执'});
 }
 const omitted=selected.length-attempted;
 let answer=artifacts.length?`已将${request.selection==='latest'?'最新的 ':''}${artifacts.length} 个${request.label}附在这条回复中，可以打开或下载。\n\n`
  +artifacts.map(a=>`- [${label(a.name)}](${a.url})`).join('\n'):
  found.status!=='completed'?`这次未能查询服务器文件：${found.error || '未取得查询回执'}。`:
  entries.length?'找到了文件，但这次没有成功添加附件。':`这次在常用数据目录中没有找到${request.label}。`;
 if(failures.length)answer+='\n\n以下文件未发送成功：\n'+failures.map(f=>`- ${label(f.path.split('/').at(-1))}：${label(f.error)}`).join('\n');
 if(omitted)answer+=`\n\n本次达到批量上限（31 个文件或累计 200 MB），还有 ${omitted} 个候选未处理。`;
 if(found.truncated || found.errors?.length)answer+='\n\n部分目录未能完整检索；上面只包含本次实际找到并成功导出的文件。';
 else if(artifacts.length)answer+='\n\n查找范围为服务器常用数据目录，源文件保持不变。';
 const elapsed=Math.round(performance.now()-started);
 await options.onDelta?.(answer);
 return {answer,model:null,engine:'Host server file delivery',response_origin:'host_server_file_delivery',artifacts,
  wiki_reads:[],template_reads:[],skill_reads:[],
  workflow:{scope:'chat-scoped-tools',receipts,observations,model_usage:[],gaps:failures.map(f=>f.error),max_actions:32},
  server_delivery:{...request,found:entries.length,delivered:artifacts.length,failed:failures.length,omitted,truncated:Boolean(found.truncated)},
  answer_check:{status:'host_verified',reason:'server_file_attachment_receipts',calls:0,model_usage:[]},
  context_usage:{total_calls:0,total_input_tokens:0,total_output_tokens:0,included:[],omitted:[],summary:{status:'not_needed',calls:0}},
  timing:{model_ms:0,provider_ms:0,tool_ms:elapsed,first_text_ms:elapsed,answer_check_ms:0,intake_total_ms:elapsed,chunks:1}};
}
