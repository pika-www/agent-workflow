/** Background continuation memory only: no answer, tools or Wiki writes. */
import {contextConfig,updateSummary} from './context-budget.mjs';
import {configuredRuntime} from './intake-turn.mjs';
const chunks=[];let size=0;
for await(const chunk of process.stdin){size+=chunk.length;if(size>400000)throw new Error('后台摘要输入超过预算');chunks.push(chunk);}
const memory=JSON.parse(Buffer.concat(chunks).toString('utf8'));
const runtime=await configuredRuntime();
const provider=runtime.resolveConfiguredProvider(),model=runtime.resolveModelId({},provider);
const result=await updateSummary(runtime,provider,model,memory,contextConfig());
process.stdout.write(JSON.stringify({update:result.update||null,receipt:{...result.receipt,provider,model}})+'\n');
