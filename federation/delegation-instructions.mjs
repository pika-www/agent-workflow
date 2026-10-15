/** Recover explicit role clauses without splitting quoted literals or JSON. */
export function explicitMemberTask(original, memberName, agentId) {
  if(typeof original!=='string' || typeof memberName!=='string')return null;
  const name=memberName.trim().replace(/\s*Agent$/u,'').trim();
  if(!name)return null;
  const escape=value=>value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
  const starts=new RegExp('^(?:请)?\\s*(?:'+escape(name)+'(?:\\s*Agent)?|'+escape(agentId)+')(?=\\s|[^A-Za-z]|$)','u');
  const parts=[];let start=0,quote=null,escaped=false,depth=0;
  const quotes={'"':'"','“':'”','‘':'’','「':'」'};
  for(let i=0;i<original.length;i++) {
    const char=original[i];
    if(quote) {
      if(escaped){escaped=false;continue;}
      if(char==='\\'){escaped=true;continue;}
      if(char===quote)quote=null;
      continue;
    }
    if(quotes[char]){quote=quotes[char];continue;}
    if(char==='{' || char==='['){depth++;continue;}
    if(char==='}' || char===']'){depth=Math.max(0,depth-1);continue;}
    // Preserve punctuation inside literal strings and JSON. A parent may
    // introduce the first member after a colon; subsequent members use ';'.
    if(!depth && (/[。；\n]/u.test(char) || char==='：' && starts.test(original.slice(i+1).trim()))) {
      parts.push(original.slice(start,i));start=i+1;
    }
  }
  parts.push(original.slice(start));
  const clauses=parts.map(value=>value.trim()).filter(value=>starts.test(value));
  // If the user did not assign this role directly, keep the model's task.
  return clauses.length ? clauses.join('。')+'。' : null;
}

/** This marker is written by the host, never inferred from planner output. */
export function originalTaskFromPrompt(prompt) {
  const marker='本轮用户原始请求（完整保留）：\n';
  const start=prompt.indexOf(marker);
  if(start>=0) {
    try { const value=JSON.parse(prompt.slice(start+marker.length).split('\n')[0]);
      if(typeof value==='string')return value;
    } catch {}
  }
  const match=prompt.match(/<conversation_history>\n([\s\S]*?)\n<\/conversation_history>/u);
  try { const messages=JSON.parse(match?.[1] || '[]');
    return messages.findLast(message=>message.role==='user')?.content || '';
  } catch { return ''; }
}
