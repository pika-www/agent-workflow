/** Extract literal middle passages without inventing summary facts. */
export const EXCERPT_MARKER='\n[上下文摘录；省略部分保留在原记录]\n';
export function literalExcerpt(text,limit,question='') {
 if(text.length<=limit)return text;
 const words=(question.toLowerCase().match(/[a-z0-9_]{2,}|[\u4e00-\u9fff]{2,}/g)||[]);
 const terms=[...new Set(words.flatMap(w=>/^[\x00-\x7f]+$/.test(w)?[w]:Array.from({length:w.length-1},(_,i)=>w.slice(i,i+2))))].filter(t=>!['什么','怎么','如何','现在','之前','我们','这个','项目','一下','的是'].includes(t));
 const important=/必须|不能|不要|保留|更正|改为|取消|预算|截止|失败|风险|证据|https?:\/\/|\d+(?:\.\d+)?[%元天秒]/u;
 const blocks=[...text.matchAll(/[^\n。！？]{1,240}[\n。！？]?/gu)].map(m=>({at:m.index,text:m[0],score:terms.filter(t=>m[0].toLowerCase().includes(t)).length*4+(important.test(m[0])?2:0)}));
 let remaining=Math.max(0,limit-EXCERPT_MARKER.length*2);const selected=[];
 for(const b of blocks.sort((a,b)=>b.score-a.score||a.at-b.at)){
  if(remaining<16||selected.length===3)break;
  const piece=b.text.slice(0,remaining).replace(/[\uD800-\uDBFF]$/,'');
  selected.push({...b,text:piece});remaining-=piece.length;
 }
 return selected.sort((a,b)=>a.at-b.at).map(b=>b.text).join(EXCERPT_MARKER);
}
