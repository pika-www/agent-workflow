/** Ordinary dialogue never enters forced research; explicit mixed tasks remain intact. */
import assert from 'node:assert/strict';
import {simpleChatKind} from '../federation/simple-chat.mjs';
import {defaultOnlineLookup} from '../federation/default-online.mjs';
import {conversationIntent} from '../federation/conversation-intent.mjs';
import {runNativeIntake} from '../federation/native-intake.mjs';
import {nativeAgentRuntime} from '../federation/native-agent.mjs';
const policy={default_online:true,network_allowed:true,tools_enabled:true,services:{search:{enabled:true}}};
const casual=['good， like you','I like you','Thank you so much!','今天有点累，想跟你聊聊','我有点失落','解释 list 和 tuple 的区别','怎么培养阅读习惯','为什么我总拖延','Thanks, that helps','Tell me a joke','今天看新闻看得好累','不用搜索，只想聊聊天'];
for(const q of casual)assert.equal(defaultOnlineLookup(q,policy),null,q);
for(const q of ['good， like you','I like you','Thank you so much!'])assert.ok(simpleChatKind(q),q);
for(const q of ['good, like you, search for current job openings','谢谢，顺便查找招聘平台','我喜欢你，帮我部署项目'])assert.equal(simpleChatKind(q),null,q);
for(const q of ['查找招聘平台的功能区别','今天有哪些 AI 新闻？','ChatGPT 当前价格','推荐适合团队的招聘软件','good, like you, search for current job openings'])assert.ok(defaultOnlineLookup(q,policy),q);
const memory={goal:'找招聘平台的软件功能',recent:[{role:'user',content:'找招聘平台的软件功能'}]};
for(const q of ['好的','继续','给我一点建议','说简单点'])assert.equal(defaultOnlineLookup(q,policy,{},conversationIntent(q,memory)),null,q);
assert.ok(defaultOnlineLookup('再找找呢',policy,{},conversationIntent('再找找呢',memory)));
const requests=[];
const native=nativeAgentRuntime({provider:'openai-compatible',model:'fixture'},{client:{chat:{completions:{async create(request){requests.push(request);return(async function*(){yield {choices:[{delta:{content:'可以先歇一会儿，慢慢聊。'},finish_reason:'stop'}]};})();}}}}});
const evidence={wiki:{text:'',reads:[],retrieval:{}},templates:{text:'',reads:[]},skills:{text:'',reads:[]}};
for(const question of ['good， like you','今天有点累，想跟你聊聊','解释 list 和 tuple 的区别']){
 const before=requests.length;
 const result=await runNativeIntake(native,{createModel(){throw Error('No evidence check needed for this conversational fixture');}},'规则','','',evidence,[],'openai-compatible','fixture',{
  currentQuestion:question,toolPolicy:policy,executeTool(){throw Error('Ordinary conversation must not trigger forced public research');}});
 assert.equal(requests.length,before+1);assert.equal(result.workflow.receipts.length,0);
 if(simpleChatKind(question))assert.equal(requests.at(-1).tools,undefined);
}
console.log('Ordinary chat: social/no-tool path, no forced search for explanations/advice, fresh public research and mixed-task guards passed.');
