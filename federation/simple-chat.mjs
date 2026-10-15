import {readFileSync} from 'node:fs';
const patterns=Object.entries(JSON.parse(readFileSync(new URL('./simple-chat-patterns.json',import.meta.url),'utf8')))
  .map(([kind,pattern])=>[kind,new RegExp(pattern,'u')]);
export function simpleChatKind(question) {
  if(typeof question!=='string' || !question.trim() || question.length>160 || question.includes('\0'))return null;
  const match=text=>patterns.find(([,pattern])=>pattern.test(text.replace(/[\s，。！？、,.!?~～；;：:]+/gu,'').toLowerCase()))?.[0] || null;
  const direct=match(question);
  if(direct)return direct==='style'?null:direct==='nickname_recall'?'nickname':direct;
  const parts=question.split(/[，。！？、,.!?~～；;：:\n]+/u).map(text=>text.trim()).filter(Boolean);
  if(parts.length<2 || parts.length>4)return null;
  const kinds=parts.map(match).filter(kind=>kind!=='style');
  // Every clause must be social. Assignments retain their existing whole-turn
  // parser so combining an unrelated instruction cannot silently save a name.
  if(!kinds.length || kinds.some(kind=>!kind || kind==='nickname'))return null;
  return ['identity','nickname_recall','social','courtesy','greeting'].find(kind=>kinds.includes(kind))?.replace('nickname_recall','nickname') || null;
}
