import {rankSources,learningFocus} from './learning-strategy.mjs';
const chunks=[];let size=0;
for await(const chunk of process.stdin){size+=chunk.length;if(size>50000)throw Error('策略输入超过预算');chunks.push(chunk);}
const input=JSON.parse(Buffer.concat(chunks).toString('utf8'));
const result=input.operation==='rankSources' ? rankSources(input.candidates,input.hosts,input.query)
  : input.operation==='learningFocus' ? learningFocus(input.agent,input.history) : null;
if(result===null)throw Error('未知学习策略');
process.stdout.write(JSON.stringify(result));
