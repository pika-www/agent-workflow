/** Exploration is computed from real graph fixtures; no browser, model or disk writes. */
import assert from 'node:assert/strict';
import {
  JOURNAL_KEY, nodeKind, catalogFor, plainExcerpt, searchNodes,
  normalizeJournal, chooseWander, visitedTerritories, explorationRoutes,
  routeProgress, dailyNode,
} from '../federation/web/observatory-model.js';

const hub = (spaceId, depth, ancestors = []) => Object.freeze({
  id: `${spaceId}/index`, title: spaceId, spaceId, spaceDepth: depth,
  isFederationHub: true, ancestorSpaceIds: Object.freeze(ancestors),
});
const page = (id, title, options = {}) => Object.freeze({
  id, title, spaceId: id.split('/')[0], isFederationHub: false,
  ancestorSpaceIds: Object.freeze(['central', 'software']),
  tags: Object.freeze([]), breadcrumb: Object.freeze([]), ...options,
});
const nodes = Object.freeze([
  hub('central', 0), hub('software', 1, ['central']),
  hub('content', 1, ['central']), hub('software-uiux', 2, ['central', 'software']),
  hub('software-frontend', 2, ['central', 'software']), hub('software-testing', 2, ['central', 'software']),
  hub('content-planning', 2, ['central', 'content']),
  page('software-frontend/constraint-validation', '表单 Validation', { body: '原生 HTML 表单。', tags: Object.freeze(['constraints']) }),
  page('software-frontend/constraint-violations', '异常状态', { description: 'validation 规则与错误状态' }),
  page('software-frontend/css-validity-pseudo-classes', 'CSS 状态', { body: 'validity 伪类' }),
  page('software-frontend/sources/mdn', 'MDN 来源', { body: 'validation 原始来源' }),
  page('content-planning/story', '故事中的表单', { body: 'validation 情节', ancestorSpaceIds: Object.freeze(['central', 'content']) }),
]);
const original = JSON.stringify(nodes);
const catalog = catalogFor({ nodes });

// Empty and malformed graph payloads are safe; sources do not count as knowledge pages.
for (const graph of [null, undefined, {}, { nodes: null }, { nodes: 'bad' }]) {
  const empty = catalogFor(graph);
  assert.equal(empty.nodes.length, 0);
  assert.equal(empty.byId.size, 0);
  assert.deepEqual(explorationRoutes(empty), []);
  assert.equal(dailyNode(empty.pages), null);
  assert.equal(chooseWander(empty.nodes), null);
}
assert.equal(catalogFor({ nodes: [null, {}, { id: 'bad' }, { title: 'bad' }, nodes[0]] }).nodes.length, 1);
assert.equal(nodeKind({ id: 'software/sources/index', isFederationHub: true }), 'space');
assert.equal(nodeKind({ id: 'software/SOURCES/manual' }), 'source');
assert.equal(nodeKind({ id: 'software/sources' }), 'source');
assert.equal(nodeKind({ id: 'software/resources/page' }), 'page');
assert.equal(nodeKind({ id: 'software/my-sources/page' }), 'page');
assert.equal(catalog.spaces.length, 7);
assert.equal(catalog.pages.length, 4);
assert.equal(catalog.sources.length, 1);
assert.deepEqual(catalog.territories.map(n => n.spaceId), ['software', 'content']);
assert.equal(catalog.byId.get(nodes[7].id), nodes[7]);

// Query words, ancestry, and content kind are intersected; a child is discoverable from its territory.
assert.deepEqual(searchNodes(nodes, '  VALIDATION  表单  ', 'software', 'page').map(n => n.id), ['software-frontend/constraint-validation']);
assert.deepEqual(searchNodes(nodes, 'validation', 'software', 'source').map(n => n.id), ['software-frontend/sources/mdn']);
assert.deepEqual(searchNodes(nodes, 'validation', 'content', 'page').map(n => n.id), ['content-planning/story']);
assert.equal(searchNodes(nodes, '', 'unknown').length, 0);
assert.equal(searchNodes(nodes, 'constraints', 'software-frontend', 'page')[0].id, nodes[7].id);
assert.deepEqual(searchNodes(nodes, 'validation', 'software', 'page').map(n => n.id), [nodes[7].id, nodes[8].id], 'A title match ranks ahead of a description match');
assert.equal(searchNodes(nodes, '', 'software', 'space').length, 4);
assert.equal(searchNodes(nodes, 'missing word', 'all').length, 0);

// Excerpts strip presentation syntax rather than exposing frontmatter or fenced code.
const excerpt = plainExcerpt({ body: '---\nprivate: metadata\n---\n# 标题\n\n```js\nsecretCode()\n```\n[说明](https://example.invalid) **重点** <b>正文</b>' });
assert.equal(excerpt, '标题 说明 重点 正文');
assert.equal(plainExcerpt({ description: '  精确   摘要  ', body: '其他正文' }), '精确 摘要');
assert.equal(plainExcerpt({ body: '123456789' }, 5), '12345…');
assert.equal(plainExcerpt(null), '');

// Restored storage is bounded and normalized, including hostile prototype-shaped keys.
assert.match(JOURNAL_KEY, /^openwiki\./);
for (const value of [null, undefined, 'corrupt', 12, [], true]) {
  const restored = normalizeJournal(value);
  assert.equal(restored.version, 1);
  assert.deepEqual(restored.visits, []);
  assert.deepEqual(restored.bookmarks, []);
  assert.equal(Object.keys(restored.notes).length, 0);
}
const stored = JSON.parse('{"version":999,"visits":["one","one",null,1,"two"],"bookmarks":["two",false,"two"],"notes":{"__proto__":"unsafe","constructor":"unsafe","prototype":"unsafe","one":"<img src=x onerror=alert(1)>","bad":{},"nested":[]}}');
const storedBefore = JSON.stringify(stored);
const journal = normalizeJournal(stored);
assert.deepEqual(journal.visits, ['one', 'two']);
assert.deepEqual(journal.bookmarks, ['two']);
assert.equal(Object.getPrototypeOf(journal.notes), null);
assert.deepEqual(Object.keys(journal.notes), ['one']);
assert.equal(journal.notes.one, '<img src=x onerror=alert(1)>', 'Notes remain plain data; UI is responsible for text rendering');
assert.equal(JSON.stringify(stored), storedBefore);
const excessive = normalizeJournal({
  visits: [...Array.from({ length: 700 }, (_, i) => `node-${i}`), 'x'.repeat(500)],
  bookmarks: [null, 'y'.repeat(500), 'valid'],
  notes: { valid: '字'.repeat(3000), ['z'.repeat(500)]: 'invalid-key' },
});
assert.equal(excessive.visits.length, 500);
assert.deepEqual(excessive.bookmarks, ['valid']);
assert.equal(excessive.notes.valid.length, 2000);
assert.deepEqual(Object.keys(excessive.notes), ['valid']);
assert.equal(Object.keys(normalizeJournal({ notes: Object.fromEntries(Array.from({ length: 600 }, (_, i) => [`id-${i}`, 'note'])) }).notes).length, 500);

// Wander prioritizes unseen nodes and avoids the immediately previous node whenever alternatives exist.
const candidates = Object.freeze(catalog.pages.slice(0, 3));
assert.equal(chooseWander(candidates, [candidates[0].id, candidates[1].id], '', () => 0), candidates[2]);
assert.equal(chooseWander(candidates, [], candidates[0].id, () => 0), candidates[1]);
assert.equal(chooseWander(candidates, candidates.map(n => n.id), candidates[2].id, () => 1), candidates[1]);
assert.equal(chooseWander([candidates[0]], [candidates[0].id], candidates[0].id, () => 0), candidates[0]);
assert.equal(chooseWander(candidates, [], '', () => -1), candidates[0]);
assert.equal(chooseWander(candidates, [], '', () => 9), candidates[2]);
const visits = [];
let previous = '';
for (let i = 0; i < candidates.length; i++) {
  const chosen = chooseWander(candidates, visits, previous, () => 0);
  assert.ok(!visits.includes(chosen.id));
  visits.push(chosen.id); previous = chosen.id;
}
assert.equal(new Set(visits).size, candidates.length);

// Routes expose only existing graph IDs and do not invent a complete route for a single surviving stop.
const routes = explorationRoutes(catalog);
assert.deepEqual(routes.map(r => r.id), ['signal', 'creation']);
assert.equal(routes[0].nodes.length, 3, 'The absent cva-api-methods stop is excluded');
assert.ok(routes.flatMap(r => r.nodes).every(n => catalog.byId.get(n.id) === n));
assert.deepEqual(explorationRoutes(catalogFor({ nodes: [nodes[7]] })), []);
const route = routes[0];
assert.deepEqual(routeProgress(route, []), { done: 0, total: 3, next: route.nodes[0] });
assert.deepEqual(routeProgress(route, [route.nodes[0].id, route.nodes[0].id, 'missing']), { done: 1, total: 3, next: route.nodes[1] });
assert.deepEqual(routeProgress(route, route.nodes.map(n => n.id)), { done: 3, total: 3, next: route.nodes[0] });
assert.deepEqual(routeProgress({ nodes: [] }, ['missing']), { done: 0, total: 0, next: null });
assert.deepEqual(visitedTerritories(catalog, [nodes[7].id, nodes[7].id, 'unknown']).map(n => n.spaceId), ['software']);
assert.deepEqual(visitedTerritories(catalog, [nodes[7].id, nodes[11].id]).map(n => n.spaceId), ['software', 'content']);
assert.deepEqual(visitedTerritories(catalog, ['central/index', 'unknown']), []);

// The daily pick is stable for the local calendar date and does not depend on graph ordering.
const day = new Date(2026, 9, 5, 0, 1);
const sameDay = new Date(2026, 9, 5, 23, 59);
const pick = dailyNode(catalog.pages, day);
assert.ok(catalog.pages.includes(pick));
assert.equal(dailyNode(catalog.pages, sameDay), pick);
assert.equal(dailyNode([...catalog.pages].reverse(), day), pick);
assert.equal(dailyNode([nodes[7]], day), nodes[7]);
assert.equal(JSON.stringify(nodes), original, 'Exploration helpers never mutate graph nodes, source bodies or ordering');

console.log('Observatory model passed: truthful classification, query/territory intersections, bounded storage, unseen wander, real routes, visit progress, deterministic daily discovery and immutable graph data.');
