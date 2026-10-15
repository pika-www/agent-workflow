/** Shared host rules; extracted user statements never grant tool permissions. */
import {readFileSync} from 'node:fs';
const spec=JSON.parse(readFileSync(new URL('./requirement-rules.json',import.meta.url),'utf8'));
export const requirementRulesVersion=spec.version;
const hypothetical=new RegExp(spec.hypothetical,'i'),change=new RegExp(spec.change,'i');
const rules=spec.rules.map(r=>({...r,regex:new RegExp(r.pattern,'gi')}));
function normalized(value,mode) {
  if(mode==='compact_lower')return value.replace(/\s/g,'').toLowerCase();
  if(mode==='trim_lower')return value.trim().toLowerCase();
  if(mode==='set')return [...new Set(value.toLowerCase().split(/\s*(?:和|及|、|\/)\s*/))].sort().join('/');
  if(mode==='date'){const [year,month,day]=value.match(/\d+/g).map(Number);if(month<1||month>12||day<1||day>new Date(Date.UTC(year,month,0)).getUTCDate())return null;return `${year}-${String(month).padStart(2,'0')}-${String(day).padStart(2,'0')}`;}
  return value.trim();
}
export function requirementClaims(text) {
  const result=[];
  for(const raw of text.split(/(?<=[。！？；\n])/u)) {
    const sentence=raw.trim();if(!sentence||hypothetical.test(sentence))continue;
    const found=[];
    for(const rule of rules)for(const match of sentence.matchAll(rule.regex)) {
      if(rule.negation && /不要|不能|禁止|别再|不再|不是|不$/.test(sentence.slice(Math.max(0,match.index-4),match.index)))continue;
      const value=rule.value ?? normalized(match[1],rule.normalize);
      const start=Math.max(sentence.lastIndexOf('，',match.index-1),sentence.lastIndexOf(',',match.index-1))+1;
      const ends=[sentence.indexOf('，',match.index+match[0].length),sentence.indexOf(',',match.index+match[0].length)].filter(i=>i>=0);
      const clause=sentence.slice(start,ends.length?Math.min(...ends):sentence.length);
      if(value!=null)found.push([rule.slot,value,sentence,change.test(clause)]);
    }
    const corrected=new Map(found.filter(r=>r[3]).map(r=>[r[0],r]));
    const selected=found.filter(r=>!corrected.has(r[0])||corrected.get(r[0])===r).map(r=>r.slice(0,3));
    for(const claim of selected)if(!result.some(r=>JSON.stringify(r)===JSON.stringify(claim)))result.push(claim);
  }
  return result;
}
export function requirementDisplay(record) {
  const labels={react:'React',vue:'Vue',vue3:'Vue 3',angular:'Angular',svelte:'Svelte',flutter:'Flutter',taro:'Taro',local_only:'仅本地资料，不联网',online_requested:'用户提出联网需求，仍需宿主检查',preserve:'保留原始记录',delete_requested:'用户提出删除需求，尚未执行',zh:'中文',en:'英文'};
  return labels[record.value] || record.value;
}
