/** Current calendar questions use a fresh host clock, never remembered dates. */
const englishQuestion=text=>!/[\u3400-\u9fff]/u.test(text) && /[a-z]/iu.test(text);
const confirmation=text=>/^(?:你确定(?:吗|么)?|确定(?:吗|么)?|真的吗|你确认(?:吗|么)?|再确认一下|are\s+you\s+sure|really|can\s+you\s+confirm)[?？!！。\s]*$/iu.test(text.trim());
export const needsClockContext=question=>typeof question==='string' && /今天|今日|现在|当前|昨天|明天|今年|本月|这周|本周|下周|最近|最新|日期|时间|几号|星期|周几|\b(?:today|tomorrow|yesterday|now|current|latest|recent|date|time|this\s+(?:week|month|year))\b/iu.test(question);
export function clockQuestion(question) {
  if (typeof question !== 'string' || question.length > 160) return null;
  const language=englishQuestion(question)?'en':'zh';
  const english=question.normalize('NFKC').toLowerCase().replace(/[’]/g,"'")
    .replace(/^(?:(?:hello|hi|hey)[\s,!，]+|please\s+|(?:can\s+you\s+)?tell\s+me\s+)+/u,'')
    .replace(/[?!.,]+$/gu,'').trim().replace(/\s+/gu,' ');
  if (/^(?:what(?:'s| is)(?: the)? (?:date(?: today| now)?|day(?: today| is it(?: today)?)|today)|what (?:day|date) is (?:it(?: today)?|today)|what is today's date|today's date)(?: (?:in )?(?:utc|beijing|shanghai)(?: time)?)?$/u.test(english))
    return {timezone:/\butc\b/u.test(english)?'UTC':'Asia/Shanghai',kind:'date',language};
  if (/^(?:what(?:'s| is) (?:the (?:current )?time|the time now)|what time is it(?: now)?)(?: (?:in )?(?:utc|beijing|shanghai)(?: time)?)?$/u.test(english))
    return {timezone:/\butc\b/u.test(english)?'UTC':'Asia/Shanghai',kind:'time',language};
  let text=question.replace(/[\s，。！？、,.!?：:]+/gu,'').toLowerCase();
  let timezone='Asia/Shanghai';
  if (/utc|世界协调时|协调世界时/.test(text)) timezone='UTC';
  text=text.replace(/北京时间|中国时间|上海时间|utc|世界协调时|协调世界时/gu,'')
    .replace(/^(?:你好|您好|嗨)/u,'')
    .replace(/^[那哪](?=现在|今天|今日|当前)/u,'')
    .replace(/^(?:请问|请告诉我|告诉我|看一下|查一下|查询一下)/u,'').replace(/(?:呢|呀|啊|吗)$/u,'');
  if (/^(?:现在|今天|今日|当前)(?:是)?(?:几{1,2}年(?:几月(?:几[号日])?)?|哪一年|几月(?:几[号日])?|几[号日]|什么日期|什么日子|日期|星期几|周几)$/u.test(text)
    || /^(?:今天|今日|当前)(?:的)?日期(?:是什么|是多少)?$/u.test(text)) return {timezone,kind:'date',language};
  if (/^(?:现在|当前)(?:是)?(?:几点(?:几分)?|什么时间|时间是多少)$/u.test(text)) return {timezone,kind:'time',language};
  return null;
}

/** Resolve only a confirmation of the immediately preceding clock topic. */
export function clockRequest(options={}) {
  if (options.analysis || options.researchContext || options.toolPolicy?.has_attachments) return null;
  const direct=clockQuestion(options.currentQuestion);
  if(direct)return direct;
  if(typeof options.currentQuestion!=='string' || !confirmation(options.currentQuestion))return null;
  const history=options.conversationWindow?.messages ?? options.contextMemory?.recent ?? [];
  const users=history.filter(m=>m.role==='user' && typeof m.content==='string');
  for(const message of users.slice(-4).reverse()) {
    if(confirmation(message.content))continue;
    const previous=clockQuestion(message.content);
    return previous?{...previous,language:englishQuestion(options.currentQuestion)?'en':'zh',confirmation:true}:null;
  }
  return null;
}

export function clockAnswer(question, now=new Date(), request=clockQuestion(question)) {
  if (!request || !Number.isFinite(now.getTime())) return null;
  const parts=Object.fromEntries(new Intl.DateTimeFormat('zh-CN',{timeZone:request.timezone,
    year:'numeric',month:'numeric',day:'numeric',weekday:'long',hour:'2-digit',minute:'2-digit',hourCycle:'h23'})
    .formatToParts(now).map(p=>[p.type,p.value]));
  const zone=request.timezone==='UTC'?'UTC':'北京时间';
  let answer=`${request.kind==='time'?'现在':'今天'}是 ${parts.year} 年 ${parts.month} 月 ${parts.day} 日，${parts.weekday}`
    +(request.kind==='time'?` ${parts.hour}:${parts.minute}`:'')+`（${zone}）。`;
  if(request.language==='en') {
    const date=new Intl.DateTimeFormat('en-US',{timeZone:request.timezone,year:'numeric',month:'long',day:'numeric',weekday:'long'}).format(now);
    answer=`${request.kind==='time'?'It is':'Today is'} ${date}`+(request.kind==='time'?`, ${parts.hour}:${parts.minute}`:'')+` (${request.timezone==='UTC'?'UTC':'Beijing time'}).`;
  }
  if(request.confirmation)answer=(request.language==='en'?'According to the current system clock, ':'按本机当前时间，')+answer.replace(/^Today/u,'today').replace(/^It/u,'it');
  return {answer,clock:{checked_at:now.toISOString(),timezone:request.timezone,source:'host_system_clock'}};
}

export function withHostClock(system,now=new Date()) {
  const value={checked_at:now.toISOString(),timezone:'Asia/Shanghai',source:'host_system_clock',
    local_time:clockAnswer('现在几点',now).answer};
  const policy='本轮时钟优先于历史日期；日期问答不联网，新闻发布日期另行查证。';
  return system.replace(/\n<host_clock>[^]*?<\/host_clock>/gu,'').replace('\n'+policy,'')+'\n<host_clock>'+JSON.stringify(value)+'</host_clock>\n'+policy;
}

export async function runClockTurn(options={}) {
  const result=clockAnswer(options.currentQuestion,new Date(),clockRequest(options));
  if (!result) return null;
  if (typeof options.onDelta==='function') await options.onDelta(result.answer);
  return {...result,model:null,engine:'Host clock',response_origin:'host_clock',wiki_reads:[],template_reads:[],skill_reads:[],
    answer_check:{status:'host_verified',reason:'host_system_clock',clock:result.clock,calls:0,model_usage:[]},
    context_usage:{total_calls:0,total_input_tokens:0,total_output_tokens:0,included:[],omitted:[],summary:{status:'not_needed',calls:0}},
    timing:{model_ms:0,provider_ms:0,tool_ms:0,first_text_ms:0,answer_check_ms:0,intake_total_ms:0,chunks:1}};
}
