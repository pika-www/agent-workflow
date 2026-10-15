/* A permanent conversation workspace. Activity comes only from host receipts. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);
  const make = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = String(text); return node; };
  const state = { agents: [], jobs: [], room: null, reportModel:null, directoryKey: '', linkKey: '', hotKey: '', hotOpen: true, category: 'all', query: '', sort: 'latest', hotspotSources: [], stopped: false, hotspotItems: [], selectedHotspot: null, readerEpoch: 0, readerArticle: null };
  const active = status => ['queued', 'running'].includes(status);
  const clock = value => value && !Number.isNaN(new Date(value).valueOf()) ? new Date(value).toLocaleTimeString('zh-CN', { hour12: false }) : '—';
  const labels = { queued: '等待', running: '执行中', completed: '完成', failed: '未完成' };
  const agentName = id => id === 'central' ? '主 Agent' : state.agents.find(item => item.id === id)?.name || 'Agent';
  function createHeartbeat() {
    const graph = $('ws-pulse'), path = graph.querySelector('path'), cursor = graph.querySelector('circle');
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    const windowMs = 7000, now = () => performance.now();
    let room = null, roomKey = '', streamKey = '', revision = -1, textLength = 0;
    let online = false, running = 0, queued = 0, visible = true, destroyed = false;
    let frame = 0, lastPaint = 0, lastText = -Infinity, lastReceipt = '', lastSignal = '', actor = 'central';
    let beats = [], samples = [];
    function beat(time, chars, kind) {
      const previous = beats.at(-1);
      if (previous && time - previous.time < 900) {
        previous.chars += chars;
        if (kind === 'text') previous.kind = 'text';
      }
      else beats.push({time, chars, kind});
      beats = beats.filter(value => time - value.time < windowMs).slice(-32);
    }
    function resetStream() {
      streamKey = ''; revision = -1; textLength = 0; samples = []; lastText = -Infinity;
    }
    function ingest(reply, seed = false) {
      if (!active(room?.status) || reply?.job_id !== room.active_job_id || typeof reply.text !== 'string' ||
          reply.text.length > 64000 || !Number.isInteger(reply.revision) || reply.revision < 0) return;
      const key = reply.job_id + ':' + (reply.turn_id || reply.agent_id || 'central');
      if (key !== streamKey) { resetStream(); streamKey = key; }
      if (reply.revision <= revision) return;
      const chars = Array.from(reply.text.slice(textLength)).length;
      revision = reply.revision; textLength = reply.text.length; actor = reply.agent_id || 'central';
      if (!seed && chars > 0) {
        const time = now(); online = true; lastText = time;
        samples.push({time, chars}); samples = samples.filter(value => time - value.time < 2000);
        beat(time, chars, 'text'); $('ws-heart-time').textContent = '文本 ' + clock(new Date());
      }
    }
    function mode(time) {
      if (!online) return 'offline';
      if (active(room?.status) && time - lastText < 2500) return 'reply';
      if (running || queued || active(room?.status)) return 'waiting';
      return room?.status === 'failed' ? 'failed' : 'idle';
    }
    function paint(time) {
      const activity = mode(time), replying = activity === 'reply', working = replying || activity === 'waiting';
      samples = samples.filter(value => time - value.time < 2000);
      beats = beats.filter(value => time - value.time < windowMs);
      const rate = samples.reduce((total, value) => total + value.chars, 0) / 2;
      graph.dataset.mode = activity;
      graph.classList.toggle('active', working); $('ws-heart-dot').classList.toggle('active', working);
      $('ws-heart-dot').classList.toggle('offline', activity === 'offline' || activity === 'failed');
      $('ws-heart-state').textContent = replying ? agentName(actor) + ' 正在回复' : activity === 'offline' ? '服务未连接' :
        activity === 'failed' ? '本轮未完成' : activity === 'waiting' ? queued && !running && room?.status !== 'running' ? '等待开始' : '正在处理' : '在线 · 等你开聊';
      const signal = replying ? '接收 ' + Math.round(rate) + ' 字/秒 · 文本回执' : activity === 'waiting' ?
        '慢脉冲 · 服务回执' : activity === 'offline' ? '未收到服务回执' : activity === 'failed' ? '失败信息保留在对话中' : '依据新增文本与服务回执';
      if (signal !== lastSignal) { $('ws-heart-signal').textContent = signal; lastSignal = signal; }
      let d = 'M0 40';
      if (activity !== 'offline' && !motion.matches) {
        for (const value of beats) {
          const x = 237 - (time - value.time) / windowMs * 260;
          if (x < 12) continue;
          const amplitude = value.kind === 'text' ? Math.min(21, 8 + Math.log2(1 + value.chars) * 1.7) : 4;
          const point = (dx, dy) => `${(x + dx).toFixed(1)} ${(40 + amplitude * dy).toFixed(1)}`;
          d += ` H${(x - 11).toFixed(1)} C${point(-9, 0)} ${point(-9, -.1)} ${point(-7, -.1)} C${point(-5, -.1)} ${point(-5, .18)} ${point(-3, .18)} C${point(-2, .18)} ${point(-1, -1)} ${point(0, -1)} C${point(1, -1)} ${point(2, .45)} ${point(4, .45)} C${point(6, .45)} ${point(6, -.08)} ${point(8, -.08)} C${point(10, -.08)} ${point(11, 0)} ${point(13, 0)}`;
        }
      }
      path.setAttribute('d', d + ' H260');
      const thump = !motion.matches && replying ? Math.max(0, 1 - (time - lastText) / 500) : 0;
      cursor.setAttribute('r', (2 + thump * 1.8).toFixed(1));
      $('ws-heart-dot').style.transform = thump ? `scale(${(1 + thump * .7).toFixed(2)})` : '';
      return working || beats.length > 0;
    }
    function tick(time) {
      frame = 0;
      if (destroyed || !visible || document.hidden || motion.matches || state.stopped) return;
      if (time - lastPaint < 33) { frame = requestAnimationFrame(tick); return; }
      lastPaint = time;
      if (paint(time)) frame = requestAnimationFrame(tick);
    }
    function schedule() {
      if (destroyed) return;
      cancelAnimationFrame(frame); frame = 0;
      if (!visible || document.hidden || state.stopped) return;
      const moving = paint(now());
      if (moving && !motion.matches) frame = requestAnimationFrame(tick);
    }
    motion.addEventListener('change', schedule); document.addEventListener('visibilitychange', schedule);
    return {
      room(value) {
        const key = value?.id + ':' + (value?.active_job_id || '');
        const changed = key !== roomKey; room = value;
        if (changed) { roomKey = key; resetStream(); beats = []; }
        if (room?.live_reply) ingest(room.live_reply, changed || !streamKey);
        schedule();
      },
      reply(value) { ingest(value); schedule(); },
      receipt(data) {
        online = true; running = Number(data.running) || 0; queued = Number(data.queued) || 0;
        const time = now();
        if (data.observed_at !== lastReceipt && (running || queued || active(room?.status)) && time - lastText > 1500) beat(time, 0, 'service');
        lastReceipt = data.observed_at;
        if (time - lastText > 1500) $('ws-heart-time').textContent = '回执 ' + clock(data.observed_at);
        schedule();
      },
      offline() { online = false; schedule(); },
      setVisible(value) { visible = value; schedule(); },
      destroy() { destroyed = true; cancelAnimationFrame(frame); motion.removeEventListener('change', schedule); document.removeEventListener('visibilitychange', schedule); }
    };
  }
  const stageName = job => job?.activity && active(job.status) ? job.activity : (job?.intake_stage === 'consulting_specialist' && job?.requested_agents?.length ? '成员直接回答' : ({ chatting: '对话', reading_memory: '读取已确认要求', reading_hotspot: '读取当前热点', researching: '查阅公开资料', reading_page: '读取动态页面', checking_sources: '核对资料原文', writing_analysis: '生成产品分析', exporting_report: '生成下载文档', drafting: '整理方案', answering: '生成答复', repairing_format: '修正答复格式', consulting_specialist: '咨询成员', answered: '已回复', awaiting_confirmation: '等待确认方案', awaiting_clarification: '等待补充需求' }[job?.intake_stage] || ({ ask: '查阅知识并回答', chat: '对话', learn: '学习资料', sync: '汇总知识', social_reply: '准备回复' }[job?.action]) || '处理任务'));
  async function get(path) {
    const response = await fetch(path, { cache: 'no-store', signal: AbortSignal.timeout(12000) });
    if (!response.ok) throw new Error('HTTP ' + response.status);
    return response.json();
  }
  function currentActor() {
    const room = state.room;
    if (!room || !active(room.status)) return null;
    const current = state.agents.find(item => item.id === room.current_agent || item.name === room.current_agent);
    return current?.id || room.live_reply?.agent_id || (room.current_agent === '主 Agent' ? 'central' : null);
  }
  function hasVisibleReply() { return Boolean(state.room?.live_reply?.text && (state.room.live_reply.agent_id || 'central') === currentActor()); }
  function renderDirectory() {
    // The directory now lives beside the chat composer. This panel shows activity only.
    $('ws-cog-agent-count').textContent = state.agents.length;
    $('ws-cog-knowledge').textContent = state.agents.find(member => member.id === 'central')?.knowledge_count || 0;
    cognition?.refresh();
  }
  function graph(actor, specialist, directMember) {
    const svgNS = 'http://www.w3.org/2000/svg', svg = document.createElementNS(svgNS, 'svg'); svg.setAttribute('viewBox', '0 0 208 78');
    function element(tag, attrs, text) { const node = document.createElementNS(svgNS, tag); for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value); if (text) node.textContent = text; svg.append(node); return node; }
    const memberLabel = specialist ? agentName(specialist).replace(/ Agent$/, '').slice(0, 8) : '成员待命';
    const nodes = directMember ? [[42, '你', null], [166, memberLabel, specialist]] : specialist
      ? [[30, '你', null], [104, '主 Agent', 'central'], [178, memberLabel, specialist]]
      : [[42, '你', null], [166, '主 Agent', 'central']];
    for (let index = 1; index < nodes.length; index++) element('line', { x1: nodes[index - 1][0], y1: 34, x2: nodes[index][0], y2: 34, class: actor ? 'linked' : '' });
    for (const [x, label, id] of nodes) {
      element('circle', { cx: x, cy: 34, r: id && id === actor ? 16 : 13, ...(id && id === actor ? { style: 'stroke:#e8b363;fill:#352a1d' } : {}) });
      element('text', { x, y: 65, 'text-anchor': 'middle' }, label);
    }
    $('ws-link-graph').replaceChildren(svg);
  }
  function renderLinkage() {
    const room = state.room, actor = currentActor(), rootId = room?.active_job_id || [...(room?.messages || [])].reverse().find(message => message.role === 'user')?.round_id;
    const turns = state.jobs.filter(job => job.parent_job_id === rootId).sort((a, b) => a.created_at.localeCompare(b.created_at));
    const specialist = actor && actor !== 'central' ? actor : turns.find(turn => turn.space !== 'central')?.space;
    const directMember = Boolean(specialist && room?.purpose === 'primary' && !turns.some(turn => turn.space === 'central'));
    const key = JSON.stringify([actor, directMember, turns.map(turn => [turn.id, turn.status]), room?.status]);
    if (key === state.linkKey) return; state.linkKey = key;
    graph(actor, specialist, directMember);
    $('ws-link-state').textContent = room?.status === 'queued' ? '排队' : actor ? '接话中' : room?.status === 'failed' ? '未完成' : '待命';
    $('ws-cog-stage').textContent = actor ? agentName(actor) + (hasVisibleReply() ? ' · 正在回复' : ' · 准备回答') : room?.status === 'queued' ? '等待本地模型' : '待命 · 等你开聊';
    $('ws-cognition').classList.toggle('is-active', Boolean(actor));
    const fragment = document.createDocumentFragment();
    if (actor) fragment.append(make('p', 'ws-link-path', agentName(actor) + (hasVisibleReply() ? ' · 正在回复' : ' · 准备回答')));
    for (const turn of turns.slice(-3)) fragment.append(make('p', '', agentName(turn.space) + ' · ' + (labels[turn.status] || turn.status)));
    if (!actor && !turns.length) fragment.append(make('p', 'ws-empty', '在消息里 @ 成员，联动会跟着真实调用走。'));
    $('ws-linkage').replaceChildren(fragment);
    renderDirectory();
  }
  function renderTools() {
    const room = state.room, latestUser = [...(room?.messages || [])].reverse().find(message => message.role === 'user');
    const job = state.jobs.find(item => item.id === room?.active_job_id);
    $('ws-process').textContent = room?.status === 'queued' ? '消息已收到，等待本地模型。' : active(room?.status) ? (job?.activity ? stageName(job) : hasVisibleReply() ? agentName(currentActor() || 'central') + ' 正在生成答复。' : stageName(job) + '。') : room?.status === 'failed' ? '这轮未完整完成，失败信息保留在对话中。' : latestUser ? '本轮答复已完成。' : '等你开聊，一次弄懂一个点。';
    const answers = (room?.messages || []).filter(message => message.role === 'assistant');
    const latestAnswer = answers.at(-1);
    const messages = latestAnswer?.response_origin === 'host_product_analysis_supplement' ? [latestAnswer] : answers.filter(message => message.round_id === latestUser?.round_id);
    const fragment = document.createDocumentFragment();
    let total = 0;
    const toolRoute = [...messages].reverse().find(message => message.tool_model_route)?.tool_model_route;
    if (toolRoute) {
      const li = make('li');
      li.append(make('span','ws-read-label','工具任务 · ' + toolRoute.model),
        make('span','','本轮由此模型调用工具并继续回答。'));
      fragment.append(li); total++;
    } else if (state.reportModel?.required || state.reportModel?.configured) {
      const li = make('li');
      li.append(make('span','ws-read-label',state.reportModel.configured ? '深度报告配置 · ' + state.reportModel.model : '深度报告 · 等待强模型配置'),
        make('span','',state.reportModel.error || '已配置独立报告模型。'));
      fragment.append(li); total++;
    }
    for (const message of messages) {
      if(message.workflow) {
        for(const receipt of message.workflow.receipts || []) {
          const resultLabel={completed:'已返回实际结果',partial:'部分返回结果',no_results:'已查询，未找到结果',no_related_results:'已搜索，未找到相关结果',unavailable:receipt.tool==='web_read'?'本次未取得正文':'本次未取得结果',blocked:'读取受阻'}[receipt.status] || '本次未完成';
          const li=make('li');li.append(make('span','ws-read-label',({wiki_search:'知识补查',web_read:'网页读取',visual_browser:'浏览网页与截图',web_search:'公开搜索',profit_calculate:'盈利计算',result_review:'任务结果检查',code_interpreter:'Python 代码执行',file_search:'附件检索',file_read:'文档读取',audio_transcribe:'音频转写',video_analyze:'视频分析',image_analyze:'图片识别',image_generate:'图片生成',connector_search:'连接搜索',connector_read:'连接读取'})[receipt.tool] || '工具'),make('span','',resultLabel));fragment.append(li);total++;
        }
        if(message.workflow.gaps?.length){const li=make('li');li.append(make('span','ws-read-label','尚待验证'),make('span','',message.workflow.gaps.join('；')));fragment.append(li);total++;}
      }
      if (message.analysis_run) {
        const li = make('li');
        const native=message.native_stream || message.analysis_run.native_stream;
        const process=native?`原生 Agent · 工具 ${(native.tool_calls || []).length} 次`:
          (message.analysis_run.review_mode === 'prior_report' ? '模型自行校对' : (message.analysis_run.coverage || []).length + ' 部分') + ' · 引文存在核对 ' + (message.analysis_run.source_facts || []).length + ' 条';
        li.append(make('span','ws-read-label',agentName(message.agent_id) + ' · 自主分析草稿'),make('span','',String(message.model || '本地模型') + ' · ' + process),make('span','',message.analysis_run.quality?.calculation_checked?'演示计算已核对；真实成本和市场仍需验证。':'功能实测、市场判断和真实盈利仍需核实。'));
        fragment.append(li); total++;
      }
      for (const source of (message.research?.sources || []).slice(0, 4)) {
        const li = make('li');
        li.append(make('span', 'ws-read-label', '网页 · ' + String(source.title || source.url || '公开资料')), make('span', '', ['browser_dom','visual_browser_dom'].includes(source.read_method) ? '已读取动态页面正文' : source.read_method === 'browser_inspected' ? '已核对公开页面' : '已读取正文摘录'));
        fragment.append(li); total++;
      }
      if (message.hotspot_reads) {
        const selected = message.hotspot_reads.selected, li = make('li');
        li.append(make('span', 'ws-read-label', selected ? '热点 · ' + selected.title : '当前热点榜单'), make('span', '', selected ? selected.status === 'ready' ? '已读取正文摘录' : '仅标题与订阅摘要' : '已读取来源及采集状态'));
        fragment.append(li); total++;
      }
      for (const [field, type] of [['wiki_reads', '经验'], ['template_reads', '模板'], ['skill_reads', '技能']]) {
        for (const read of (message[field] || []).slice(0, 3)) {
          const li = make('li'), title = String(read.path || read.id || '读取记录').split('/').filter(Boolean).slice(-2).join('/');
          li.append(make('span', 'ws-read-label', type + ' · ' + title), make('span', '', agentName(message.agent_id) + ' · 已读取' + (read.truncated ? '（节选）' : ''))); fragment.append(li); total++;
        }
      }
    }
    if (!total) fragment.append(make('li', 'ws-empty', active(room?.status) ? '读取凭证会在答复完成后显示。' : '还没有本轮的查阅或工具记录。'));
    $('ws-tools').replaceChildren(fragment);
  }
  function renderJobs() {
    const fragment = document.createDocumentFragment();
    for (const job of state.jobs.slice(0, 10)) {
      const li = make('li', 'ws-log'), top = make('div', 'ws-log-top');
      const speaker = job.requested_agents?.length ? job.requested_agents.map(agentName).join('、') : agentName(job.space);
      top.append(make('span', 'ws-dot' + (active(job.status) ? ' active' : job.status === 'failed' ? ' offline' : '')), make('span', 'ws-log-title', speaker + ' · ' + (labels[job.status] || job.status)), make('time', 'ws-log-time', clock(job.finished_at || job.started_at || job.created_at).slice(0, 5)));
      li.append(top, make('div', 'ws-log-detail', job.error || stageName(job))); fragment.append(li);
    }
    if (!state.jobs.length) fragment.append(make('li', 'ws-empty', '还没有执行记录，直接开聊。'));
    $('ws-actions').replaceChildren(fragment);
  }
  function compact(value) { const number = Number(value); return Number.isFinite(number) ? number >= 10000 ? (number / 10000).toFixed(1) + '万' : number.toLocaleString('zh-CN') : String(value || ''); }
  function publicUrl(value) {
    try { const url = new URL(value); return ['https:', 'http:'].includes(url.protocol) && !url.username && !url.password ? url.href : null; }
    catch { return null; }
  }
  function newsTime(item) {
    const source = (state.hotspotSources || []).find(source => source.id === item.source_id);
    const value = item.published_at || source?.fetched_at;
    if (!value) return '时间未提供';
    const date = new Date(value);
    if (!Number.isFinite(date.valueOf())) return '时间未提供';
    const minutes = Math.floor((Date.now() - date.valueOf()) / 60000);
    const label = minutes >= 0 && minutes < 1 ? '刚刚' : minutes > 0 && minutes < 60 ? minutes + ' 分钟前' : minutes >= 60 && minutes < 1440 ? Math.floor(minutes / 60) + ' 小时前' : date.toLocaleDateString('zh-CN', {month:'numeric', day:'numeric'});
    return (item.published_at ? '' : '采集于 ') + label + (source?.status === 'stale' ? ' · 缓存' : '');
  }
  function renderNewsList() {
    const list = $('ws-news-list'); if (!list) return;
    const sourceById = new Map((state.hotspotSources || []).map(source => [source.id, source]));
    const query = (state.query || '').trim().toLocaleLowerCase();
    const business = /商业|企业|融资|市场|营收|投资|零售|电商|金融|成本|产品|business|enterprise|funding|market|revenue|investment|commerce|customer|cost|product/i;
    const items = (state.hotspotItems || []).filter(item => {
      if (!publicUrl(item.url)) return false;
      const source = sourceById.get(item.source_id), group = item.group || source?.group;
      const text = [item.title, item.summary, item.source, source?.name].filter(Boolean).join(' ');
      return (!query || text.toLocaleLowerCase().includes(query)) &&
        (!state.category || state.category === 'all' || (state.category === 'business' ? business.test(text) : group === state.category));
    }).map((item, index) => ({item, index}));
    const timestamp = item => {
      const value = Date.parse(item.published_at || sourceById.get(item.source_id)?.fetched_at || '');
      return Number.isFinite(value) ? value : 0;
    };
    items.sort((a, b) => state.sort === 'rank' ? (a.item.rank || 999) - (b.item.rank || 999) || a.index - b.index : timestamp(b.item) - timestamp(a.item) || a.index - b.index);
    const position = list.scrollTop, fragment = document.createDocumentFragment();
    for (const {item} of items) {
      const selected = item.id === state.selectedHotspot?.id;
      const button = make('button', 'ws-news-item' + (selected ? ' is-selected' : ''));
      button.type = 'button'; button.dataset.hotspotId = item.id; button.setAttribute('aria-pressed', String(selected));
      const source = item.source || sourceById.get(item.source_id)?.name || '公开来源';
      button.append(make('strong', '', item.title), make('small', '', source + ' · ' + newsTime(item)));
      button.title = item.title; button.onclick = () => { openHotspot({...item, source}); document.body.classList.remove('ws-news-drawer'); $('ws-mobile-news').setAttribute('aria-expanded', 'false'); };
      fragment.append(button);
    }
    if (!items.length) fragment.append(make('p', 'ws-empty', !state.hotKey ? '正在读取热点来源…' : query ? '没有找到相关资讯，试试其他关键词。' : state.category === 'business' ? '当前来源中暂无商业相关资讯。' : '这个分类暂时没有可用资讯。'));
    list.replaceChildren(fragment); list.scrollTop = position;
    $('ws-news-count').textContent = '实时热点' + (items.length ? ' · ' + items.length : '');
    document.querySelectorAll('[data-category]').forEach(button => button.setAttribute('aria-pressed', String(button.dataset.category === (state.category || 'all'))));
  }
  function renderHotspots(data) {
    $('ws-hot-time').textContent = data.checked_at ? '采集 ' + clock(data.checked_at) + ' · 每 5 分钟更新' : '正在接入公开来源 · 每 5 分钟更新';
    const key = JSON.stringify(data); if (key === state.hotKey) return; state.hotKey = key;
    const columnPositions = [$('ws-hot-ai').scrollTop, $('ws-hot-general').scrollTop];
    state.hotspotSources = data.sources || [];
    state.hotspotItems = data.items || state.hotspotSources.flatMap(source => source.items || []);
    renderNewsList();
    const sources = data.sources || [], ready = sources.filter(source => source.status === 'ready').length;
    const stale = sources.filter(source => source.status === 'stale').length;
    $('ws-hot-checked').textContent = data.checked_at ? '采集 ' + clock(data.checked_at).slice(0, 5) : '等待采集';
    $('ws-hot-available').textContent = ready + '/' + sources.length;
    $('ws-hot-source-state').textContent = ready === sources.length && ready > 0 ? '来源正常' : stale ? stale + ' 路为缓存' : '部分未就绪';
    $('ws-hot-status-dot').classList.toggle('offline', ready !== sources.length);
    for (const group of ['ai', 'general']) $('ws-hot-' + group + '-count').textContent = sources.filter(source => group === 'ai' ? ['ai', 'tech'].includes(source.group) : source.group === group).reduce((total, source) => total + (source.items || []).filter(item => publicUrl(item.url)).length, 0);
    const selectedSource = $('ws-hot-source').value, options = [make('option', '', '全部来源')]; options[0].value = 'all';
    for (const source of sources) {
      const option = make('option', '', source.name + (source.kind === 'pending' ? '（待接入）' : ''));
      option.value = source.id; options.push(option);
    }
    $('ws-hot-source').replaceChildren(...options);
    $('ws-hot-source').value = sources.some(source => source.id === selectedSource) ? selectedSource : 'all';
    const ai = document.createDocumentFragment(), general = document.createDocumentFragment(), stories = document.createDocumentFragment();
    for (const source of sources) {
      const section = make('section', 'ws-feed'), head = make('header', 'ws-feed-head'), title = make('h3'), link = make('span', '', source.name);
      section.dataset.sourceId = source.id;
      title.append(link, make('span', 'ws-feed-kind', source.group === 'ai' ? 'AI 动态' : source.group === 'tech' ? '开源' : '综合'));
      head.append(title, make('span', '', source.status === 'ready' ? clock(source.fetched_at).slice(0, 5) : source.status === 'stale' ? '上次缓存' : source.status === 'unavailable' ? '暂不可用' : '采集中')); section.append(head);
      if (source.description) section.append(make('p', 'ws-feed-description', source.description));
      if (source.data_route?.label) {
        const route = make('p', 'ws-feed-description', source.data_route.label + (source.data_route.board ? ' · ' + source.data_route.board : ''));
        route.title = source.mcp?.error || (source.mcp?.status === 'connected' ? source.mcp.repository : '');
        section.append(route);
      }
      if (source.error) section.append(make('p', 'ws-feed-error', (source.status === 'stale' ? '更新失败，保留 ' + clock(source.fetched_at) + ' 的缓存。' : '来源读取失败。') + ' ' + source.error));
      const list = make('ol');
      for (const item of source.items || []) {
        const li = make('li', 'ws-hot-item'), anchor = make('button', '', item.title);
        const url = publicUrl(item.url); if (!url) continue;
        anchor.type = 'button'; anchor.dataset.hotspotId = item.id; anchor.onclick = () => openHotspot(item);
        anchor.title = item.title + (item.published_at ? ' · 发布 ' + new Date(item.published_at).toLocaleString('zh-CN') : '');
        li.append(make('span', 'ws-rank', item.rank), anchor);
        if (source.group === 'ai' && item.published_at) li.append(make('time', '', new Date(item.published_at).toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' })));
        else if (item.score !== null && item.score !== undefined) { const score = make('span', 'ws-score', compact(item.score) + (source.id === 'github' ? ' ★' : '')); score.title = item.score_label || (source.id === 'bilibili' ? '播放量' : '平台热度'); li.append(score); }
        list.append(li);
      }
      if (!source.items?.length) list.append(make('li', 'ws-empty', source.status === 'loading' ? '正在读取公开数据…' : '暂时没有可展示的数据。'));
      section.append(list); (['ai', 'tech'].includes(source.group) ? ai : general).append(section);
      for (const item of (source.items || []).filter(item => publicUrl(item.url)).slice(0, 2)) {
        const story = make('button', 'ws-story'); story.type = 'button'; story.dataset.hotspotId = item.id; story.onclick = () => openHotspot(item); story.title = item.title;
        const meta = make('span', '', source.name); meta.append(make('time', '', source.status === 'stale' ? '缓存' : clock(source.fetched_at).slice(0, 5)));
        story.append(meta, make('strong', '', item.title), make('small', '', '在这里阅读 · 右边继续聊')); stories.append(story);
      }
    }
    $('ws-hot-ai').replaceChildren(ai); $('ws-hot-general').replaceChildren(general);
    $('ws-hot-ai').scrollTop = columnPositions[0]; $('ws-hot-general').scrollTop = columnPositions[1];
    $('ws-hot-stories').replaceChildren(stories);
    if (!$('ws-hot-stories').childNodes.length) $('ws-hot-stories').append(make('p', 'ws-empty', '来源暂未就绪，接入后会显示焦点。'));
  }
  function jumpHotspotSource() {
    const identifier = $('ws-hot-source').value;
    const container = $('ws-sources-dialog').querySelector('.ws-sources-body');
    if (identifier === 'all') { container.scrollTop = 0; return; }
    const section = [...$('ws-hot-feeds').querySelectorAll('.ws-feed')].find(node => node.dataset.sourceId === identifier);
    if (!section) return;
    container.scrollTo({top: container.scrollTop + section.getBoundingClientRect().top - container.getBoundingClientRect().top,
      behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth'});
  }
  function updateHotspotChatContext() {
    const item = state.selectedHotspot, article = state.readerArticle;
    const node = $('ws-hot-chat-context'); node.hidden = !state.hotOpen || !item;
    node.replaceChildren();
    if (item) {
      const copy = make('div', 'ws-context-copy');
      copy.append(make('small', '', '正在阅读'), make('strong', '', item.title), make('span', '', item.source + ' · ' + (article?.status === 'ready' ? '正文已读取' : article?.status ? '标题与来源摘要' : '正在读取正文')));
      const read = make('button', 'ws-context-read', '阅读正文'); read.type = 'button';
      read.onclick = () => { $('ws-hot-reader').hidden = false; $('ws-reader-title').focus({preventScroll:true}); };
      node.append(copy, read);
    }
    $('ws-topic-crumb').textContent = state.hotOpen ? item?.source || '与未明一起读' : '与未明对话';
    $('ws-page-title').textContent = state.hotOpen ? '热点研读' : '和未明聊聊';
    $('ws-page-description').textContent = state.hotOpen ? '围绕当前热点的分析与学习笔记' : '带着问题、资料或想法，继续这段对话。';
    $('ws-summary-focus').textContent = item ? (article?.summary || item.summary || '该来源未提供摘要。可以阅读原文，再讨论这条资讯。') : '选择左侧的一条资讯，查看来源摘要与正文。';
    $('ws-summary-relevance').textContent = item ? '正在关注「' + item.source + '」。你可以追问它与你的项目、产品或工作有什么关系。' : '带着你的项目或问题提问，让讨论落到具体任务。';
    $('ws-summary-evidence').textContent = item ? article?.status === 'ready' ? '已提取来源正文' + (article.truncated ? '（节选）' : '') + '；来源中的判断仍需结合证据核对。' : article?.error ? '正文未取得：' + article.error + ' 当前仅有标题与来源摘要。' : '正在读取正文。读取完成前，仅依据标题和来源摘要。' : '来源摘要与 Agent 分析分开呈现，结论可继续追问核对。';
    const cite = $('ws-cite-hotspot'); if (cite) cite.hidden = !item || !state.hotOpen;
    if (typeof renderNewsList === 'function') renderNewsList();
    if (typeof syncConversationShell === 'function') syncConversationShell();
  }
  function closeReader() {
    state.readerEpoch++; state.selectedHotspot = null; state.readerArticle = null;
    $('ws-reader-frame-host').replaceChildren();
    $('ws-hot-reader').hidden = true; $('ws-hotspots').classList.remove('is-reading');
    globe?.setVisible(state.hotOpen); updateHotspotChatContext();
  }
  function readerFrameUrl(item) {
    const hosts = { openai: ['openai.com', 'www.openai.com'], 'google-ai': ['blog.google'],
      baidu: ['www.baidu.com', 'top.baidu.com'], bilibili: ['www.bilibili.com'],
      douyin: ['www.douyin.com'], xiaohongshu: ['www.xiaohongshu.com'] };
    // GitHub currently returns X-Frame-Options: deny and frame-ancestors 'none'.
    try {
      const url = new URL(item?.url);
      return url.protocol === 'https:' && !url.username && !url.password && !url.port && hosts[item.source_id]?.includes(url.hostname) ? url.href : null;
    } catch { return null; }
  }
  function updateOriginalNote() {
    const article = state.readerArticle;
    $('ws-reader-web-note').textContent = '原网页由 ' + state.selectedHotspot.source + ' 提供。若未显示或需要登录，可在新标签打开。' +
      (article?.status === 'ready' ? 'Agent 已读取正文，原网页中的后续变化不会自动同步。' : 'Agent 当前只有榜单标题' + (article?.summary ? '和摘要' : '') + '，原网页的内容不会自动提供给 Agent。');
  }
  function setReaderView(original) {
    const url = original && readerFrameUrl(state.selectedHotspot);
    if (original && !url) return;
    $('ws-reader-text-view').hidden = Boolean(original); $('ws-reader-web').hidden = !original;
    $('ws-reader-text').setAttribute('aria-pressed', String(!original));
    $('ws-reader-original').setAttribute('aria-pressed', String(Boolean(original)));
    if (!original) { $('ws-reader-frame-host').replaceChildren(); return; }
    updateOriginalNote();
    const frame = make('iframe', 'ws-reader-frame'); frame.title = state.selectedHotspot.title + ' · 原网页';
    frame.setAttribute('sandbox', 'allow-scripts allow-same-origin allow-forms');
    frame.setAttribute('allow', 'fullscreen; picture-in-picture'); frame.referrerPolicy = 'no-referrer';
    frame.src = url; $('ws-reader-frame-host').replaceChildren(frame);
  }
  $('ws-reader-text').addEventListener('click', () => setReaderView(false));
  $('ws-reader-original').addEventListener('click', () => setReaderView(true));
  $('ws-reader-fallback-frame').addEventListener('click', () => setReaderView(true));
  async function openHotspot(item) {
    const epoch = ++state.readerEpoch;
    state.selectedHotspot = item; state.readerArticle = null;
    setReaderView(false);
    const url = publicUrl(item.url), frameUrl = readerFrameUrl(item);
    for (const link of [$('ws-reader-open'), $('ws-reader-url'), $('ws-reader-fallback-open')]) { if (url) link.href = url; else link.removeAttribute('href'); }
    $('ws-reader-open').hidden = !url;
    $('ws-reader-fallback').hidden = true;
    $('ws-reader-fallback-open').hidden = !url;
    $('ws-reader-fallback-open').textContent = '打开' + item.source.replace(/热榜|热搜$/, '') + '原网页 ↗';
    $('ws-reader-fallback-frame').hidden = !frameUrl;
    $('ws-reader-original').disabled = !frameUrl;
    $('ws-reader-original').title = frameUrl ? '在这里查看原站网页' : item.source_id === 'github' ? 'GitHub 禁止跨站嵌入，请使用新标签打开' : '此来源暂不支持页内嵌入，请使用新标签打开';
    $('ws-hot-reader').hidden = true; globe?.setVisible(false);
    $('ws-reader-title').textContent = item.title;
    $('ws-reader-source').textContent = item.source;
    $('ws-reader-meta').textContent = [item.source, item.published_at ? '发布 ' + new Date(item.published_at).toLocaleString('zh-CN') : '榜单第 ' + item.rank + ' 条'].join(' · ');
    $('ws-reader-status').textContent = '正在读取网页正文…'; $('ws-reader-body').replaceChildren(); $('ws-reader-url').textContent = item.url;
    updateHotspotChatContext();
    try {
      const response = await fetch('/api/hotspots/items/' + encodeURIComponent(item.id), {signal:AbortSignal.timeout(27000)});
      const article = await response.json();
      if (epoch !== state.readerEpoch) return;
      if (!response.ok) throw new Error(article.detail || '读取失败。');
      state.readerArticle = article;
      $('ws-reader-fallback').hidden = article.status === 'ready';
      $('ws-reader-status').textContent = article.status === 'ready' ? '正文已读取，回到对话即可继续追问。' + (article.truncated ? ' 本页正文过长，展示了节选。' : '') : '正文暂时读不到：' + (article.error || '来源未提供可读正文。') + ' 当前仅有标题' + (article.summary ? '和订阅摘要。' : '。');
      const text = article.status === 'ready' ? article.text : article.summary || '';
      if (text) {
        const body = window.openWikiChat.renderBody(text, 'ws-reader-markdown');
        const heading = body.querySelector('h1');
        if (heading?.textContent.trim() === item.title.trim()) heading.remove();
        body.querySelectorAll('a').forEach(link => link.replaceWith(document.createTextNode(link.textContent)));
        $('ws-reader-body').replaceChildren(body);
      }
      updateHotspotChatContext();
      if (!$('ws-reader-web').hidden) updateOriginalNote();
    } catch (error) {
      if (epoch === state.readerEpoch) {
        $('ws-reader-status').textContent = '正文读取失败：' + error.message + ' 你仍可以结合标题继续讨论。';
        $('ws-reader-fallback').hidden = false;
        state.readerArticle = {status:'unavailable', error:error.message}; updateHotspotChatContext();
      }
    }
  }
  $('ws-reader-back').addEventListener('click', () => {
    $('ws-hot-reader').hidden = true; $('ws-reader-frame-host').replaceChildren(); setReaderView(false);
    $('ws-hot-chat-context').querySelector('button')?.focus({preventScroll:true});
  });
  window.openWikiHotspots = { context: () => state.hotOpen && state.selectedHotspot ? { hotspot_view: true, hotspot_id: state.selectedHotspot?.id || '' } : {} };
  $('ws-chat-host').addEventListener('click', event => {
    const link = event.target.closest('a[href]');
    if (!link) return;
    const item = [...state.hotspotItems, state.selectedHotspot].filter(Boolean).find(item => publicUrl(item.url) === publicUrl(link.href));
    if (item) { event.preventDefault(); setHotView(true); openHotspot(item); }
  });
  function setHotView(open) {
    state.hotOpen = open;
    document.body.classList.toggle('ws-hot-open', open);
    document.body.classList.remove('ws-news-drawer');
    $('ws-hotspots').hidden = !open;
    $('ws-hot-toggle').setAttribute('aria-expanded', String(open));
    $('ws-hot-toggle').classList.toggle('is-active', open);
    $('ws-nav-chat').classList.toggle('is-active', !open);
    $('ws-mobile-news').setAttribute('aria-expanded', 'false');
    if (!open) { $('ws-hot-reader').hidden = true; $('ws-reader-frame-host').replaceChildren(); setReaderView(false); }
    updateHotspotChatContext();
  }
  function showNews() {
    document.body.classList.remove('ws-summary-drawer');
    setHotView(true);
    if (window.matchMedia('(max-width: 800px)').matches) { document.body.classList.add('ws-news-drawer'); $('ws-mobile-news').setAttribute('aria-expanded', 'true'); }
  }
  $('ws-hot-toggle').addEventListener('click', showNews);
  $('ws-nav-chat').addEventListener('click', () => { setHotView(false); $('ag-message')?.focus(); });
  $('ws-mobile-news').addEventListener('click', showNews);
  $('ws-search-open').addEventListener('click', () => { showNews(); $('ws-news-search').focus(); });
  $('ws-hot-source').addEventListener('change', jumpHotspotSource);
  $('ws-hot-close').addEventListener('click', () => { document.body.classList.remove('ws-news-drawer'); $('ws-mobile-news').setAttribute('aria-expanded', 'false'); $('ws-hot-toggle').focus(); });
  $('ws-news-search').addEventListener('input', event => { state.query = event.target.value; renderNewsList(); });
  $('ws-news-sort').addEventListener('change', event => { state.sort = event.target.value; renderNewsList(); });
  for (const button of document.querySelectorAll('[data-category], [data-topic]')) button.addEventListener('click', () => {
    state.category = button.dataset.category || button.dataset.topic; showNews(); $('ws-news-list').scrollTop = 0; renderNewsList();
  });
  for (const [buttonId, dialogId] of [['ws-nav-tasks','ws-task-dialog'], ['ws-nav-settings','ws-settings-dialog'], ['ws-sources-open','ws-sources-dialog'], ['ws-aside-sources','ws-sources-dialog']]) $(buttonId).addEventListener('click', () => {
    $(dialogId).showModal(); if (dialogId === 'ws-task-dialog') heartbeat.setVisible(true);
  });
  for (const button of document.querySelectorAll('[data-close-dialog]')) button.addEventListener('click', () => $(button.dataset.closeDialog).close());
  $('ws-task-dialog').addEventListener('close', () => heartbeat.setVisible(false));
  function chatMenu(open) { $('ws-chat-menu').hidden = !open; $('ws-chat-menu-open').setAttribute('aria-expanded', String(open)); }
  $('ws-menu-summary').addEventListener('click', () => { chatMenu(false); document.body.classList.add('ws-summary-drawer'); $('ws-summary-close').focus(); });
  $('ws-summary-close').addEventListener('click', () => { document.body.classList.remove('ws-summary-drawer'); $('ws-chat-menu-open').focus(); });
  $('ws-chat-menu-open').addEventListener('click', () => chatMenu($('ws-chat-menu').hidden));
  document.addEventListener('click', event => { if (!event.target.closest('.ws-page-bar')) chatMenu(false); });
  for (const [buttonId, targetId] of [['ws-menu-primary','ag-return-primary'], ['ws-menu-history','ag-history-open'], ['ws-menu-memory','ag-memory-open'], ['ws-nav-profile','ag-memory-open'], ['ws-menu-skills','ag-skills-open'], ['ws-menu-templates','ag-templates-open']]) $(buttonId).addEventListener('click', () => { chatMenu(false); $(targetId)?.click(); });
  $('ws-settings-tools').addEventListener('click', () => { $('ws-settings-dialog').close(); document.querySelector('.ag-tool-settings')?.click(); });
  window.addEventListener('keydown', event => {
    if (event.key !== 'Escape' || document.querySelector('dialog:modal')) return;
    if (document.body.classList.contains('ws-summary-drawer')) { $('ws-summary-close').click(); return; }
    if (!$('ws-chat-menu').hidden) { chatMenu(false); $('ws-chat-menu-open').focus(); return; }
    if (document.body.classList.contains('ws-news-drawer')) { $('ws-hot-close').click(); return; }
    if (!$('ws-hot-reader').hidden) { event.preventDefault(); $('ws-reader-back').click(); }
  });
  let pollTimer = 0, polling = false, pollAgain = false;
  async function poll() {
    if (state.stopped) return;
    clearTimeout(pollTimer);
    if (document.hidden) { pollTimer = setTimeout(poll, 15000); return; }
    if (polling) { pollAgain = true; return; }
    polling = true;
    try {
      const data = await get('/api/workspace'); state.agents = data.agents || []; state.jobs = data.jobs || []; state.reportModel = data.report_model || null;
      $('ws-service').textContent = '服务在线'; $('ws-service-dot').classList.remove('offline');
      $('ws-heart-agent-count').textContent = state.agents.length;
      $('ws-heart-job-count').textContent = data.running + data.queued;
      $('ws-heart-knowledge').textContent = state.agents.find(member => member.id === 'central')?.knowledge_count || 0;
      $('ws-running').textContent = '执行 ' + data.running; $('ws-queued').textContent = '等待 ' + data.queued;
      heartbeat.receipt(data);
      renderDirectory(); renderJobs(); renderLinkage(); renderTools();
    } catch { $('ws-service').textContent = '连接中断'; $('ws-service-dot').classList.add('offline'); heartbeat.offline(); }
    polling = false;
    if (!state.stopped) pollTimer = setTimeout(poll, pollAgain ? 0 : active(state.room?.status) && $('ws-task-dialog').open ? 3000 : 15000);
    pollAgain = false;
  }
  let hotTimer = 0, hotPolling = false;
  async function pollHotspots() {
    if (state.stopped || hotPolling) return;
    if (document.hidden) { clearTimeout(hotTimer); hotTimer = setTimeout(pollHotspots, 15000); return; }
    clearTimeout(hotTimer); hotPolling = true;
    let loading = false;
    try { const data = await get('/api/hotspots'); renderHotspots(data); loading = data.sources?.some(source => source.status === 'loading'); }
    catch { $('ws-hot-time').textContent = '本地服务未连接，暂时无法更新热点。'; $('ws-news-foot-status')?.remove(); if (!state.hotspotItems.length) $('ws-news-list').replaceChildren(make('p', 'ws-empty', '热点暂时无法连接，请稍后刷新。')); }
    hotPolling = false;
    if (!state.stopped) hotTimer = setTimeout(pollHotspots, loading ? 1500 : 15000);
  }
  $('ws-hot-refresh').addEventListener('click', async () => { $('ws-hot-refresh').disabled = true; try { await pollHotspots(); } finally { $('ws-hot-refresh').disabled = false; } });
  function syncConversationShell() {
    const primary = !state.room || state.room.purpose === 'primary';
    $('ws-menu-primary').hidden = primary && !$('ag-notice')?.classList.contains('ag-error');
    document.body.dataset.primaryChat = String(primary);
    if (!primary) {
      $('ws-page-title').textContent = state.room.title || '历史对话';
      $('ws-topic-crumb').textContent = '历史对话';
      $('ws-page-description').textContent = '正在查看历史会话，可从右上角菜单返回主 Agent。';
    } else {
      $('ws-page-title').textContent = state.hotOpen ? '热点研读' : '和未明聊聊';
      $('ws-topic-crumb').textContent = state.hotOpen ? state.selectedHotspot?.source || '与未明一起读' : '与未明对话';
      $('ws-page-description').textContent = state.hotOpen ? '围绕当前热点的分析与学习笔记' : '带着问题、资料或想法，继续这段对话。';
    }
    $('ws-hot-chat-context').hidden = !primary || !state.hotOpen || !state.selectedHotspot;
    if ($('ws-cite-hotspot')) $('ws-cite-hotspot').hidden = !primary || !state.hotOpen || !state.selectedHotspot;
    if (primary && state.hotOpen && state.selectedHotspot) $('ag-message').placeholder = '继续追问这条热点，或输入你想了解的问题…';
  }
  window.addEventListener('openwiki:chat-state', event => {
    const changed = state.room?.active_job_id !== event.detail?.active_job_id || active(state.room?.status) !== active(event.detail?.status);
    state.room = event.detail; syncConversationShell(); heartbeat.room(event.detail); renderLinkage(); renderTools();
    if (changed) poll();
  });
  window.addEventListener('openwiki:chat-stream', event => { if (state.room) state.room.live_reply = event.detail; heartbeat.reply(event.detail); renderLinkage(); $('ws-process').textContent = agentName(event.detail.agent_id || 'central') + ' 正在生成答复。'; });
  window.addEventListener('pagehide', event => { state.stopped = true; clearTimeout(pollTimer); clearTimeout(hotTimer); globe?.setVisible(false); cognition?.setVisible(false); heartbeat.setVisible(false); if (!event.persisted) { globe?.destroy(); cognition?.destroy(); heartbeat.destroy(); } });
  window.addEventListener('pageshow', event => { if (event.persisted) { state.stopped = false; globe?.setVisible(state.hotOpen); cognition?.setVisible(!state.hotOpen); heartbeat.setVisible($('ws-task-dialog').open); poll(); pollHotspots(); } });
  const dialog = $('ag-dialog');
  if (dialog && window.openWikiChat) { $('ws-chat-host').append(dialog); dialog.setAttribute('open', ''); dialog.addEventListener('cancel', event => event.preventDefault()); window.openWikiChat.open(); }
  else $('ws-chat-host').append(make('p', 'ws-empty', '聊天组件未加载，请刷新页面。'));
  // Decorative canvases no longer run on the reading page. Runtime evidence remains in Tasks.
  const globe = null, cognition = null, heartbeat = createHeartbeat();
  heartbeat.setVisible(false);
  const compose = $('ag-message-form'), footer = compose?.querySelector('.ag-compose-footer');
  if (footer) {
    const cite = make('button', 'ws-cite-button', '引用当前热点'); cite.id = 'ws-cite-hotspot'; cite.type = 'button'; cite.hidden = true; cite.title = '发送时自动携带当前热点标题、来源和已读取正文';
    cite.onclick = () => { $('ag-message')?.focus(); };
    const clip = document.createElementNS('http://www.w3.org/2000/svg','svg'); clip.setAttribute('viewBox','0 0 24 24'); clip.setAttribute('fill','none'); clip.setAttribute('stroke','currentColor'); clip.setAttribute('stroke-width','1.6'); clip.setAttribute('aria-hidden','true');
    const path = document.createElementNS(clip.namespaceURI,'path'); path.setAttribute('d','m8 13 7-7a3 3 0 0 1 4 4L9 20a5 5 0 0 1-7-7L13 2M6 15l9-9'); clip.append(path); cite.prepend(clip);
    footer.prepend(cite);
    const send = $('ag-send');
    function syncSendLabel() {
      const label = send.textContent.trim(), special = label !== '发送';
      send.classList.toggle('ws-send-action',special); send.setAttribute('aria-label',special ? label : '发送消息'); send.title = special ? label : '发送消息';
      $('ag-compose-hint').classList.toggle('ws-important-hint',special);
    }
    new MutationObserver(syncSendLabel).observe(send,{childList:true,characterData:true,subtree:true}); syncSendLabel();
    $('ag-message').placeholder = '继续追问这条热点，或输入你想了解的问题…';
  }
  updateHotspotChatContext();
  function updateClock() { $('ws-clock').textContent = new Date().toLocaleDateString('zh-CN', { month: '2-digit', day: '2-digit' }) + '  ' + clock(new Date()); }
  updateClock(); setInterval(updateClock, 1000); poll(); pollHotspots();
})();
