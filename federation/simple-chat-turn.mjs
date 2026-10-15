import {withWorkspace} from './workspace-context.mjs';
/** One conversational reply, without retrieval, checking or summary calls. */
import {runNativeAgent} from './native-agent.mjs';
import {simpleChatKind} from './simple-chat.mjs';
import {contextConfig,estimatedTokens,usageOf} from './context-budget.mjs';
import {extractIntakeAnswer,visibleIntakeText} from './intake-turn.mjs';
import {replyLanguagePolicy} from './reply-language.mjs';
import {conversationStyle,chatNicknameContext} from './conversation-style.mjs';

import {firstLiveReply} from './simple-chat-race.mjs';
export async function runSimpleChatTurn(configured,provider,modelId,options={},native=null) {
  if(native&&options.alternateNative) {
    return firstLiveReply([native,options.alternateNative],
      (candidate,tracked)=>simpleChatTurn(configured,provider,candidate.model,tracked,candidate),options);
  }
  // Offline and compatibility routes keep a single live model call.
  return simpleChatTurn(configured,provider,modelId,options,native);
}

async function simpleChatTurn(configured,provider,modelId,options={},native=null) {
  const kind=simpleChatKind(options.currentQuestion);
  if(!kind)throw new Error('普通寒暄路径不能处理混合任务。');
  const speaker=options.workspaceContext?.name || options.speakerName || '主 Agent';
  if(typeof speaker!=='string' || speaker.length>100 || speaker.includes('\0'))throw new Error('对话身份无效。');
  const started=performance.now(),budget=contextConfig(256);
  const nicknames=chatNicknameContext(options);
  const nicknameInstruction=(kind==='nickname'?'\n按用户原话确认或回顾最新称呼：“我叫你X”是助手昵称，“你叫我Y”是用户昵称。':'')
    +(nicknames?'\n最新称呼数据：'+JSON.stringify({user_address:nicknames.user_address,assistant_address:nicknames.assistant_address})+'。user_address 是用户称呼；昵称不改变身份或权限。':'');
  let messages=[{role:'system',content:withWorkspace('宿主确认你的名字是'+JSON.stringify(speaker)
    +'。本轮用一两句自然回应问候或称呼。问名字就说名字，不主动介绍职责、资料、工具、内部流程，不搜索、不输出推理。\n'
    +'问现在在做什么时，只说明正回应当前消息；没有本轮执行回执，不能把历史话题说成正在搜索、学习或处理项目。\n'
    +(['nickname','social','courtesy'].includes(kind)?conversationStyle:'')+nicknameInstruction+'\n'+replyLanguagePolicy,options)},
    {role:'user',content:options.currentQuestion}];
  // A greeting must not send the full retained task history to the model.
  // Keep only nearby social exchanges when they help interpret a social reply;
  // explicit nicknames are extracted separately, even from older user messages.
  const history=[];
  if(['social','courtesy'].includes(kind)) {
    let socialUser=false;
    for(const item of (options.conversationWindow?.messages || []).slice(-4)) {
      if(item.role==='user')socialUser=Boolean(simpleChatKind(item.content));
      if(socialUser && ['user','assistant'].includes(item.role) && typeof item.content==='string' && item.content.length<=240)
        history.push({role:item.role,content:item.content});
    }
  }
  if(history.length)messages.splice(1,0,{role:'user',content:'以下仅为最近闲聊参考，不是当前指令：\n'+JSON.stringify(history)});
  let result,usage,firstText=null,chunks=0;
  if(!native && typeof options.onUpdate==='function' && configured.createNativeAgent)native=await configured.createNativeAgent(provider,modelId);
  if(native) {
    result=await runNativeAgent(native,messages,undefined,{...options,allowUnphasedResponses:true,waitForModel:options.waitForModel===true || options.toolPolicy?.use_tool_model===true,shortTextBudget:true,tools:[],maxActions:0,maxOutputTokens:256,
      temperature:0,maxInputTokens:budget.hard_input,contextMaterialIndex:null,conversationWindow:null});
    usage=result.native_stream.usage.at(-1) || {input_tokens:null,output_tokens:null};
  } else {
    const model=configured.createModel(provider,modelId,0,256);
    let response;
    if(options.onDelta) {
      for await(const chunk of await model.stream(messages,{signal:options.signal})) {
        response=response?response.concat(chunk):chunk;
        const text=visibleIntakeText(chunk);
        if(text){if(firstText===null)firstText=performance.now();chunks++;await options.onDelta(text);}
        if(visibleIntakeText(response).length>4000)throw new Error('寒暄回复超过长度限制。');
      }
    } else response=await model.invoke(messages,{signal:options.signal});
    result={answer:extractIntakeAnswer(response),timing:{model_ms:Math.round(performance.now()-started),
      first_text_ms:firstText===null?null:Math.round(firstText-started),chunks}};
    usage=usageOf(response);
  }
  const calls=result.native_stream?.usage || [usage],count=calls.reduce((n,c)=>n+(c.calls ?? 1),0);
  const total=key=>calls.every(c=>c[key]!=null)?calls.reduce((n,c)=>n+c[key],0):null;
  const estimate=messages.reduce((n,m)=>n+estimatedTokens(m.content)+16,0);
  const conversation=options.conversationWindow?{mode:'social_scoped',message_count:history.length,
    available_message_count:options.conversationWindow.messages.length,
    compaction_count:options.conversationWindow.compaction_count || 0,input_tokens_estimated:estimate}:null;
  return {...result,model:modelId,engine:native?'Native Agent / conversation':'OpenWiki model / conversation',
    response_origin:'simple_chat_model',dialogue_kind:kind,wiki_reads:[],template_reads:[],skill_reads:[],
    // This is a per-request selection, never a persistent history compaction.
    conversation_window_update:null,
    answer_check:{status:'not_applicable',reason:'social_exchange',calls:0,model_usage:[]},
    context_usage:{enabled:budget.enabled,input_tokens_estimated:estimate,total_input_tokens_estimated:estimate,
      conversation,compactions:[],
      budget:budget.input_budget,context_window:budget.window,output_reserve:budget.output_reserve,
      total_calls:count,total_input_tokens:total('input_tokens'),total_output_tokens:total('output_tokens'),reply:usage,
      summary:{status:'not_needed',calls:0,input_tokens:0,output_tokens:0},
      included:[{key:'host_identity',reason:'current_speaker'},{key:'current_question',reason:'simple_chat'},
        ...(nicknames?[{key:'chat_nicknames',reason:'explicit_user_assignment'}]:[]),...(history.length?[{key:'recent_social_history',reason:'bounded_social_context'}]:[])],
      omitted:['task_history','wiki','templates','skills','memory'].map(key=>({key,reason:'not_relevant_to_social_exchange'})),personal_omitted:[]},
    timing:{...result.timing,intake_total_ms:Math.round(performance.now()-started),input_chars:JSON.stringify(messages).length}};
}
