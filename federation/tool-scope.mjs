/** Honor an explicit single-tool restriction without inventing a tool or ID. */
export function exclusiveRequestedTool(question) {
  if(typeof question!=='string')return null;
  const matches=[...question.matchAll(/(?:只|仅)(?:允许)?(?:调用|使用)\s*(?:工具\s*)?[`「“"']?([a-z][a-z0-9_]{2,60})\b/gu)];
  const names=[...new Set(matches.map(m=>m[1]))];
  return names.length===1?names[0]:null;
}
