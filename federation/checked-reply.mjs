/** Keep draft prose private until the existing answer checks have completed. */
export function checkedReply(options={}) {
  const started=performance.now();
  let firstDraft=null,stage=null,published=false;
  const progress=async event=>{stage=event.stage;await options.onProgress?.(event);};
  const draft=async text=>{
    if(!text || firstDraft!==null)return;
    firstDraft=Math.round(performance.now()-started);
    if(stage!=='checking_evidence')await progress({stage:'composing_answer',detail:'正在整理回答，核对后显示正文'});
  };
  return {
    options:{...options,deferAnswerUntilChecked:true,
      ...(options.onDelta?{onDelta:draft}:{}),
      ...(options.onUpdate?{onUpdate:event=>draft(event?.text)}:{}),
      onProgress:async event=>progress(event.stage==='writing_analysis'
        ? {...event,detail:options.analysis?'正在撰写报告，核对后显示正文':'正在整理回答，核对后显示正文'}:event),
      onAgentEvent:async event=>{
        // Provider text also travels on the native SSE channel. Suppressing
        // only onDelta would still leak a draft through that second channel.
        if(event.origin==='provider')return;
        await options.onAgentEvent?.(event);
      }},
    async publish(result) {
      if(published)throw new Error('本轮答复已发布');
      options.signal?.throwIfAborted();
      if(typeof result?.answer!=='string'||!result.answer.trim())throw new Error('没有可发布的最终答复');
      published=true;
      const elapsed=Math.round(performance.now()-started);
      await progress({stage:'answer_ready',detail:'回答已整理完成'});
      await options.onDelta?.(result.answer);
      return {...result,initial_reply:null,preliminary_reply:null,
        reply_delivery:{mode:'after_checks',draft_visible:false,release_ms:elapsed,
          check_status:result.answer_check?.status || result.analysis_run?.assertion_check?.status || 'not_needed'},
        timing:{...result.timing,model_first_text_ms:result.timing?.first_text_ms ?? null,
          draft_first_text_ms:firstDraft,answer_release_ms:elapsed,intake_first_text_ms:elapsed,
          first_text_ms:elapsed,intake_total_ms:elapsed,visible_chunks:options.onDelta?1:0}};
    }
  };
}
