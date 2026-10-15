/** Explicit synthetic-data disclosures apply across the following report.
 * Claimed sources, execution and real results still need evidence.
 */
export function hypotheticalSections(prose) {
  const spans=[];
  let active=false, level=0;
  for(const match of prose.matchAll(/[^\n]+(?:\n(?!\s*\n)[^\n]+)*/gu)) {
    const paragraph=match[0], heading=/^\s*(#{1,6})\s+/u.exec(paragraph);
    const marker=/(?:数据|数值|数字|金额)(?:均|全部|全都)?(?:为|是|均为|采用|使用|仅为|仅作|仅用于)\s*(?:假设|虚构|模拟|示例|演示)|(?:假设|虚构|模拟|示例|演示)(?:的)?数据|\b(?:synthetic|fictional|hypothetical|simulated|dummy|sample) data\b/iu.exec(paragraph);
    const disclosure=marker && !/(?:不(?:要|是|用)|没有|禁止|并非|not|no|without)(?:使用|采用|提供|任何|\s)*$/iu.test(paragraph.slice(0,marker.index));
    const reality=/^(?:\s*#{1,6}\s*)?(?:[\d一二三四五六七八九十]+[.)、]\s*)?\**(?:真实(?:情况|数据|经营)|实际(?:情况|数据|经营)|现实中|回到现实|真实案例|real(?:[- ]world)? (?:data|results)|actual (?:data|results))/iu.test(paragraph);
    if(reality || heading && active && heading[1].length<=level)active=false;
    if(disclosure && !reality){active=true;level=heading?.[1].length || 0;}
    if(active)spans.push({start:match.index,end:match.index+paragraph.length});
  }
  return spans;
}

export function hypotheticalAssertion(text,start,end,spans) {
  if(!spans.some(span=>start>=span.start && end<=span.end))return false;
  // An example label cannot turn sources, product facts or completed work into fiction.
  return !/研究|实验|调查|METR|报告(?:指出|称|显示|表明|证明)|据(?:统计|报道)|实测|已核实|已(?:经)?(?:完成|部署|发布|执行|验证|修复)|(?:我|我们)(?:已|刚|正在)[^。！？]{0,25}(?:读取|查阅|查到|查看|查询|调用)|实际(?:营收|费用|价格|数据)|真实(?:营收|数据)|(?:页面|平台|产品)(?:提供|支持|采用)|\[Wiki:|https?:\/\/|\b(?:according to|research|study|studies|verified|deployed|published|real[- ]world|actual (?:revenue|price|data))\b/iu.test(text);
}
