/** Compose independent wikis with the unmodified upstream OpenWiki visualizer. */
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { readFile, mkdir, mkdtemp, writeFile, rm } from 'node:fs/promises';
import os from 'node:os';
import assert from 'node:assert/strict';
import { buildGraph } from '../openwiki-upstream/dist/visualize/graph.js';
import { PAGE, CSP } from '../openwiki-upstream/dist/visualize/page.js';

const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const UPSTREAM_VISUALIZER = path.join(ROOT, 'openwiki-upstream', 'dist', 'visualize');
const TWO_DIMENSIONAL_SCRIPT = /<script\s+src="https:\/\/cdn\.jsdelivr\.net\/npm\/force-graph@[^\"]+"[\s\S]*?<\/script>/;

export const assetPaths = Object.freeze({
  client: path.join(UPSTREAM_VISUALIZER, 'client.js'),
  clientLib: path.join(UPSTREAM_VISUALIZER, 'client-lib.js'),
  styles: path.join(UPSTREAM_VISUALIZER, 'styles.css'),
});

export function federationPage() {
  // Preserve upstream reading/navigation markup and apply the local app title.
  // Controls use same-origin assets under the original strict CSP.
  return PAGE.replace('<html lang="en"', '<html lang="zh-CN"')
    .replace('<title>OpenWiki visualizer</title>', '<title>未明 · 知识观测站</title>')
    .replace(TWO_DIMENSIONAL_SCRIPT, '')
    .replace('</head>', '<link rel="stylesheet" href="/federation-controls.css" />\n<link rel="stylesheet" href="/agent-chat.css" />\n<link rel="stylesheet" href="/knowledge-graph-3d.css" />\n</head>')
    .replace('</body>', '<script type="module" src="/federation-controls.js"></script>\n<script type="module" src="/agent-chat.js"></script>\n</body>');
}

function text(value) {
  return String(value ?? '').replace(/[\r\n\u0000-\u001f]/g, ' ').trim();
}

function markdownLabel(value) {
  return text(value).replace(/[\\[\]]/g, '\\$&');
}

function count(value) {
  return Number.isInteger(value) && value >= 0 ? value : 0;
}

function relativeLink(from, target) {
  return path.posix.relative(path.posix.dirname(from), target) + '.md';
}

function localMarkdownBody(body, spaceId, localId, wikiRoot) {
  // Ordinary relative paths retain their exact spelling. Root-relative Wiki
  // paths are rebased within this space, and relative escapes cannot turn into
  // links to another space after the graph receives its space prefix.
  return body.replace(/(\]\()([^\s)]+\.md)(#[^)]*)?(\))/g,
    (whole, open, rawTarget, fragment = '', close) => {
      if (/^[a-z][a-z0-9+.-]*:/i.test(rawTarget) || rawTarget.startsWith('//')) return whole;
      let decoded;
      try { decoded = decodeURIComponent(rawTarget); } catch { decoded = rawTarget; }
      let localTarget;
      if (decoded.startsWith('/')) {
        const nativeRoot = wikiRoot.replace(/\\/g, '/').replace(/\/$/, '');
        localTarget = decoded.startsWith(nativeRoot + '/')
          ? decoded.slice(nativeRoot.length + 1) : decoded.slice(1);
        localTarget = path.posix.normalize(localTarget);
      } else {
        localTarget = path.posix.normalize(path.posix.join(path.posix.dirname(localId), decoded));
      }
      if (localTarget === '..' || localTarget.startsWith('../')) return `${open}#outside-industry${close}`;
      if (!decoded.startsWith('/')) return whole;
      const targetId = `${spaceId}/${localTarget.replace(/\.md$/, '')}`;
      const relative = relativeLink(`${spaceId}/${localId}`, targetId);
      return `${open}${relative}${fragment}${close}`;
    });
}

function statusDescription(space, central = false, branchCount = 0) {
  if (central) {
    return `连接 ${branchCount} 个直属行业分支；中央知识页 ${count(space.knowledge_count)}。中央学习仅使用已审核发布快照；图中的分支页面仍包含待审核草稿。`;
  }
  const knowledge = count(space.knowledge_count);
  return `${knowledge ? `本分支草稿知识页 ${knowledge}` : '尚未学习本分支知识'}；已发布页面 ${count(space.published_count)}；待发布变更 ${count(space.pending_count)}。中央只读取审核发布版本；上下级群内发言不会自动入库。`;
}

function validateSpaces(input) {
  if (!input || !Array.isArray(input.spaces)) throw new Error('Expected stdin JSON object with spaces array.');
  const seen = new Set();
  for (const space of input.spaces) {
    if (!space || !/^[a-z][a-z0-9-]{0,63}$/.test(space.id) || seen.has(space.id)) {
      throw new Error('Each space must have a unique safe id.');
    }
    if (typeof space.wiki_dir !== 'string' || !path.isAbsolute(space.wiki_dir)) {
      throw new Error('Each space must supply an absolute wiki_dir.');
    }
    seen.add(space.id);
  }
  if (!seen.has('central')) throw new Error('The central space is required.');
  const spaces = input.spaces.map(space => ({ ...space,
    parent_id: Object.hasOwn(space, 'parent_id') ? space.parent_id : space.id === 'central' ? null : 'central',
  }));
  const byId = new Map(spaces.map(space => [space.id, space]));
  if (byId.get('central').parent_id !== null) throw new Error('The central space cannot have a parent.');
  const resolved = new Set();
  function resolve(space, pending = new Set()) {
    if (resolved.has(space.id)) return;
    if (pending.has(space.id)) throw new Error('Space hierarchy contains a cycle.');
    pending.add(space.id);
    if (space.id === 'central') {
      space.depth = 0;
      space.ancestor_ids = [];
      space.breadcrumb = [text(space.name || space.id)];
    } else {
      const parent = byId.get(space.parent_id);
      if (!parent) throw new Error('Each branch must have a known parent.');
      resolve(parent, pending);
      space.depth = parent.depth + 1;
      space.ancestor_ids = [...parent.ancestor_ids, parent.id];
      space.breadcrumb = [...parent.breadcrumb, text(space.name || space.id)];
    }
    pending.delete(space.id);
    resolved.add(space.id);
  }
  spaces.forEach(space => resolve(space));
  return spaces;
}

export async function buildFederatedGraph(input) {
  const spaces = validateSpaces(input);
  const branchCount = spaces.filter(space => space.parent_id === 'central').length;
  const nodes = [];
  const edges = [];
  for (const space of spaces) {
    const graph = await buildGraph(space.wiki_dir);
    const role = space.id === 'central' ? 'central' : 'branch';
    const localNodes = graph.nodes.map(node => ({
      ...node,
      id: `${space.id}/${node.id}`,
      body: localMarkdownBody(node.body, space.id, node.id, space.wiki_dir),
      links: node.links.map(target => `${space.id}/${target}`),
      backlinks: node.backlinks.map(source => `${space.id}/${source}`),
      spaceId: space.id,
      parentSpaceId: space.parent_id,
      spaceDepth: space.depth,
      ancestorSpaceIds: [...space.ancestor_ids],
      breadcrumb: [...space.breadcrumb],
      federationRole: role,
      isFederationHub: node.id === 'index',
    }));
    const hubId = `${space.id}/index`;
    let hub = localNodes.find(node => node.id === hubId);
    if (!hub) {
      const body = `# ${text(space.name || space.id)}\n\n此页为知识库结构入口；当前导航信息不是行业知识事实。\n`;
      hub = { id: hubId, title: text(space.name || space.id), type: '', description: '', tags: [],
              body, size: body.length, links: [], backlinks: [], spaceId: space.id,
              parentSpaceId: space.parent_id, spaceDepth: space.depth,
              ancestorSpaceIds: [...space.ancestor_ids], breadcrumb: [...space.breadcrumb],
              federationRole: role, isFederationHub: true };
      localNodes.unshift(hub);
    }
    hub.title = role === 'central' ? '中央智能体知识库' : text(space.name || space.id);
    hub.type = role === 'central' ? '中央主库' : space.depth === 1 ? '行业分支' : '专业分支';
    hub.description = statusDescription(space, role === 'central', branchCount);
    nodes.push(...localNodes);
    edges.push(...graph.edges.map(edge => ({ source: `${space.id}/${edge.source}`, target: `${space.id}/${edge.target}` })));
  }

  const byId = new Map(nodes.map(node => [node.id, node]));
  const seenEdges = new Set();
  const resolvedEdges = [];
  function addEdge(source, target) {
    const key = `${source}\n${target}`;
    if (source === target || !byId.has(source) || !byId.has(target) || seenEdges.has(key)) return;
    seenEdges.add(key);
    resolvedEdges.push({ source, target });
  }
  edges.forEach(edge => addEdge(edge.source, edge.target));
  // Root-relative links only become valid after rebasing. Resolve those and
  // ordinary links against the composed identities without changing content.
  for (const node of nodes) {
    for (const match of node.body.matchAll(/\]\(([^\s)]+\.md)(?:#[^)]*)?\)/g)) {
      if (/^[a-z][a-z0-9+.-]*:/i.test(match[1]) || match[1].startsWith('//')) continue;
      let relative;
      try { relative = decodeURIComponent(match[1]); } catch { relative = match[1]; }
      const target = path.posix.normalize(path.posix.join(path.posix.dirname(node.id), relative)).replace(/\.md$/, '');
      if (target.startsWith(node.spaceId + '/')) addEdge(node.id, target);
    }
  }
  for (const space of spaces) {
    const hub = byId.get(`${space.id}/index`);
    const children = spaces.filter(item => item.parent_id === space.id).map(item => byId.get(`${item.id}/index`));
    const pages = nodes.filter(node => node.spaceId === space.id && node.id !== hub.id);
    for (const member of [...children, ...pages]) addEdge(hub.id, member.id);
    const links = members => members.map(member => `- [${markdownLabel(member.title)}](${relativeLink(hub.id, member.id)})`).join('\n');
    const childrenSection = children.length
      ? `\n\n### ${space.id === 'central' ? '直属行业分支' : '直属专业分支'}\n\n${links(children)}` : '';
    const pagesSection = `\n\n### 本知识库页面\n\n${pages.length ? links(pages) : '当前尚无主题页面；请添加资料并学习。'}`;
    hub.body += `\n\n---\n\n## 知识库分支（系统导航）\n\n归属：${space.breadcrumb.map(markdownLabel).join(' → ')}。\n\n${hub.description}${childrenSection}${pagesSection}\n\n这些连线表示知识库归属与导航，不表示分支之间存在未经证据确认的事实关系。\n`;
  }

  // Rebuild references after adding topology edges so the upstream backlinks,
  // connection lists and graph use exactly the same prefixed identities.
  for (const node of nodes) {
    node.links = [];
    node.backlinks = [];
    node.size = node.body.length;
  }
  for (const edge of resolvedEdges) {
    byId.get(edge.source).links.push(edge.target);
    byId.get(edge.target).backlinks.push(edge.source);
  }
  return { root: '行业知识网络', generatedAt: new Date().toISOString(),
           types: [...new Set(nodes.map(node => node.type))].sort(), nodes, edges: resolvedEdges };
}

async function verify() {
  const temporary = await mkdtemp(path.join(os.tmpdir(), 'openwiki-federation-visualizer-'));
  try {
    const spaces = [];
    for (const [id, name] of [['central', '中央智能体知识库'], ['software', '互联网与软件'],
                              ['content', '影视与内容'], ['commerce', '电商与零售'], ['business', '企业经营']]) {
      const wiki = path.join(temporary, id, 'wiki');
      await mkdir(wiki, { recursive: true });
      // Omit one index to verify a missing hub can be created without pretending
      // professional knowledge has been learned.
      if (id !== 'business') await writeFile(path.join(wiki, 'index.md'), `# ${name}\n\n尚未学习；结构模板。\n`);
      spaces.push({ id, name, wiki_dir: wiki, knowledge_count: 0, published_count: 0 });
    }
    const software = spaces.find(space => space.id === 'software');
    await mkdir(path.join(software.wiki_dir, 'topics'));
    await writeFile(path.join(software.wiki_dir, 'topics', 'test.md'),
      '# 链接验收\n\n[本库](../index.md) [本库绝对](/index.md) [越界](../../commerce/index.md)\n');
    software.knowledge_count = 1;
    const graph = await buildFederatedGraph({ spaces });
    assert.equal(graph.nodes.filter(node => node.isFederationHub).length, 5);
    assert.equal(graph.edges.filter(edge => edge.source === 'central/index').length, 4);
    assert.equal(new Set(graph.nodes.map(node => node.id)).size, graph.nodes.length);
    const article = graph.nodes.find(node => node.id === 'software/topics/test');
    assert.match(article.body, /\[本库绝对\]\(\.\.\/index\.md\)/);
    assert.match(article.body, /\[越界\]\(#outside-industry\)/);
    assert(graph.edges.some(edge => edge.source === 'software/index' && edge.target === article.id));
    const central = graph.nodes.find(node => node.id === 'central/index');
    assert.equal(central.federationRole, 'central');
    for (const node of graph.nodes) assert.equal(node.size, node.body.length);
    // Keep the legacy five-space fixture above: missing parent_id must still
    // mean a top-level industry. Then independently exercise nested branches.
    const specialistWiki = path.join(temporary, 'frontend', 'wiki');
    await mkdir(specialistWiki, { recursive: true });
    await writeFile(path.join(specialistWiki, 'index.md'), '# 前端\n\n结构模板。\n');
    await writeFile(path.join(specialistWiki, 'topic.md'), '# 前端独立页面\n\n隔离验证。\n');
    await writeFile(path.join(spaces.find(space => space.id === 'central').wiki_dir, 'topic.md'), '# 中央页面\n');
    const nestedSpaces = [...spaces, { id: 'frontend', name: '前端', parent_id: 'software', wiki_dir: specialistWiki }];
    const nested = await buildFederatedGraph({ spaces: nestedSpaces });
    assert(nested.edges.some(edge => edge.source === 'software/index' && edge.target === 'frontend/index'));
    assert(!nested.edges.some(edge => edge.source === 'central/index' && edge.target === 'frontend/index'));
    assert(nested.edges.some(edge => edge.source === 'central/index' && edge.target === 'central/topic'));
    const specialist = nested.nodes.find(node => node.id === 'frontend/topic');
    assert.equal(specialist.parentSpaceId, 'software');
    assert.equal(specialist.spaceDepth, 2);
    assert.deepEqual(specialist.breadcrumb, ['中央智能体知识库', '互联网与软件', '前端']);
    assert.deepEqual(specialist.ancestorSpaceIds, ['central', 'software']);
    assert(!nested.nodes.find(node => node.id === 'central/index').body.includes('frontend/index.md'));
    assert(nested.nodes.find(node => node.id === 'software/index').body.includes('../frontend/index.md'));
    await assert.rejects(buildFederatedGraph({ spaces: nestedSpaces.map(space =>
      space.id === 'software' ? { ...space, parent_id: 'frontend' } : space) }), /cycle/);
    await assert.rejects(buildFederatedGraph({ spaces: nestedSpaces.map(space =>
      space.id === 'frontend' ? { ...space, parent_id: 'unknown' } : space) }), /known parent/);
    const page = federationPage();
    assert(page.includes('<html lang="zh-CN"'));
    assert(page.includes('<title>未明 · 知识观测站</title>'));
    assert(page.includes('class="lc-logo-full"'));
    assert(page.includes('id="graph"') && page.includes('id="sidebar"') && page.includes('id="detail"'));
    assert.equal(page.replace('<html lang="zh-CN"', '<html lang="en"')
      .replace('<title>未明 · 知识观测站</title>', '<title>OpenWiki visualizer</title>')
      .replace('<link rel="stylesheet" href="/federation-controls.css" />\n', '')
      .replace('<link rel="stylesheet" href="/agent-chat.css" />\n', '')
      .replace('<link rel="stylesheet" href="/knowledge-graph-3d.css" />\n', '')
      .replace('<script type="module" src="/federation-controls.js"></script>\n', '')
      .replace('<script type="module" src="/agent-chat.js"></script>\n', ''), PAGE.replace(TWO_DIMENSIONAL_SCRIPT, ''));
    for (const asset of Object.values(assetPaths)) await readFile(asset);
    return { ok: true, hubs: 5, centralHubEdges: 4, nodes: graph.nodes.length,
             uniqueIds: true, boundaryLinks: true, originalPagePreserved: true,
             nestedParentLinks: true, hierarchyMetadata: true, centralOwnPageLinks: true,
             cyclicHierarchyRejected: true };
  } finally {
    await rm(temporary, { recursive: true, force: true });
  }
}

async function main() {
  switch (process.argv[2]) {
    case '--page': process.stdout.write(federationPage()); break;
    case '--csp': process.stdout.write(CSP); break;
    case '--paths': process.stdout.write(JSON.stringify(assetPaths)); break;
    case '--verify': process.stdout.write(JSON.stringify(await verify())); break;
    case '--graph': {
      let input = '';
      for await (const chunk of process.stdin) {
        input += chunk;
        if (input.length > 8 * 1024 * 1024) throw new Error('Graph metadata exceeds 8 MiB.');
      }
      process.stdout.write(JSON.stringify(await buildFederatedGraph(JSON.parse(input))));
      break;
    }
    default: throw new Error('Usage: visualizer.mjs --page | --csp | --graph | --paths | --verify');
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main().catch(error => { process.stderr.write(`${error.message}\n`); process.exitCode = 1; });
}
