/** Enforce only explicit, mechanical output limits; this is not factual review. */
import {explicitTextOnlyRules} from './delegated-text.mjs';
function requiredLiterals(task) {
  const literals = [];
  for (const match of task.matchAll(/(?:必须|务必|请)?(?:原样|逐字)?(?:包含|保留)((?:“[^”\n]{1,120}”|‘[^’\n]{1,120}’|「[^」\n]{1,120}」|"[^"\n]{1,120}"|[^。；\n]){1,300})/gu)) {
    if (/不要|不得|不能|禁止|不必|无需/u.test(task.slice(Math.max(0, match.index - 5), match.index))) continue;
    for (const quoted of match[1].matchAll(/[“‘「]([^”’」\n]{1,120})[”’」]|"([^"\n]{1,120})"/gu)) {
      literals.push(quoted[1] || quoted[2]);
    }
  }
  return [...new Set(literals)];
}

export function outputContract(task, phase, originalTask = '') {
  if (!['execute', 'summary'].includes(phase)) return null;
  let lengthText = task;
  if (phase === 'summary') {
    const clauses = task.match(/[^。；\n]*汇总[^。；\n]*/gu) || [];
    lengthText = clauses.map(clause => clause.slice(clause.lastIndexOf('汇总') + 2)).join('；');
    lengthText += '；' + (originalTask.match(/(?:两级|各级|所有)汇总[^。；\n]{0,60}/gu) || []).join('；');
  } else if (originalTask) {
    // A planner's shorter assignment must not erase a user limit shared by all
    // execution members. Role-specific limits are not applied to other roles.
    lengthText += '；' + (originalTask.match(/(?:每(?:名|位|个)(?:执行)?成员|所有(?:执行)?成员|各(?:执行)?成员|成员(?:各|均))[^。；\n]{0,60}/gu) || []).join('；');
  }
  const limits = [...lengthText.matchAll(/(?:最多|不超过|不得超过|限制在|上限(?:为|是)?|[<≤]=?)\s*(\d{1,5})\s*(?:字|字符)|(?:\b|(?<!\d))(\d{1,5})\s*(?:字|字符)(?:以内|内)|字数\s*[<≤]=?\s*(\d{1,5})\b/gu)]
    .map(match => Number(match[1] || match[2] || match[3])).filter(value => value > 0 && value <= 10000);
  const inherited = originalTask ? requiredLiterals(originalTask).filter(value => task.includes(value)) : [];
  const contract = {max_characters: limits.length ? Math.min(...limits) : null,
    required_literals: [...new Set([...requiredLiterals(task),...inherited])]};
  if(explicitTextOnlyRules(originalTask))contract.text_only_no_execution=true;
  const count=phase==='execute' && task.match(/(?:给出|提供|列出)([两二三四五2-5])(?:条|项)(?:回滚|发布前)?检查/u);
  if(count)contract.check_items=({两:2,二:2,三:3,四:4,五:5})[count[1]]||Number(count[1]);
  const field=phase==='execute' && task.match(/(?:返回|输出)包含\s*`?([A-Za-z_][A-Za-z0-9_]*)`?\s*的[^。；\n]{0,12}\bJSON\b/iu);
  if(field) {
    contract.json_fields=[field[1]];
    if(/标识|编号/u.test(task))contract.json_string_fields=[field[1]];
  }
  const literal=phase==='execute' && task.match(/(?:返回|输出)\s*(?:严格|极简)?\s*JSON\s*(\{(?:"(?:\\.|[^"\\])*"|[^{}"])*\})/iu);
  if(literal) {
    let value;try{value=JSON.parse(literal[1]);}catch{}
    if(value && typeof value==='object' && !Array.isArray(value)
      && Object.keys(value).length>0 && Object.keys(value).length<=8
      && Object.values(value).every(v=>v===null || ['string','number','boolean'].includes(typeof v))) {
      contract.json_fields=Object.keys(value);
      contract.json_constants=value;
      contract.json_string_fields=Object.keys(value).filter(key=>typeof value[key]==='string' && value[key].length>0);
    }
  }
  return contract.max_characters || contract.required_literals.length || contract.json_fields || contract.check_items || contract.text_only_no_execution ? contract : null;
}

export function unsupportedExecutionClaims(answer) {
  return answer.split(/[。！？；\n]/u).filter(sentence=>{
    const match=sentence.match(/(?:验证|测试|验收|核验|检查)(?:已|均|全部|全部已)?(?:通过|完成)|已(?:经)?(?:部署|回滚|修改|修复|运行|执行|上线)|(?:执行|完成)(?:了)?(?:\d+|[一二两三四五六七八九十]+)条检查|(?:加载|渲染|启动|发布|部署)(?:页面|界面|确认页|服务)?(?:已|均)?(?:成功|完成)/u);
    if(!match)return false;
    const prefix=sentence.slice(0,match.index),suffix=sentence.slice(match.index+match[0].length);
    // A requested UI status label is content to display, not a report that
    // the described operation occurred. Keep actual success claims checked.
    if (/^(?:指示|提示|图标|文案|字样|标签)/u.test(suffix)
      && /(?:显示|展示|设计|文案)/u.test(prefix)) return false;
    if(/建议|计划|如果|只有|须|应当|需要|需先|待|不代表|不声称|不得声称|没有|尚未|未$/u.test(prefix)
      || /^(?:后|才|再|方可|前)/u.test(suffix))return false;
    return true;
  }).map(sentence=>sentence.trim());
}

export function outputViolations(answer, contract) {
  if (!contract) return [];
  const issues = [];
  if(contract.text_only_no_execution)
    for(const claim of unsupportedExecutionClaims(answer))issues.push('本轮仅交付文字，无实际操作回执，必须撤回无依据的执行或验证声明：'+claim);
  if (contract.max_characters && [...answer].length > contract.max_characters)
    issues.push(`正文为 ${[...answer].length} 字符，超过 ${contract.max_characters} 字符上限`);
  for (const value of contract.required_literals)
    if (!answer.includes(value)) issues.push('缺少指定原文：' + value);
  const suffix=contract.required_literals.length?'\n约束：'+contract.required_literals.join('；')+'。':'';
  const prose=(suffix && answer.endsWith(suffix)?answer.slice(0,-suffix.length):answer).trimEnd();
  if(contract.max_characters && !contract.json_fields
    && /(?:不得|不能|不|以及|并且|依赖|通过|使用|必须|需要|[，、：])$/u.test(prose)
    && !contract.required_literals.some(value=>prose.endsWith(value)))
    issues.push('正文在条件或谓语中途结束，须改写为完整短句');
  if(contract.check_items) {
    const numbered=[...answer.matchAll(/(?:^|[\n\s：:；;。])(\d+)[.、．]\s*([^\n]+)/gu)];
    const numbers=[...answer.matchAll(/(?:^|[\n\s：:；;。])(\d+)[.、．]/gu)].map(m=>Number(m[1]));
    if(numbers.length!==contract.check_items || numbers.some((n,i)=>n!==i+1) || !numbered.length)
      issues.push('必须逐项交付 '+contract.check_items+' 条检查内容');
  }
  // Reproduce a provider leaking a closing JSON wrapper into its answer value.
  // Keep valid JSON/code excerpts unchanged; do not silently strip user text.
  if(!answer.includes('{') && /[”"]\s*\}\s*$/u.test(answer)
    && !contract.required_literals.some(value=>value.endsWith(answer.match(/[”"]\s*\}\s*$/u)[0].trim())))
    issues.push('正文末尾含没有对应起始括号的 JSON 包装残片');
  if(contract.json_fields) {
    let value;try{value=JSON.parse(answer);}catch{}
    if(!value || Array.isArray(value) || typeof value!=='object'
      || contract.json_fields.some(field=>!Object.hasOwn(value,field))
      || (contract.json_string_fields || []).some(field=>typeof value[field]!=='string' || !value[field].trim())
      || contract.json_constants && (Object.keys(value).length!==contract.json_fields.length
        || Object.entries(contract.json_constants).some(([key,expected])=>value[key]!==expected)))
      issues.push('正文必须是包含指定字段的 JSON 对象');
  }
  return issues;
}

export async function enforceOutputContract(task, phase, answer, rewrite, originalTask = '') {
  const contract = outputContract(task, phase, originalTask);
  if (!contract) return {answer, receipt: {status:'not_requested', calls:0}};
  const violations = outputViolations(answer, contract);
  const receipt = {status:'passed', calls:0, contract, original_characters:[...answer].length,
    violations, semantic_correctness:'not_evaluated'};
  if (!violations.length) return {answer, receipt};
  const tail=answer.match(/[”"]\s*\}\s*$/u)?.[0];
  if(tail && !answer.includes('{') && !task.includes(tail.trim()) && !originalTask.includes(tail.trim())) {
    const normalized=answer.slice(0,-tail.length).trimEnd();
    if(normalized && !outputViolations(normalized,contract).length)
      return {answer:normalized,receipt:{...receipt,status:'normalized',original_answer:answer,
        final_characters:[...normalized].length,removed_unmatched_wrapper:tail}};
  }
  // Preserve actual identifiers during shortening. A rewrite cannot substitute
  // its own identifier for a value produced by an upstream member.
  const identifiers = [...new Set(answer.match(/\b[A-Z][A-Z0-9]{1,20}-\d{2,20}\b/gu) || [])];
  const result = await rewrite({task, answer, contract, violations, preserve_identifiers:identifiers});
  if (typeof result !== 'string' || !result.trim()) throw new Error('任务产物纠正没有返回正文');
  const revised = result.trim();
  const remaining = outputViolations(revised, contract);
  if (identifiers.some(value => !revised.includes(value))) remaining.push('纠正丢失了实际标识');
  const allowedIdentifiers = new Set([...identifiers, ...contract.required_literals.flatMap(value => value.match(/\b[A-Z][A-Z0-9]{1,20}-\d{2,20}\b/gu) || [])]);
  if ((revised.match(/\b[A-Z][A-Z0-9]{1,20}-\d{2,20}\b/gu) || []).some(value => !allowedIdentifiers.has(value)))
    remaining.push('纠正新增了没有依据的标识');
  if (remaining.length) throw new Error('任务产物纠正后仍未通过输出约束：' + remaining.join('；'));
  return {answer:revised, receipt:{...receipt,status:'repaired',calls:1,
    final_characters:[...revised].length, original_answer:answer,
    required_literals_source:'task_original_appended_by_host'}};
}
