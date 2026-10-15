import { JOURNAL_KEY, nodeKind, catalogFor, plainExcerpt, searchNodes, normalizeJournal,
  chooseWander, visitedTerritories, explorationRoutes, routeProgress, dailyNode } from './observatory-model.js';
import { openServerState } from './browser-state.js';

// Exploration content is persisted by the same server as knowledge and chat.
(async () => {
  'use strict';
  if (document.getElementById('ob-shell')) return;
  const make = (tag, cls, text) => { const el = document.createElement(tag); if (cls) el.className = cls; if (text !== undefined) el.textContent = text; return el; };
  const $ = id => document.getElementById(`ob-${id}`);
  const button = (text, cls, action) => { const el = make('button', cls, text); el.type = 'button'; if (action) el.addEventListener('click', action); return el; };
  const journalStorage = await openServerState('journal', 'localStorage', JOURNAL_KEY);
  let journal = normalizeJournal(journalStorage.value), storageAvailable = true;
  const state = { catalog: catalogFor(null), view: 'home', territory: 'all', kind: 'all', query: '',
    selected: null, previousWander: '', activeRoute: null, loaded: false, revision: 0, graphShown: false, pending: null };
  const territoryCopy = {
    software: ['互联网与软件', '产品设计、开发、部署和测试。', '软件'],
    content: ['影视与内容', '策划、视觉、拍摄、制作和运营。', '内容'],
    commerce: ['电商与零售', '商品、供应链、店铺、营销和服务。', '零售'],
    business: ['企业经营', '战略、组织、财务、项目和流程。', '经营'],
  };
  // Four small architectural studies, decorative rather than knowledge data.
  const glyphs = [
    '<ellipse cx="150" cy="145" rx="70" ry="12" fill="#4e645b" opacity=".1"/><path d="m150 36 61 35-61 35-61-35Z" fill="#c5d0c4"/><path d="m89 71 61 35v54l-61-35Z" fill="#657d70"/><path d="m150 106 61-35v54l-61 35Z" fill="#8b9e8c"/><path d="m150 36 61 35-61 35-61-35Zm0 70v54" stroke="#f0f3e9" stroke-opacity=".75"/><path d="m111 84 39-23 39 23m-59 11 40-23m-20 34 41-24" stroke="#dce3d5" stroke-opacity=".6"/>',
    '<ellipse cx="151" cy="150" rx="74" ry="10" fill="#806a49" opacity=".09"/><path d="M93 144V71a51 51 0 0 1 102 0v73h-20V72a31 31 0 0 0-62 0v72Z" fill="#b49d76"/><path d="M101 144V72a51 51 0 0 1 102 0v72h-20V72a31 31 0 0 0-62 0v72Z" fill="#d2bea0"/><path d="M130 144V86a30 30 0 0 1 60 0v58h-13V86a17 17 0 0 0-34 0v58Z" fill="#ac9270"/><path d="M137 144V86a30 30 0 0 1 60 0v58h-13V86a17 17 0 0 0-34 0v58Z" fill="#e8d9bf"/>',
    '<ellipse cx="150" cy="148" rx="76" ry="9" fill="#5b727b" opacity=".1"/><g fill="none" stroke-width="14"><ellipse cx="150" cy="87" rx="65" ry="35" transform="rotate(-34 150 87)" stroke="#7d949a"/><ellipse cx="150" cy="96" rx="65" ry="35" transform="rotate(34 150 96)" stroke="#adbfc0"/></g><path d="M92 120c29 7 67-11 94-42" fill="none" stroke="#d8e1dc" stroke-width="2"/><circle cx="150" cy="91" r="12" fill="#e6e5d5"/>',
    '<ellipse cx="150" cy="148" rx="73" ry="10" fill="#876e5b" opacity=".1"/><path d="m85 123 49-26 83 36-48 26Z" fill="#a98970"/><path d="m85 111 49-26 83 36-48 26Z" fill="#cfb59e"/><path d="M85 111v12l84 36v-12m48-26v12l-48 26v-12" fill="#b4977e"/><path d="m109 83 41-22 43 19-41 22Z" fill="#dbc5b1"/><path d="M109 83v37l43 19v-37Z" fill="#bda18a"/><path d="m152 102 41-22v37l-41 22Z" fill="#9d8068"/><path d="m134 43 33-17 25 11-33 18Z" fill="#ede0ce"/><path d="M134 43v41l25 11V55Z" fill="#c9b09a"/><path d="m159 55 33-18v41l-33 17Z" fill="#ac8f75"/>',
  ];
  const svg = (inner, cls = '') => { const wrap = make('span', cls); wrap.innerHTML = `<svg viewBox="0 0 300 180" fill="none" aria-hidden="true">${inner}</svg>`; return wrap; };
  const kindText = node => ({ space: '知识库入口', source: '来源档案', page: '知识页面' })[nodeKind(node)];
  const trailText = node => (node.breadcrumb || []).slice(1).join(' / ') || '中央观测站';
  async function persist() {
    try { await journalStorage.save(journal); storageAvailable = true; return true; }
    catch { storageAvailable = false; announce('服务器暂时无法保存，请保留当前页面并重试；未另存到这台电脑。'); return false; }
  }
  let noticeTimer;
  function announce(text) { $('notice').textContent = text; $('notice').hidden = false; clearTimeout(noticeTimer); noticeTimer = setTimeout(() => { $('notice').hidden = true; }, 4000); }
  async function bookmark(node) {
    if (!node) return;
    const saved = journal.bookmarks.includes(node.id);
    journal.bookmarks = saved ? journal.bookmarks.filter(id => id !== node.id) : [node.id, ...journal.bookmarks].slice(0, 500);
    const stored = await persist(); renderReaderBar(); renderHome(); if (state.view === 'journal') renderJournal();
    if (stored) announce(saved ? '服务器已更新星标。' : '已保存到服务器的星标。');
  }
  function recordVisit(node) {
    const before = visitedTerritories(state.catalog, journal.visits).length;
    journal.visits = [node.id, ...journal.visits.filter(id => id !== node.id)].slice(0, 500);
    persist();
    const after = visitedTerritories(state.catalog, journal.visits).length;
    if (after === state.catalog.territories.length && after >= 4 && before < after) announce('你已走过所有星域。观测台上，有一扇新的门。');
    renderReaderBar();
  }

  const shell = make('div', 'ob-shell'); shell.id = 'ob-shell';
  shell.innerHTML = `
    <header class="ob-header">
      <button type="button" class="ob-brand" id="ob-brand" aria-label="未明 · 返回观测台"><span class="ob-brand-mark" aria-hidden="true">✧</span><span><strong>未明<span class="ob-brand-divider"> / </span></strong><small>知识观测站</small></span></button>
      <nav class="ob-nav" aria-label="知识探索导航">
        <button type="button" data-view="home">观测台</button><button type="button" data-view="atlas">知识星图</button><button type="button" data-view="archive">全部档案</button><button type="button" data-view="journal">我的足迹<span id="ob-journal-dot" hidden></span></button>
      </nav>
      <div class="ob-header-tools"><button type="button" class="ob-search-launch" id="ob-search-launch" aria-label="搜索知识，快捷键 Command 或 Ctrl 加 K"><svg viewBox="0 0 20 20" fill="none" stroke="currentColor" aria-hidden="true"><circle cx="8.5" cy="8.5" r="5.5"/><path d="m13 13 4 4"/></svg><kbd>⌘ K</kbd></button><span class="ob-header-separator"></span><button type="button" class="ob-agent" id="ob-agent"><span aria-hidden="true">✳</span> 与主 Agent 对话 <span aria-hidden="true">↗</span></button></div>
    </header>
    <main class="ob-content" id="ob-content">
      <section id="ob-home" aria-labelledby="ob-home-title">
        <div class="ob-hero">
          <div class="ob-hero-copy"><p class="ob-eyebrow">个人知识库</p><h1 id="ob-home-title">未明知识库</h1><p class="ob-hero-description">阅读已积累的知识，保存资料，<br>或带着具体问题与主 Agent 讨论。</p><div class="ob-hero-actions"><button type="button" class="ob-primary" id="ob-wander">读一篇知识 <span aria-hidden="true">↗</span></button><button type="button" class="ob-text-button" id="ob-show-map">查看知识星图 <span aria-hidden="true">→</span></button></div><div class="ob-hero-note"><span id="ob-hero-note">正在接收知识库的微光…</span></div></div>
        </div>
        <div class="ob-section-heading"><div><h2>知识领域</h2></div><span class="ob-section-aside" id="ob-territory-count">正在读取目录</span></div>
        <div class="ob-territories" id="ob-territories"></div>
        <div class="ob-lower-grid">
          <section class="ob-signal" aria-labelledby="ob-signal-title"><div class="ob-signal-top"><p class="ob-eyebrow">今日阅读</p><span id="ob-today"></span></div><h3 id="ob-signal-title">正在选择知识页</h3><p id="ob-signal-description"></p><button type="button" class="ob-text-button" id="ob-signal-open">阅读这篇 <span aria-hidden="true">↗</span></button></section>
          <section class="ob-routes" aria-labelledby="ob-routes-title"><div class="ob-route-heading"><h2 id="ob-routes-title">阅读路线</h2></div><div id="ob-routes-list"></div></section>
        </div>
        <button type="button" class="ob-secret" id="ob-secret" hidden><span aria-hidden="true">◈</span><span><small>你已走过所有星域</small><strong>第零号观测室，现在为你打开。</strong></span><span aria-hidden="true">↗</span></button>
        <footer class="ob-footer"><span>未明知识库</span><span>资料、知识页与学习记录由服务器保存。</span><button type="button" id="ob-workspace">进入工作台 ↗</button></footer>
      </section>
      <section id="ob-archive" hidden aria-labelledby="ob-archive-title"><div class="ob-page-heading"><h1 id="ob-archive-title">全部档案</h1><p>按标题、正文或所属领域查找知识和资料。</p></div><label class="ob-search-field"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" aria-hidden="true"><circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/></svg><input id="ob-search" type="search" placeholder="搜索标题或内容" aria-label="搜索档案" autocomplete="off"><span>ESC 取消</span></label><div class="ob-filter-row"><div id="ob-territory-filters" class="ob-chips" aria-label="筛选星域"></div><select id="ob-kind" aria-label="筛选档案类型"><option value="all">所有类型</option><option value="page">知识页面</option><option value="space">知识库入口</option><option value="source">来源档案</option></select></div><p class="ob-result-count" id="ob-result-count" aria-live="polite"></p><div class="ob-archive-grid" id="ob-results"></div></section>
      <section id="ob-journal" hidden aria-labelledby="ob-journal-title"><div class="ob-page-heading"><h1 id="ob-journal-title">我的足迹</h1><p>查看收藏、阅读记录和自己的短笺。</p></div><div class="ob-journal-summary" id="ob-journal-summary"></div><p class="ob-journal-storage" id="ob-journal-storage"></p><h2 class="ob-subheading">收藏 <span id="ob-bookmark-count"></span></h2><div class="ob-archive-grid" id="ob-bookmarks"></div><h2 class="ob-subheading">最近阅读</h2><div class="ob-history" id="ob-history"></div></section>
      <div class="ob-error" id="ob-error" hidden role="alert"><strong>暂时没有收到知识库的信号。</strong><p id="ob-error-message"></p><button type="button" class="ob-primary" id="ob-retry">重新连接 ↻</button></div>
    </main>
    <div class="ob-reader-bar" id="ob-reader-bar" hidden><button type="button" id="ob-back-home">← 返回观测台</button><span class="ob-reader-title" id="ob-reader-title">知识星图</span><span class="ob-reader-actions"><button type="button" id="ob-read-save">☆ 收进星标</button><button type="button" id="ob-note">写下短笺</button><button type="button" id="ob-next">下一站 ↗</button></span></div>
    <div class="ob-notice" id="ob-notice" role="status" hidden></div>
    <dialog class="ob-dialog" id="ob-dialog" aria-labelledby="ob-dialog-title"><div class="ob-dialog-top"><span class="ob-eyebrow" id="ob-dialog-label">AN UNEXPECTED ENCOUNTER</span><button type="button" id="ob-dialog-close" aria-label="关闭探索窗口">×</button></div><div id="ob-dialog-body"></div></dialog>
  `;
  document.body.prepend(shell);
  $('content').prepend($('error'));
  document.body.classList.add('ob-active');
  document.title = '未明 · 知识观测站';

  function setView(view, focus = false) {
    state.view = view;
    const native = view === 'atlas';
    document.body.classList.toggle('ob-native', native);
    $('content').hidden = native;
    $('reader-bar').hidden = !native;
    for (const name of ['home', 'archive', 'journal']) $(name).hidden = name !== view;
    document.querySelectorAll('.ob-nav [data-view]').forEach(el => { const active = el.dataset.view === view; el.classList.toggle('active', active); if (active) el.setAttribute('aria-current', 'page'); else el.removeAttribute('aria-current'); });
    if (view === 'home') renderHome();
    if (view === 'archive') renderArchive();
    if (view === 'journal') renderJournal();
    if (!native) $('content').scrollTop = 0;
    if (!native) state.pending = null;
    if (native) {
      window.dispatchEvent(new Event('resize'));
      if (!state.graphShown) {
        state.graphShown = true;
        requestAnimationFrame(() => requestAnimationFrame(() => {
          const reset = Array.from(document.querySelectorAll('.kg3d-controls button')).find(el => el.textContent === '重置视角');
          if (state.view === 'atlas') reset?.click();
        }));
      }
    }
    document.dispatchEvent(new CustomEvent('observatory:view', { detail: { view } }));
    if (focus && !native) { const heading = $(view).querySelector('h1'); heading?.setAttribute('tabindex', '-1'); heading?.focus({ preventScroll: true }); }
  }
  function openNode(node) {
    if (!node || !state.catalog.byId.has(node.id)) return;
    $('dialog').close();
    state.selected = node;
    if (state.activeRoute && !state.activeRoute.nodes.some(n => n.id === node.id)) state.activeRoute = null;
    setView('atlas');
    // The native sidebar is the reader's existing public navigation surface.
    const target = Array.from(document.querySelectorAll('#sidebar .nav-item[data-id]')).find(el => el.dataset.id === node.id);
    if (target) { target.click(); recordVisit(node); state.pending = null; const heading = document.querySelector('#detail .doc-title'); heading?.setAttribute('tabindex', '-1'); heading?.focus({ preventScroll: true }); }
    else { state.pending = node; announce('阅读器正在连接，页面就绪后会为你打开。'); }
    renderReaderBar();
  }
  const sidebar = document.getElementById('sidebar');
  if (sidebar) new MutationObserver(() => {
    if (state.pending) {
      const node = state.pending;
      const target = Array.from(sidebar.querySelectorAll('.nav-item[data-id]')).find(el => el.dataset.id === node.id);
      if (target) { state.pending = null; target.click(); recordVisit(node); }
    }
  }).observe(sidebar, { childList: true, subtree: true });
  document.addEventListener('openwiki:select', event => {
    const node = state.catalog.byId.get(event.detail?.nodeId);
    if (!node) return;
    state.selected = node;
    if (state.activeRoute && !state.activeRoute.nodes.some(n => n.id === node.id)) state.activeRoute = null;
    if (state.view === 'atlas') recordVisit(node);
  });

  function renderHome() {
    const c = state.catalog, visits = new Set(journal.visits), visited = visitedTerritories(c, journal.visits);
    $('hero-note').textContent = state.loaded ? `${c.spaces.length} 个知识库入口 · ${c.pages.length} 篇知识 · ${c.sources.length} 份来源` : '正在接收知识库的微光…';
    $('territory-count').textContent = `${String(visited.length).padStart(2, '0')} / ${String(c.territories.length).padStart(2, '0')} 星域已抵达`;
    $('journal-dot').hidden = journal.visits.length === 0;
    $('territories').replaceChildren();
    c.territories.forEach((t, index) => {
      const copy = territoryCopy[t.spaceId] || [t.title, '阅读这个领域的知识和资料。', '专题'];
      const nodes = searchNodes(c.nodes, '', t.spaceId), pages = nodes.filter(n => nodeKind(n) === 'page');
      const count = nodes.filter(n => visits.has(n.id)).length;
      const card = button('', 'ob-territory', () => { state.territory = t.spaceId; state.query = ''; setView('archive', true); });
      card.setAttribute('aria-label', `探索${t.title}`);
      const top = make('div', 'ob-territory-top'); top.append(make('span', 'ob-index', String(index + 1).padStart(2, '0')), make('span', 'ob-territory-category', copy[2]));
      const name = make('h3', '', copy[0]); name.append(make('span', '', '↗'));
      const foot = make('div', 'ob-territory-foot'); foot.append(make('span', '', t.title), make('span', '', pages.length ? `${pages.length} 篇知识` : '待充实'));
      const progress = make('div', 'ob-territory-progress'); const line = make('span'); line.style.width = `${nodes.length ? count / nodes.length * 100 : 0}%`; progress.append(line);
      card.append(top, svg(glyphs[index % glyphs.length], 'ob-territory-art'), name, make('p', '', copy[1]), foot, progress); $('territories').append(card);

    });
    const signal = dailyNode(c.pages.length ? c.pages : c.spaces);
    $('today').textContent = new Date().toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }).replace('/', ' / ');
    $('signal-title').textContent = signal?.title || (state.loaded ? '星图正在等待第一份档案' : '等待一束来自知识库的信号');
    $('signal-description').textContent = signal ? plainExcerpt(signal, 110) : '知识页会在这里成为下一次探索的起点。';
    $('signal-open').disabled = !signal; $('signal-open').onclick = () => openNode(signal);
    $('routes-list').replaceChildren();
    explorationRoutes(c).forEach((route, i) => {
      const progress = routeProgress(route, journal.visits);
      const row = button('', 'ob-route-row', () => routeDialog(route));
      const name = make('span', 'ob-route-copy'); name.append(make('strong', '', route.title), make('small', '', `${route.label} · ${route.nodes.length} 个坐标`));
      row.append(make('span', 'ob-route-number', `0${i + 1}`), name, make('span', 'ob-route-progress', `${progress.done}/${progress.total}`), make('span', 'ob-route-arrow', '↗')); $('routes-list').append(row);
    });
    $('secret').hidden = !(c.territories.length >= 4 && visited.length === c.territories.length);
  }

  function nodeCard(node, removable = false) {
    const card = make('article', 'ob-node-card');
    const meta = make('div', 'ob-node-meta'); meta.append(make('span', '', kindText(node)), make('span', 'ob-node-visited', journal.visits.includes(node.id) ? '已抵达' : '待探索'));
    const open = button(node.title, 'ob-node-title', () => openNode(node));
    card.append(meta, open, make('p', '', plainExcerpt(node, 115) || '这里保留了知识的来源线索。'), make('small', 'ob-node-trail', trailText(node)));
    const foot = make('div', 'ob-node-foot'); foot.append(button('打开档案 ↗', 'ob-text-button', () => openNode(node)), button(journal.bookmarks.includes(node.id) ? '★' : '☆', 'ob-save-icon', () => {
      bookmark(node);
      if (state.view === 'archive') { renderArchive(); Array.from($('results').querySelectorAll('[data-bookmark]')).find(el => el.dataset.bookmark === node.id)?.focus(); }
    }));
    foot.lastChild.dataset.bookmark = node.id;
    foot.lastChild.setAttribute('aria-label', `${journal.bookmarks.includes(node.id) ? '取消收藏' : '收藏'} ${node.title}`);
    foot.lastChild.setAttribute('aria-pressed', String(journal.bookmarks.includes(node.id)));
    card.append(foot);
    if (removable && journal.notes[node.id]) card.append(make('blockquote', 'ob-card-note', journal.notes[node.id]));
    if (removable) card.append(button(journal.notes[node.id] ? '编辑短笺' : '写下短笺', 'ob-text-button ob-card-note-edit', () => noteDialog(node)));
    return card;
  }
  function empty(message, detail, actionText, action) {
    const el = make('div', 'ob-empty'); el.append(make('span', 'ob-empty-symbol', '✧'), make('h3', '', message), make('p', '', detail)); if (action) el.append(button(actionText, 'ob-text-button', action)); return el;
  }
  function renderArchive() {
    $('search').value = state.query; $('kind').value = state.kind;
    $('territory-filters').replaceChildren();
    [{ spaceId: 'all', title: '全部星域' }, ...state.catalog.territories].forEach(t => {
      const el = button(t.title, 'ob-chip' + (state.territory === t.spaceId ? ' selected' : ''), () => { state.territory = t.spaceId; renderArchive(); Array.from($('territory-filters').children).find(item => item.dataset.territory === t.spaceId)?.focus(); });
      el.dataset.territory = t.spaceId;
      el.setAttribute('aria-pressed', String(state.territory === t.spaceId)); $('territory-filters').append(el);
    });
    const nodes = searchNodes(state.catalog.nodes, state.query, state.territory, state.kind);
    $('result-count').textContent = `${nodes.length} 个坐标${state.query ? ` · 与「${state.query}」有关` : ''} · 知识库入口与来源页面分别标注`;
    $('results').replaceChildren(...nodes.map(n => nodeCard(n)));
    if (!nodes.length) $('results').append(empty('这片区域暂时没有回音', '试试更短的词，或放宽星域与类型的筛选。', '查看全部档案 →', () => { state.query = ''; state.territory = state.kind = 'all'; renderArchive(); $('search').focus(); }));
  }
  function renderJournal() {
    const c = state.catalog, visited = journal.visits.map(id => c.byId.get(id)).filter(Boolean), saved = journal.bookmarks.map(id => c.byId.get(id)).filter(Boolean);
    $('journal-summary').replaceChildren();
    [[String(visited.length).padStart(2, '0'), '抵达的坐标'], [String(saved.length).padStart(2, '0'), '收藏的星光'], [`${visitedTerritories(c, journal.visits).length} / ${c.territories.length}`, '走过的星域']].forEach(([value, label]) => { const el = make('div'); el.append(make('strong', '', value), make('span', '', label)); $('journal-summary').append(el); });
    $('journal-storage').textContent = storageAvailable ? '足迹、星标与短笺由服务器保存，可在这里继续阅读。' : '服务器暂时无法保存本次修改，请保留当前页面并重试。';
    $('journal-storage').append(button('导出探索手记 ↓', 'ob-text-button', exportJournal));
    $('bookmark-count').textContent = saved.length;
    $('bookmarks').replaceChildren(...saved.map(n => nodeCard(n, true)));
    if (!saved.length) $('bookmarks').append(empty('还没有收集到星光', '读到想再回来的一页，点一下「收进星标」。', '开始一次漫游 ↗', wander));
    $('history').replaceChildren();
    visited.forEach((node, i) => { const row = button('', 'ob-history-row', () => openNode(node)); row.append(make('span', 'ob-index', String(i + 1).padStart(2, '0')), make('strong', '', node.title), make('small', '', trailText(node)), make('span', '', '↗')); $('history').append(row); });
    if (!visited.length) $('history').append(empty('旅程，从第一次出发开始', '打开任意档案，这里就会留下它的坐标。'));
  }
  function exportJournal() {
    const lines = ['# 未明 · 探索手记', '', '导出日期：' + new Date().toLocaleDateString('zh-CN'), '', '## 收藏的星光', ''];
    for (const id of journal.bookmarks) { const n = state.catalog.byId.get(id); lines.push(`### ${n?.title || id}`, '', `坐标：${id}`, '', journal.notes[id] || '（暂无短笺）', ''); }
    lines.push('## 最近经过', '');
    for (const id of journal.visits) lines.push(`- ${state.catalog.byId.get(id)?.title || id} · ${id}`);
    const remaining = Object.entries(journal.notes).filter(([id, note]) => note && !journal.bookmarks.includes(id));
    if (remaining.length) { lines.push('', '## 其他短笺', ''); remaining.forEach(([id, note]) => lines.push(`### ${state.catalog.byId.get(id)?.title || id}`, '', note, '')); }
    const url = URL.createObjectURL(new Blob([lines.join('\n')], { type: 'text/markdown;charset=utf-8' }));
    const link = make('a'); link.href = url; link.download = '未明-探索手记.md'; document.body.append(link); link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
    announce('探索手记已交给浏览器下载。');
  }

  function dialog(label, title) {
    $('dialog-label').textContent = label; $('dialog-body').replaceChildren();
    const heading = make('h2', '', title); heading.id = 'ob-dialog-title'; $('dialog-body').append(heading);
    if (!$('dialog').open) $('dialog').showModal();
    return $('dialog-body');
  }
  function wander() {
    if (!state.loaded) { announce('星图正在连接，请稍候再出发。'); return; }
    const pool = state.catalog.pages.length ? state.catalog.pages : state.catalog.spaces;
    const node = chooseWander(pool, journal.visits, state.previousWander);
    if (!node) { announce('知识库中还没有可探索的页面。'); return; }
    state.previousWander = node.id;
    const body = dialog('SERENDIPITY / 偶然相遇', '这一次，微光指向这里。');
    body.append(make('p', 'ob-dialog-intro', journal.visits.includes(node.id) ? '重访也许会带来不一样的发现。' : '一个你还没有留下足迹的坐标。'));
    const reveal = make('div', 'ob-reveal'); reveal.append(make('span', 'ob-reveal-star', '✧'), make('small', '', kindText(node) + ' / ' + trailText(node)), make('h3', '', node.title), make('p', '', plainExcerpt(node, 180))); body.append(reveal);
    const actions = make('div', 'ob-dialog-actions'); actions.append(button('再接收一束信号 ↻', 'ob-secondary', wander), button('就从这里出发 ↗', 'ob-primary', () => { state.activeRoute = null; openNode(node); })); body.append(actions);
    body.append(make('p', 'ob-fine', '从已有页面中随机选取，优先带你去尚未到访的地方。'));
  }
  function routeDialog(route) {
    const body = dialog('FOLLOW A THREAD / 探索路线', route.title);
    body.append(make('p', 'ob-dialog-intro', route.subtitle));
    const steps = make('div', 'ob-route-steps');
    route.nodes.forEach((node, i) => { const row = button('', 'ob-route-step', () => { state.activeRoute = route; openNode(node); }); row.append(make('span', '', journal.visits.includes(node.id) ? '✓' : String(i + 1).padStart(2, '0')), make('strong', '', node.title), make('small', '', kindText(node)), make('span', '', '↗')); steps.append(row); }); body.append(steps);
    const p = routeProgress(route, journal.visits);
    body.append(make('p', 'ob-fine', `${p.done} / ${p.total} 个坐标已抵达。路线是阅读建议；分支入口可能尚未积累主题知识。`));
    body.append(button(p.done === p.total ? '重新走一遍 ↗' : p.done ? '继续这条路线 ↗' : '沿线出发 ↗', 'ob-primary ob-full', () => { state.activeRoute = route; openNode(p.next); }));
  }
  function noteDialog(node) {
    if (!node) return;
    const body = dialog('A NOTE TO YOUR FUTURE SELF / 留给未来', node.title);
    body.append(make('p', 'ob-dialog-intro', '此刻想到了什么？留一句话，给下次经过的自己。'));
    const input = make('textarea', 'ob-note-input'); input.maxLength = 2000; input.rows = 6; input.value = journal.notes[node.id] || ''; input.placeholder = '一个问题、一种联想，或还没想明白的地方…'; input.setAttribute('aria-label', '探索短笺'); body.append(input);
    const remaining = make('p', 'ob-fine', `${input.value.length} / 2000 字`); input.addEventListener('input', () => { remaining.textContent = `${input.value.length} / 2000 字`; }); body.append(remaining);
    body.append(button('保存短笺与星标', 'ob-primary ob-full', async () => {
      journal.notes[node.id] = input.value.trim(); if (!journal.bookmarks.includes(node.id)) journal.bookmarks.unshift(node.id);
      if (!await persist()) return;
      $('dialog').close(); renderReaderBar(); if (state.view === 'journal') renderJournal(); announce('短笺与星标已保存到服务器。');
    }));
    input.focus();
  }
  function renderReaderBar() {
    const node = state.selected;
    $('reader-title').textContent = node ? `${kindText(node)} / ${node.title}` : '知识星图 · 点击一个星点开始阅读';
    $('read-save').textContent = node && journal.bookmarks.includes(node.id) ? '★ 已在星标中' : '☆ 收进星标';
    $('read-save').disabled = $('note').disabled = !node;
    $('read-save').setAttribute('aria-pressed', String(Boolean(node && journal.bookmarks.includes(node.id))));
    $('next').textContent = state.activeRoute ? `沿线前行 ${routeProgress(state.activeRoute, journal.visits).done}/${state.activeRoute.nodes.length} ↗` : '随机下一站 ↗';
  }
  function secretDialog() {
    const body = dialog('ROOM ZERO / 第零号观测室', '答案之外，还有连接。');
    body.append(make('p', 'ob-dialog-intro', '你已经走过构筑、叙事、流转与秩序。现在，试着把两个遥远的领域放在一起。'));
    const pair = make('div', 'ob-secret-pair'); pair.append(make('span', '', '设计'), make('span', '', '×'), make('span', '', '叙事')); body.append(pair);
    body.append(make('p', 'ob-secret-question', '如果一个界面是一部电影，用户第一次点击，会是什么样的开场？'));
    body.append(make('p', 'ob-fine', '这是一张思考邀请卡，不是知识库中的事实结论。把你的联想留成短笺，或者带着它去与主 Agent 聊聊。'));
    const node = state.catalog.byId.get('software-uiux/index') || state.catalog.territories[0];
    body.append(button('带着这个问题，再出发 ↗', 'ob-primary ob-full', () => openNode(node)));
  }

  async function load() {
    const revision = ++state.revision;
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 15000);
    try {
      const response = await fetch('/api/graph', { signal: controller.signal }); if (!response.ok) throw new Error(`知识库暂时不可读（${response.status}）。`);
      const graph = await response.json(); if (!Array.isArray(graph.nodes)) throw new Error('收到的星图格式不完整，请稍后重试。');
      if (revision !== state.revision) return;
      state.catalog = catalogFor(graph); state.loaded = true; $('error').hidden = true;
      if (state.selected) state.selected = state.catalog.byId.get(state.selected.id) || null;
      if (state.activeRoute) state.activeRoute = explorationRoutes(state.catalog).find(route => route.id === state.activeRoute.id) || null;
      renderHome(); if (state.view === 'archive') renderArchive(); if (state.view === 'journal') renderJournal(); renderReaderBar();
    } catch (error) {
      if (revision !== state.revision) return;
      $('error-message').textContent = error.name === 'AbortError' ? '连接等待较久，请检查本地服务后重新连接。' : error.message;
      $('error').hidden = false; $('hero-note').textContent = '信号暂时中断 · 可重试连接';
    } finally { clearTimeout(timeout); }
  }
  document.querySelectorAll('.ob-nav [data-view]').forEach(el => el.addEventListener('click', () => { if (el.dataset.view === 'archive') { state.territory = state.kind = 'all'; state.query = ''; } setView(el.dataset.view, true); }));
  $('brand').onclick = $('back-home').onclick = () => setView('home', true);
  $('show-map').onclick = $('workspace').onclick = () => setView('atlas');
  $('wander').onclick = wander; $('secret').onclick = secretDialog;
  $('agent').onclick = () => { const target = document.getElementById('ag-launch'); if (target) target.click(); else announce('主 Agent 入口正在加载，请稍后再试。'); };
  function searchFocus() { state.territory = state.kind = 'all'; setView('archive'); $('search').focus(); }
  $('search-launch').onclick = searchFocus;
  $('search').addEventListener('input', event => { state.query = event.target.value; renderArchive(); });
  $('kind').addEventListener('change', event => { state.kind = event.target.value; renderArchive(); });
  $('dialog-close').onclick = () => $('dialog').close();
  $('dialog').addEventListener('click', event => { if (event.target === $('dialog')) { const rect = $('dialog').getBoundingClientRect(); if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) $('dialog').close(); } });
  $('read-save').onclick = () => bookmark(state.selected); $('note').onclick = () => noteDialog(state.selected);
  $('next').onclick = () => {
    if (!state.activeRoute) { wander(); return; }
    const route = state.activeRoute, current = route.nodes.findIndex(n => n.id === state.selected?.id);
    if (current + 1 < route.nodes.length) openNode(route.nodes[current + 1]);
    else { announce('这条路线已经走完。也许，新的问题才刚刚开始。'); routeDialog(route); }
  };
  $('retry').onclick = load;
  document.addEventListener('keydown', event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k' && !document.querySelector('dialog[open]')) { event.preventDefault(); searchFocus(); }
    if (event.key === 'Escape' && !document.querySelector('dialog[open]') && state.view === 'archive') { if (state.query) { state.query = ''; renderArchive(); } else setView('home', true); }
  });
  window.addEventListener('federation:changed', load);
  setView('home'); load();
})().catch(error => {
  const message = document.createElement('p'); message.setAttribute('role', 'alert');
  message.textContent = '服务器上的阅读手记暂时无法读取，请刷新重试。原有浏览器副本尚未清除。';
  document.body.prepend(message); console.error(error);
});
