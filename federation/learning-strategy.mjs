/** Pure learning policies, eligible for tested automatic improvement. */
export function rankSources(candidates, preferredHosts, query) {
  const terms = [...new Set([...new Intl.Segmenter('zh', {granularity: 'word'}).segment(query.toLowerCase())]
    .filter(part => part.isWordLike && part.segment.length >= 2)
    .map(part => part.segment))];
  const score = url => {
    const parsed = new URL(url);
    return (preferredHosts.includes(parsed.hostname) ? 10 : 0)
      + terms.filter(term => url.toLowerCase().includes(term)).length;
  };
  return [...new Set(candidates)].sort((a, b) => score(b) - score(a));
}

export function learningFocus(agent, history) {
  return {scope: agent.description,
    emphasis: history.last_success ? '优先补足现有知识缺口、核对来源变化和纠正失败经验。' : '先积累本行业能用于具体任务的基础方法与可靠来源。',
    previous: history.last_goal || ''};
}
