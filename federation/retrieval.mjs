/** Query expansion uses explicit aliases and real link neighbours, not invented facts. */
import concepts from './retrieval-concepts.json' with {type:'json'};
const aliases = [
  ['盈利','赚钱','变现','收费','商业模式','收入','成本','盈亏','monetization','pricing'],
  ['拉新','获客','增长','市场','运营','激活','留存','growth','retention'],
  ['检索','查资料','知识库','RAG','retrieval'],
  ['幻觉','编造','事实','可靠性','评估','验证','evaluation','hallucination'],
  ['用户需求','用户任务','场景','痛点','产品定位','jobs','JTBD'],
  ['工作流','固定流程','workflow','动态决策','agent','智能体'],
  ['交互','体验','界面','设计','UI','UX','可用性'],
];
const stop = new Set(['我们','你们','这个','那个','现在','所有','本轮','问题','回答','请问','你的','自己','分别','哪些','如何','什么','以及','可以','一下','行业','资料','怎么','请先','两句话','清楚','只用','本库','联网','根据']);
export function cleanQuery(question) {
  return question.replace(/@[^\n@]{1,100}?Agent(?![A-Za-z0-9_])/gi,'').trim();
}
export function queryTerms(question) {
  question=cleanQuery(question);
  const original = [...new Intl.Segmenter('zh',{granularity:'word'}).segment(question)]
    .filter(p=>p.isWordLike && p.segment.length>=2 && !stop.has(p.segment)).map(p=>p.segment);
  const direct = [...new Set(original)].slice(0,12);
  const expanded = [...aliases.filter(group=>group.some(term=>question.toLowerCase().includes(term.toLowerCase()))).flat(),
    ...Object.values(concepts).filter(spec=>spec.triggers.some(term=>question.includes(term))).flatMap(spec=>spec.terms)];
  return [...new Set([...direct,...expanded])].slice(0,32).map(term=>({term,weight:direct.includes(term)?3:1}));
}
export function relevance(ranked, terms) {
  const hits=[...ranked.values()].map(item=>({score:item.score,matched_terms:[...item.terms]}));
  const best=hits.sort((a,b)=>b.score-a.score)[0];
  return {method:'keyword-alias-ranking-and-wiki-links',confidence:!best?'none':best.score>=6?'high':'low',
    missing_evidence:!best || best.score<3,query_terms:terms.map(item=>item.term),
    note:'相关度用于决定是否补查，不证明资料中的事实正确；未使用向量模型。'};
}
