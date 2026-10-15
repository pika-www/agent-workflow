/** Real configured local Qwen over isolated, synthetic context only. */
import {readFile,writeFile} from 'node:fs/promises';
import {runIntakeTurn} from '../federation/intake-turn.mjs';
import {createModel} from '../openwiki-upstream/dist/agent/index.js';
Object.assign(process.env,{OPENAI_COMPATIBLE_BASE_URL:'http://127.0.0.1:11436/v1',OPENAI_COMPATIBLE_API_KEY:'ollama',OPENWIKI_REASONING_EFFORT:'none',OPENWIKI_OPENAI_COMPATIBLE_REASONING_EFFORT_SUPPORTED:'true'});
const input=JSON.parse(await readFile(process.argv[2],'utf8'));
const runtime={async loadOpenWikiEnv(){},resolveConfiguredProvider(){return 'openai-compatible';},resolveModelId(){return 'qwen3.5:9b';},resolveProviderRetryAttempts(){return 0;},createModel(...args){
  const model=createModel(...args);return {async invoke(...invokeArgs){const message=await model.invoke(...invokeArgs);if(args[3]===1200)await writeFile(process.argv[3]+'.summary-raw.json',JSON.stringify({content:message.content,usage:message.usage_metadata},null,2));return message;}};
}};
const empty={text:'',reads:[]};
const result=await runIntakeTurn('隔离记忆评估。按当前任务状态回答；旧助手文字不代表真实执行。明确冲突先请用户选择。只回答用户这次问题。','consultation',{wiki:empty,templates:empty,skills:empty},runtime,{currentQuestion:input.question,contextMemory:input.context});
await writeFile(process.argv[3],JSON.stringify(result,null,2));
