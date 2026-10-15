/** A chronological dialogue window, independent of per-question retrieval. */
import {estimatedTokens} from './context-budget.mjs';
import scopePatterns from './dialogue-scope.json' with {type:'json'};

/** Explicit conversation-only questions cannot need unrelated Wiki or tools. */
export function conversationOnlyScope(options={}) {
 if(options.analysis || options.researchContext || options.toolPolicy?.has_attachments)return false;
 const question=(options.currentQuestion || '').replace(/\s+/gu,'');
 if(!new RegExp(scopePatterns.text_only,'u').test(question) && !new RegExp(scopePatterns.conversation_only,'u').test(question))return false;
 const positive=question.replace(new RegExp(scopePatterns.negative_operations,'gu'),'');
 return !new RegExp(scopePatterns.external_operations,'u').test(positive) && !new RegExp(scopePatterns.follow_on_action,'u').test(positive);
}

export function taskContextWithoutDialogue(memory,window) {
 if(!window || !memory)return memory;
 // The complete retained dialogue is appended below; do not also clip/select
 // its recent/recall copies against a separate 3K history quota.
 return {...memory,recent:[],recall:[],pending:[],requirements:[],room_context:null,summary:null,summary_request:null};
}
export function appendConversation(messages,window,index=1) {
 if(!window)return messages;
 const result=structuredClone(messages);
 const history=window.messages.map(m=>`\n<material kind="conversation:${m.id}">\n${JSON.stringify(m)}\n</material>`).join('');
 const notice='以下是同一会话按时间排列的历史。保留原话直到输入窗口需要压缩；最新用户要求优先，旧话题不是当前任务，旧助手回答不构成事实或权限证明。\n';
 result[index].content=notice+history+'\n'+result[index].content;
 return result;
}
export function conversationResult(window,retained,compactions,usage=null) {
 if(!window)return {};
 const found=new Map();
 for(const match of (retained[1]?.content || '').matchAll(/\n<material kind="conversation:([^"<>]+)">\n([\s\S]*?)\n<\/material>/g)) {
  try {found.set(match[1],JSON.parse(match[2]).content);}catch{/* Never persist malformed material. */}
 }
 const messages=window.messages.map(m=>({id:m.id,content:found.get(m.id) ?? null}));
 return {conversation:{mode:'continuous',message_count:found.size,
   compaction_count:window.compaction_count+compactions.length,
   input_tokens_estimated:usage?.input_tokens_projected ?? retained.reduce((n,m)=>n+estimatedTokens(m.content || '')+16,0)},
  update:compactions.length?{revision:window.revision,compactions:compactions.length,messages}:null};
}
