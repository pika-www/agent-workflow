/** Reference resolution stays inside model context, never an external search string. */
import {readFileSync} from 'node:fs';
const patterns=Object.fromEntries(Object.entries(JSON.parse(readFileSync(new URL('./conversation-patterns.json',import.meta.url),'utf8')))
 .map(([key,value])=>[key,new RegExp(value,'u')]));
export function conversationIntent(question='',memory) {
 const compact=question.replace(/[\s，。！？!?,.]/gu,'');
 const followup=compact.length<150 && !patterns.reset.test(compact) && !patterns.standalone_temporal_public.test(compact) && (patterns.followup.test(compact)||patterns.rephrase.test(compact));
 const rephrase=followup && patterns.rephrase.test(compact);
 // Only user-authored topic and corrections inform coverage/checking. Assistant
 // prose is available to the model for referents, but is not factual evidence.
 const focus=memory?.turn_focus;
 const recent=memory?.recent || [];
 const focusIndex=focus?recent.findIndex(m=>m.id===focus.source_message_id):-1;
 const scopedRecent=focus?focusIndex>=0?recent.slice(focusIndex):[]:recent;
 const context=followup?[focus?.question || memory?.goal,...(memory?.intent_clarifications || []).map(m=>m.content),...scopedRecent.filter(m=>m.role==='user'&&!m.truncated).slice(-4).map(m=>m.content)] : [];
 const topics=[...new Set(context.filter(value=>typeof value==='string' && value.trim() && value.length<=1800 && value!==question))];
 return {followup,rephrase,hasTopic:topics.length>0,
  question:topics.length?topics.join('\n')+'\n用户当前追问（以此为准）：'+question:question};
}
