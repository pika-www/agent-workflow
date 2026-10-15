/** At most two concurrent tool-free paths; transient failures may reconnect. */
export async function firstLiveReply(candidates,execute,options={},policy={}) {
  const hedgeAfterMs=policy.hedgeAfterMs ?? 1200,slowNoticeMs=policy.slowNoticeMs ?? 15000;
  const started=performance.now(),attempts=[],controllers=[],buffers=[];
  let winner=null,firstText=null,settled=false,hedge,deadline,flush=Promise.resolve();
  let resolveResult,rejectResult;
  const result=new Promise((resolve,reject)=>{resolveResult=resolve;rejectResult=reject;});
  const stop=()=>{clearTimeout(hedge);clearTimeout(deadline);options.signal?.removeEventListener('abort',cancel);};
  const fail=error=>{if(settled)return;settled=true;stop();controllers.forEach(c=>c.abort());rejectResult(error);};
  const cancel=()=>fail(options.signal.reason || new Error('Request cancelled'));
  const elapsed=()=>Math.round(performance.now()-started);
  async function publish(index,name,value,hasText=false) {
    if(settled)return;
    if(hasText&&winner===null) {
      winner=index;firstText=elapsed();clearTimeout(hedge);clearTimeout(deadline);
      for(let i=0;i<controllers.length;i++)if(i!==winner&&attempts[i].status==='running') {
        attempts[i].status='cancelled';attempts[i].elapsed_ms=elapsed()-attempts[i].started_ms;
        controllers[i].abort();buffers[i]=[];
      }
      // Flush provider events only for the selected reply, before its first text.
      flush=(async()=>{for(const [method,item] of buffers[index])await options[method]?.(item);buffers[index]=[];})();
    }
    if(winner===null){if(buffers[index].length>=256)throw new Error('Too many pre-text model events');buffers[index].push([name,value]);return;}
    if(winner!==index)return;
    await flush;await options[name]?.(value);
  }
  async function launch(index) {
    if(settled||winner!==null||attempts[index])return;
    const candidate=candidates[index],control=new AbortController();controllers[index]=control;buffers[index]=[];
    const row={model:candidate.model,protocol:candidate.protocol,status:'running',started_ms:elapsed(),calls:0};attempts[index]=row;
    const tracked={...options,signal:options.signal?AbortSignal.any([control.signal,options.signal]):control.signal,
      waitForModel:true,onModelCall:()=>{row.calls++;},
      onDelta:text=>publish(index,'onDelta',text,Boolean(text?.trim())),
      onUpdate:item=>publish(index,'onUpdate',item,Boolean(item?.text?.trim())),
      onAgentEvent:event=>{
        if(winner===null&&event.type==='agent.transport.retrying')buffers[index]=[];
        return publish(index,'onAgentEvent',event);
      },
      onCheckpoint:item=>publish(index,'onCheckpoint',item),
      onProgress:item=>settled||control.signal.aborted?undefined:winner===null&&item.stage==='reconnecting'
        ?options.onProgress?.(item):publish(index,'onProgress',item)};
    try {
      const answer=await execute(candidate,tracked);
      if(!answer?.answer?.trim())throw new Error('模型接口没有返回正文');
      if(control.signal.aborted||settled)return;
      // Non-streaming adapters can finish without invoking a text callback.
      if(winner===null)await publish(index,'onDelta',answer.answer,true);
      if(winner!==index)return;
      row.status='completed';row.elapsed_ms=elapsed()-row.started_ms;
      const totalCalls=attempts.reduce((sum,item)=>sum+Math.max(1,item.calls),0);
      settled=true;stop();
      resolveResult({...answer,model_transport:{strategy:'first_live_reply',winner:index,hedge_after_ms:hedgeAfterMs,
        first_text_ms:firstText,total_ms:elapsed(),attempts:structuredClone(attempts)},
        timing:{...answer.timing,first_text_ms:firstText,intake_total_ms:elapsed()},
        context_usage:{...answer.context_usage,...(attempts.length>1?{total_calls:totalCalls,
          total_input_tokens:null,total_output_tokens:null,usage_complete:false,
          total_input_tokens_estimated:Number.isFinite(answer.context_usage?.input_tokens_estimated)?answer.context_usage.input_tokens_estimated*totalCalls:null,
          usage_note:'Only the winning call returned complete usage; cancelled requests may still be billed.'}:{})}});
    } catch(error) {
      if(settled||control.signal.aborted)return;
      row.status='failed';row.elapsed_ms=elapsed()-row.started_ms;
      if(winner===index)return fail(error); // Never splice a second answer into visible text.
      if(options.signal?.aborted)return cancel();
      if(index===0&&candidates.length>1&&!attempts[1]){clearTimeout(hedge);void launch(1);}
      else if(attempts.length===candidates.length&&attempts.every(a=>a.status==='failed'))fail(error);
    }
  }
  if(options.signal?.aborted){cancel();return result;}
  options.signal?.addEventListener('abort',cancel,{once:true});
  // A slow first token is a progress update, never a reason to discard a turn.
  deadline=setTimeout(()=>{
    if(!settled&&winner===null)Promise.resolve(options.onProgress?.({stage:'waiting_model',detail:'模型响应较慢，仍在等待；连接异常会自动重试，可随时停止等待。'})).catch(fail);
  },slowNoticeMs);
  if(candidates.length>1)hedge=setTimeout(()=>{void launch(1);},hedgeAfterMs);
  void launch(0);
  return result;
}
