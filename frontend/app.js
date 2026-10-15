(() => {
  'use strict';

  const $ = (selector, root = document) => root.querySelector(selector);
  const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  const iconPaths = {
    chat: '<path d="M21 11.5a8.4 8.4 0 0 1-.9 3.8 8.5 8.5 0 0 1-7.6 4.7 8.4 8.4 0 0 1-3.8-.9L3 21l1.9-5.7a8.4 8.4 0 0 1-.9-3.8 8.5 8.5 0 0 1 4.7-7.6 8.4 8.4 0 0 1 3.8-.9h.5a8.5 8.5 0 0 1 8 8v.5Z"/><path d="M8 10h8M8 14h5"/>',
    inbox: '<path d="m4 5-2 9v6h20v-6l-2-9H4Z"/><path d="M2 14h6l2 3h4l2-3h6M8 9h8"/>',
    book: '<path d="M12 5v16M3 3h5a4 4 0 0 1 4 4 4 4 0 0 1 4-4h5v16h-5a4 4 0 0 0-4 2 4 4 0 0 0-4-2H3V3Z"/>',
    activity: '<path d="M3 12h4l3-8 4 16 3-8h4"/>',
    settings: '<path d="m9 3-.6 2-2 .9-1.9-.5-2 3.5L4 10.5v2.8L2.5 15l2 3.5 2-.5 1.9.9L9 21h4l.6-2 2-.9 1.9.5 2-3.5-1.5-1.6v-2.8L19.5 9l-2-3.5-2 .5-1.9-.9L13 3H9Z"/><circle cx="11" cy="12" r="3"/>',
    spark: '<path d="m12 3 2.8 6.2L21 12l-6.2 2.8L12 21l-2.8-6.2L3 12l6.2-2.8L12 3ZM20 2v4M18 4h4"/>',
    refresh: '<path d="M20 7v5h-5M4 17v-5h5"/><path d="M6 7a7 7 0 0 1 11.6-1.3L20 8M4 16l2.4 2.3A7 7 0 0 0 18 17"/>',
    plug: '<path d="M9 3v5m6-5v5M6 8h12v3a6 6 0 0 1-12 0V8Zm6 9v4"/>',
    search: '<circle cx="10.5" cy="10.5" r="6.5"/><path d="m16 16 5 5"/>',
    layers: '<path d="m12 3 10 5-10 5L2 8l10-5ZM2 12l10 5 10-5M2 16l10 5 10-5"/>',
    plus: '<path d="M12 5v14M5 12h14"/>',
    'arrow-up': '<path d="M12 19V5m-6 6 6-6 6 6"/>',
    folder: '<path d="M3 5h6l2 2h10v13H3V5Z"/>',
    check: '<path d="m5 12 4 4L19 6"/>',
    shield: '<path d="m12 3 8 3v6c0 5-8 9-8 9s-8-4-8-9V6l8-3Z"/><path d="m8 12 3 3 5-6"/>',
    close: '<path d="m6 6 12 12M6 18 18 6"/>',
    upload: '<path d="M12 16V3m-5 5 5-5 5 5M4 15v6h16v-6"/>',
    file: '<path d="M14 2H5v20h14V7l-5-5Z"/><path d="M14 2v5h5M8 12h8m-8 4h6"/>',
    clock: '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    warning: '<path d="m12 3 10 18H2L12 3ZM12 9v4m0 4h.01"/>',
  };

  function icon(name) {
    const span = document.createElement('span');
    span.setAttribute('aria-hidden', 'true');
    // Only hardcoded icon paths enter this markup; API content is always text.
    span.innerHTML = `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.65" stroke-linecap="round" stroke-linejoin="round">${iconPaths[name] || iconPaths.file}</svg>`;
    return span;
  }

  function node(tag, className, text) {
    const element = document.createElement(tag);
    if (className) element.className = className;
    if (text !== undefined && text !== null) element.textContent = String(text);
    return element;
  }

  $$('[data-icon]').forEach((element) => element.append(icon(element.dataset.icon).firstChild));

  const data = { agent: {}, stats: {}, runtime: {}, sources: [], pages: [], jobs: [] };
  let activeView = 'chat';
  let online = false;
  let stateLoading = false;
  let refreshInFlight = Promise.resolve();
  let chatBusy = false;
  let pollTimer = null;
  let settingsLoaded = false;
  let readerItem = null;
  let readerRequest = 0;
  let conversation = [];

  async function api(path, options = {}, timeout = 20000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeout);
    const headers = { Accept: 'application/json', ...(options.headers || {}) };
    const method = options.method || 'GET';
    if (method !== 'GET' && method !== 'HEAD') headers['X-Wiki-Client'] = 'local';
    if (options.body && !(options.body instanceof FormData)) headers['Content-Type'] = 'application/json';
    try {
      const response = await fetch(`/api${path}`, { ...options, method, headers, signal: controller.signal, credentials: 'same-origin', cache: 'no-store' });
      const contentType = response.headers.get('content-type') || '';
      const result = contentType.includes('application/json') ? await response.json() : null;
      if (!response.ok) {
        const raw = result?.detail || result?.error || result?.message;
        const message = typeof raw === 'string' ? raw : raw ? JSON.stringify(raw) : `请求失败（HTTP ${response.status}）`;
        throw new Error(message);
      }
      if (result === null) throw new Error('服务返回了非 JSON 内容，请确认本地服务已正常启动。');
      return result;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('请求等待超时，请稍后刷新查看结果。');
      if (error instanceof TypeError) throw new Error('无法连接本地服务，请检查服务是否正在运行。');
      throw error;
    } finally {
      clearTimeout(timer);
    }
  }

  function listFrom(value, key) {
    if (Array.isArray(value)) return value;
    return Array.isArray(value?.[key]) ? value[key] : [];
  }

  function dateText(value, includeTime = false) {
    if (!value) return '时间未记录';
    const date = new Date(value);
    if (Number.isNaN(date.getTime())) return String(value);
    return date.toLocaleString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit', ...(includeTime ? { hour: '2-digit', minute: '2-digit' } : {}) });
  }

  function statusLabel(status) {
    return ({ queued: '等待学习', pending: '尚未学习', running: '正在学习', succeeded: '学习完成', failed: '学习失败', learned: '已学习', ready: '待学习', imported: '待学习', stored: '待学习', new: '待学习', updated: '待重新学习', unlearned: '待学习' })[status] || '待学习';
  }

  function activeJobs() {
    return data.jobs.filter((job) => ['queued', 'running'].includes(job.status));
  }

  function sourceName(id) {
    return data.sources.find((source) => source.id === id)?.title || id || '资料学习';
  }

  function pageName(id) {
    return data.pages.find((page) => page.id === id || page.slug === id)?.title || id || 'Wiki 页面';
  }

  function toast(message, isError = false) {
    const item = node('div', `toast${isError ? ' error' : ''}`, message);
    $('#toast-region').append(item);
    setTimeout(() => item.remove(), 5000);
  }

  function formStatus(selector, message, isError = false) {
    const target = $(selector);
    target.textContent = message;
    target.classList.toggle('is-error', isError);
  }

  function busyButton(button, busy) {
    button.disabled = busy;
    button.setAttribute('aria-busy', String(busy));
  }

  function emptyState(symbol, title, description, actionLabel, action) {
    const wrapper = node('div', 'empty-state');
    wrapper.append(icon(symbol), node('h2', '', title), node('p', '', description));
    if (actionLabel) {
      const button = node('button', 'button primary', actionLabel);
      button.type = 'button';
      button.addEventListener('click', action);
      wrapper.append(button);
    }
    return wrapper;
  }

  function citationButton(citation) {
    const button = node('button', 'citation-button');
    button.type = 'button';
    const kind = citation.kind === 'source' ? 'source' : 'page';
    const label = citation.title || (kind === 'source' ? sourceName(citation.id) : pageName(citation.id));
    button.append(icon(kind === 'source' ? 'file' : 'book'), node('span', '', `${citation.number ? `[${citation.number}] ` : ''}${label}`));
    button.addEventListener('click', () => openReader(kind, citation.id, citation.revision ?? (kind === 'source' ? citation.source_revision : undefined)));
    return button;
  }

  // A deliberately small Markdown renderer. No HTML, scripts, images or external links
  // from documents are inserted into the DOM. Wiki links resolve only to known local pages.
  function inlineText(target, text) {
    const expression = /(`[^`\n]+`|\*\*[^*\n]+\*\*|\[\[[^\]\n]+\]\])/g;
    let last = 0;
    let match;
    while ((match = expression.exec(text))) {
      target.append(document.createTextNode(text.slice(last, match.index)));
      const token = match[0];
      if (token.startsWith('`')) target.append(node('code', '', token.slice(1, -1)));
      else if (token.startsWith('**')) target.append(node('strong', '', token.slice(2, -2)));
      else {
        const parts = token.slice(2, -2).split('|');
        const key = parts[0].replace(/\.md$/, '');
        const page = data.pages.find((item) => item.id === key || item.slug === key || item.title === key);
        if (page) target.append(citationButton({ kind: 'page', id: page.id || page.slug, title: parts[1] || page.title }));
        else target.append(document.createTextNode(parts[1] || key));
      }
      last = expression.lastIndex;
    }
    target.append(document.createTextNode(text.slice(last)));
  }

  function markdown(text) {
    const wrapper = node('div', 'markdown-body');
    const lines = String(text || '').replace(/\r\n?/g, '\n').split('\n');
    let paragraph = [];
    let list = null;
    let code = null;
    function flush() {
      if (paragraph.length) {
        const p = node('p');
        inlineText(p, paragraph.join('\n'));
        wrapper.append(p);
        paragraph = [];
      }
      list = null;
    }
    for (const line of lines) {
      if (/^\s*```/.test(line)) {
        if (code !== null) {
          const pre = node('pre');
          pre.append(node('code', '', code.join('\n')));
          wrapper.append(pre);
          code = null;
        } else {
          flush();
          code = [];
        }
        continue;
      }
      if (code !== null) { code.push(line); continue; }
      if (!line.trim()) { flush(); continue; }
      const heading = line.match(/^(#{1,6})\s+(.+)$/);
      const bullet = line.match(/^\s*(?:([-*+])\s+|(\d+)[.)]\s+)(.*)$/);
      if (heading) {
        flush();
        const h = node(`h${heading[1].length}`);
        inlineText(h, heading[2]);
        wrapper.append(h);
      } else if (/^\s*(---+|___+|\*\*\*+)\s*$/.test(line)) {
        flush(); wrapper.append(node('hr'));
      } else if (bullet) {
        if (paragraph.length) flush();
        const type = bullet[2] ? 'OL' : 'UL';
        if (!list || list.tagName !== type) {
          list = node(type.toLowerCase());
          wrapper.append(list);
        }
        const li = node('li');
        inlineText(li, bullet[3]);
        list.append(li);
      } else if (/^>\s?/.test(line)) {
        flush();
        const quote = node('blockquote');
        inlineText(quote, line.replace(/^>\s?/, ''));
        wrapper.append(quote);
      } else {
        list = null;
        paragraph.push(line);
      }
    }
    flush();
    if (code !== null) {
      const pre = node('pre'); pre.append(node('code', '', code.join('\n'))); wrapper.append(pre);
    }
    return wrapper;
  }

  function renderOverview() {
    const sources = data.stats.sources ?? data.sources.length;
    const pages = data.stats.pages ?? data.pages.length;
    $('#nav-source-count').textContent = sources;
    $('#nav-page-count').textContent = pages;
    $('#stat-sources').textContent = sources;
    $('#stat-pages').textContent = pages;
    $('#nav-job-active').hidden = activeJobs().length === 0;
    $('#sidebar-agent-name').textContent = data.agent.name || '我的知识智能体';
    $('#footer-model').textContent = data.agent.configured ? `${data.agent.provider === 'ollama' ? 'Ollama' : '兼容接口'} · ${data.agent.model || '模型已配置'}` : '尚未连接模型';
    $('#chat-setup-notice').hidden = Boolean(data.agent.configured);
    $('#send-button').disabled = chatBusy || !online || !data.agent.configured;
    $('#send-button').title = data.agent.configured ? '发送问题' : '请先在设置中连接模型';
    const badge = $('#connection-badge');
    badge.classList.toggle('offline', !online);
    badge.classList.toggle('ready', online && Boolean(data.agent.configured));
    badge.replaceChildren(node('span'), document.createTextNode(online ? (data.agent.configured ? '模型已配置 · 本地工作区' : '本地工作区 · 待配置模型') : '本地服务未连接'));
    const recent = $('#recent-pages');
    recent.replaceChildren();
    const sorted = [...data.pages].sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || ''))).slice(0, 4);
    if (!sorted.length) {
      const empty = node('div', 'recent-empty');
      empty.append(node('p', '', '知识从第一份资料开始'), node('span', '', '学习完成后，页面会出现在这里'));
      recent.append(empty);
    }
    sorted.forEach((page) => {
      const button = node('button', 'recent-item');
      const info = node('div');
      info.append(node('strong', '', page.title || page.id), node('small', '', dateText(page.updated_at)));
      button.append(icon('file'), info);
      button.addEventListener('click', () => openReader('page', page.id || page.slug));
      recent.append(button);
    });
  }

  function renderSources() {
    const list = $('#sources-list');
    list.replaceChildren();
    const search = $('#source-search').value.trim().toLocaleLowerCase();
    const sources = [...data.sources].filter((source) => String(source.title || '').toLocaleLowerCase().includes(search)).sort((a, b) => String(b.updated_at || b.created_at || '').localeCompare(String(a.updated_at || a.created_at || '')));
    $('#source-total').textContent = `共 ${data.sources.length} 份资料`;
    if (!sources.length) {
      list.append(search ? emptyState('search', '没有找到相关资料', '换一个关键词试试。') : emptyState('inbox', '把第一份资料放进来', '导入你经常查阅的说明、笔记或项目经验。原文会保存在资料箱中，连接模型后即可学习。', '导入第一份资料', openImport));
      return;
    }
    sources.forEach((source) => {
      const row = node('article', 'source-row');
      const symbol = node('span', 'source-symbol'); symbol.append(icon('file'));
      const main = node('div', 'source-main');
      const title = node('button', 'source-title', source.title || '未命名资料');
      title.addEventListener('click', () => openReader('source', source.id));
      const details = node('div', 'source-description');
      details.append(node('span', '', dateText(source.updated_at || source.created_at, true)));
      if (source.origin) details.append(node('span', '', String(source.origin).slice(0, 80)));
      main.append(title, details);
      const status = source.status || 'ready';
      const pill = node('span', `status-pill ${['running', 'queued', 'succeeded', 'failed', 'learned'].includes(status) ? status : ''}`, statusLabel(status));
      const pending = activeJobs().some((job) => job.source_id === source.id);
      const learn = node('button', 'button secondary', pending ? '学习中…' : ['succeeded', 'learned'].includes(status) ? '重新学习' : '学习资料');
      learn.disabled = !data.agent.configured || pending;
      learn.title = data.agent.configured ? '学习资料并更新 Wiki' : '请先在设置中连接模型';
      learn.addEventListener('click', () => learnSource(source.id, learn));
      row.append(symbol, main, pill, learn);
      list.append(row);
    });
  }

  function renderPages() {
    const list = $('#pages-list'); list.replaceChildren();
    const search = $('#page-search').value.trim().toLocaleLowerCase();
    const pages = [...data.pages].filter((page) => String(page.title || '').toLocaleLowerCase().includes(search)).sort((a, b) => String(b.updated_at || '').localeCompare(String(a.updated_at || '')));
    $('#page-total').textContent = `共 ${data.pages.length} 个页面`;
    if (!pages.length) {
      list.append(search ? emptyState('search', '还没有这个主题', '试试其他标题关键词。') : emptyState('book', '这里会长出你的知识', '学习资料后，智能体会整理主题页面、关联已有知识，并保留原始资料作为依据。', '前往资料箱', () => navigate('sources')));
      return;
    }
    pages.forEach((page) => {
      const card = node('button', 'page-card');
      card.append(icon('book'), node('h2', '', page.title || page.id));
      const excerpt = String(page.summary || page.body || page.content || '').replace(/^#+\s+.*\n?/m, '').replace(/[#*`\[\]]/g, '').trim();
      if (excerpt) card.append(node('p', '', excerpt.slice(0, 200)));
      const footer = node('footer');
      footer.append(node('span', '', `更新于 ${dateText(page.updated_at)}`), node('span', '', `${Array.isArray(page.source_ids) ? page.source_ids.length : 0} 份来源`));
      card.append(footer);
      card.addEventListener('click', () => openReader('page', page.id || page.slug));
      list.append(card);
    });
  }

  function renderJobs() {
    const list = $('#jobs-list'); list.replaceChildren();
    if (!data.jobs.length) {
      list.append(emptyState('activity', '每一次学习，都有迹可循', '学习开始后，你可以在这里查看进度、受影响的 Wiki 页面，以及需要处理的问题。', '选择一份资料', () => navigate('sources')));
      return;
    }
    [...data.jobs].sort((a, b) => String(b.created_at || '').localeCompare(String(a.created_at || ''))).forEach((job) => {
      const card = node('article', 'job-card');
      const indicator = node('div', `job-indicator ${['running', 'queued', 'succeeded', 'failed'].includes(job.status) ? job.status : ''}`);
      indicator.append(icon(job.status === 'succeeded' ? 'check' : job.status === 'failed' ? 'warning' : 'clock'));
      const info = node('div', 'job-info');
      const top = node('div', 'job-topline');
      top.append(node('h2', '', job.source_title || sourceName(job.source_id)), node('span', `status-pill ${['running', 'queued', 'succeeded', 'failed'].includes(job.status) ? job.status : ''}`, statusLabel(job.status)));
      info.append(top);
      const description = job.error || job.message || ({ queued: '任务已加入队列，正在等待处理。', running: '正在读取资料并整理相关知识。', succeeded: '资料学习已完成。', failed: '学习未完成，请检查模型连接或重试。' })[job.status] || '任务状态待确认。';
      info.append(node('p', '', typeof description === 'string' ? description : JSON.stringify(description)), node('div', 'job-time', dateText(job.created_at, true)));
      const pageIds = job.result?.page_ids || job.page_ids || [];
      if (Array.isArray(pageIds) && pageIds.length) {
        const refs = node('div', 'job-pages');
        pageIds.forEach((id) => refs.append(citationButton({ kind: 'page', id, title: pageName(id) })));
        info.append(refs);
      }
      card.append(indicator, info); list.append(card);
    });
  }

  function renderAll() {
    renderOverview(); renderSources(); renderPages(); renderJobs();
    const runtimeErrors = [
      data.runtime.last_error ? `学习任务：${data.runtime.last_error}` : '',
      data.runtime.watch_error ? `自动学习投递箱：${data.runtime.watch_error}` : '',
    ].filter(Boolean);
    const runtimeBanner = $('#runtime-error');
    runtimeBanner.hidden = runtimeErrors.length === 0;
    runtimeBanner.replaceChildren(...runtimeErrors.map((message) => node('p', '', message)));
    if (readerItem?.kind === 'source') updateReaderAction();
  }

  async function refreshState(visibleError = true) {
    if (stateLoading) { await refreshInFlight; return refreshState(visibleError); }
    stateLoading = true;
    let releaseRefresh;
    refreshInFlight = new Promise((resolve) => { releaseRefresh = resolve; });
    try {
      const result = await api('/state');
      data.agent = result.agent || {};
      data.stats = result.stats || {};
      data.runtime = result.runtime || {};
      data.sources = listFrom(result.sources, 'sources');
      data.pages = listFrom(result.pages, 'pages');
      data.jobs = listFrom(result.jobs, 'jobs');
      online = true;
      $('#global-error').hidden = true;
      if (!settingsLoaded) { populateSettings(data.agent); settingsLoaded = true; }
      renderAll();
    } catch (error) {
      online = false;
      renderOverview();
      if (visibleError) { $('#global-error').textContent = error.message; $('#global-error').hidden = false; }
    } finally {
      stateLoading = false;
      clearTimeout(pollTimer);
      pollTimer = setTimeout(() => { if (!document.hidden) refreshState(false); else schedulePoll(); }, activeJobs().length ? 3500 : 18000);
      releaseRefresh();
    }
  }

  function schedulePoll() {
    clearTimeout(pollTimer);
    pollTimer = setTimeout(() => { if (!document.hidden) refreshState(false); else schedulePoll(); }, 18000);
  }

  function navigate(view) {
    if (!['chat', 'sources', 'wiki', 'jobs', 'settings'].includes(view)) view = 'chat';
    activeView = view;
    $$('.view').forEach((section) => { const active = section.id === `view-${view}`; section.hidden = !active; section.classList.toggle('active', active); });
    $$('.nav-item').forEach((button) => { const active = button.dataset.view === view; button.classList.toggle('active', active); if (active) button.setAttribute('aria-current', 'page'); else button.removeAttribute('aria-current'); });
    $('#breadcrumb-view').textContent = ({ chat: '对话', sources: '资料箱', wiki: 'Wiki', jobs: '学习记录', settings: '设置' })[view];
    if (location.hash !== `#${view}`) history.replaceState(null, '', `#${view}`);
    if (view === 'settings' && !settingsLoaded) loadSettings();
  }

  function openImport() {
    formStatus('#import-status', '');
    if (!$('#import-dialog').open) $('#import-dialog').showModal();
  }

  function setImportTab(type) {
    const isText = type === 'text';
    $('#text-tab').classList.toggle('selected', isText);
    $('#file-tab').classList.toggle('selected', !isText);
    $('#text-tab').setAttribute('aria-selected', String(isText));
    $('#file-tab').setAttribute('aria-selected', String(!isText));
    $('#text-import-form').hidden = !isText;
    $('#file-import-form').hidden = isText;
    formStatus('#import-status', '');
  }

  async function submitSource(event, type) {
    event.preventDefault();
    const button = type === 'text' ? $('#save-text-button') : $('#save-file-button');
    busyButton(button, true); formStatus('#import-status', '正在保存资料…');
    try {
      let result;
      if (type === 'text') {
        const title = $('#import-title').value.trim();
        const text = $('#import-text').value.trim();
        if (!title || !text) throw new Error('请填写资料标题和原文内容。');
        result = await api('/sources', { method: 'POST', body: JSON.stringify({ title, text, origin: $('#import-origin').value.trim() }) });
      } else {
        const file = $('#import-file').files[0];
        if (!file) throw new Error('请先选择一份文件。');
        if (!/\.(md|txt|markdown)$/i.test(file.name)) throw new Error('当前支持 Markdown 与 TXT 文件。');
        if (file.size > 120000) throw new Error('文件超过 120 KB，请拆分后导入。');
        const form = new FormData(); form.append('file', file);
        result = await api('/upload', { method: 'POST', body: form }, 60000);
      }
      $('#import-dialog').close();
      event.target.reset();
      await refreshState();
      navigate('sources');
      toast(data.agent.configured ? '资料已保存，可以开始学习。' : '资料已保存。连接模型后即可学习。');
      const source = result.source || result;
      if (source.id) await openReader('source', source.id);
    } catch (error) { formStatus('#import-status', error.message, true); }
    finally { busyButton(button, false); }
  }

  function updateReaderAction() {
    const button = $('#reader-learn-button');
    if (!readerItem || readerItem.kind !== 'source') { button.hidden = true; return; }
    if (readerItem.sourceRevision) {
      button.hidden = true;
      formStatus('#reader-status', `当前显示引用时保存的原文 v${readerItem.sourceRevision}。如需学习最新资料，请从资料箱操作。`);
      return;
    }
    button.hidden = false;
    const pending = activeJobs().some((job) => job.source_id === readerItem.id);
    const source = data.sources.find((item) => item.id === readerItem.id);
    const learned = ['learned', 'succeeded'].includes(source?.status);
    button.replaceChildren(icon('spark'), document.createTextNode(pending ? '正在学习…' : learned ? '重新学习' : '学习这份资料'));
    button.disabled = !data.agent.configured || pending;
    if (!data.agent.configured) formStatus('#reader-status', '资料已保存。请先在设置中连接模型。');
    else if (pending) formStatus('#reader-status', '已加入学习队列，可在学习记录中查看进度。');
    else formStatus('#reader-status', '');
  }

  function renderPageSnapshot(page) {
    $('#reader-title').textContent = page.title || readerItem.id;
    const isHistory = page.revision !== readerItem.currentPage.revision;
    $('#reader-kind').textContent = isHistory ? 'WIKI · 历史版本预览' : 'WIKI · 知识页面';
    $('#reader-meta').textContent = `版本 v${page.revision} · 更新于 ${dateText(page.updated_at || page.created_at, true)}${page.model ? ` · ${String(page.model).startsWith('restore:') ? `恢复自 v${String(page.model).slice(8)}` : `模型：${page.model}`}` : ''}`;
    $('#reader-body').replaceChildren(...markdown(page.body || page.content || '').childNodes);
    const refs = $('#reader-references'); refs.replaceChildren();
    const sources = Array.isArray(page.sources) ? page.sources : [];
    refs.hidden = sources.length === 0;
    if (sources.length) {
      refs.append(node('strong', '', '来源资料 · 引用时的版本'));
      sources.forEach((source) => {
        if (typeof source.id !== 'string') return;
        if (!Number.isInteger(source.revision) || source.revision < 1) {
          refs.append(node('span', 'field-help', `${source.title || sourceName(source.id)}（未记录版本，无法定位引用原文）`));
          return;
        }
        refs.append(citationButton({ kind: 'source', id: source.id, revision: source.revision, title: `${source.title || sourceName(source.id)} · v${source.revision}` }));
      });
    } else if (Array.isArray(page.source_ids) && page.source_ids.length) {
      refs.hidden = false;
      refs.append(node('span', 'field-help', '此页面只记录了资料 ID，缺少来源版本信息，无法定位引用时的原文。'));
    }
    readerItem.previewRevision = page.revision;
    $('#history-current-label').textContent = `当前发布 v${readerItem.currentPage.revision}${isHistory ? ` · 正在预览 v${page.revision}` : ''}`;
    $('#history-restore-button').disabled = !isHistory;
  }

  async function openReader(kind, id, revision) {
    if (typeof id !== 'string' || !id) { toast('这条引用缺少有效的页面标识。', true); return; }
    const request = ++readerRequest;
    const requestedRevision = Number.isInteger(revision) && revision > 0 ? revision : null;
    const sourceRevision = kind === 'source' ? requestedRevision : null;
    readerItem = { kind, id, sourceRevision };
    $('#reader-kind').textContent = kind === 'source' ? 'SOURCE · 原始资料' : 'WIKI · 知识页面';
    $('#reader-title').textContent = '正在读取…';
    $('#reader-meta').textContent = '';
    $('#reader-body').replaceChildren();
    $('#reader-references').replaceChildren(); $('#reader-references').hidden = true;
    $('#reader-learn-button').hidden = true;
    $('#reader-history').hidden = true;
    $('#history-controls').hidden = true;
    $('#history-toggle-button').setAttribute('aria-expanded', 'false');
    $('#history-toggle-button').disabled = false;
    $('#history-select').replaceChildren();
    formStatus('#history-status', '');
    formStatus('#reader-status', '');
    if (!$('#reader-dialog').open) $('#reader-dialog').showModal();
    try {
      const path = `/${kind === 'source' ? 'sources' : 'pages'}/${encodeURIComponent(id)}`;
      const [raw, currentPage] = await Promise.all([
        api(`${path}${requestedRevision ? `?revision=${requestedRevision}` : ''}`),
        kind === 'page' && requestedRevision ? api(path) : Promise.resolve(null),
      ]);
      if (request !== readerRequest) return;
      const item = raw[kind] || raw;
      if (kind === 'page') {
        readerItem.currentPage = currentPage?.page || currentPage || item;
        $('#reader-history').hidden = false;
        renderPageSnapshot(item);
      } else {
        $('#reader-title').textContent = item.title || id;
        $('#reader-meta').textContent = `${item.revision ? `原文 v${item.revision} · ` : ''}保存于 ${dateText(item.updated_at || item.created_at, true)}${item.origin ? ` · 来源：${item.origin}` : ''}`;
        $('#reader-body').replaceChildren(...markdown(item.text || item.content || '').childNodes);
      }
      updateReaderAction();
    } catch (error) {
      if (request !== readerRequest) return;
      $('#reader-title').textContent = '未能读取内容';
      formStatus('#reader-status', error.message, true);
    }
  }

  async function toggleHistory() {
    if (readerItem?.kind !== 'page' || !readerItem.currentPage) return;
    const controls = $('#history-controls');
    const button = $('#history-toggle-button');
    if (!controls.hidden) { controls.hidden = true; button.setAttribute('aria-expanded', 'false'); return; }
    controls.hidden = false; button.setAttribute('aria-expanded', 'true');
    if (readerItem.revisions) return;
    busyButton(button, true);
    formStatus('#history-status', '正在读取历史版本…');
    const request = readerRequest;
    try {
      const result = await api(`/pages/${encodeURIComponent(readerItem.id)}/revisions`);
      if (request !== readerRequest) return;
      readerItem.revisions = listFrom(result, 'revisions');
      const select = $('#history-select'); select.replaceChildren();
      readerItem.revisions.forEach((page) => {
        const current = page.revision === readerItem.currentPage.revision;
        const option = node('option', '', `v${page.revision}${current ? ' · 当前发布' : ''} · ${dateText(page.updated_at, true)}`);
        option.value = String(page.revision); select.append(option);
      });
      select.value = String(readerItem.previewRevision);
      formStatus('#history-status', readerItem.revisions.length ? `共 ${readerItem.revisions.length} 个版本` : '尚未找到历史快照。');
    } catch (error) { if (request === readerRequest) formStatus('#history-status', error.message, true); }
    finally { if (request === readerRequest) busyButton(button, false); }
  }

  function selectHistory() {
    if (readerItem?.kind !== 'page') return;
    const revision = Number($('#history-select').value);
    const page = readerItem.revisions?.find((item) => item.revision === revision);
    if (!page) return;
    renderPageSnapshot(page);
    formStatus('#history-status', revision === readerItem.currentPage.revision ? '正在查看当前发布版本。' : `预览 v${revision}，尚未修改当前页面。`);
  }

  async function restoreHistory() {
    if (readerItem?.kind !== 'page' || !readerItem.previewRevision || readerItem.previewRevision === readerItem.currentPage.revision) return;
    const button = $('#history-restore-button'); busyButton(button, true);
    const id = readerItem.id;
    const revision = readerItem.previewRevision;
    const request = readerRequest;
    formStatus('#history-status', `正在从 v${revision} 创建恢复版本…`);
    try {
      const restored = await api(`/pages/${encodeURIComponent(id)}/restore`, { method: 'POST', body: JSON.stringify({ revision }) });
      await refreshState();
      toast(`已恢复 v${revision} 的内容，当前版本为 v${restored.revision}，历史记录已保留。`);
      if (request === readerRequest) {
        readerItem.currentPage = restored;
        readerItem.revisions = null;
        renderPageSnapshot(restored);
        $('#history-controls').hidden = true;
        await toggleHistory();
        formStatus('#history-status', `已从 v${revision} 恢复为 v${restored.revision}。`);
      }
    } catch (error) { if (request === readerRequest) formStatus('#history-status', error.message, true); else toast(error.message, true); }
    finally { if (request === readerRequest) { busyButton(button, false); button.disabled = readerItem.previewRevision === readerItem.currentPage.revision; } }
  }

  async function learnSource(id, button) {
    if (!data.agent.configured) { toast('请先在设置中连接模型。'); return; }
    if (button) busyButton(button, true);
    try {
      await api('/learn', { method: 'POST', body: JSON.stringify({ source_id: id }) });
      await refreshState();
      toast('学习任务已创建，可在学习记录中查看进度。');
    } catch (error) { toast(error.message, true); }
    finally { if (button?.isConnected) busyButton(button, false); updateReaderAction(); renderSources(); }
  }

  function chatMessage(message) {
    const role = message.role === 'user' ? 'user' : 'assistant';
    const block = node('article', `chat-message ${role}`);
    const avatar = node('div', 'message-avatar');
    if (role === 'user') avatar.textContent = '我'; else avatar.append(icon('spark'));
    const content = node('div', 'message-content');
    content.append(node('div', 'message-label', role === 'user' ? '我' : data.agent.name || '知识智能体'));
    const text = message.content ?? message.answer ?? message.text ?? '';
    content.append(markdown(typeof text === 'string' ? text : JSON.stringify(text)));
    if (Array.isArray(message.citations) && message.citations.length) {
      const citations = node('div', 'message-citations');
      message.citations.filter((item) => item && typeof item.id === 'string').forEach((citation) => citations.append(citationButton(citation)));
      content.append(citations);
    }
    block.append(avatar, content);
    return block;
  }

  function renderConversation() {
    $$('.chat-message, .message-error, .message-pending', $('#chat-messages')).forEach((item) => item.remove());
    $('#chat-welcome').hidden = conversation.length > 0;
    conversation.forEach((message) => $('#chat-messages').append(chatMessage(message)));
  }

  async function loadChat() {
    try {
      const result = await api('/chat');
      if (chatBusy) return;
      conversation = listFrom(result, 'messages').filter((message) => ['user', 'assistant'].includes(message.role));
      renderConversation();
    } catch (error) { if (online) toast(`无法读取对话记录：${error.message}`, true); }
  }

  async function submitChat(event) {
    event.preventDefault();
    if (chatBusy) return;
    const input = $('#chat-input');
    const message = input.value.trim();
    if (!message) return;
    if (!data.agent.configured) { toast('先连接模型，就可以与知识库对话。'); navigate('settings'); return; }
    chatBusy = true; renderOverview();
    conversation.push({ role: 'user', content: message });
    input.value = ''; renderConversation();
    const pending = node('div', 'message-pending', '正在查阅知识并组织回答…');
    $('#chat-messages').append(pending);
    pending.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    try {
      const result = await api('/chat', { method: 'POST', body: JSON.stringify({ message }) }, 240000);
      if (typeof result.answer !== 'string') throw new Error('模型没有返回可显示的回答。');
      conversation.push({ role: 'assistant', content: result.answer, citations: result.citations || [] });
      renderConversation();
      const messages = $$('.chat-message', $('#chat-messages'));
      messages.at(-1)?.scrollIntoView({ block: 'start', behavior: 'smooth' });
    } catch (error) {
      pending.remove();
      $('#chat-messages').append(node('div', 'message-error', `这次回答未完成：${error.message}`));
      if (!input.value) input.value = message;
    } finally { pending.remove(); chatBusy = false; renderOverview(); }
  }

  function populateSettings(agent) {
    $('#setting-name').value = agent.name || '我的知识智能体';
    $('#setting-purpose').value = agent.purpose || '';
    $('#setting-provider').value = ['disabled', 'ollama', 'compatible'].includes(agent.provider) ? agent.provider : 'disabled';
    $('#setting-base-url').value = agent.base_url || '';
    $('#setting-model').value = agent.model || '';
    $('#setting-api-key').value = '';
    $('#setting-api-key').placeholder = agent.api_key_set ? '已保存密钥 · 留空保持不变' : '填写 API Key（服务无需密钥时可留空）';
    $('#api-key-help').textContent = agent.api_key_set ? '后端已有密钥。同一服务留空保持原值，切换服务需重新填写。' : '密钥仅写入后端配置，页面不会回显。';
    $('#setting-watch-inbox').checked = Boolean(agent.watch_inbox);
    updateProviderFields();
  }

  function updateProviderFields() {
    const provider = $('#setting-provider').value;
    $('#model-fields').hidden = provider === 'disabled';
    $('#api-key-field').hidden = provider !== 'compatible';
    $('#setting-base-url').required = provider !== 'disabled';
    $('#setting-model').required = provider !== 'disabled';
    $('#setting-watch-inbox').disabled = provider === 'disabled' || !data.agent.configured;
    if (provider === 'disabled') $('#setting-watch-inbox').checked = false;
    $('#watch-help').textContent = data.agent.configured && provider !== 'disabled' ? '服务停止时不会执行后台学习。你也可以在资料箱手动扫描。' : '请先保存有效的模型配置，再开启自动学习。服务停止时不会执行后台学习。';
    $('#setting-base-url').placeholder = provider === 'ollama' ? 'http://127.0.0.1:11434' : 'https://your-provider.example/v1';
    $('#base-url-help').textContent = provider === 'ollama' ? '填写 Ollama 基础地址，例如 http://127.0.0.1:11434。' : '填写兼容 API 的基础地址，通常以 /v1 结尾。';
    $('#check-model-button').disabled = !data.agent.configured;
  }

  async function loadSettings() {
    try {
      const result = await api('/settings');
      data.agent = result.agent || result;
      populateSettings(data.agent); settingsLoaded = true;
    } catch (error) { formStatus('#settings-status', error.message, true); }
  }

  async function saveSettings(event) {
    event.preventDefault();
    const button = $('#save-settings-button'); busyButton(button, true);
    formStatus('#settings-status', '正在保存…');
    const payload = {
      name: $('#setting-name').value.trim(),
      purpose: $('#setting-purpose').value.trim(),
      provider: $('#setting-provider').value,
      base_url: $('#setting-base-url').value.trim(),
      model: $('#setting-model').value.trim(),
      watch_inbox: $('#setting-watch-inbox').checked,
    };
    const apiKey = $('#setting-api-key').value.trim();
    if (apiKey) payload.api_key = apiKey;
    try {
      await api('/settings', { method: 'PUT', body: JSON.stringify(payload) });
      $('#setting-api-key').value = '';
      await refreshState();
      populateSettings(data.agent);
      formStatus('#settings-status', '设置已保存。');
      formStatus('#model-check-status', '');
    } catch (error) { formStatus('#settings-status', error.message, true); }
    finally { busyButton(button, false); }
  }

  async function checkModel() {
    const button = $('#check-model-button'); busyButton(button, true);
    formStatus('#model-check-status', '正在检测已保存的模型配置…');
    try {
      const result = await api('/model/check', { method: 'POST' }, 90000);
      let message = result.detail || (result.ok ? '模型连接正常。' : '模型连接检测失败。');
      if (typeof message !== 'string') message = JSON.stringify(message);
      if (Array.isArray(result.models) && result.models.length) message += ` 可用模型：${result.models.map((item) => typeof item === 'string' ? item : item.name || item.id || '').filter(Boolean).slice(0, 8).join('、')}`;
      formStatus('#model-check-status', message, !result.ok);
    } catch (error) { formStatus('#model-check-status', error.message, true); }
    finally { busyButton(button, false); }
  }

  async function scanInbox() {
    const button = $('#scan-inbox-button'); busyButton(button, true); button.classList.add('is-spinning');
    try {
      const result = await api('/inbox/scan', { method: 'POST' }, 60000);
      const count = (value) => Array.isArray(value) ? value.length : Number(value || 0);
      const imported = count(result.imported);
      const queued = count(result.queued);
      const errors = Array.isArray(result.errors) ? result.errors : [];
      await refreshState();
      const report = $('#scan-results');
      report.hidden = false;
      report.replaceChildren(node('p', '', `扫描完成：导入 ${imported} 份资料，新增 ${queued} 个学习任务。`));
      errors.forEach((error) => report.append(node('p', 'scan-error', typeof error === 'string' ? error : `${error.file || '未知文件'}：${error.error || error.message || JSON.stringify(error)}`)));
      toast(`扫描完成：导入 ${imported} 份资料，新增 ${queued} 个学习任务。${errors.length ? ` ${errors.length} 项未成功，详情已显示在资料箱。` : ''}`, errors.length > 0);
    } catch (error) { toast(error.message, true); }
    finally { busyButton(button, false); button.classList.remove('is-spinning'); }
  }

  async function lintWiki() {
    const button = $('#lint-button'); busyButton(button, true);
    const results = $('#lint-results'); results.replaceChildren(node('p', 'muted', '正在检查页面、链接与引用…'));
    if (!$('#lint-dialog').open) $('#lint-dialog').showModal();
    try {
      const result = await api('/lint', { method: 'POST' }, 60000);
      results.replaceChildren();
      const issues = Array.isArray(result.issues) ? result.issues : [];
      const summary = data.pages.length === 0 ? '知识库还没有页面。学习资料后，再检查页面与来源。' : issues.length === 0 ? '本次规则检查未发现问题。事实准确性仍需结合原文核验。' : `发现 ${issues.length} 项需要关注的问题。`;
      results.append(node('div', 'lint-summary', summary));
      issues.forEach((issue) => {
        const item = node('div', 'lint-issue');
        if (typeof issue === 'string') item.textContent = issue;
        else {
          item.append(node('p', '', issue.message || issue.detail || issue.description || JSON.stringify(issue)));
          if (issue.page_id || issue.page) item.append(node('small', '', `页面：${issue.page_id || issue.page}`));
        }
        results.append(item);
      });
    } catch (error) { results.replaceChildren(node('div', 'message-error', error.message)); }
    finally { busyButton(button, false); }
  }

  $$('[data-view]').forEach((button) => button.addEventListener('click', () => navigate(button.dataset.view)));
  $$('[data-navigate]').forEach((button) => button.addEventListener('click', () => navigate(button.dataset.navigate)));
  $$('[data-action="import"]').forEach((button) => button.addEventListener('click', openImport));
  $$('[data-close]').forEach((button) => button.addEventListener('click', () => $(`#${button.dataset.close}`).close()));
  $$('[data-prompt]').forEach((button) => button.addEventListener('click', () => { $('#chat-input').value = button.dataset.prompt; $('#chat-input').focus(); }));
  $('#text-tab').addEventListener('click', () => setImportTab('text'));
  $('#file-tab').addEventListener('click', () => setImportTab('file'));
  $('#text-import-form').addEventListener('submit', (event) => submitSource(event, 'text'));
  $('#file-import-form').addEventListener('submit', (event) => submitSource(event, 'file'));
  $('#source-search').addEventListener('input', renderSources);
  $('#page-search').addEventListener('input', renderPages);
  $('#reader-learn-button').addEventListener('click', () => { if (readerItem?.kind === 'source') learnSource(readerItem.id, $('#reader-learn-button')); });
  $('#history-toggle-button').addEventListener('click', toggleHistory);
  $('#history-select').addEventListener('change', selectHistory);
  $('#history-restore-button').addEventListener('click', restoreHistory);
  $('#chat-form').addEventListener('submit', submitChat);
  $('#chat-input').addEventListener('keydown', (event) => { if (event.key === 'Enter' && !event.shiftKey && !event.isComposing) { event.preventDefault(); $('#chat-form').requestSubmit(); } });
  $('#settings-form').addEventListener('submit', saveSettings);
  $('#setting-provider').addEventListener('change', updateProviderFields);
  $('#check-model-button').addEventListener('click', checkModel);
  $('#scan-inbox-button').addEventListener('click', scanInbox);
  $('#lint-button').addEventListener('click', lintWiki);
  $('#refresh-button').addEventListener('click', async () => {
    const button = $('#refresh-button'); button.classList.add('is-spinning');
    try { await refreshState(); if (activeView === 'chat') await loadChat(); }
    finally { button.classList.remove('is-spinning'); }
  });
  window.addEventListener('hashchange', () => navigate(location.hash.slice(1)));
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refreshState(false); });
  $('#reader-dialog').addEventListener('close', () => { readerRequest++; readerItem = null; });
  $('#import-dialog').addEventListener('close', () => formStatus('#import-status', ''));

  navigate(location.hash.slice(1) || 'chat');
  renderAll();
  refreshState().then(loadChat);
})();
