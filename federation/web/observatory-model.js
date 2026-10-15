/* Read-only exploration of actual OpenWiki nodes. No generated knowledge. */
export const JOURNAL_KEY = 'openwiki.observatory.journal.v1';

export function nodeKind(node) {
  if (node?.isFederationHub) return 'space';
  return /(?:^|\/)sources(?:\/|$)/i.test(node?.id || '') ? 'source' : 'page';
}

export function catalogFor(graph) {
  const nodes = Array.isArray(graph?.nodes) ? graph.nodes.filter(n => n && typeof n.id === 'string' && typeof n.title === 'string') : [];
  return { nodes, byId: new Map(nodes.map(n => [n.id, n])),
    territories: nodes.filter(n => n.isFederationHub && n.spaceDepth === 1),
    spaces: nodes.filter(n => nodeKind(n) === 'space'),
    pages: nodes.filter(n => nodeKind(n) === 'page'),
    sources: nodes.filter(n => nodeKind(n) === 'source') };
}

export function plainExcerpt(node, limit = 150) {
  const body = String(node?.body || '');
  const experience = !node?.description && body.match(/^##\s+提炼经验\s*\r?\n([\s\S]*?)(?=^#{1,2}\s|$(?![\s\S]))/m)?.[1]?.trim();
  const text = String(node?.description || (experience ? `经验：${experience}` : body))
    .replace(/^---\s*\n[\s\S]*?\n---\s*\n/, '')
    .replace(/^#\s+([^\n]*)\n+/, (heading, title) => title.trim() === node?.title?.trim() ? '' : heading)
    .replace(/```[\s\S]*?```/g, ' ')
    .replace(/<[^>]*>/g, '')
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, '$1')
    .replace(/^[#>\s*-]+/gm, '').replace(/[`*_]/g, '');
  const clean = text.replace(/\s+/g, ' ').trim();
  return clean.length > limit ? clean.slice(0, limit) + '…' : clean;
}

export function searchNodes(nodes, query = '', territory = 'all', kind = 'all') {
  const words = query.trim().toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return nodes.filter(n => {
    if (territory !== 'all' && n.spaceId !== territory && !(n.ancestorSpaceIds || []).includes(territory)) return false;
    if (kind !== 'all' && nodeKind(n) !== kind) return false;
    const haystack = [n.title, n.description, n.body, ...(n.tags || []), ...(n.breadcrumb || [])].join(' ').toLocaleLowerCase();
    return words.every(word => haystack.includes(word));
  }).sort((a, b) => {
    if (!words.length) return a.title.localeCompare(b.title, 'zh-CN');
    const rank = n => words.reduce((s, w) => s + (n.title.toLocaleLowerCase().includes(w) ? 5 : 0), 0);
    return rank(b) - rank(a) || a.title.localeCompare(b.title, 'zh-CN');
  });
}

export function normalizeJournal(value) {
  const data = value && typeof value === 'object' && !Array.isArray(value) ? value : {};
  const ids = list => Array.isArray(list) ? [...new Set(list.filter(x => typeof x === 'string' && x.length < 500))].slice(0, 500) : [];
  const notes = Object.create(null);
  if (data.notes && typeof data.notes === 'object' && !Array.isArray(data.notes)) {
    for (const [key, text] of Object.entries(data.notes).slice(0, 500)) {
      if (typeof text === 'string' && key.length < 500 && !['__proto__', 'constructor', 'prototype'].includes(key)) notes[key] = text.slice(0, 2000);
    }
  }
  return { version: 1, visits: ids(data.visits), bookmarks: ids(data.bookmarks), notes };
}

export function chooseWander(nodes, visits = [], previous = '', random = Math.random) {
  const options = nodes.filter(n => n.id !== previous);
  const candidates = options.length ? options : nodes;
  const unseen = candidates.filter(n => !visits.includes(n.id));
  const pool = unseen.length ? unseen : candidates;
  return pool[Math.min(pool.length - 1, Math.max(0, Math.floor(random() * pool.length)))] || null;
}

export function visitedTerritories(catalog, visits) {
  const seen = new Set(visits);
  return catalog.territories.filter(t => catalog.nodes.some(n => seen.has(n.id) && (n.spaceId === t.spaceId || (n.ancestorSpaceIds || []).includes(t.spaceId))));
}

export function explorationRoutes(catalog) {
  const ideas = [
    { id: 'signal', title: 'HTML 表单验证', subtitle: '约束规则、错误状态、样式与 API。', label: '知识阅读', ids: ['software-frontend/constraint-validation', 'software-frontend/constraint-violations', 'software-frontend/css-validity-pseudo-classes', 'software-frontend/cva-api-methods'] },
    { id: 'creation', title: '从设计到开发与测试', subtitle: '查看设计、前端和测试三个分支。', label: '分支浏览', ids: ['software-uiux/index', 'software-frontend/index', 'software-testing/index'] },
    { id: 'story', title: '内容制作流程', subtitle: '查看策划、视觉、后期和运营分支。', label: '分支浏览', ids: ['content-planning/index', 'content-design/index', 'content-postproduction/index', 'content-operations/index'] },
  ];
  return ideas.map(route => ({ ...route, nodes: route.ids.map(id => catalog.byId.get(id)).filter(Boolean) })).filter(route => route.nodes.length > 1);
}

export function routeProgress(route, visits) {
  const seen = new Set(visits);
  return { done: route.nodes.filter(n => seen.has(n.id)).length, total: route.nodes.length,
    next: route.nodes.find(n => !seen.has(n.id)) || route.nodes[0] || null };
}

export function dailyNode(nodes, date = new Date()) {
  if (!nodes.length) return null;
  const key = `${date.getFullYear()}-${date.getMonth() + 1}-${date.getDate()}`;
  const seed = [...key].reduce((n, ch) => (n * 31 + ch.charCodeAt(0)) >>> 0, 0);
  const sorted = [...nodes].sort((a, b) => a.id.localeCompare(b.id));
  return sorted[seed % sorted.length];
}
