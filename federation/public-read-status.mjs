/** Classify host reader errors only; page text and search snippets are not access rules. */
export function publicReadFailure(result) {
  if (!result || ['completed','partial'].includes(result.status)) return null;
  const known=['robots_blocked','robots_check_failed','login_required','access_restricted','rate_limited','article_http_error','no_readable_body','read_timeout','network_error'];
  const structured=[result,...(Array.isArray(result.errors)?result.errors:[])].find(e=>e && known.includes(e.code));
  if(structured)return structured.code;
  const errors=[result.error,...(Array.isArray(result.errors)?result.errors:[]).map(e=>typeof e==='string'?e:e?.error)]
    .filter(e=>typeof e==='string').join('\n');
  if (/robots(?:\.txt)?[^\n]{0,80}(?:不允许|禁止|disallow)/iu.test(errors)) return 'robots_blocked';
  if (/robots(?:\.txt)?[^\n]*(?:无法确认|检查|异常|HTTP)|无法确认 robots/iu.test(errors)) return 'robots_check_failed';
  if (/HTTP\s*401/iu.test(errors) || errors.split('\n').some(error=>
    /(?:必须|请先|需要)登录|requires? (?:a )?login|authentication required/iu.test(error)
    && !/可能|或|\b(?:may|might|could|or)\b/iu.test(error))) return 'login_required';
  if (/HTTP\s*(?:403|429)|forbidden|access denied|拒绝访问|访问被拒绝|请求过于频繁/iu.test(errors)) return 'access_restricted';
  // This extractor error is a reason to render the page, not proof of a login wall.
  if (/未提取到足够的可读正文|没有读到公开正文|没有可读取的公开浏览页面|正文不足|需要(?:执行)?脚本|javascript.*required/iu.test(errors)) return 'no_readable_body';
  if (/超时|timeout|timed out/iu.test(errors)) return 'read_timeout';
  if (/ENOTFOUND|ECONN|DNS|连接失败|连接中断|网络不可达|certificate|SSL|TLS/iu.test(errors)) return 'network_error';
  if (/HTTP\s*[45]\d\d/iu.test(errors)) return 'article_http_error';
  return null;
}

export function explicitlyDenied(result) {
  return ['robots_blocked','login_required','access_restricted'].includes(publicReadFailure(result));
}

/** Browser rendering cannot repair missing permission, throttling or HTTP errors. */
export function browserFallbackBlocked(result) {
  return explicitlyDenied(result) || ['robots_check_failed','rate_limited','article_http_error','network_error','read_timeout'].includes(publicReadFailure(result));
}

export function publicReadDetail(result) {
  const code=publicReadFailure(result);if(!code)return '';
  const item=[result,...(Array.isArray(result.errors)?result.errors:[])].find(e=>e && typeof e==='object' && e.code===code);
  const errors=[result.error,...(Array.isArray(result.errors)?result.errors:[]).map(e=>typeof e==='string'?e:e?.error)].filter(e=>typeof e==='string').join('\n');
  const http=item?.http_status || Number(errors.match(/HTTP\s*(\d{3})/iu)?.[1]);
  const count=Number.isInteger(item?.attempts)?item.attempts:null;
  const info=[http>=100&&http<=599?'HTTP '+http:'',count?'已尝试 '+count+' 次':''].filter(Boolean).join('，');
  const labels={robots_check_failed:'robots.txt 检查异常',robots_blocked:'robots.txt 明确禁止自动采集',login_required:'文章需要登录',access_restricted:'文章请求被拒绝',rate_limited:'网站要求暂缓请求',article_http_error:'文章请求失败',no_readable_body:'已取得页面，但未读到正文',read_timeout:'读取超时',network_error:'文章连接失败'};
  return labels[code]+(info?'（'+info+'）':'')+(code==='robots_check_failed'?'；尚未请求文章正文':code==='no_readable_body'?'；可尝试浏览器渲染':'')+(item?.retry_after?'；请在 '+Math.ceil(item.retry_after)+' 秒后重试':'');
}
