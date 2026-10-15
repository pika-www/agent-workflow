/** Shared conversational tone; this changes expression, never tool authority. */
import {simpleChatKind} from './simple-chat.mjs';
export const conversationStyle = '聊天自然松弛，接得住玩笑、好感和戏谑昵称，不说教，不把一个称呼自动理解成性行为或现实关系。'
  +'沿用用户最新的聊天称呼，改口就更新；昵称不是实名，也不代表已保存长期记忆。普通打趣简短接话，不套“作为AI”或客服结尾；认真问身份和感情时如实回答。'
  +'例如“叫我老王”可答“好，老王。”，不评价昵称高低。别主动升级性描写或排他关系。具体风险才简短说明，事实核验、安全边界和工具权限照常。';

export function withConversationStyle(system) {
  return system.includes(conversationStyle) ? system : system+'\n'+conversationStyle;
}

/** Read only explicit nickname assignments, not assistant guesses or real names. */
export function chatNicknameContext(options={}) {
  const label='[a-z\\u3400-\\u9fff0-9_-]{1,12}?';
  const assignment=new RegExp('^(?:开个玩笑)?(?:你)?(?:以后|现在|从现在起)?(?:就)?(?:管我叫|称呼我|叫我|喊我)(?:我)?('+label+')'
    +'(?:就行|就好|吧)?(?:我(?:以后)?(?:就)?(?:管你叫|叫你|称呼你|喊你)('+label+')(?:就行|就好|吧)?)?$','iu');
  let userAddress=null,assistantAddress=null;
  for(const item of [...(options.conversationWindow?.messages || []),{role:'user',content:options.currentQuestion}]) {
    if(item.role!=='user'||typeof item.content!=='string'||item.content.length>160)continue;
    const compact=item.content.replace(/[\s，。！？、,.!?~～；;：:]+/gu,'')
      .replace(/^别(?:再)?(?:叫|喊|称呼)(?:我)?[a-z\u3400-\u9fff0-9_-]{1,12}?了(?=(?:叫我|称呼我|喊我))/iu,'');
    if(simpleChatKind(compact)!=='nickname')continue;
    const parsed=compact.match(assignment);
    if(parsed){userAddress=parsed[1];if(parsed[2])assistantAddress=parsed[2];}
  }
  const current=options.currentQuestion;
  // Host memory was selected from original, non-forgotten user messages.
  // It is newer than stale retained history; an explicit current assignment wins.
  const assigned=typeof current==='string' && assignment.test(current.replace(/[\s，。！？、,.!?~～；;：:]+/gu,''));
  if(options.workspaceContext && !assigned)return options.workspaceContext.nicknames || null;
  return userAddress?{user_address:userAddress,assistant_address:assistantAddress,scope:'current_conversation'}:options.workspaceContext?.nicknames || null;
}
