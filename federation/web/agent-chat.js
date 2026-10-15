/* Agent conversations extend the original OpenWiki viewer without replacing it. */
(() => {
  "use strict";
  const state = {
    agents: [], rooms: [], room: null, view: "room", roomId: null, primaryRoomId: null,
    drafts: new Map(), sending: new Set(), submissions: new Map(), unconfirmed: new Map(),
    sendModes: new Map(), videoRequests: new Map(),
    epoch: 0, listRevision: 0, polling: false, timer: null, failures: 0,
    feedSignature: "", taskExpanded: new Map(), feedPositions: new Map(), preferredRoomId: null, graphSpace: "central", loaded: false,
    learningStatus: null, learningStatusError: false, templateSpace: null, templateEpoch: 0,
    skillSpace: null, skillEpoch: 0, skillData: null,
    replyStream: null, replyStreamKey: null, streamConnected: false,
    streamReconnect: null,
    memoryEpoch: 0, memoryView: 'tasks', memoryData: null, memoryBusy: false,
    contextMeterRoom: null, contextMeterSignature: '',
  };
  const storageKey = "openwiki-agent-chat-view-v2";
  const viewStorage = import('/browser-state.js')
    .then(module => module.openServerState('chat', 'sessionStorage', storageKey))
    .then(storage => {
    const saved = storage.value;
    if (saved && typeof saved === "object") {
      state.drafts = new Map(Array.isArray(saved.drafts) ? saved.drafts : []);
      state.sendModes = new Map(saved.videoModeVersion === 2 && Array.isArray(saved.sendModes) ? saved.sendModes : []);
      state.videoRequests = new Map(Array.isArray(saved.videoRequests) ? saved.videoRequests : []);
      state.unconfirmed = new Map(Array.isArray(saved.unconfirmed) ? saved.unconfirmed : []);
      // Reloading cannot prove whether an in-flight POST reached the server.
      for (const [id, submission] of Array.isArray(saved.submissions) ? saved.submissions : []) {
        state.unconfirmed.set(id, [...(state.unconfirmed.get(id) || []), submission]);
      }
      state.taskExpanded = new Map(Array.isArray(saved.expanded) ? saved.expanded : []);
      state.feedPositions = new Map(Array.isArray(saved.positions) ? saved.positions : []);
      state.preferredRoomId = typeof saved.roomId === "string" ? saved.roomId : null;
    }
    return storage;
  });
  viewStorage.catch(error => notice(error.message, true));
  function persistView(requireSaved = false) {
    const value = { videoModeVersion: 2, drafts: [...state.drafts], sendModes: [...state.sendModes], videoRequests: [...state.videoRequests], submissions: [...state.submissions], unconfirmed: [...state.unconfirmed], expanded: [...state.taskExpanded], positions: [...state.feedPositions], roomId: state.preferredRoomId };
    const pending = viewStorage.then(storage => storage.save(value));
    return requireSaved ? pending : pending.catch(error => notice(error.message, true));
  }
  const modeName = (mode) => mode === "orchestrated" ? "主 Agent 协作群" : mode === "group" ? "手选成员群聊" : "单独聊天";
  const $ = (id) => document.getElementById(`ag-${id}`);
  const make = (tag, cls, text) => {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text !== undefined) node.textContent = String(text);
    return node;
  };
  function markdownBody(value, className) {
    const text = typeof value === "string" ? value : "", node = make("div", className);
    // Reuse the reader's existing libraries without changing its global options.
    // A failed/missing parser must leave readable text, never unsanitized HTML.
    if (typeof window === "undefined" || !window.marked?.parse || !window.DOMPurify?.sanitize) {
      node.textContent = text; return node;
    }
    try {
      const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (char) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[char]);
      const renderer = new window.marked.Renderer();
      // Support both the reader's Marked 12 API and the upstream Node API.
      renderer.html = (token) => escape(typeof token === "string" ? token : token.text);
      renderer.image = (token, title, label) => {
        const href = typeof token === "object" ? token.href : token;
        const alt = typeof token === "object" ? token.text : label;
        const url = publicSourceURL(href), caption = escape(`图片：${alt || "查看图片"}`);
        // Images are opt-in links, so opening a reply cannot load remote pixels.
        return url ? `<a href="${escape(url)}">${caption}</a>` : caption;
      };
      const html = window.marked.parse(text, { renderer, gfm: true, breaks: false, async: false });
      const fragment = window.DOMPurify.sanitize(html, {
        RETURN_DOM_FRAGMENT: true,
        ALLOWED_TAGS: ["p", "h1", "h2", "h3", "h4", "h5", "h6", "ul", "ol", "li", "strong", "em", "del", "s", "code", "pre", "blockquote", "hr", "br", "table", "thead", "tbody", "tfoot", "tr", "td", "th", "a", "input"],
        ALLOWED_ATTR: ["href", "title", "start", "align", "class", "type", "checked", "disabled"],
        ALLOW_DATA_ATTR: false, ALLOW_ARIA_ATTR: false,
      });
      for (const link of fragment.querySelectorAll("a")) {
        const href = link.getAttribute("href") || "";
        const attachment = /^\/api\/chat\/rooms\/[a-f0-9]{32}\/files\/[a-f0-9]{32}$/.test(href)
          && href.startsWith(`/api/chat/rooms/${state.room?.id}/files/`);
        const url = attachment ? href : publicSourceURL(href);
        if (!url) { link.replaceWith(...link.childNodes); continue; }
        link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer";
      }
      for (const element of fragment.querySelectorAll("[class]")) {
        const language = element.tagName === "CODE" && /^language-[a-z0-9_-]+$/i.test(element.className) ? element.className : "";
        element.removeAttribute("class"); if (language) element.className = language;
      }
      for (const input of fragment.querySelectorAll("input")) {
        if (input.type !== "checkbox") input.remove(); else input.disabled = true;
      }
      for (const table of fragment.querySelectorAll("table")) {
        const wrap = make("div", "ag-markdown-table");
        wrap.setAttribute("tabindex", "0"); wrap.setAttribute("role", "region"); wrap.setAttribute("aria-label", "表格，可横向滚动");
        table.replaceWith(wrap); wrap.append(table);
      }
      for (const code of fragment.querySelectorAll("pre")) {
        code.setAttribute("tabindex", "0"); code.setAttribute("aria-label", "代码块，可横向滚动");
      }
      node.append(fragment); node.classList.add("ag-markdown");
    } catch {
      node.textContent = text;
    }
    return node;
  }
  const active = (status) => ["queued", "running"].includes(status);
  const agent = (id) => state.agents.find((item) => item.id === id);
  const agentName = (id) => agent(id)?.name || id || "Agent";
  const depth = (item) => count(item?.depth ?? (item?.id === "central" ? 0 : 1));
  const breadcrumb = (item) => (item?.breadcrumb?.length ? item.breadcrumb : [item?.name || "Agent"]).join(" › ");
  const industryId = (item) => (item?.ancestor_ids || []).find((id) => agent(id) && depth(agent(id)) === 1) || (item?.id !== "central" ? item?.id : "central");
  function orderedAgents() {
    const result = [], seen = new Set();
    function visit(item) { if (seen.has(item.id)) return; seen.add(item.id); result.push(item); state.agents.filter((child) => child.parent_id === item.id).forEach(visit); }
    state.agents.filter((item) => !item.parent_id).forEach(visit); state.agents.forEach(visit); return result;
  }
  const date = (value) => {
    if (!value) return "";
    const parsed = new Date(typeof value === "number" && value < 1e12 ? value * 1000 : value);
    return Number.isNaN(parsed.valueOf()) ? "" : parsed.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
  };
  const count = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
  const topbar = document.querySelector(".topbar");
  if (!topbar || $("launch")) return;
  const launch = make("button", "icon-btn ag-launch", "主 Agent");
  launch.id = "ag-launch"; launch.type = "button"; launch.title = "与主 Agent 沟通需求，确认方案后开始协作";
  const toolbar = document.querySelector(".federation-toolbar");
  if (toolbar) toolbar.prepend(launch); else topbar.insertBefore(launch, document.getElementById("live"));

  // Static markup only. All names, descriptions, messages, and errors use textContent.
  const template = document.createElement("template");
  template.innerHTML = `
    <dialog class="ag-dialog" id="ag-dialog" aria-labelledby="ag-title">
      <header class="ag-dialog-header">
        <div><h2 id="ag-title">主 Agent</h2></div>
        <div class="ag-header-actions"><button class="ag-text-button" id="ag-memory-open" type="button">记忆</button><button class="ag-button" id="ag-history-open" type="button">历史记录</button><button class="ag-button" id="ag-skills-open" type="button">技能库</button><button class="ag-button" id="ag-templates-open" type="button">模板库</button><button class="icon-btn" id="ag-close" type="button" aria-label="关闭主 Agent 对话">×</button></div>
      </header>
      <div class="ag-layout">
        <main class="ag-main">
          <p class="ag-notice" id="ag-notice" role="status" hidden></p>
          <section class="ag-conversation" id="ag-conversation" aria-label="主 Agent 与任务群">
            <header class="ag-conversation-header"><div class="ag-room-title-line"><h3 id="ag-conversation-title">主 Agent</h3><span class="ag-mode-label" id="ag-conversation-mode"></span><button class="ag-text-button ag-return-primary" id="ag-return-primary" type="button" hidden>返回主 Agent</button></div><div class="ag-members" id="ag-members" aria-label="参与 Agent 与本轮进度"></div><p class="ag-orchestration-note" id="ag-orchestration-note" hidden>先聊需求，方案确认后开始协作。普通问题由主 Agent 直接回答；项目需求先调研、给方案，你确认后再邀请成员、分派任务。</p></header>
            <div class="ag-feed" id="ag-feed" role="log" aria-label="聊天消息" aria-live="polite" aria-relevant="additions"></div>
            <div class="ag-turn-status" id="ag-turn-status" role="status" hidden><span class="ag-status-dot" aria-hidden="true"></span><span id="ag-turn-label"></span></div>
            <p class="ag-stream-notice" id="ag-stream-notice" role="status" hidden></p>
            <form class="ag-compose" id="ag-message-form"><label class="ag-sr-only" for="ag-message">发送消息或继续追问</label><textarea id="ag-message" rows="3" maxlength="6000" placeholder="问一个问题，或和主 Agent 聊聊你的需求…" required disabled></textarea>
              <div class="ag-learning-controls" id="ag-research-controls" hidden>
                <div class="ag-learning-choice"><label for="ag-research"><input id="ag-research" type="checkbox" aria-describedby="ag-research-description">联网查询</label></div>
                <p class="ag-learning-description" id="ag-research-description">本轮只查阅公开资料并回答，不写入知识库；也可以直接提供网页链接。</p>
              </div>
              <div class="ag-learning-controls" id="ag-learning-controls" hidden>
                <div class="ag-learning-choice"><label for="ag-learning"><input id="ag-learning" type="checkbox" aria-describedby="ag-learning-description"><span id="ag-learning-label">本轮自主联网学习</span></label><span id="ag-learning-prefix" class="ag-learning-prefix" hidden>已识别 /学习 指令</span><details class="ag-learning-options" id="ag-learning-options"><summary>学习范围</summary><div><label for="ag-learning-pages">每个 Agent 最多采集</label><input id="ag-learning-pages" type="number" min="1" max="5" step="1" value="2" aria-label="每个 Agent 最多采集页数"><span>页</span></div></details></div>
                <p class="ag-learning-description" id="ag-learning-description">子 Agent 自主选题、发现公开资料并更新自己的知识草稿；中央采用仍需审核发布。</p><p class="ag-learning-provider" id="ag-learning-provider" hidden></p>
              </div>
              <div class="ag-compose-footer"><div class="ag-send-mode"><label class="ag-sr-only" for="ag-send-mode">发送方式</label><select id="ag-send-mode"><option value="chat">普通对话</option><option value="video">生成视频（本次）</option></select><a id="ag-video-settings" href="/video-generation" target="_blank" rel="noopener" hidden>接口设置</a></div><span class="ag-compose-hint" id="ag-compose-hint">⌘ / Ctrl + Enter 发送 · 需要查证时再联网</span><div class="ag-compose-actions">
                <details class="ag-context-meter" id="ag-context-meter"><summary id="ag-context-toggle" aria-label="查看上下文用量" aria-controls="ag-context-panel" title="查看上下文用量"><svg class="ag-context-ring" viewBox="0 0 24 24" aria-hidden="true"><circle class="ag-context-track" cx="12" cy="12" r="9"/><circle class="ag-context-fill" id="ag-context-fill" cx="12" cy="12" r="9" pathLength="100"/></svg></summary><section class="ag-context-popover" id="ag-context-panel" aria-labelledby="ag-context-heading"><h4 id="ag-context-heading">上下文</h4><div id="ag-context-body"></div></section></details>
                <button class="ag-text-button" id="ag-stop-reply" type="button" hidden>停止等待</button>
                <button class="ag-button ag-primary" id="ag-send" type="submit" disabled>发送</button></div></div></form>
          </section>
        </main>
      </div>
    </dialog>
    <dialog class="ag-dialog ag-history-dialog" id="ag-history-dialog" aria-labelledby="ag-history-title">
      <header class="ag-dialog-header"><div><p class="ag-eyebrow">OPENWIKI · HISTORY</p><h2 id="ag-history-title">历史记录</h2></div><button class="icon-btn" id="ag-history-close" type="button" aria-label="关闭历史记录">×</button></header>
      <div class="ag-history-body"><div class="ag-sidebar-heading"><h3>已保存的会话</h3><button class="ag-text-button" id="ag-refresh" type="button">刷新</button></div><nav class="ag-room-list" id="ag-rooms" aria-label="查看历史会话"></nav><p class="ag-sidebar-note">旧会话与实际分派记录由服务器保存。新任务直接交给主 Agent，无需另建会话。</p></div>
    </dialog>
    <dialog class="ag-dialog ag-template-dialog" id="ag-templates-dialog" aria-labelledby="ag-templates-title">
      <header class="ag-dialog-header"><div><p class="ag-eyebrow">OPENWIKI · TEMPLATES</p><h2 id="ag-templates-title">Agent 模板库</h2></div><button class="icon-btn" id="ag-templates-close" type="button" aria-label="关闭模板库">×</button></header>
      <div class="ag-template-library">
        <div class="ag-template-toolbar"><label for="ag-template-agent">所属 Agent</label><select id="ag-template-agent" aria-label="选择模板所属 Agent"></select><button class="ag-text-button" id="ag-templates-refresh" type="button">刷新列表</button></div>
        <label class="ag-template-search-label" for="ag-template-search">查找模板<input id="ag-template-search" type="search" placeholder="框架、样式或平台，例如 Angular、SCSS、微信" autocomplete="off"></label>
        <p class="ag-template-policy" id="ag-template-policy">按任务自动读取本 Agent 的规范与相关模板；学习时维护版本，普通聊天不会升级模板。</p>
        <p class="ag-template-status" id="ag-template-status" role="status"></p>
        <div class="ag-template-list" id="ag-template-list" aria-label="模板与规范列表"></div>
      </div>
    </dialog>
    <dialog class="ag-dialog ag-template-dialog ag-skill-dialog" id="ag-skills-dialog" aria-labelledby="ag-skills-title">
      <header class="ag-dialog-header"><div><p class="ag-eyebrow">OPENWIKI · SKILLS</p><h2 id="ag-skills-title">Agent 技能库</h2></div><button class="icon-btn" id="ag-skills-close" type="button" aria-label="关闭技能库">×</button></header>
      <div class="ag-template-library">
        <div class="ag-template-toolbar"><label for="ag-skill-agent">所属 Agent</label><select id="ag-skill-agent" aria-label="选择技能所属 Agent"></select><button class="ag-text-button" id="ag-skills-refresh" type="button">刷新列表</button></div>
        <label class="ag-template-search-label" for="ag-skill-search">查找技能<input id="ag-skill-search" type="search" placeholder="名称、职责或工具，例如 Figma、设计、测试" autocomplete="off"></label>
        <p class="ag-template-policy" id="ag-skill-policy">已导入的技能规范可以按任务读取；外部执行工具尚未接入。</p>
        <p class="ag-template-status" id="ag-skill-status" role="status"></p>
        <div class="ag-template-list" id="ag-skill-list" aria-label="技能规范列表"></div>
      </div>
    </dialog>
    <dialog class="ag-dialog ag-memory-dialog" id="ag-memory-dialog" aria-labelledby="ag-memory-title">
      <header class="ag-dialog-header"><h2 id="ag-memory-title">记忆</h2><button class="icon-btn" id="ag-memory-close" type="button" aria-label="关闭记忆">×</button></header>
      <div class="ag-memory-body">
        <div class="ag-memory-toolbar"><div class="ag-memory-tabs" role="group" aria-label="记忆类型"><button class="ag-text-button" id="ag-memory-tasks" type="button" aria-pressed="true">任务记忆</button><button class="ag-text-button" id="ag-memory-profile" type="button" aria-pressed="false">我的资料</button><button class="ag-text-button" id="ag-memory-projects" type="button" aria-pressed="false">项目续接</button><button class="ag-text-button" id="ag-memory-personal" type="button" aria-pressed="false">个人偏好</button><button class="ag-text-button" id="ag-memory-usage" type="button" aria-pressed="false">用量</button></div><button class="ag-text-button" id="ag-memory-refresh" type="button">刷新</button></div>
        <label class="ag-memory-scope" id="ag-memory-agent-label" for="ag-memory-agent">所属 Agent<select id="ag-memory-agent" aria-label="记忆所属 Agent"></select></label>
        <p class="ag-memory-description">任务记忆用于续聊，个人偏好来自你的明确保存。修正或忘记记忆会影响后续回复，原始聊天继续保留。</p>
        <p class="ag-memory-status" id="ag-memory-status" role="status"></p>
        <div class="ag-memory-list" id="ag-memory-list"></div>
      </div>
    </dialog>`;
  document.body.append(template.content);

  async function api(path, options = {}) {
    const chatPath = path.split('?')[0], roomMatch = chatPath.match(/^\/api\/chat\/rooms\/([a-f0-9]{32})(?:\/messages|\/jobs\/[a-f0-9]{32}\/resume)?$/);
    if ((chatPath === '/api/chat/primary' || roomMatch) && !/[?&]message_limit=/.test(path)) {
      const limit = state.visibleMessages?.get(roomMatch?.[1] || state.roomId) || 60;
      path += (path.includes('?') ? '&' : '?') + 'message_limit=' + Math.min(20000, limit);
    }
    const controller = new AbortController(), timeout = setTimeout(() => controller.abort(), 20000);
    let response;
    try { response = await fetch(path, { cache: "no-store", ...options, signal: controller.signal, headers: { "Content-Type": "application/json", ...(options.headers || {}) } }); }
    catch (error) { throw new Error(error.name === "AbortError" ? "本地服务响应超时，请刷新核对会话状态。" : "暂时无法连接本地服务，请确认启动窗口仍在运行。正在进行的任务可能仍会继续。"); }
    finally { clearTimeout(timeout); }
    let data;
    try { data = await response.json(); } catch { throw new Error(`无法读取服务响应（HTTP ${response.status}）。`); }
    if (!response.ok) {
      const error = new Error(typeof data.detail === "string" ? data.detail : `操作未完成（HTTP ${response.status}），请刷新后重试。`);
      error.code = data.code; error.accepted = data.accepted; throw error;
    }
    return data;
  }
  function notice(message, error = false) {
    $("notice").textContent = message;
    $("notice").hidden = !message;
    $("notice").classList.toggle("ag-error", error);
  }
  function memoryScopePath(data) {
    return `/api/chat/rooms/${encodeURIComponent(data.roomId)}/context-memory`;
  }
  function memoryAction(label, handler) {
    const button = make('button', 'ag-text-button', label); button.type = 'button';
    button.disabled = state.memoryBusy; button.addEventListener('click', handler); return button;
  }
  async function changeMemory(path, payload) {
    if (state.memoryBusy) return;
    state.memoryBusy = true; const epoch = state.memoryEpoch;
    $('memory-status').textContent = '正在保存…';
    $('memory-list').querySelectorAll('button,input,textarea,select').forEach(node => node.disabled = true);
    try {
      await api(path, {method:'POST',body:JSON.stringify(payload)});
      state.memoryBusy = false;
      if (epoch === state.memoryEpoch && $('memory-dialog').open) await loadMemory('已保存。后续回复使用更新后的记忆。');
    } catch(error) {
      if (epoch === state.memoryEpoch && $('memory-dialog').open) {
        $('memory-status').textContent = error.message + '；请刷新核对，未自动重试。';
        $('memory-status').classList.add('ag-error');
        // Keep edits visible after a rejected revision; refresh is explicit.
      }
    } finally {
      state.memoryBusy = false;
      if (epoch === state.memoryEpoch && $('memory-dialog').open) $('memory-list').querySelectorAll('button,input,textarea,select').forEach(node => node.disabled = false);
    }
  }
  function memoryEditor(host, text, save, personal = null) {
    host.replaceChildren(); const form = make('form','ag-memory-editor');
    const label = make('label','','修正内容'), input = make('textarea'); input.value = text; input.maxLength = personal ? 1000 : 6000; input.required = true;
    input.setAttribute('aria-label','修正记忆内容'); label.append(input); form.append(label);
    let scope, expiry;
    if (personal) {
      const scopeLabel = make('label','','适用范围'); scope = make('select'); scope.setAttribute('aria-label','偏好适用范围');
      for (const item of [{id:'project',name:'整个工作区'},...state.agents]) {const option=make('option','',item.name);option.value=item.id;scope.append(option);}
      scope.value = personal.scope || 'project'; scopeLabel.append(scope); form.append(scopeLabel);
      const expiryLabel = make('label','','到期时间（含时区，可留空）'); expiry = make('input'); expiry.value = personal.expires_at || ''; expiry.placeholder='2026-12-31T23:59:00+08:00'; expiry.setAttribute('aria-label','偏好到期时间');expiryLabel.append(expiry);form.append(expiryLabel);
    }
    const actions = make('div','ag-memory-actions'), submit = make('button','ag-button ag-primary','保存修正'); submit.type='submit';
    actions.append(submit,memoryAction('取消',()=>host.replaceChildren()));form.append(actions);
    form.addEventListener('submit',event=>{event.preventDefault(); if(input.value.trim())save(input.value.trim(),scope?.value,expiry?.value.trim() || null);});host.append(form); input.focus();
  }
  function memoryConfirm(host, text, confirm, label='确认忘记') {
    host.replaceChildren(make('p','',text));
    const actions = make('div','ag-memory-actions');actions.append(memoryAction(label,confirm),memoryAction('取消',()=>host.replaceChildren()));host.append(actions);
  }
  function memorySources(ids, data) {
    const detail = make('details','ag-memory-sources');detail.append(make('summary','','查看原消息依据'));
    const body=make('div');detail.append(body);
    const allIds=[...new Set(ids)].reverse();let visible=0;
    const more=memoryAction('显示更早的来源',()=>appendPage());
    function appendPage() {
    for(const id of allIds.slice(visible,visible+30)) {
      const row=make('div','ag-memory-source'), output=make('pre','ag-memory-original');output.hidden=true;
      const button=memoryAction(`读取原消息 ${id.slice(0,8)}`,async()=>{
        if(!output.hidden){output.hidden=true;return;} const epoch=state.memoryEpoch;button.disabled=true;
        try {const source=await api(`${memoryScopePath(data)}/sources/${encodeURIComponent(id)}?agent_id=${encodeURIComponent(data.agentId)}`);
          if(epoch!==state.memoryEpoch || !row.isConnected)return;output.textContent=`${source.role==='user'?'你':source.agent_name || 'Agent'} · ${date(source.created_at)}\n${source.content}`;output.hidden=false;
        }catch(error){if(epoch===state.memoryEpoch){output.textContent=error.message;output.hidden=false;}}finally{button.disabled=false;}
      });row.append(button,output);body.append(row);
    }
    visible+=30;more.hidden=visible>=allIds.length;body.append(more);
    }
    appendPage();
    return detail;
  }
  function renderMemory(data) {
    const list=$('memory-list');list.replaceChildren();
    const personal=state.memoryView==='personal';$('memory-agent-label').hidden=personal || state.memoryView==='profile';
    for(const view of ['tasks','profile','projects','personal','usage'])$('memory-'+view)?.setAttribute('aria-pressed',String(state.memoryView===view));
    if(state.memoryView==='profile'){renderProfile(data);return;}
    if(state.memoryView==='projects'){renderProjects(data);return;}
    if(state.memoryView==='usage'){renderMemoryUsage(data);return;}
    if(personal) {
      let count=0;
      for(const category of ['preferences','learning'])for(const [id,item] of Object.entries(data.personal[category] || {})) {
        count++;const row=make('section','ag-memory-entry'), controls=make('div','ag-memory-actions'), edit=make('div');
        row.append(make('p','ag-memory-text',item.text),make('p','ag-memory-meta',`${category==='preferences'?'个人偏好':'学习偏好'} · ${item.scope==='project' || !item.scope?'整个工作区':agentName(item.scope)} · 版本 ${item.revision || 1}${item.expires_at?' · '+(new Date(item.expires_at).getTime()<=Date.now()?'已过期 ':'到期 ')+date(item.expires_at):''}`));
        const payload={category,memory_id:id,expected_revision:item.revision || 1,text:item.text,scope:item.scope || 'project',expires_at:item.expires_at || null};
        controls.append(memoryAction('修正',()=>memoryEditor(edit,item.text,(text,scope,expires_at)=>changeMemory('/api/user-memory',{...payload,text,scope,expires_at}),item)),
          memoryAction('忘记',()=>memoryConfirm(edit,'忘记这条偏好后，后续回复不再使用它。',()=>changeMemory('/api/user-memory',{...payload,forget:true}))));
        row.append(controls,edit);if(item.versions?.length){const versions=make('details');versions.append(make('summary','','查看旧版本'));for(const old of item.versions)versions.append(make('p','ag-memory-version',`版本 ${old.revision} · ${old.text}`));row.append(versions);}list.append(row);
      }
      if(!count)list.append(make('p','ag-memory-empty','还没有明确保存的个人偏好。你可以在聊天中使用“/记住 回复用中文”等指令。'));
      return;
    }
    const tasks=(data.tasks.tasks || []).filter(task=>task.status!=='forgotten').reverse();
    if(!tasks.length)list.append(make('p','ag-memory-empty','这个会话还没有任务记忆。普通咨询完成后会在这里显示。'));
    for(const task of tasks) {
      const row=make('section','ag-memory-entry'), controls=make('div','ag-memory-actions'), edit=make('div');
      row.append(make('h3','',task.goal),make('p','ag-memory-meta',`${({active:'正在续聊',paused:'已暂停',archived:'已归档'})[task.status] || task.status} · ${agentName(data.agentId)} · ${task.message_ids.length} 条关联消息 · 目标描述中的旧要求以当前要求为准`));
      const ledger=task.requirement_state || {}, records=ledger.records || [];
      const values={react:'React',vue:'Vue',vue3:'Vue 3',angular:'Angular',svelte:'Svelte',flutter:'Flutter',local_only:'不联网，只用本地资料',online_requested:'提出联网需求（仍受宿主检查）',preserve:'保留原始记录',delete_requested:'提出删除需求（尚未执行）',zh:'中文',en:'英文'};
      if(records.length){const rules=make('ul','ag-memory-rules');for(const item of records){const li=make('li',`ag-memory-rule ag-memory-rule-${item.status}`);li.append(make('span','',`${item.label} · ${({active:'当前要求',superseded:'已替代',conflict:'待你选择'})[item.status]}：${values[item.value] || item.value}`));
        const original=make('details');original.append(make('summary','','查看这条要求的原句'),make('p','',item.text));li.append(original);
        if(item.status==='conflict')li.append(memoryAction('采用这条要求',()=>changeMemory(memoryScopePath(data),{agent_id:data.agentId,task_id:task.id,expected_revision:data.tasks.revision,action:'resolve',requirement_id:item.id})));rules.append(li);}row.append(rules);}
      if(task.summary){const summary=make('details','ag-memory-summary');summary.append(make('summary','','查看任务摘要'));for(const field of ['constraints','decisions','progress','open_questions']){const items=task.summary[field] || [];if(items.length)summary.append(make('h4','',({constraints:'约束',decisions:'决定',progress:'进展',open_questions:'待办'})[field]));for(const item of items)summary.append(make('p','',item.text));}row.append(summary);}
      const payload={agent_id:data.agentId,task_id:task.id,expected_revision:data.tasks.revision};
      if(task.manual_summary)row.append(make('p','ag-memory-text','你的摘要修正：'+task.manual_summary.text));
      controls.append(memoryAction('修正目标',()=>memoryEditor(edit,task.goal,text=>changeMemory(memoryScopePath(data),{...payload,action:'update',text}))),
        memoryAction('修正摘要',()=>memoryEditor(edit,task.manual_summary?.text || '',text=>changeMemory(memoryScopePath(data),{...payload,action:'correct_summary',text}))),
        memoryAction('归档',()=>changeMemory(memoryScopePath(data),{...payload,action:'archive'})),
        memoryAction('忘记',()=>memoryConfirm(edit,'忘记会清除这个任务的摘要，并阻止旧消息自动重新成为任务记忆。原始聊天继续保留。',()=>changeMemory(memoryScopePath(data),{...payload,action:'forget'}))));
      if(task.manual_summary)controls.append(memoryAction('移除摘要修正',()=>changeMemory(memoryScopePath(data),{...payload,action:'clear_summary_correction'})));
      row.append(controls,edit,memorySources(task.message_ids,data));
      if(task.versions?.length){const versions=make('details');versions.append(make('summary','','查看版本变化'));for(const old of task.versions.slice(-20))versions.append(make('pre','ag-memory-version',JSON.stringify(old,null,2)));row.append(versions);}list.append(row);
    }
  }
  async function loadMemory(success='') {
    const epoch=++state.memoryEpoch,roomId=state.roomId,agentId=$('memory-agent').value || 'central';
    $('memory-status').classList.remove('ag-error');$('memory-status').textContent='正在读取记忆…';$('memory-refresh').disabled=true;
    try {const query=`?agent_id=${encodeURIComponent(agentId)}`,base=`/api/chat/rooms/${encodeURIComponent(roomId)}`;
      const [tasks,personal,projects,usage,profile]=await Promise.all([api(`${memoryScopePath({roomId})}${query}`),api('/api/user-memory'),api(`${base}/memory-projects${query}`),api(`${base}/context-usage${query}`),api('/api/user-profile')]);
      if(epoch!==state.memoryEpoch || !$('memory-dialog').open)return;
      state.memoryData={roomId,agentId,tasks,personal,projects,usage,profile};renderMemory(state.memoryData);$('memory-status').textContent=success || `${state.room?.title || '当前会话'} · ${agentName(agentId)}${tasks.enabled?'':' · 任务记忆策略已关闭'}`;
    }catch(error){if(epoch===state.memoryEpoch){$('memory-status').textContent=error.message;$('memory-status').classList.add('ag-error');$('memory-list').replaceChildren();}}
    finally{if(epoch===state.memoryEpoch)$('memory-refresh').disabled=false;}
  }
  function renderProfile(data) {
    const profile=data.profile,list=$('memory-list'),form=make('form','ag-memory-editor ag-profile-editor');
    list.append(make('h3','ag-profile-title','让 Agent 了解你'));
    list.append(make('p','ag-memory-description','保存后，日常交流会参考你的背景和目标，求职问题会按需读取简历片段。资料由服务器保存，相关内容会提供给当前配置的回复模型；联系方式默认隐藏，不写入公共知识库。'));
    const fields={};
    for(const [key,label,limit,hint] of [
      ['about','关于我',1200,'可以写职业背景、经验、技能、生活习惯或感兴趣的事。'],
      ['goals','当前目标',800,'例如正在找什么工作、想学什么、目前需要解决什么。'],
      ['preferences','交流偏好',500,'例如回答简短直接，给建议时考虑时间和预算。']]) {
      const wrapper=make('label','',label),field=make('textarea');field.value=profile[key];field.maxLength=limit;field.placeholder=hint;field.setAttribute('aria-label',label);field.rows=key==='preferences'?2:3;wrapper.append(field);form.append(wrapper);fields[key]=field;
    }
    const resume=make('details','ag-profile-resume'),summary=make('summary','','简历');resume.open=Boolean(profile.resume_text);resume.append(summary);
    const uploadLabel=make('label','','导入简历（PDF、Word、TXT、Markdown，5 MB 内）'),upload=make('input');upload.type='file';upload.accept='.pdf,.docx,.txt,.md';upload.setAttribute('aria-label','导入简历');uploadLabel.append(upload);
    const source=make('p','ag-memory-meta',profile.resume_name || '可以先导入简历，也可以直接填写下面的个人信息。');form.prepend(uploadLabel,source);
    const resumeLabel=make('label','','简历正文'),text=make('textarea');text.value=profile.resume_text;text.maxLength=20000;text.rows=10;text.setAttribute('aria-label','简历正文');resumeLabel.append(text);resume.append(resumeLabel);fields.resume_text=text;
    let resumeName=profile.resume_name,importing=false;
    upload.addEventListener('change',async()=>{
      const file=upload.files?.[0];if(!file || importing)return;
      upload.value='';
      if(file.size>5000000){$('memory-status').textContent='文件须小于 5 MB；当前资料未修改。';return;}
      if(text.value.trim()){const confirmation=make('div');resume.append(confirmation);memoryConfirm(confirmation,'替换当前编辑区的简历正文？原来保存的资料会保留到你点击“保存资料”。',()=>{confirmation.remove();importResume(file);},'确认替换');return;}
      await importResume(file);
    });
    async function importResume(file) {
      const epoch=state.memoryEpoch;importing=true;upload.disabled=true;save.disabled=true;$('memory-status').textContent='正在本机提取简历文字…';
      try {
        const encoded=await new Promise((resolve,reject)=>{const reader=new FileReader();reader.onload=()=>resolve(String(reader.result).split(',')[1]);reader.onerror=()=>reject(new Error('文件读取失败'));reader.readAsDataURL(file);});
        const preview=await api('/api/user-profile/preview',{method:'POST',body:JSON.stringify({filename:file.name,data_base64:encoded})});
        if(epoch!==state.memoryEpoch || !form.isConnected)return;
        text.value=preview.text;resumeName=preview.name;source.textContent=resumeName+' · 已提取，尚未保存';resume.open=true;text.focus();
        $('memory-status').textContent='简历文字已提取，请检查后点击“保存资料”。尚未提供给回复模型。';
      }catch(error){if(epoch===state.memoryEpoch && form.isConnected)$('memory-status').textContent=error.message;}
      finally{importing=false;upload.disabled=false;save.disabled=false;upload.value='';}
    }
    form.append(resume);
    const scopeLabel=make('label','','使用范围'),scope=make('select');scope.setAttribute('aria-label','个人资料使用范围');
    for(const [value,label] of [['central','主 Agent'],['workspace','主 Agent 和我咨询的其他成员']]){const option=make('option','',label);option.value=value;scope.append(option);}scope.value=profile.scope;scopeLabel.append(scope);form.append(scopeLabel);
    const enabledLabel=make('label','ag-profile-enabled'),enabled=make('input');enabled.type='checkbox';enabled.checked=profile.enabled;enabledLabel.append(enabled,document.createTextNode('后续聊天使用这些资料'));form.append(enabledLabel);
    const actions=make('div','ag-memory-actions ag-profile-actions'),save=make('button','ag-button ag-primary','保存资料');save.type='submit';actions.append(save);
    const confirm=make('div');
    actions.append(memoryAction('清空资料',()=>memoryConfirm(confirm,'清空后，新的回复不再读取这些个人资料。已有聊天中的内容继续保留。',()=>changeMemory('/api/user-profile',{expected_revision:profile.revision,enabled:false,scope:profile.scope,about:'',goals:'',preferences:'',resume_text:'',resume_name:''}),'确认清空')));
    form.append(actions,confirm);form.addEventListener('submit',event=>{event.preventDefault();if(importing)return;changeMemory('/api/user-profile',{expected_revision:profile.revision,enabled:enabled.checked,scope:scope.value,resume_name:resumeName,...Object.fromEntries(Object.entries(fields).map(([key,field])=>[key,field.value]))});});
    list.append(form);
  }
  function projectEditor(host, data, project=null) {
    host.replaceChildren();const form=make('form','ag-memory-editor'),inputs={};
    const active=(data.tasks.tasks || []).find(t=>t.id===data.tasks.active_task && t.status!=='forgotten');
    for(const [key,label,max] of [['title','项目名称',80],['progress','你记录的当前进度',2000],['next_steps','下一步',2000]]) {
      const field=make('label','',label),input=make(key==='title'?'input':'textarea');input.value=project?.[key] || (key==='title'?(active?.goal || '').slice(0,80):'');input.maxLength=max;input.required=key==='title';input.setAttribute('aria-label',label);field.append(input);form.append(field);inputs[key]=input;
    }
    const scope=make('details','ag-project-scope');scope.append(make('summary','','可续接这个项目的 Agent'));
    const choices=[];for(const item of state.agents){const label=make('label'),check=make('input');check.type='checkbox';check.value=item.id;check.checked=(project?.allowed_agents || [data.agentId]).includes(item.id);if(item.id===data.agentId){check.checked=true;check.disabled=true;}label.append(check,document.createTextNode(item.name));scope.append(label);choices.push(check);}form.append(scope);
    if(!project)form.append(make('p','ag-memory-meta','保存当前任务的已确认要求；进度和下一步由你填写。新会话选择这个项目后才能续接。'));
    const actions=make('div','ag-memory-actions'),save=make('button','ag-button ag-primary',project?'保存项目记录':'保存项目并关联');save.type='submit';actions.append(save,memoryAction('取消',()=>host.replaceChildren()));form.append(actions);
    form.addEventListener('submit',event=>{event.preventDefault();if(!inputs.title.value.trim())return;
      changeMemory(`/api/chat/rooms/${encodeURIComponent(data.roomId)}/memory-projects`,{action:project?'update':'create',agent_id:data.agentId,project_id:project?.id || null,expected_revision:project?.revision ?? data.projects.revision,expected_task_revision:data.tasks.revision,task_id:active?.id || null,binding_revision:data.projects.binding.revision,title:inputs.title.value.trim(),progress:inputs.progress.value.trim(),next_steps:inputs.next_steps.value.trim(),allowed_agents:choices.filter(c=>c.checked).map(c=>c.value)});
    });host.append(form);inputs.title.focus();
  }
  function renderProjects(data) {
    const list=$('memory-list'),binding=data.projects?.binding || {revision:0},projects=data.projects?.projects || [];
    const active=(data.tasks.tasks || []).find(t=>t.id===data.tasks.active_task && t.status!=='forgotten');
    const create=make('section','ag-memory-entry'),edit=make('div');create.append(make('p','ag-memory-text','把已确认的任务要求保存为项目，在另一个会话中选择后继续。'));
    const button=memoryAction('保存当前任务为项目',()=>projectEditor(edit,data));button.disabled=state.memoryBusy || !active;create.append(button,edit);if(!active)create.append(make('p','ag-memory-meta','先完成一次普通咨询，才能把任务保存为项目。'));list.append(create);
    if(!projects.length)list.append(make('p','ag-memory-empty','还没有可供当前 Agent 续接的项目。'));
    for(const project of projects) {
      const selected=binding.project_id===project.id,row=make('section','ag-memory-entry'),controls=make('div','ag-memory-actions'),editor=make('div');
      row.append(make('h3','',project.title),make('p','ag-memory-meta',`${selected?'已关联当前会话':'未关联'} · 版本 ${project.revision} · ${({current:'来源已核对',changed:'来源已变化，请核对后同步',forgotten:'来源已忘记，旧要求停止使用',missing:'来源不存在，旧要求停止使用'})[project.source_status] || project.source_status}${selected && binding.task_id && binding.task_id!==active?.id?' · 仅用于原关联任务，当前任务尚未关联':''}`));
      if(project.original_goal)row.append(make('p','ag-memory-text','来源任务：'+project.original_goal));
      if(project.requirements?.length){const rules=make('ul','ag-memory-rules');for(const text of new Set(project.requirements.map(item=>item.text)))rules.append(make('li','',text));row.append(rules);}
      for(const [key,label] of [['progress','你记录的进度'],['next_steps','下一步']])if(project[key])row.append(make('p','ag-memory-text',label+'：'+project[key]));
      const payload={agent_id:data.agentId,project_id:project.id,expected_revision:project.revision,expected_task_revision:data.tasks.revision,task_id:active?.id || null,binding_revision:binding.revision};const path=`/api/chat/rooms/${encodeURIComponent(data.roomId)}/memory-projects`;
      if(!selected || binding.task_id!==(active?.id || null))controls.append(memoryAction('关联此项目',()=>changeMemory(path,{...payload,action:'attach'})));
      controls.append(memoryAction('编辑记录',()=>projectEditor(editor,data,project)));
      if(active)controls.append(memoryAction('同步当前任务要求',()=>{editor.replaceChildren(make('p','','用当前任务的已确认要求替换项目快照；其他关联会话也会以这个来源续接。'));const actions=make('div','ag-memory-actions');actions.append(memoryAction('确认同步',()=>changeMemory(path,{...payload,action:'sync'})),memoryAction('取消',()=>editor.replaceChildren()));editor.append(actions);}));
      if(selected)controls.append(memoryAction('取消关联',()=>changeMemory(path,{...payload,action:'detach'})));
      controls.append(memoryAction('忘记项目',()=>memoryConfirm(editor,'忘记会清除项目快照和全部会话关联。各会话的原始聊天继续保留。',()=>changeMemory(path,{...payload,action:'forget'}))));row.append(controls,editor);list.append(row);
    }
  }
  function renderMemoryUsage(data) {
    const list=$('memory-list'),format=value=>value==null?'未返回':Number(value).toLocaleString('zh-CN',{maximumFractionDigits:0});
    list.append(make('p','ag-memory-meta','普通咨询保留分项统计。下方全部调用另汇总 Jev 路由、执行、规划、报告及失败尝试；缺失计数保留为未知。'));
    const operations=data.usage?.operations;
    if(operations?.events){
      const row=make('section','ag-memory-entry');row.append(make('h3','','本会话全部调用'),make('p','ag-memory-text',`${format(operations.calls)} 次调用尝试 · 已返回输入 ${format(operations.input)} token · 输出 ${format(operations.output)} token`));
      const names={routing:'Jev 路由',consultation:'咨询',consultation_legacy:'历史咨询',plan:'规划',review:'结果检查',execute:'执行',summary:'汇总',memory_summary:'后台会话摘要',report:'报告',execution:'独立执行'};
      for(const item of operations.categories || [])row.append(make('p','ag-memory-meta',`${names[item.kind] || item.kind}：${format(item.calls)} 次调用，输入 ${format(item.input)}、输出 ${format(item.output)} token`));
      row.append(make('p','ag-memory-meta',`输入缺失 ${operations.input_unknown} 项，输出缺失 ${operations.output_unknown} 项，调用次数缺失 ${operations.calls_unknown} 项。${operations.notice}`));list.append(row);
    }
    const admission=data.usage?.admission;
    if(admission && (admission.limits.calls || admission.limits.input))list.append(make('p','ag-memory-meta',`累计门槛：调用 ${admission.limits.calls || '未设置'} 次，输入 ${admission.limits.input || '未设置'} token。${admission.allowed?'尚可开始新一轮':'已达到门槛，暂停新一轮'}。${admission.notice}`));
    if(admission?.settings){
      const section=make('section','ag-memory-entry'),settings=admission.settings,fields={},editor=make('div','ag-memory-editor');
      section.append(make('h3','','会话用量门槛'),make('p','ag-memory-meta','设置本会话累计调用次数和已返回输入 token 的上限；0 表示不设会话门槛。若已有管理员门槛，实际采用较低的非零值。'));
      for(const [key,label,max] of [['calls','累计调用次数',1000000000],['input','累计输入 token',1000000000000]]){
        const wrapper=make('label','',label),input=document.createElement('input');input.type='number';input.min='0';input.max=String(max);input.step='1';input.value=String(settings[key]);input.setAttribute('aria-label',label);fields[key]=input;wrapper.append(input);editor.append(wrapper);
      }
      if(admission.near?.length)section.append(make('p','ag-memory-meta','已使用至少 80% 的门槛额度，请留意下一轮消耗。'));
      const save=memoryAction('保存门槛',async()=>{
        const epoch=state.memoryEpoch;
        if(state.memoryBusy)return;
        if(Object.values(fields).some(input=>!input.value.trim()||!input.checkValidity()||!Number.isSafeInteger(Number(input.value)))){ $('memory-status').textContent='请输入范围内的非负整数；0 表示不设置。';return; }
        state.memoryBusy=true;save.disabled=true;Object.values(fields).forEach(input=>input.disabled=true);
        try{
          const updated=await api(`/api/chat/rooms/${encodeURIComponent(data.roomId)}/context-limits`,{method:'POST',body:JSON.stringify({expected_revision:settings.revision,calls:Number(fields.calls.value),input:Number(fields.input.value)})});
          if(epoch!==state.memoryEpoch)return;data.usage.admission=updated;state.memoryBusy=false;renderMemory(data);$('memory-status').textContent='已保存本会话门槛。正在运行的任务继续执行。';
        }catch(error){if(epoch===state.memoryEpoch)$('memory-status').textContent=error.message+'；填写内容保留，请刷新核对，未自动重试。';}
        finally{state.memoryBusy=false;if(epoch===state.memoryEpoch){save.disabled=false;Object.values(fields).forEach(input=>input.disabled=false);}}
      });editor.append(save);section.append(editor,make('p','ag-memory-meta',admission.notice));list.append(section);
    }
    for(const [scope,label] of [[data.usage?.room,'本会话累计'],[data.usage?.project,data.usage?.project?'项目累计 · '+data.usage.project.title:'']]) {
      if(!scope)continue;const row=make('section','ag-memory-entry');row.append(make('h3','',label));
      if(!scope.rounds){row.append(make('p','ag-memory-empty','还没有可统计的普通咨询回执。'));list.append(row);continue;}
      row.append(make('p','ag-memory-text',`${scope.rounds} 次咨询回复 · ${format(scope.calls)} 次模型调用 · ${scope.failed_rounds || 0} 次未完成`));
      const table=make('table','ag-usage-table'),head=make('tr');for(const title of ['已返回的计数','输入 token','输出 token'])head.append(make('th','',title));table.append(head);
      for(const [name,input,output] of [['累计',scope.input,scope.output],['回复',scope.reply_input,scope.reply_output],['摘要',scope.summary_input,scope.summary_output],['补查',scope.lookup_input,scope.lookup_output],['检查',scope.check_input,scope.check_output]]){const tr=make('tr');tr.append(make('th','',name),make('td','',format(input)),make('td','',format(output)));table.append(tr);}row.append(table);
      row.append(make('p','ag-memory-meta',`输入计数缺失 ${scope.input_unknown_rounds || 0} 次，输出缺失 ${scope.output_unknown_rounds || 0} 次，调用次数缺失 ${scope.calls_unknown_rounds || 0} 次。累计值只包含已返回计数。输入估算 ${format(scope.estimate)} token，单独展示，不与实际计数相加。缓存命中 ${format(scope.cached)} token（仅供应商返回部分）。`));
      const latency=scope.first_text_ms || {};row.append(make('p','ag-memory-text',`从请求开始到首字：P50 ${latency.p50==null?'未返回':(latency.p50/1000).toFixed(2)+' 秒'} · P95 ${latency.p95==null?'未返回':(latency.p95/1000).toFixed(2)+' 秒'} · ${latency.samples || 0} 条完整计时`));
      row.append(make('p','ag-memory-meta',scope.notice));list.append(row);
      if(scope.operations?.events)list.append(make('p','ag-memory-meta',`项目有明确归属的调用：${format(scope.operations.calls)} 次，已返回输入 ${format(scope.operations.input)}、输出 ${format(scope.operations.output)} token。${scope.operations.notice}`));
    }
    if(!data.usage?.project)list.append(make('p','ag-memory-meta','关联项目后，这里会显示该项目在多个会话中的累计用量。'));
    const refresh=memoryAction('重新核对全部回执',async()=>{const epoch=state.memoryEpoch;refresh.disabled=true;try{const usage=await api(`/api/chat/rooms/${encodeURIComponent(data.roomId)}/context-usage?agent_id=${encodeURIComponent(data.agentId)}&refresh=true`);if(epoch!==state.memoryEpoch)return;data.usage=usage;renderMemory(data);$('memory-status').textContent='已重新核对保存的回执。';}catch(error){if(epoch===state.memoryEpoch)$('memory-status').textContent=error.message;}finally{refresh.disabled=false;}});list.append(refresh);
  }
  function openMemory() {
    if(!state.roomId || !state.room)return;
    $('memory-agent').replaceChildren(...(state.room.participants || ['central']).map(id=>{const option=make('option','',agentName(id));option.value=id;return option;}));
    $('memory-agent').value=(state.room.participants || []).includes('central')?'central':state.room.participants?.[0];
    if(!$('memory-dialog').open)$('memory-dialog').showModal();loadMemory();
  }
  function templateFileURL(space, identifier, path) {
    const validPart = (value) => typeof value === "string" && value.length > 0 && ![".", ".."].includes(value) && !/[\\/\u0000-\u001f\u007f]/u.test(value);
    if (!validPart(space) || !validPart(identifier) || typeof path !== "string") return null;
    const parts = path.split("/");
    if (!parts.every(validPart)) return null;
    return `/api/spaces/${encodeURIComponent(space)}/templates/${encodeURIComponent(identifier)}/files/${parts.map(encodeURIComponent).join("/")}`;
  }
  function defaultTemplateSpace() {
    const direct = state.view === "room" && state.room?.mode === "direct" ? state.room.participants?.[0] : null;
    return [direct, state.graphSpace, "central", state.agents[0]?.id].find((id) => id && agent(id)) || null;
  }
  function renderTemplatePicker() {
    const items = orderedAgents();
    if (!items.some((item) => item.id === state.templateSpace)) state.templateSpace = defaultTemplateSpace();
    $("template-agent").replaceChildren(...items.map((item) => {
      const option = make("option", "", breadcrumb(item)); option.value = item.id; return option;
    }));
    $("template-agent").value = state.templateSpace || "";
    $("template-agent").disabled = !items.length;
  }
  async function previewTemplateFile(url, button, output, label = "模板") {
    if (button.disabled) return;
    if (output.dataset.loaded === "true") { output.hidden = !output.hidden; button.textContent = output.hidden ? "查看" : "收起"; return; }
    button.disabled = true; button.textContent = "读取中…"; output.hidden = false;
    output.textContent = `正在读取本地${label}文件…`;
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
    try {
      const response = await fetch(url, { cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(`文件读取未完成（HTTP ${response.status}）。`);
      if (Number(response.headers.get("content-length")) > 262144) throw new Error("文件较大，请下载后查看。");
      const text = await response.text();
      if (text.length > 262144) throw new Error("文件较大，请下载后查看。");
      output.textContent = text || "（空文件）"; output.dataset.loaded = "true"; button.textContent = "收起";
    } catch (error) {
      output.textContent = error.name === "AbortError" ? "文件读取超时，请重试或下载查看。" : error.message || "暂时无法读取文件，请重试。";
      button.textContent = "重试查看";
    } finally { clearTimeout(timer); button.disabled = false; }
  }
  function renderTemplateList(data, space) {
    state.templateData = { data, space };
    const allItems = Array.isArray(data.templates) ? data.templates.filter((item) => item && typeof item === "object" && !Array.isArray(item)) : [];
    const query = ($("template-search").value || "").trim().toLocaleLowerCase();
    const items = allItems.filter((item) => !query || [item.id, item.name, item.framework, ...(Array.isArray(item.keywords) ? item.keywords : []), ...Object.keys(item.files || {})].join(" ").toLocaleLowerCase().includes(query));
    $("template-policy").textContent = data.automatic_read === true ? "按任务自动读取本 Agent 的规范与相关模板；学习时维护版本，普通聊天不会升级模板。此面板只查看和下载。" : "这里展示本 Agent 已保存的规范与模板；自动读取状态尚未确认。此面板只查看和下载。";
    $("template-status").classList.remove("ag-template-error");
    $("template-status").textContent = `${agentName(space)} · ${query ? `匹配 ${items.length} / ${allItems.length}` : allItems.length} 个规范与模板包`;
    const cards = items.map((item) => {
      const card = make("details", "ag-template-card"), summary = make("summary", "ag-template-heading"), heading = make("span", "ag-template-name");
      const kind = item.kind === "agent-standard" ? "通用工作规范" : item.kind ? "专项模板" : "框架源码模板";
      heading.append(make("strong", "", item.name || item.id || "模板"), make("span", "ag-template-kind", `${kind}${item.framework && item.framework !== "general" ? ` · ${item.framework}` : ""}`));
      summary.append(heading, make("span", "ag-template-version", item.source_version || "版本未记录")); card.append(summary);
      card.open = item.kind === "agent-standard";
      const body = make("div", "ag-template-body");
      const source = item.source_url === "local-agent-policy" ? "本 Agent 职责与本库知识" : item.source_url || item.upstream_repository || "本地专项模板";
      body.append(make("p", "ag-template-provenance", `来源：${source}`));
      if (item.upstream_commit) body.append(make("p", "ag-template-provenance", `上游版本：${item.upstream_commit}`));
      if (item.updated_at || item.created_at) body.append(make("p", "ag-template-provenance", `记录时间：${date(item.updated_at || item.created_at)}`));
      const files = item.files && typeof item.files === "object" && !Array.isArray(item.files) ? Object.keys(item.files).sort((a, b) => (a === "GUIDELINES.md" ? -1 : b === "GUIDELINES.md" ? 1 : a.localeCompare(b))) : [];
      const list = make("ul", "ag-template-files");
      for (const path of files) {
        const row = make("li"), line = make("div", "ag-template-file-line"), url = templateFileURL(space, item.id, path);
        line.append(make("span", "ag-template-file-path", path));
        if (url) {
          const actions = make("span", "ag-template-file-actions"), download = make("a", "ag-template-download", "下载");
          download.href = url; download.download = path.split("/").at(-1);
          if (/\.(md|txt|json|[cm]?[jt]sx?|css|less|scss|sass|wxss|wxml|html?|vue|svelte|astro|ya?ml|csv|xml|svg|toml|ini|sh|dart|swift|kts?|py)$|(?:^|\/)(?:LICENSE|Dockerfile|\.gitignore)$/iu.test(path)) {
            const button = make("button", "ag-text-button", "查看"), output = make("pre", "ag-template-preview");
            button.type = "button"; button.setAttribute("aria-label", `查看 ${path}`); output.hidden = true;
            button.addEventListener("click", () => previewTemplateFile(url, button, output)); actions.append(button); row.append(line, output);
          } else row.append(line);
          download.setAttribute("aria-label", `下载 ${path}`); actions.append(download); line.append(actions);
        } else { line.append(make("span", "ag-template-error", "文件路径无效")); row.append(line); }
        list.append(row);
      }
      body.append(files.length ? list : make("p", "ag-template-provenance", "当前包没有文件记录。")); card.append(body); return card;
    });
    $("template-list").replaceChildren(...(cards.length ? cards : [make("p", "ag-template-empty", query ? "没有匹配的模板，请换一个关键词。" : "这个 Agent 还没有已保存的模板。模板学习与维护完成后会显示在这里。") ]));
  }
  async function loadTemplates(space = state.templateSpace) {
    const epoch = ++state.templateEpoch;
    state.templateData = null;
    state.templateSpace = space; $("template-status").classList.remove("ag-template-error");
    $("template-status").textContent = "正在读取模板库…"; $("template-list").replaceChildren(); $("templates-refresh").disabled = true;
    try {
      if (!space || !agent(space)) throw new Error("暂未读取到 Agent，请重新打开模板库。");
      const data = await api(`/api/spaces/${encodeURIComponent(space)}/templates`);
      if (epoch === state.templateEpoch && space === state.templateSpace && $("templates-dialog").open) renderTemplateList(data, space);
    } catch (error) {
      if (epoch === state.templateEpoch && $("templates-dialog").open) { $("template-status").textContent = error.message; $("template-status").classList.add("ag-template-error"); }
    } finally { if (epoch === state.templateEpoch) $("templates-refresh").disabled = false; }
  }
  function skillFileURL(space, identifier, path) {
    const validPart = (value) => typeof value === "string" && value.length > 0 && ![".", ".."].includes(value) && !/[\\/\u0000-\u001f\u007f]/u.test(value);
    if (!validPart(space) || !validPart(identifier) || typeof path !== "string") return null;
    const parts = path.split("/");
    if (!parts.every(validPart)) return null;
    return `/api/spaces/${encodeURIComponent(space)}/skills/${encodeURIComponent(identifier)}/files/${parts.map(encodeURIComponent).join("/")}`;
  }
  function renderSkillPicker() {
    const items = orderedAgents();
    if (!items.some((item) => item.id === state.skillSpace)) state.skillSpace = defaultTemplateSpace();
    $("skill-agent").replaceChildren(...items.map((item) => {
      const option = make("option", "", breadcrumb(item)); option.value = item.id; return option;
    }));
    $("skill-agent").value = state.skillSpace || "";
    $("skill-agent").disabled = !items.length;
  }
  function renderSkillList(data, space) {
    state.skillData = { data, space };
    const allItems = Array.isArray(data.skills) ? data.skills.filter((item) => item && typeof item === "object" && !Array.isArray(item)) : [];
    const query = ($("skill-search").value || "").trim().toLocaleLowerCase();
    const items = allItems.filter((item) => !query || [item.id, item.name, item.display_name, item.description,
      ...(Array.isArray(item.keywords) ? item.keywords : []), ...(Array.isArray(item.dependencies) ? item.dependencies : []),
      ...Object.keys(item.files || {})].join(" ").toLocaleLowerCase().includes(query));
    $("skill-policy").textContent = `${data.automatic_read === true ? "按当前任务自动匹配本 Agent 技能，每轮最多读取 3 个技能规范。" : "这里展示本 Agent 已导入的技能规范；自动读取状态尚未确认。"}外部执行工具尚未接入，读取规范不代表已执行工具。`;
    $("skill-status").classList.remove("ag-template-error");
    $("skill-status").textContent = `${agentName(space)} · ${query ? `匹配 ${items.length} / ${allItems.length}` : allItems.length} 个技能`;
    const cards = items.map((item) => {
      const card = make("details", "ag-template-card ag-skill-card"), summary = make("summary", "ag-template-heading"), heading = make("span", "ag-template-name");
      const conflict = item.status === "conflict";
      heading.append(make("strong", "", item.display_name || item.name || item.id || "技能"), make("span", "ag-template-kind", `技能标识：${item.id || "未记录"}`));
      const fullVersion = typeof item.version === "string" ? item.version : "";
      const version = make("span", "ag-template-version", /^[a-f0-9]{64}$/iu.test(fullVersion) ? `sha256:${fullVersion.slice(0, 12)}` : fullVersion || "版本未记录");
      if (fullVersion) version.title = fullVersion;
      summary.append(heading, version); card.append(summary);
      const body = make("div", "ag-template-body");
      if (/^[a-f0-9]{64}$/iu.test(fullVersion)) body.append(make("p", "ag-template-provenance", `完整版本 SHA-256：${fullVersion}`));
      if (typeof item.description === "string" && item.description) body.append(make("p", "ag-skill-description", item.description));
      body.append(make("p", conflict ? "ag-skill-state ag-template-error" : "ag-skill-state", conflict ? "校验失败 · 保留人工修改 · 暂不自动读取" : item.execution_status === "reference_only" ? "已导入 · 可读取规范 · 执行工具尚未接入" : "已导入规范 · 外部执行状态未核实"));
      if (conflict) {
        summary.append(make("span", "ag-skill-conflict-label", "需处理"));
        body.append(make("p", "ag-template-provenance ag-template-error", typeof item.error === "string" && item.error ? item.error : "技能完整性校验未通过，请保留现有文件后处理冲突。"));
      }
      body.append(make("p", "ag-template-provenance", `来源：${item.source_path || "来源路径未记录"}${item.source_kind ? ` · ${item.source_kind}` : ""}`));
      const dependencies = Array.isArray(item.dependencies) ? item.dependencies.filter((value) => typeof value === "string" && value.trim()) : [];
      body.append(make("p", "ag-template-provenance", `依赖：${dependencies.length ? dependencies.join("、") : "未声明"}；是否可用以实际连接与执行回执为准。`));
      const files = !conflict && item.files && typeof item.files === "object" && !Array.isArray(item.files) ? Object.keys(item.files).sort((a, b) => a === "SKILL.md" ? -1 : b === "SKILL.md" ? 1 : a.localeCompare(b)) : [];
      const list = make("ul", "ag-template-files");
      for (const path of files) {
        const row = make("li"), line = make("div", "ag-template-file-line"), url = skillFileURL(space, item.id, path);
        line.append(make("span", "ag-template-file-path", path));
        if (url) {
          const actions = make("span", "ag-template-file-actions"), download = make("a", "ag-template-download", "下载");
          download.href = url; download.download = path.split("/").at(-1);
          if (/\.(md|txt|json|[cm]?[jt]sx?|css|less|scss|sass|wxss|wxml|html?|vue|svelte|astro|ya?ml|csv|xml|svg|toml|ini|sh|dart|swift|kts?|py)$|(?:^|\/)(?:LICENSE|Dockerfile|\.gitignore)$/iu.test(path)) {
            const button = make("button", "ag-text-button", "查看"), output = make("pre", "ag-template-preview");
            button.type = "button"; button.setAttribute("aria-label", `查看技能文件 ${path}`); output.hidden = true;
            button.addEventListener("click", () => previewTemplateFile(url, button, output, "技能规范"));
            actions.append(button); row.append(output);
          }
          actions.append(download); line.append(actions);
        } else line.append(make("span", "ag-template-error", "文件路径无效"));
        row.prepend(line); list.append(row);
      }
      if (!files.length) body.append(make("p", "ag-template-provenance", conflict ? "当前版本暂不开放文件读取。修复冲突并完成校验后再使用。" : "尚无可核验的文件清单。"));
      body.append(list); card.append(body); return card;
    });
    $("skill-list").replaceChildren(...(cards.length ? cards : [make("p", "ag-template-empty", query ? "没有匹配的技能。可以更换关键词或所属 Agent。" : "这个 Agent 还没有已导入的技能规范。") ]));
  }
  async function loadSkills(space = state.skillSpace) {
    const epoch = ++state.skillEpoch;
    state.skillData = null; state.skillSpace = space;
    $("skill-status").classList.remove("ag-template-error");
    $("skill-status").textContent = "正在读取技能库…"; $("skill-list").replaceChildren(); $("skills-refresh").disabled = true;
    try {
      if (!space || !agent(space)) throw new Error("暂未读取到 Agent，请重新打开技能库。");
      const data = await api(`/api/spaces/${encodeURIComponent(space)}/skills`);
      if (epoch === state.skillEpoch && space === state.skillSpace && $("skills-dialog").open) renderSkillList(data, space);
    } catch (error) {
      if (epoch === state.skillEpoch && $("skills-dialog").open) { $("skill-status").textContent = error.message; $("skill-status").classList.add("ag-template-error"); }
    } finally { if (epoch === state.skillEpoch) $("skills-refresh").disabled = false; }
  }
  function saveDraft() {
    if (state.view === "room" && state.roomId) {
      state.drafts.set(state.roomId, $("message").value);
      state.feedPositions.set(state.roomId, $("feed").scrollTop);
    }
    persistView();
  }
  function renderRooms() {
    const sorted = [...state.rooms].sort((a, b) => String(b.updated_at || b.created_at || "").localeCompare(String(a.updated_at || a.created_at || "")));
    $("rooms").replaceChildren(...(sorted.length ? sorted.map((room) => {
      const button = make("button", `ag-room${state.view === "room" && room.id === state.roomId ? " ag-selected" : ""}`);
      button.type = "button"; button.setAttribute("aria-current", state.view === "room" && room.id === state.roomId ? "page" : "false");
      const heading = make("span", "ag-room-heading");
      heading.append(make("span", "ag-room-symbol", room.mode === "direct" ? "◉" : "◎"), make("span", "ag-room-name", room.title || "未命名会话"));
      button.append(heading, make("span", "ag-room-meta", `${room.mode === "orchestrated" ? "自动分派" : room.mode === "group" ? `${(room.participants || []).length} 位 Agent` : "单独聊天"} · ${active(room.status) ? (room.status === "queued" ? "等待中" : "回答中") : date(room.updated_at || room.created_at)}`));
      if (active(room.status)) button.classList.add("ag-room-running");
      button.addEventListener("click", () => { $("history-dialog").close(); selectRoom(room.id); });
      return button;
    }) : [make("p", "ag-room-empty", state.loaded ? "还没有会话。把第一个任务交给主 Agent。" : "正在读取会话…")]));
    launch.classList.toggle("ag-has-active", state.rooms.some((room) => active(room.status)));
  }
  function currentChatContext(room) {
    const groups = Array.isArray(room.task_groups) ? room.task_groups : [];
    const group = (room.current_task_group_id && groups.find((item) => item.id === room.current_task_group_id || item.round_id === room.current_task_group_id)) || groups.at(-1);
    const messages = [...(room.messages || [])].reverse(), user = messages.find((message) => message.role === "user");
    const reply = messages.find((message) => message.role === "assistant" && message.agent_id === "central");
    const confirmed = (Array.isArray(room.proposals) ? room.proposals : []).find((proposal) => proposal.status === "confirmed" && proposal.confirmed_job_id && proposal.confirmed_job_id === room.active_job_id);
    const pendingGroup = room.mode === "orchestrated" && room.status === "queued" && room.active_job_id !== room.current_task_group_id && Boolean(confirmed);
    const discussion = room.mode === "orchestrated" && !pendingGroup && (user?.phase === "consultation" || (!group && !(room.delegations || []).length && user?.phase !== "confirmation") || (user?.phase !== "confirmation" && ["consultation", "proposal"].includes(reply?.phase)));
    const roundId = pendingGroup || discussion ? room.active_job_id || user?.round_id : group?.round_id || group?.id || user?.round_id;
    return { group, pendingGroup, discussion, roundId, confirmed };
  }
  function renderMembers(room) {
    const { group: latest, pendingGroup, discussion, roundId } = currentChatContext(room);
    const primary = room.purpose === "primary" || room.id === state.primaryRoomId;
    const ids = pendingGroup || discussion ? ["central"] : latest ? latest.members : room.mode === "orchestrated" && primary ? ["central"] : room.participants;
    const members = new Set((Array.isArray(ids) ? ids : []).filter((id) => typeof id === "string" && id));
    if (!pendingGroup && !discussion && !latest && room.mode === "orchestrated" && !primary) {
      for (const message of room.messages || []) if (message.round_id === roundId) for (const id of [message.agent_id, message.actor_agent_id, message.recipient_agent_id]) if (typeof id === "string" && id) members.add(id);
      for (const task of room.delegations || []) if (task.round_id === roundId && typeof task.agent_id === "string" && task.agent_id) members.add(task.agent_id);
    }
    $("members").replaceChildren(...[...members].map((id) => {
      const tasks = discussion ? [] : (room.delegations || []).filter((task) => task.agent_id === id && roundId && task.round_id === roundId);
      const running = tasks.find((task) => task.status === "running"), failed = tasks.some((task) => task.status === "failed");
      const status = pendingGroup ? "等待组群" : discussion ? room.status === "queued" ? "等待回复" : room.status === "running" ? "处理中" : "" : running ? running.phase === "plan" ? "分派中" : running.phase === "summary" ? "汇总中" : "处理中" : failed ? "未完成" : tasks.some((task) => task.status === "queued") ? "待处理" : tasks.length && tasks.every((task) => task.status === "completed") ? "已完成" : "";
      const chip = make("span", `ag-member${id === "central" ? " ag-central" : ""}${running ? " ag-member-running" : ""}${failed && !running ? " ag-member-failed" : ""}`, `${room.mode === "orchestrated" && id === "central" ? "主 Agent" : agentName(id)}${status ? ` · ${status}` : ""}`);
      chip.title = `${breadcrumb(agent(id))} · ${agent(id)?.description || "独立知识库 Agent"}`; return chip;
    }));
  }
  function taskStatus(task, childCount = 0) {
    if (task.status === "failed") return "未完成";
    if (task.status === "queued") return "待处理";
    if (task.kind === "web_learning" && task.phase === "execute" && task.web_learning?.status) {
      const labels = { planning: "研究主题中", collecting: "采集资料中", learning: "整理知识中", completed: "学习完成", unchanged: "无新增变化", failed: "学习未完成" };
      if (labels[task.web_learning.status]) return labels[task.web_learning.status];
    }
    if (task.status === "running") return task.phase === "plan" ? childCount > 0 ? "等待子任务" : "拆分任务中" : task.phase === "summary" ? "汇总中" : "处理中";
    if (task.status === "completed") return task.phase === "plan" ? "已回答" : task.phase === "summary" ? "已汇总" : "已完成";
    return "状态待确认";
  }
  function rememberDetails(details, key, defaultOpen = false) {
    details.open = state.taskExpanded.has(key) ? Boolean(state.taskExpanded.get(key)) : defaultOpen;
    details.addEventListener("toggle", () => {
      if (!details.isConnected) return;
      state.taskExpanded.set(key, details.open); persistView();
    });
  }
  function publicSourceURL(value) {
    if (typeof value !== "string" || /[\u0000-\u0020\u007f]/u.test(value)) return null;
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }
  function renderTemplateReads(entry, key) {
    const selected = Array.isArray(entry.template_selection) ? entry.template_selection.filter((item) => item && typeof item === "object" && !Array.isArray(item) && typeof item.id === "string") : [];
    const reads = Array.isArray(entry.template_reads) ? entry.template_reads.filter((item) => item && typeof item === "object" && !Array.isArray(item) && typeof item.path === "string") : [];
    const notices = Array.isArray(entry.template_notices) ? entry.template_notices.filter((item) => typeof item === "string" || item && typeof item.text === "string") : [];
    if (!selected.length && !reads.length && !notices.length) return null;
    const details = make("details", "ag-task-section ag-template-reads"), summary = make("summary", "ag-task-section-title", "本轮读取的规范与模板");
    summary.dataset.taskKey = `${key}:template-reads`; details.append(summary);
    rememberDetails(details, `${key}:template-reads`);
    const body = make("div", "ag-template-reads-body"), groups = new Map();
    for (const item of notices) body.append(make("p", "ag-template-provenance", typeof item === "string" ? item : `${item.agent_id ? agentName(item.agent_id) + "：" : ""}${item.text}`));
    function groupFor(item, templateId) {
      const owner = typeof item.agent_id === "string" ? item.agent_id : typeof entry.agent_id === "string" ? entry.agent_id : "";
      const groupKey = JSON.stringify([owner, templateId]);
      if (!groups.has(groupKey)) groups.set(groupKey, { owner, id: templateId, selected: [], reads: [] });
      return groups.get(groupKey);
    }
    for (const item of selected) groupFor(item, item.id).selected.push(item);
    for (const item of reads) groupFor(item, typeof item.template_id === "string" ? item.template_id : "未记录模板 ID").reads.push(item);
    for (const group of groups.values()) {
      const section = make("section", "ag-template-read-group");
      section.append(make("h4", "", `${group.owner ? agentName(group.owner) : "未记录 Agent"} · ${group.id}`));
      for (const item of group.selected) section.append(make("p", "", `已选模板版本：${item.source_version || "版本未记录"}${item.framework ? ` · ${item.framework}` : ""}${item.upstream_commit ? ` · ${String(item.upstream_commit).slice(0, 12)}` : ""}`));
      if (group.reads.length) {
        section.append(make("p", "", `实际文件读取 · ${group.reads.length}`));
        const list = make("ul");
        for (const item of group.reads) {
          const file = make("li", "", item.path);
          if (typeof item.sha256 === "string" && item.sha256) file.append(make("span", "ag-template-read-hash", `SHA-256：${item.sha256}`));
          list.append(file);
        }
        section.append(list);
      } else section.append(make("p", "", "本条记录没有实际文件读取回执。"));
      body.append(section);
    }
    details.append(body); return details;
  }
  function renderSkillReads(entry, key) {
    const selected = Array.isArray(entry.skill_selection) ? entry.skill_selection.filter((item) => item && typeof item === "object" && !Array.isArray(item) && typeof item.id === "string") : [];
    const reads = Array.isArray(entry.skill_reads) ? entry.skill_reads.filter((item) => item && typeof item === "object" && !Array.isArray(item) && typeof item.path === "string") : [];
    const notices = Array.isArray(entry.skill_notices) ? entry.skill_notices.filter((item) => typeof item === "string" || item && typeof item.text === "string") : [];
    if (!selected.length && !reads.length && !notices.length) return null;
    const details = make("details", "ag-task-section ag-template-reads ag-skill-reads"), summary = make("summary", "ag-task-section-title", "本轮读取的技能规范");
    summary.dataset.taskKey = `${key}:skill-reads`; details.append(summary); rememberDetails(details, `${key}:skill-reads`);
    const body = make("div", "ag-template-reads-body"), groups = new Map();
    for (const item of notices) body.append(make("p", "ag-template-provenance", typeof item === "string" ? item : `${item.agent_id ? agentName(item.agent_id) + "：" : ""}${item.text}`));
    function groupFor(item, skillId) {
      const owner = typeof item.agent_id === "string" ? item.agent_id : typeof entry.agent_id === "string" ? entry.agent_id : "";
      const groupKey = JSON.stringify([owner, skillId]);
      if (!groups.has(groupKey)) groups.set(groupKey, { owner, id: skillId, selected: [], reads: [] });
      return groups.get(groupKey);
    }
    for (const item of selected) groupFor(item, item.id).selected.push(item);
    for (const item of reads) groupFor(item, typeof item.skill_id === "string" ? item.skill_id : "未记录技能 ID").reads.push(item);
    for (const group of groups.values()) {
      const section = make("section", "ag-skill-read-group"), name = group.selected.find((item) => typeof item.display_name === "string" && item.display_name)?.display_name;
      section.append(make("h4", "", `${group.owner ? agentName(group.owner) : "未记录 Agent"} · ${name ? name + " · " : ""}${group.id}`));
      for (const item of group.selected) {
        section.append(make("p", "", `已选技能版本：${item.version || "版本未记录"}`));
        if (typeof item.selection_reason === "string" && item.selection_reason) section.append(make("p", "", `匹配原因：${item.selection_reason}`));
      }
      if (group.reads.length) {
        section.append(make("p", "", `实际文件读取 · ${group.reads.length}`));
        const list = make("ul");
        for (const item of group.reads) {
          const file = make("li", "", item.path);
          const fullHash = typeof item.full_sha256 === "string" && item.full_sha256 ? item.full_sha256 : null;
          if (fullHash) file.append(make("span", "ag-template-read-hash", `完整文件 SHA-256：${fullHash}`));
          if (typeof item.sha256 === "string" && item.sha256 && item.sha256 !== fullHash) file.append(make("span", "ag-template-read-hash", `读取回执 SHA-256：${item.sha256}`));
          if (typeof item.excerpt_sha256 === "string" && item.excerpt_sha256) file.append(make("span", "ag-template-read-hash", `模型所见摘录 SHA-256：${item.excerpt_sha256}`));
          if (item.truncated === true) file.append(make("span", "ag-skill-read-note", "已按上下文预算截取；模型本轮未收到文件全文。"));
          list.append(file);
        }
        section.append(list);
      } else section.append(make("p", "", "本条记录只有技能选择，没有实际文件读取回执。"));
      body.append(section);
    }
    body.append(make("p", "ag-skill-read-note", "以上是技能规范的读取记录，不代表已经调用技能依赖的外部工具。"));
    details.append(body); return details;
  }
  function renderWikiReads(entry, key) {
    const reads = Array.isArray(entry.wiki_reads) ? entry.wiki_reads.filter((item) => item && typeof item === "object" && !Array.isArray(item) && typeof item.path === "string") : [];
    const checks = Array.isArray(entry.wiki_citation_checks) ? entry.wiki_citation_checks.filter((item) => item && typeof item === "object" && !Array.isArray(item) && typeof item.status === "string") : [];
    if (entry.wiki_citation_check && typeof entry.wiki_citation_check === "object" && !Array.isArray(entry.wiki_citation_check) && typeof entry.wiki_citation_check.status === "string") checks.push(entry.wiki_citation_check);
    if (!reads.length && !checks.length) return null;
    const details = make("details", "ag-task-section ag-template-reads ag-wiki-reads"), summary = make("summary", "ag-task-section-title", "本轮读取的知识与引用核对");
    summary.dataset.taskKey = `${key}:wiki-reads`; details.append(summary); rememberDetails(details, `${key}:wiki-reads`);
    const body = make("div", "ag-template-reads-body"), labels = { current: "已记录", stale: "待更新", untracked: "未追溯", review_due: "待复核" };
    const supplied = entry.wiki_input && Array.isArray(entry.wiki_input.inputs) ? entry.wiki_input.inputs : null;
    if (supplied) body.append(make('p', '', `宿主预读 ${reads.length} 页；预算后实际提供 ${new Set(supplied.map(item => item.path)).size} 页正文。引用核对以实际输入为准。`));
    const assessment = entry.answer_check;
    if (assessment && typeof assessment === 'object' && Array.isArray(assessment.checks)) {
      const section = make('section', 'ag-wiki-citation-check');
      section.append(make('h4', '', assessment.status === 'corrected_with_limits' ? '本轮已补充纠正' : '本轮结论核对'));
      section.append(make('p', '', '扫描正文中的事实、数字、因果和时效表述，按批次辅助核对；模型判定供参考，知识页的人工审核状态保留。'));
      if (Number.isFinite(assessment.assertion_total)) section.append(make('p','',`检测到 ${count(assessment.assertion_total)} 条候选断言；得到辅助判定 ${count(assessment.assessed_assertions)} 条；未完成 ${count(assessment.unassessed_assertions)} 条${assessment.unchecked_assertions_withdrawn ? '，已从最终模型结论中撤回' : ''}。`));
      if (Array.isArray(assessment.user_restricted_paths)) section.append(make('p','',`本轮限定依据：${assessment.user_restricted_paths.filter(path=>typeof path==='string').join('、') || '实际输入中没有匹配正文'}${assessment.user_scope_check?.status==='scope_violation' ? '；先前引用包含范围外资料，已进入纠正' : ''}。`));
      for (const check of assessment.checks) {
        if(typeof check.assertion_text==='string') section.append(make('p','',`待核对表述：${check.assertion_text}`));
        section.append(make('p', '', `${({supported:'辅助判定可支持',contradicted:'辅助判定与材料矛盾',insufficient:'依据不足'})[check.status] || '未确定'}：${check.reason || ''}`));
        for (const ref of Array.isArray(check.references) ? check.references : []) {
          if (typeof ref.path === 'string' && typeof ref.quote === 'string') section.append(make('p', '', `${ref.source_basis==='user_record'?'用户要求或记录（不代表执行已核实）':ref.path}：“${ref.quote}”`));
        }
      }
      if (assessment.failure) section.append(make('p', 'ag-wiki-read-warning', '这次自动核对未完成，相关部分保留为待核实。'));
      if (assessment.omitted_assertions) section.append(make('p', '', `另有 ${count(assessment.omitted_assertions)} 条风险断言未进入本次自动核对。`));
      body.append(section);
    }
    if (Number.isFinite(entry.timing?.request_first_text_ms)) body.append(make('p', '', `服务收到问题至首段回复 ${(entry.timing.request_first_text_ms / 1000).toFixed(2)} 秒${Number.isFinite(entry.timing.request_to_answer_ms) ? `；至本轮答复完成 ${(entry.timing.request_to_answer_ms / 1000).toFixed(2)} 秒` : ''}。`));
    if(Number.isFinite(entry.timing?.request_acceptance_ms)) body.append(make('p','',`服务受理回执 ${(entry.timing.request_acceptance_ms/1000).toFixed(2)} 秒；它记录收到消息与排队情况，正文回复耗时另计。`));
    const reasonLabels = { no_learning_record: "缺少学习追溯记录", page_lineage_untracked: "该页未建立追溯", source_lineage_untracked: "未记录来源关系",
      source_version_changed: "来源版本已变化", source_missing: "来源缺失", source_unavailable_or_conflicting: "来源不可用或有冲突",
      source_check_time_unknown: "来源核查日期未知", source_review_due: "来源已到复核期", source_freshness_not_verified: "来源核查记录需要复核",
      page_version_mismatch: "页面版本与追溯快照不一致", page_changed_after_learning: "页面在学习后被修改",
      knowledge_metadata_unavailable: "知识追溯元数据不可用", knowledge_metadata_invalid: "知识追溯元数据无效",
      full_page_hash_unavailable: "未取得整页哈希", full_page_hash_size_limit: "整页超过哈希读取大小限制", page_changed_during_read: "读取时页面发生变化" };
    for (const check of checks) {
      const owner = typeof check.agent_id === "string" ? check.agent_id : entry.agent_id;
      const phase = ({ execute: "处理", summary: "汇总", plan: "规划" })[check.phase] || "";
      const status = ({ valid: "引用路径匹配", invalid: "存在未匹配的引用", no_citations: "未检测到引用标记" })[check.status] || "引用核对状态未记录";
      const section = make("section", "ag-wiki-citation-check");
      section.append(make("h4", "", `${owner ? agentName(owner) : "未记录 Agent"}${phase ? ` · ${phase}` : ""} · ${status}`));
      section.append(make("p", "", `引用标记 ${count(check.citation_count)} 个 · 未匹配 ${count(check.invalid_count)} 个`));
      const invalid = Array.isArray(check.citations) ? check.citations.filter((item) => item && item.valid === false && typeof item.path === "string") : [];
      for (const citation of invalid) section.append(make("p", "ag-wiki-read-warning", `未匹配本轮可引用的正文：${citation.path}`));
      for (const mention of Array.isArray(check.path_mentions) ? check.path_mentions : []) if (mention.valid === false) section.append(make('p', 'ag-wiki-read-warning', `未提供正文却声称已读：${mention.path}`));
      body.append(section);
    }
    for (const read of reads) {
      const owner = typeof read.agent_id === "string" ? read.agent_id : entry.agent_id;
      const status = Object.hasOwn(labels, read.knowledge_status) ? read.knowledge_status : "untracked";
      const section = make("section", "ag-wiki-read-group");
      section.append(make("h4", "", `${owner ? agentName(owner) : "未记录 Agent"} · ${read.path} · ${labels[status]}`));
      if (supplied) {
        const inputs = supplied.filter(item => item.path === read.path);
        section.append(make('p', inputs.length ? '' : 'ag-wiki-read-warning', inputs.length ? '预算后已提供正文摘录。' : '宿主预读过，但预算后未提供正文，不能用于本轮引用。'));
        for (const input of inputs) if (typeof input.excerpt_sha256 === 'string') section.append(make('p', 'ag-template-read-hash', `实际输入摘录 SHA-256：${input.excerpt_sha256}${input.truncated ? ' · 片段已裁剪' : ''}`));
      }
      if (typeof read.citation_label === "string") section.append(make("p", "", `引用标记：${read.citation_label}`));
      section.append(make("p", "ag-template-read-hash", `页面 ID：${read.page_id || "未记录"}`), make("p", "ag-template-read-hash", `完整页面 SHA-256：${read.page_version || "未取得"}`));
      if (typeof read.sha256 === "string" && read.sha256) section.append(make("p", "ag-template-read-hash", `读取回执 SHA-256：${read.sha256}${read.hash_scope ? ` · ${read.hash_scope}` : ""}`));
      if (read.truncated === true) section.append(make("p", "ag-wiki-read-warning", "本轮提供的是页面摘录，不能据此声称已读全文。"));
      const reasons = Array.isArray(read.reasons) ? read.reasons.filter((value) => typeof value === "string").map((value) => Object.hasOwn(reasonLabels, value) ? reasonLabels[value] : value) : [];
      if (reasons.length) section.append(make("p", "", `状态原因：${reasons.join("；")}`));
      const sources = Array.isArray(read.sources) ? read.sources.filter((item) => item && typeof item === "object" && !Array.isArray(item)) : [];
      if (sources.length) {
        section.append(make("p", "", `已记录的学习输入来源 · ${sources.length}`));
        const list = make("ul");
        for (const source of sources) {
          const row = make("li"), url = publicSourceURL(source.url), label = make(url ? "a" : "span", url ? "ag-learning-source-title" : "", source.name || source.source_id || "来源");
          if (url) { label.href = url; label.target = "_blank"; label.rel = "noopener noreferrer"; }
          row.append(label); list.append(row);
        }
        section.append(list);
      } else section.append(make("p", "", "此读取记录没有可展示的来源关系。"));
      const claims = Array.isArray(read.claims) ? read.claims.filter(c => c && typeof c.text === 'string') : [];
      for (const claim of claims) {
        const block = make('details', 'ag-task-section');
        block.append(make('summary', '', `结论原文依据 · ${({pending:'含义待核对',approved:'用户已核对',rejected:'已否定'})[claim.semantic_review] || '未核对'} · ${({current:'版本一致',review_due:'需复查',stale:'来源已变化'})[claim.status] || '未追溯'}`));
        block.append(make('p', '', claim.text));
        for (const ref of Array.isArray(claim.references) ? claim.references : []) {
          if (!ref || typeof ref.quote !== 'string') continue;
          const url = publicSourceURL(ref.url), link = make(url ? 'a' : 'span', '', ref.title || '原文');
          if (url) {link.href=url;link.target='_blank';link.rel='noopener noreferrer';}
          block.append(link, make('blockquote', '', ref.quote), make('p', 'ag-skill-read-note', `原文第 ${ref.start_line || '?'} 行 · ${ref.freshness === 'online_checked' ? '已比对网页正文' : '本地归档；网页时效另行复查'}${ref.quote_truncated ? ' · 片段已截短' : ''}`));
        }
        section.append(block);
      }
      body.append(section);
    }
    body.append(make("p", "ag-skill-read-note", supplied ? "引用路径只认模型实际收到的正文。结论核对是辅助判定，未覆盖每条事实，不能代替人工审核。“已记录”只表示版本记录一致；run_inputs 只代表学习输入。" : "引用核对只检查标记是否匹配本轮已记录的预读路径，不评判事实正确、语义支持或每条结论是否都有引用。“已记录”只表示版本记录一致；run_inputs 只代表学习输入。完整追溯可在“知识库操作 → 知识状态”查看。"));
    details.append(body); return details;
  }
  function renderResearchReceipt(entry, key) {
    const receipt = entry.research;
    if (!receipt || typeof receipt !== "object" || Array.isArray(receipt)) return null;
    const sources = Array.isArray(receipt.sources) ? receipt.sources.filter((source) => source && typeof source === "object" && !Array.isArray(source) && (typeof source.url === "string" || typeof source.title === "string")) : [];
    const errors = Array.isArray(receipt.errors) ? receipt.errors.filter((error) => typeof error === "string" || error && typeof error === "object" && !Array.isArray(error)) : [];
    if (typeof receipt.status !== "string" && !sources.length && !errors.length && !receipt.note) return null;
    const query = entry.research_only === true || entry.phase === "consultation";
    const labels = { completed: sources.length ? "公开资料读取完成" : "未成功读取资料", partial: sources.length ? "部分资料读取成功" : "未成功读取资料", unavailable: "未成功读取资料", not_researched: query ? "未取得查询资料" : "未进行联网调研" };
    const searchLabels = { not_configured: "未配置搜索服务", no_results: "未找到查询结果", failed: "查询服务调用失败" };
    const status = !sources.length && Object.hasOwn(searchLabels, receipt.search_status) ? searchLabels[receipt.search_status] : Object.hasOwn(labels, receipt.status) ? labels[receipt.status] : query ? "查询状态未确认" : "调研状态未确认";
    const details = make("details", "ag-task-section ag-template-reads ag-research-receipt"), summary = make("summary", "ag-task-section-title", query ? "本轮联网查询" : "本轮调研来源");
    summary.dataset.taskKey = `${key}:research`;
    summary.append(make("span", "ag-research-state", ` · ${status} · ${sources.length} 项来源`));
    details.append(summary); rememberDetails(details, `${key}:research`);
    const body = make("div", "ag-template-reads-body");
    if (typeof receipt.note === "string" && receipt.note) body.append(make("p", "ag-research-note", receipt.note));
    if (typeof receipt.query === "string" && receipt.query) body.append(make("p", "ag-research-note", `查询内容：${receipt.query}`));
    if (typeof receipt.run_id === "string" && receipt.run_id) body.append(make("p", "ag-template-read-hash", `${query ? "查询" : "调研"}记录 ID：${receipt.run_id}`));
    if (sources.length) {
      const list = make("ul", "ag-research-sources");
      for (const [index, source] of sources.entries()) {
        const row = make("li"), url = publicSourceURL(source.url);
        row.append(make("strong", "ag-learning-source-title", source.title || "已记录的公开资料"));
        if (typeof source.url === "string" && source.url) {
          const link = make(url ? "a" : "span", "ag-research-url", url || source.url);
          if (url) { link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer"; }
          row.append(link);
        }
        if (source.fetched_at) row.append(make("span", "ag-research-time", `读取时间：${date(source.fetched_at)}`));
        if (source.truncated === true) row.append(make("span", "ag-research-time", query ? "本次回答依据的是网页摘录，不能视为已阅读全文。" : "提供给方案的是截断摘录，不能据此声称模型读过全文。"));
        const fields = [["正文 SHA-256", source.sha256], ["摘录 SHA-256", source.excerpt_sha256], ["记录文件", source.path]].filter(([, value]) => typeof value === "string" && value);
        if (fields.length) {
          const hashes = make("details", "ag-task-section ag-research-hashes"), heading = make("summary", "ag-task-section-title", "查看正文与摘录校验记录");
          heading.dataset.taskKey = `${key}:research:${index}:hashes`; hashes.append(heading); rememberDetails(hashes, `${key}:research:${index}:hashes`);
          for (const [label, value] of fields) hashes.append(make("p", "ag-template-read-hash", `${label}：${value}`));
          row.append(hashes);
        }
        list.append(row);
      }
      body.append(list);
    } else body.append(make("p", "ag-research-note", "本轮没有成功读取并记录的网页来源。"));
    if (errors.length) {
      body.append(make("h4", "ag-learning-receipt-error", "未成功读取的资料"));
      const list = make("ul", "ag-learning-receipt-error");
      for (const error of errors) {
        const row = make("li");
        if (typeof error === "string") row.textContent = error;
        else {
          if (typeof error.url === "string" && error.url) row.append(make("span", "ag-research-url", error.url));
          row.append(make("span", "", typeof error.error === "string" ? error.error : "未记录具体错误"));
        }
        list.append(row);
      }
      body.append(list);
    }
    body.append(make("p", "ag-skill-read-note", query ? "本轮仅查询公开资料，没有写入知识库。回答中的结论仍需结合所列来源核对；没有成功读取的资料不会列为已查阅。" : "以上来自本轮系统调研回执；网页读取成功不代表方案每条结论都获得支持，也不代表完成用户访谈或市场调研。模型正文里的来源描述不能替代这份回执。"));
    details.append(body); return details;
  }
  function renderLearningReceipt(task, key) {
    const receipt = task.web_learning;
    if (task.kind !== "web_learning" || !receipt || typeof receipt !== "object" || Array.isArray(receipt)) return null;
    const section = make("details", "ag-task-section ag-learning-receipt");
    section.append(make("summary", "ag-task-section-title", "学习来源、知识与模板变化"));
    rememberDetails(section, `${key}:web-learning`);
    const body = make("div", "ag-learning-receipt-body");
    const labels = { planning: "自主规划检索主题", collecting: "正在发现和采集资料", learning: "正在整理本库知识", completed: "本库学习已完成", unchanged: "本轮未发现新增变化", failed: "本轮学习未完整完成" };
    body.append(make("p", "ag-learning-receipt-status", labels[receipt.status] || "学习状态待确认"));
    if (typeof receipt.provider === "string" && receipt.provider) body.append(make("p", "ag-learning-receipt-note", `资料发现：${({ "official-sites": "公开官方资料", tavily: "Tavily 网络搜索" })[receipt.provider] || receipt.provider}`));
    const queries = Array.isArray(receipt.queries) ? receipt.queries.filter((item) => typeof item === "string") : [];
    if (queries.length) {
      body.append(make("h4", "", "自主检索主题"));
      const list = make("ul"); queries.forEach((query) => list.append(make("li", "", query))); body.append(list);
    }
    const sources = Array.isArray(receipt.sources) ? receipt.sources.filter((item) => item && typeof item === "object") : [];
    if (sources.length) {
      body.append(make("h4", "", `已记录来源 · ${sources.length}`));
      const list = make("ul", "ag-learning-sources");
      for (const source of sources) {
        const item = make("li"), url = publicSourceURL(source.url);
        const title = typeof source.title === "string" && source.title.trim() ? source.title : typeof source.url === "string" ? source.url : "来源";
        const label = make(url ? "a" : "span", "ag-learning-source-title", title);
        if (url) { label.href = url; label.target = "_blank"; label.rel = "noopener noreferrer"; label.title = url; }
        item.append(label);
        const sourceStatus = { new: "新增来源", updated: "来源已更新", unchanged: "来源未变化" }[source.status];
        if (sourceStatus) item.append(make("span", "ag-learning-source-state", sourceStatus));
        if (typeof source.filename === "string" && source.filename) item.append(make("span", "ag-learning-source-file", source.filename));
        list.append(item);
      }
      body.append(list);
    }
    const changes = Array.isArray(receipt.changed_pages) ? receipt.changed_pages.filter((item) => item && typeof item.path === "string") : [];
    if (changes.length) {
      body.append(make("h4", "", `知识文件变化 · ${changes.length}`));
      const list = make("ul", "ag-learning-changes");
      for (const change of changes) list.append(make("li", "", `${({ new: "新增", updated: "更新", removed: "移除" })[change.change] || "变化"} · ${change.path}`));
      body.append(list);
    } else if (["completed", "unchanged"].includes(receipt.status)) body.append(make("p", "", "本轮没有记录到知识文件变化。"));
    const templates = Array.isArray(receipt.templates) ? receipt.templates.filter((item) => item && typeof item === "object") : [];
    if (templates.length) {
      body.append(make("h4", "", `规范与模板维护 · ${templates.length}`));
      const list = make("ul", "ag-learning-templates");
      for (const item of templates) {
        const status = ({ new: "新增", created: "新增", installed: "已保存", ready: "已保存", updated: "已更新", unchanged: "版本未变化", conflict: "存在冲突，保留原版本", failed: "维护未完成" })[item.status] || item.status || "状态未记录";
        const row = make("li", ["conflict", "failed"].includes(item.status) ? "ag-learning-receipt-error" : "", `${item.name || item.id || item.framework || "模板"} · ${status}${item.source_version || item.version ? ` · ${item.source_version || item.version}` : ""}${item.upstream_commit ? ` · ${String(item.upstream_commit).slice(0, 12)}` : ""}`);
        if (typeof item.error === "string" && item.error) row.append(make("span", "ag-learning-source-file ag-learning-receipt-error", item.error));
        list.append(row);
      }
      body.append(list);
    }
    const templateErrors = Array.isArray(receipt.template_errors) ? receipt.template_errors : [];
    if (templateErrors.length) {
      body.append(make("h4", "ag-learning-receipt-error", "模板维护未完成"));
      const list = make("ul", "ag-learning-receipt-error");
      for (const error of templateErrors) list.append(make("li", "", typeof error === "string" ? error : error && typeof error === "object" ? `${error.id ? `${error.id} · ` : ""}${error.error || error.message || error.code || JSON.stringify(error)}` : String(error)));
      body.append(list);
    }
    const errors = Array.isArray(receipt.errors) ? receipt.errors.map((item) => typeof item === "string" ? item : JSON.stringify(item)) : [];
    if (typeof receipt.error === "string" && receipt.error && !errors.includes(receipt.error)) errors.push(receipt.error);
    if (errors.length) {
      body.append(make("h4", "ag-learning-receipt-error", "未完成与跳过说明"));
      const list = make("ul", "ag-learning-receipt-error"); errors.forEach((error) => list.append(make("li", "", error))); body.append(list);
    }
    if (typeof receipt.notice === "string" && receipt.notice) body.append(make("p", "ag-learning-receipt-note", receipt.notice));
    body.append(make("p", "ag-learning-receipt-note", "以上按执行回执展示；知识草稿保存在本 Agent，中央采用仍需审核发布。"));
    section.append(body); return section;
  }
  function renderDelegations(room, roundId) {
    const tasks = (room.delegations || []).filter((task) => task.round_id === roundId && task.id);
    if (!tasks.length) return null;
    const panel = make("details", "ag-delegations");
    panel.setAttribute("aria-label", "本轮分工详情"); panel.dataset.roundId = roundId;
    const heading = make("summary", "ag-delegations-heading"), counts = [];
    heading.dataset.taskKey = `${room.id}:${roundId}:delegations`;
    rememberDetails(panel, `${room.id}:${roundId}:delegations`);
    const done = tasks.filter((task) => task.status === "completed").length;
    const running = tasks.filter((task) => task.status === "running").length;
    const failed = tasks.filter((task) => task.status === "failed").length;
    if (done) counts.push(`${done} 项完成`);
    if (running) counts.push(`${running} 项进行中`);
    if (failed) counts.push(`${failed} 项未完成`);
    heading.append(make("strong", "", tasks.some((task) => task.kind === "web_learning") ? "分工详情 · 自主学习" : "分工详情"), make("span", "", counts.join(" · ") || "任务已下发，等待处理"));
    panel.append(heading);
    const ids = new Set(tasks.map((task) => task.id)), seen = new Set();
    function taskNode(task, level = 0) {
      if (seen.has(task.id)) return null;
      seen.add(task.id);
      const children = tasks.filter((child) => child.parent_task_id === task.id && child.id !== task.id);
      const status = ["queued", "running", "completed", "failed"].includes(task.status) ? task.status : "unknown";
      const details = make("details", `ag-task ag-task-${status}`), key = `${room.id}:${task.id}`;
      const summary = make("summary", "ag-task-heading"); summary.dataset.taskKey = key;
      const owner = make("span", "ag-task-owner", task.agent_id === "central" ? "主 Agent" : task.agent_name || agentName(task.agent_id));
      const copy = make("span", "ag-task-copy");
      copy.append(owner, make("span", "ag-task-title", task.title || "知识任务"));
      summary.append(copy, make("span", "ag-task-status", taskStatus(task, children.length)));
      if (children.length) summary.append(make("span", "ag-task-child-count", `${children.length} 个子任务`));
      details.append(summary); rememberDetails(details, key, level === 0);
      const body = make("div", "ag-task-body");
      function appendText(label, value, kind) {
        if (typeof value !== "string" || !value.trim()) return;
        const section = make("details", `ag-task-section ag-task-${kind}`);
        const title = make("summary", "ag-task-section-title", label);
        section.append(title, kind === "error" ? make("div", "ag-task-text", value) : markdownBody(value, "ag-task-text"));
        rememberDetails(section, `${key}:${kind}`, kind === "error" && task.status === "failed");
        body.append(section);
      }
      appendText("交办任务", task.instruction, "instruction");
      const childList = make("div", "ag-task-children");
      for (const child of children) { const node = taskNode(child, level + 1); if (node) childList.append(node); }
      if (childList.childElementCount) body.append(childList);
      const operations=renderOperations(task,key,{inline:true});
      if (operations) body.append(operations);
      appendText(task.phase === "plan" ? "回答结果" : task.phase === "summary" ? "汇总结果" : "处理结果", task.result, "result");
      appendText("未完成原因", task.error, "error");
      details.append(body); return details;
    }
    for (const task of tasks.filter((entry) => !entry.parent_task_id || !ids.has(entry.parent_task_id))) {
      const node = taskNode(task); if (node) panel.append(node);
    }
    // Preserve an inspectable record even if an older room has incomplete parent references.
    for (const task of tasks) { const node = taskNode(task); if (node) panel.append(node); }
    return panel;
  }
  function renderProgressMessage(message, room) {
    const kind = message.event_kind;
    if (message.role !== "system" || message.event_origin !== "host" || !["group_started", "member_joined", "delegation", "work_started", "error"].includes(kind)) return null;
    const task = (room.delegations || []).find((item) => item.id === message.delegation_task_id);
    const actorId = message.actor_agent_id || message.agent_id;
    const actorName = actorId === "central" ? "主 Agent" : actorId ? agentName(actorId) : "执行系统";
    const recipientId = message.recipient_agent_id || (kind === "delegation" ? task?.agent_id : null);
    const recipient = recipientId === "central" ? "主 Agent" : recipientId ? agentName(recipientId) : "接收人未记录";
    const card = make("article", `ag-progress-card ag-progress-${kind}`), header = make("div", "ag-progress-heading");
    card.dataset.messageId = message.id || "";
    const workLabel = ({ plan: "分析分工", summary: "开始汇总" })[message.phase] || "开始处理";
    header.append(make("strong", "", kind === "delegation" ? `${actorName} → ${recipient}` : kind === "member_joined" && recipientId ? `${actorName} 邀请 ${recipient}` : actorName), make("span", "ag-progress-kind", ({ group_started: "已创建任务群", member_joined: "加入任务群", delegation: "分派任务", work_started: workLabel, error: "未完成" })[kind]));
    header.append(make("span", "ag-progress-origin", "系统执行记录"));
    if (message.created_at) header.append(make("time", "", date(message.created_at)));
    card.append(header);
    const text = typeof message.content === "string" && message.content ? message.content : kind === "delegation" && typeof task?.instruction === "string" ? task.instruction : "";
    if (text) card.append(kind === "delegation" ? markdownBody(text, "ag-progress-text") : make("p", "ag-progress-text", text));
    return card;
  }
  function renderReportArtifacts(message) {
    const artifacts = Array.isArray(message.artifacts) ? message.artifacts : [];
    const links = make('div', 'ag-report-downloads');
    for (const artifact of artifacts) {
      if (artifact?.kind==='image' && artifact.generated===true && artifact.source_url &&
          /^[a-f0-9]{32}$/.test(artifact.id || '') && /^[a-f0-9]{32}$/.test(artifact.room_id || '') &&
          artifact.url===`/api/chat/rooms/${artifact.room_id}/files/${artifact.id}` &&
          artifact.room_id===(message.room_id || state.room?.id || state.roomId)) {
        const capture=make('details','ag-browser-capture');
        const size=artifact.viewport?.width===390?'手机':'桌面';
        const source=publicSourceURL(artifact.source_url), path=source?new URL(source).pathname.slice(0,90):'';
        capture.append(make('summary','ag-browser-caption',`网页截图 · ${size} · ${path}${artifact.scroll_y>0?' · 滚动 '+artifact.scroll_y:''}`));
        const image=make('img','ag-browser-image');image.src=artifact.url;image.alt='实际浏览器网页截图';image.loading='lazy';
        capture.append(image);
        const open=make('a','ag-report-download','打开截图');open.href=artifact.url;open.target='_blank';open.rel='noopener noreferrer';capture.append(open);
        if(source){const link=make('a','ag-browser-source','原网页 ↗');link.href=source;link.target='_blank';link.rel='noopener noreferrer';capture.append(link);}
        links.append(capture);continue;
      }
      if (!artifact || !['md', 'docx'].includes(artifact.format) ||
          typeof artifact.url !== 'string' || !/^\/api\/reports\/[a-f0-9]{32}\/(?:md|docx)$/.test(artifact.url) ||
          !artifact.url.endsWith('/' + artifact.format)) continue;
      const link = make('a', 'ag-report-download', artifact.format === 'docx' ? '下载 Word 文档' : '下载 Markdown');
      link.href = artifact.url; link.download = artifact.filename || ('产品分析报告.' + artifact.format);
      links.append(link);
    }
    if (message.artifact_error) links.append(make('p', 'ag-research-note', message.artifact_error));
    return links.childNodes.length ? links : null;
  }
  function validInterimReplies(value) {
    if (!Array.isArray(value)) return [];
    return value.slice(0, 8).filter(item => item && typeof item.id === 'string' && /^[a-z0-9-]{1,32}$/.test(item.id)
      && !/(?:^|-)(?:before-check|first-evidence)$/.test(item.id)
      && typeof item.title === 'string' && item.title.length <= 100 && typeof item.text === 'string' && item.text.length <= 40000 && item.text.trim());
  }
  function renderInterimReplies(message) {
    if (isNativeReply(message)) return null;
    const updates = validInterimReplies(message.interim_replies).filter(update =>
      !(message.reply_parts || []).some(part => part.text.trim() === update.text.trim()));
    if (!updates.length) return null;
    const details = make('details', 'ag-task-section ag-interim-history'), summary = make('summary', 'ag-task-section-title', '查看处理过程中先发的回答');
    summary.dataset.taskKey = `${message.reply_key || message.id}:interim`; rememberDetails(details, summary.dataset.taskKey);
    details.append(summary, make('p', 'ag-research-note', '这里保留先发的回应、依据与分析草稿。请以本轮最终回复为准，辅助核对仍需人工判断。'));
    for (const update of updates) {
      details.append(make('h4', '', update.title), markdownBody(update.text, 'ag-message-text'));
    }
    return details;
  }
  function mergeReplyMessages(messages, room = {}) {
    // This is a view of the recorded messages. Never rewrite the room's history.
    const displayed = [], pending = new Map();
    for (const original of messages) {
      if (original.role === 'user') pending.clear();
      if (original.role !== 'assistant' || !original.round_id || !original.agent_id) { displayed.push(original); continue; }
      const key = JSON.stringify([original.round_id, original.agent_id, original.delegation_task_id || '']);
      const staged = ['acknowledgement', 'interim'].includes(original.phase);
      let pendingKey = key;
      if (!pending.has(key) && original.agent_id !== 'central' && room.mode === 'orchestrated'
          && !original.delegation_task_id && original.event_kind !== 'result'
          && (['consultation', 'interim'].includes(original.phase) || original.status === 'streaming')
          && !(room.task_groups || []).some(group => (group.round_id || group.id) === original.round_id)
          && !(room.delegations || []).some(task => task.round_id === original.round_id)) {
        const accepted = JSON.stringify([original.round_id, 'central', '']);
        if (pending.has(accepted) && displayed[pending.get(accepted).index].phase === 'acknowledgement') pendingKey = accepted;
      }
      const previous = pending.get(pendingKey);
      const message = { ...original, reply_key: key };
      if (previous) {
        const earlier = displayed[previous.index];
        message.created_at = earlier.created_at || message.created_at;
        message.acceptance_reply = message.acceptance_reply || earlier.acceptance_reply;
        if (earlier.phase === 'acknowledgement') message.acceptance_reply = { text: earlier.content };
        const updates = [...validInterimReplies(earlier.interim_replies), ...validInterimReplies(message.interim_replies)];
        if (earlier.phase === 'interim') updates.push(...validInterimReplies([{ id: earlier.interim_id || earlier.id,
          title: earlier.interim_title || '先前的回答', text: earlier.content, status: 'completed', created_at: earlier.created_at }]));
        const seen = new Set();
        message.interim_replies = updates.filter(update => {
          const text = update.text.trim();
          if (text === message.content?.trim() || seen.has(text)) return false;
          seen.add(text); return true;
        }).slice(-8);
        displayed[previous.index] = message;
      }
      if (message.phase === 'interim' || message.status === 'streaming') {
        const parts = validInterimReplies(message.interim_replies)
          .filter(update => message.phase === 'interim' || !update.id.endsWith('before-check'));
        parts.push({ id: message.interim_id || 'current', title: message.interim_title || '继续补充', text: message.content || '' });
        message.reply_parts = parts.filter((part, index) => !parts.slice(index + 1).some(next =>
          next.text.trim() === part.text.trim() || (next.id.endsWith('before-check') && next.text.includes(part.text))));
      }
      if (!previous) displayed.push(message);
      if (pendingKey !== key) pending.delete(pendingKey);
      if (staged) pending.set(key, { index: previous ? previous.index : displayed.length - 1 });
      else pending.delete(key); // Distinct completed member/task replies stay distinct.
    }
    return displayed;
  }
  function questionLanguage(value, fallback = 'zh') {
    // UI status text follows the user's request, never retrieved source text.
    const text=String(value || '').replace(/```[\s\S]*?(?:```|$)|`[^`]*`|https?:\/\/\S+|^>.*$/gm,'')
      .replace(/[“「][\s\S]*?[”」]|"[^"\n]*"/g,'');
    const explicit=[...text.matchAll(/(?:用|使用|请以|改为|改用)\s*(中文|英文|英语)|(?:answer|reply|respond|translate|write)[^.!?。！？\n]{0,50}?\b(?:in|into|to)\s+(English|Chinese|Mandarin)\b/giu)].at(-1);
    if(explicit && !/(?:不要|不用|别|not|don't)\s*$/iu.test(text.slice(Math.max(0,explicit.index-8),explicit.index)))
      return /英文|英语|English/i.test(explicit[1] || explicit[2])?'en':'zh';
    const han=(text.match(/[\u3400-\u9fff]/g) || []).length, words=(text.match(/[a-z]+(?:'[a-z]+)?/gi) || []).length;
    if(han>0)return han<=2 && words>=3?'en':'zh';
    return words?'en':fallback;
  }
  function turnLanguage(room) {
    let language='zh';
    for(const message of room?.messages || [])if(message.role==='user')language=questionLanguage(message.content,language);
    return language;
  }
  function conversationMessages(room) {
    const messages = [...(room.messages || [])].filter(message=>!(room.live_reply?.native_protocol && active(room.status)
      && message.phase==='acknowledgement' && message.round_id===room.active_job_id)), submission = state.submissions?.get(room.id);
    if (submission && !active(room.status)) {
      messages.push({id:'submitting-user-'+submission.id,role:'user',content:submission.content,created_at:submission.created_at});
    }
    for (const pending of state.unconfirmed?.get(room.id) || []) {
      const received = (room.messages || []).some(message => message.role === 'user' && message.content === pending.content
        && !(pending.known_message_ids || []).includes(message.id));
      if (!received) messages.push({id:'unconfirmed-user-'+pending.id,role:'user',content:pending.content,
        created_at:pending.created_at,send_unconfirmed:true});
    }
    const live = room.live_reply;
    if (active(room.status) && room.active_job_id && live?.job_id === room.active_job_id) {
      const persisted = messages.some(message => message.stream_turn_id && message.stream_turn_id === live.turn_id);
      if (!persisted) {
        if (live.native_protocol) {
          if (live.text || validInterimReplies(live.updates).length || replyOperations(live).length || live.context_compaction || live.processing_stage) messages.push({
            id:`live-${room.active_job_id}-${live.agent_id || 'central'}`,role:'assistant',
            agent_id:live.agent_id || 'central',round_id:room.active_job_id,agent_name:live.agent_name,
            content:live.text,status:'streaming',created_at:live.received_at,
            native_protocol:live.native_protocol,interim_replies:validInterimReplies(live.updates),
            operations:live.operations,
            context_compaction:live.context_compaction,
            processing_stage:live.processing_stage,
            reply_timeline:live.timeline,
          });
        } else {
        for (const update of validInterimReplies(live.updates)) messages.push({
          id:`live-${room.active_job_id}-update-${update.id}`,role:'assistant',agent_id:live.agent_id || 'central',round_id:room.active_job_id,
          agent_name:live.agent_name,content:update.text,phase:'interim',interim_id:update.id,interim_title:update.title,
          status:update.status==='completed'?'draft':'streaming',created_at:update.created_at,
        });
        const archivedDraft = validInterimReplies(live.updates).some(update => update.id.endsWith('before-check') && update.text.trim() === live.text?.trim());
        if (!archivedDraft && live.text) messages.push({id:`live-${room.active_job_id}-${live.agent_id || 'central'}`,role:'assistant',
          agent_id:live.agent_id || 'central',round_id:room.active_job_id,agent_name:live.agent_name,content:live.text,status:'streaming',created_at:live.received_at});
        }
      }
    }
    const displayed = mergeReplyMessages(messages, room).filter(message => message.phase !== 'acknowledgement');
    if ((active(room.status) && room.active_job_id) || submission || state.sending?.has(room.id)) {
      const roundId = active(room.status) && room.active_job_id ? room.active_job_id : `submitting-${submission?.id || room.id}`;
      if (!displayed.some(message => message.role === 'assistant' && message.round_id === roundId)) {
        const currentAgent = state.agents?.find(item => item.id === room.current_agent || item.name === room.current_agent);
        const agentId = live && live.job_id === roundId ? live.agent_id || 'central' : currentAgent?.id || 'central';
        displayed.push({id:`loading-${roundId}`,role:'assistant',agent_id:agentId,round_id:roundId,
          reply_key:JSON.stringify([roundId,agentId,'']),phase:'loading',status:'streaming',content:'',
          processing_stage:live?.processing_stage,
          response_origin:submission?.intent==='status'?'host_video_status':undefined,
          loading_label:submission?(submission.loading_label || '正在发送'):room.status==='queued'?'等待回复':'正在回复'});
      }
    }
    const byRound=new Map(),byMessage=new Map();let language='zh';
    for(const message of messages) {
      if(message.role==='user') {
        language=questionLanguage(message.content,language);
        if(message.round_id)byRound.set(message.round_id,language);
      }
      byMessage.set(message.id,language);
    }
    return displayed.map(message=>({...message,reply_language:byRound.get(message.round_id) || byMessage.get(message.id) || language}));
  }
  function processingLabel(stage, english=false) {
    const labels={using_tool:['正在使用工具','Using tools'],checking_sources:['正在查阅资料','Reading sources'],checking_calculation:['正在核对计算','Checking calculations'],reviewing_analysis:['正在检查报告','Reviewing report'],exporting_report:['正在生成文件','Preparing files'],reading_sources:['正在查阅资料','Reading sources'],composing_answer:['正在整理回答','Preparing answer'],
      writing_analysis:['正在整理回答','Preparing answer'],checking_evidence:['正在核对依据','Checking sources'],
      waiting_model:['模型响应较慢，仍在等待','The model is taking longer; still waiting'],reconnecting:['连接暂时不可用，正在自动重试','Connection unavailable; retrying automatically'],
      answer_ready:['回答已就绪','Answer ready']};
    return labels[stage]?.[english?1:0] || '';
  }
  function replyStageLabel(message) {
    if (isNativeReply(message)) return '';
    if (message.phase === 'loading' || message.phase === 'acknowledgement') return '';
    if(message.reply_language==='en')return message.phase==='submission'?'Sending':message.phase==='interim'?message.status==='streaming'?'Writing':'Draft response':message.status==='streaming'?'Replying':'';
    if (message.phase === 'submission') return '本机先回应 · 等待服务确认';
    if (message.phase === 'interim') return `${message.interim_title} · ${message.status === 'streaming' ? '正在写' : '先给你这部分'} · 待校对`;
    return message.status === 'streaming' ? '正在补充' : '';
  }
  function operationTarget(name, value) {
    if (typeof value !== 'string') return '';
    if (['web_read','visual_browser'].includes(name)) {
      const safe=publicSourceURL(value); if (!safe) return '';
      const url=new URL(safe); return (url.origin+url.pathname).slice(0,180);
    }
    if (['wiki_search','web_search'].includes(name)) return value
      .replace(/(?:bearer\s+\S+|(?:api[_-]?key|token|password|secret|authorization)\s*[:=]\s*\S+)/gi,'[已隐藏]')
      .replace(/[\u0000-\u001f\u007f]/g,' ').slice(0,180);
    return '';
  }
  function operationReadFailure(message, raw) {
    if (!['web_read','visual_browser'].includes(raw.name || raw.tool) || ['completed','partial','running'].includes(raw.status)) return '';
    const codes=['robots_blocked','robots_check_failed','login_required','access_restricted','rate_limited','article_http_error','no_readable_body','read_timeout','network_error'];
    const receipts=Array.isArray(message.workflow?.receipts)?message.workflow.receipts:[], index=receipts.findIndex(item=>item===raw || raw.call_id && item.call_id===raw.call_id);
    const result=message.workflow?.observations?.[index]?.result;
    const entries=[result,...(Array.isArray(result?.errors)?result.errors:[])];
    const structured=entries.find(e=>e && codes.includes(e.code));
    if(structured)return structured.code;
    const errors=[result?.error,...(Array.isArray(result?.errors)?result.errors:[]).map(e=>typeof e==='string'?e:e?.error)].filter(e=>typeof e==='string').join('\n');
    // Reclassify historical receipts from their host errors without rewriting history.
    if (/robots(?:\.txt)?[^\n]{0,80}(?:不允许|禁止|disallow)/iu.test(errors)) return 'robots_blocked';
    if (/robots(?:\.txt)?[^\n]*(?:无法确认|检查|异常|HTTP)|无法确认 robots/iu.test(errors)) return 'robots_check_failed';
    const code=raw.failure_code || receipts[index]?.failure_code || raw.status;
    if (codes.includes(code)) return code;
    if (/HTTP\s*401/iu.test(errors) || errors.split('\n').some(error=>
      /(?:必须|请先|需要)登录|requires? (?:a )?login|authentication required/iu.test(error)
      && !/可能|或|\b(?:may|might|could|or)\b/iu.test(error))) return 'login_required';
    if (/HTTP\s*(?:403|429)|forbidden|access denied|拒绝访问|访问被拒绝|请求过于频繁/iu.test(errors)) return 'access_restricted';
    if (/未提取到足够的可读正文|没有读到公开正文|没有可读取的公开浏览页面|正文不足|需要(?:执行)?脚本|javascript.*required/iu.test(errors)) return 'no_readable_body';
    if (/超时|timeout|timed out/iu.test(errors)) return 'read_timeout';
    if (/ENOTFOUND|ECONN|DNS|连接失败|连接中断|网络不可达|certificate|SSL|TLS/iu.test(errors)) return 'network_error';
    if (/HTTP\s*[45]\d\d/iu.test(errors)) return 'article_http_error';
    return '';
  }
  function operationFailureDetail(message, raw, code) {
    if (!['web_read','visual_browser'].includes(raw.name || raw.tool) || ['completed','partial','running'].includes(raw.status)) return '';
    const receipts=message.workflow?.receipts || [], index=receipts.findIndex(item=>item===raw || raw.call_id && item.call_id===raw.call_id);
    const result=message.workflow?.observations?.[index]?.result;
    const entries=[result,...(Array.isArray(result?.errors)?result.errors:[])];
    const item=entries.find(e=>e && typeof e==='object' && e.code===code);
    const errors=[result?.error,...entries.slice(1).map(e=>typeof e==='string'?e:e?.error)].filter(e=>typeof e==='string').join('\n');
    const http=item?.http_status || Number(errors.match(/HTTP\s*(\d{3})/iu)?.[1]);
    const count=Number.isInteger(item?.attempts)?item.attempts:null;
    if(http || count) return [http?'HTTP '+http:'',count?'已尝试 '+count+' 次':'',code==='robots_check_failed'?'尚未请求文章正文':'',item?.retry_after?'请在 '+Math.ceil(item.retry_after)+' 秒后重试':''].filter(Boolean).join(' · ');
    const detail=raw.failure_detail || receipts[index]?.failure_detail;
    return typeof detail==='string'?detail.replace(/[\u0000-\u001f\u007f]/g,' ').replace(/(?:bearer\s+\S+|(?:api[_-]?key|token|password|secret|authorization)\s*[:=]\s*\S+)/gi,'[已隐藏]').slice(0,200):'';
  }
  function replyOperations(message) {
    const allowed=['server_files','wiki_search','web_read','web_search','visual_browser','profit_calculate','file_search','file_read','audio_transcribe','video_analyze','code_interpreter','image_analyze','image_generate','connector_search','connector_read','research_review','result_review'], operations=[];
    const receipts=Array.isArray(message.workflow?.receipts)?message.workflow.receipts:[];
    const stored=Array.isArray(message.operations)?message.operations:[];
    for (const [index,raw] of [...stored,...receipts].slice(0,64).entries()) {
      if (!raw || !allowed.includes(raw.name || raw.tool)) continue;
      const name=raw.name || raw.tool, id=typeof raw.call_id==='string'?raw.call_id.slice(0,200):`receipt-${index}`;
      if (operations.some(item=>item.call_id===id)) continue;
      const status=operationReadFailure(message,raw) || (typeof raw.status==='string'?raw.status:'unknown');
      const value=typeof raw.target==='string'?raw.target:(['web_read','visual_browser'].includes(name)?raw.args?.url:raw.args?.query);
      operations.push({call_id:id,name,target:operationTarget(name,value),failure_detail:operationFailureDetail(message,raw,status),
        status:status==='running' && message.status==='failed'?'interrupted':status,
        elapsed_ms:Number.isInteger(raw.elapsed_ms) && raw.elapsed_ms>=0 && raw.elapsed_ms<=86400000?raw.elapsed_ms:null});
    }
    return operations;
  }
  function validReplyTimeline(value) {
    if (!Array.isArray(value)) return [];
    const result=[];
    for (const entry of value.slice(0,32)) {
      if (!entry || typeof entry!=='object') continue;
      if (entry.kind==='text' && (entry.source==='answer' || entry.source==='update' && /^[a-z0-9-]{1,32}$/.test(entry.id || ''))) {
        const item={kind:'text',source:entry.source,id:entry.source==='answer'?'answer':entry.id};
        if (!result.some(previous=>previous.kind==='text' && previous.source===item.source && previous.id===item.id)) result.push(item);
      } else if (entry.kind==='tools' && typeof entry.id==='string' && entry.id.length<=80 && Array.isArray(entry.call_ids)) {
        const ids=entry.call_ids.slice(0,32).filter(id=>typeof id==='string' && id.length>0 && id.length<=200 && !id.includes('\0')
          && !result.some(previous=>previous.call_ids?.includes(id)));
        if (ids.length) result.push({kind:'tools',id:entry.id,call_ids:[...new Set(ids)]});
      }
    }
    return result;
  }
  function replyTimeline(message) {
    const saved=validReplyTimeline(message.reply_timeline);
    if (saved.length) return saved;
    // Historical Responses events preserve model order. Only execution receipts
    // count as operations; the host executes them after response completion.
    const native=message.native_stream || message.analysis_run?.native_stream;
    if (native?.protocol!=='responses' || !Array.isArray(native.events)) return [];
    const updates=validInterimReplies(message.interim_replies), operations=replyOperations(message), timeline=[], pending=[];
    for (const event of native.events.slice(0,2000)) {
      if (!event || typeof event!=='object') continue;
      if (event.type==='response.output_text.delta') {
        if (event.phase==='final_answer') timeline.push({kind:'text',source:'answer',id:'answer'});
        else if (event.phase==='commentary' && typeof event.update_id==='string') {
          const update=updates.find(item=>item.id===event.update_id || item.id.endsWith('-'+event.update_id));
          if (update) timeline.push({kind:'text',source:'update',id:update.id});
        }
      } else if (event.type==='response.output_item.done' && event.item_type==='function_call'
        && operations.some(item=>item.call_id===event.call_id && item.name===event.name)) pending.push(event.call_id);
      else if (event.type==='response.completed' && pending.length) {
        timeline.push({kind:'tools',id:'recorded-'+timeline.length,call_ids:pending.splice(0)});
      }
      if (timeline.length>1) {
        const a=timeline.at(-1), b=timeline.at(-2);
        if (a.kind==='text' && b.kind==='text' && a.source===b.source && a.id===b.id) timeline.pop();
      }
    }
    return validReplyTimeline(timeline);
  }
  function recordReplyTimeline(reply, event) {
    const timeline=reply.timeline;
    if (event.origin==='host_tool' && ['agent.tool.started','agent.tool.completed'].includes(event.type)) {
      if (timeline.some(item=>item.call_ids?.includes(event.call_id))) return;
      if (timeline.at(-1)?.kind==='tools') timeline.at(-1).call_ids.push(event.call_id);
      else timeline.push({kind:'tools',id:'tools-'+timeline.length,call_ids:[event.call_id]});
    } else if (['response.output_text.delta','chat.completion.content.delta'].includes(event.type) && event.delta) {
      const source=event.phase==='final_answer'?'answer':'update',id=source==='answer'?'answer':event.update_id;
      if (!timeline.some(item=>item.kind==='text' && item.source===source && item.id===id)) timeline.push({kind:'text',source,id});
    }
    reply.timeline=validReplyTimeline(timeline);
  }
  function renderUnplacedOperations(message, key) {
    const placed=new Set(isNativeReply(message)?replyTimeline(message).flatMap(entry=>entry.call_ids || []):[]);
    const remaining=replyOperations(message).filter(item=>!placed.has(item.call_id));
    return renderOperations(message,`${key}:receipts`,{operations:remaining,
      inline:true});
  }
  function renderOperations(message, key, options = {}) {
    const operations=options.operations || replyOperations(message); if (!operations.length) return null;
    const details=make('details','ag-operation-log'), running=operations.filter(item=>item.status==='running').length;
    const names={server_files:'处理服务器文件',wiki_search:'检索知识',web_read:'读取网页',visual_browser:'浏览网页',file_search:'检索附件',file_read:'读取文档',audio_transcribe:'转写音频',video_analyze:'分析视频',code_interpreter:'执行沙箱代码',image_analyze:'读取图片',image_generate:'生成图片',connector_search:'检索第三方资料',connector_read:'读取第三方资料',web_search:'搜索公开资料',profit_calculate:'计算收入、成本与利润',research_review:'核对多来源证据',result_review:'检查任务结果'};
    const statuses={pending_confirmation:'等待确认：',running:'正在',completed:'已',partial:'部分完成：',failed:'失败：',cancelled:'已取消：',interrupted:'已中断：',
      invalid_arguments:'参数校验未通过，未执行：',unknown_object:'对象无效，未执行：',repeated_failure:'重复失败，已停止重试：',duplicate_creation:'已阻止重复创建：',unavailable:'未取得结果：',no_results:'未找到结果：',no_related_results:'未找到相关结果：',blocked:'已阻止：',unknown:'结果待核对：'};
    const failures={robots_blocked:'网站禁止自动读取',robots_check_failed:'robots.txt 检查异常',article_http_error:'文章请求失败',rate_limited:'网站要求暂缓请求',login_required:'文章需要登录',access_restricted:'文章访问受限',
      no_readable_body:'未读到网页正文',read_timeout:'网页读取超时',network_error:'网页连接失败'};
    const english=message.reply_language==='en';
    const englishNames={server_files:['Server files','Reading server files','Read server files'],wiki_search:['Search knowledge','Searching knowledge','Searched knowledge'],web_read:['Read webpage','Reading webpage','Read webpage'],visual_browser:['Browse webpage','Browsing webpage','Browsed webpage'],web_search:['Search public sources','Searching public sources','Searched public sources'],file_search:['Search files','Searching files','Searched files'],file_read:['Read document','Reading document','Read document'],audio_transcribe:['Transcribe audio','Transcribing audio','Transcribed audio'],video_analyze:['Analyze video','Analyzing video','Analyzed video'],code_interpreter:['Run sandboxed code','Running sandboxed code','Ran sandboxed code'],image_analyze:['Read image','Reading image','Read image'],image_generate:['Generate image','Generating image','Generated image'],connector_search:['Search connected sources','Searching connected sources','Searched connected sources'],connector_read:['Read connected source','Reading connected source','Read connected source'],profit_calculate:['Calculate revenue, cost and profit','Calculating revenue, cost and profit','Calculated revenue, cost and profit'],research_review:['Cross-check sources','Cross-checking sources','Cross-checked sources'],result_review:['Review result','Reviewing result','Reviewed result']};
    const englishStatuses={invalid_arguments:'Invalid arguments, not executed',unknown_object:'Invalid object, not executed',repeated_failure:'Repeated failure, retry stopped',duplicate_creation:'Duplicate creation blocked',partial:'Partly completed',failed:'Failed',cancelled:'Cancelled',interrupted:'Interrupted',unavailable:'No result',no_results:'No results',no_related_results:'No relevant results',blocked:'Blocked',unknown:'Result unverified'};
    const englishFailures={robots_check_failed:'robots.txt check failed',article_http_error:'Article request failed',rate_limited:'Website rate limit',robots_blocked:'Website disallows automated access',login_required:'Login required',access_restricted:'Website access restricted',no_readable_body:'No readable page content',read_timeout:'Page read timed out',network_error:'Page connection failed'};
    const actionLabel=operation=>english
      ? englishFailures[operation.status] || (['running','completed'].includes(operation.status)?englishNames[operation.name]?.[operation.status==='running'?1:2]:(englishStatuses[operation.status] || englishStatuses.unknown)+': '+englishNames[operation.name]?.[0])
      : failures[operation.status] || (statuses[operation.status] || statuses.unknown)+names[operation.name];
    const icons={wiki_search:'⌕',web_read:'↗',visual_browser:'▣',web_search:'⌕',profit_calculate:'∑',file_search:'▤',file_read:'▤',audio_transcribe:'♪',video_analyze:'▣',code_interpreter:'⌘',image_analyze:'▧',image_generate:'▧',connector_search:'⌕',connector_read:'▤',research_review:'✓',result_review:'✓'};
    const one=operations[0],label=options.inline && operations.length===1
      ? actionLabel(one)
      : options.inline ? english?`${running?'Using tools':'Tool activity'} · ${operations.length}`:`${running?'正在使用工具':'工具操作'} · ${operations.length} 项`
      : english?`${options.label || 'Tool receipts (order not recorded)'} · ${operations.length}${running?` · ${running} running`:''}`:`${options.label || '操作回执（未记录顺序）'} · ${operations.length} 项${running?` · ${running} 项进行中`:''}`;
    const summary=make('summary','ag-operation-summary',label);
    if(options.inline)details.classList.add('ag-operation-inline');
    details.append(summary); rememberDetails(details,`operations:${key}`);
    const list=make('ol','ag-operation-list');
    for (const operation of operations) {
      const row=make('li','ag-operation-row'); row.dataset.callId=operation.call_id; row.dataset.status=operation.status;
      const icon=make('span','ag-operation-icon',icons[operation.name] || '≡'); icon.setAttribute('aria-hidden','true');
      const text=make('span','ag-operation-text'), action=make('span','ag-operation-action',operation.name==='material_read'
        ? '资料预读：已读取'+operation.label : actionLabel(operation)); text.append(action);
      if (operation.target) text.append(make('span','ag-operation-target',operation.target));
      if (operation.failure_detail) text.append(make('span','ag-operation-detail',operation.failure_detail));
      row.append(icon,text);
      if (operation.elapsed_ms!==null) row.append(make('span','ag-operation-time',(operation.elapsed_ms/1000).toFixed(1)+(english?' s':' 秒')));
      list.append(row);
    }
    details.append(list); return details;
  }
  function renderReplyLoading(label = '正在回复') {
    const loading = make('div', 'ag-reply-loading');
    loading.setAttribute('role', 'status'); loading.setAttribute('aria-label', label);
    const dots = make('span', 'ag-loading-dots'); dots.setAttribute('aria-hidden', 'true');
    for (let i = 0; i < 3; i++) dots.append(make('span'));
    loading.append(dots, make('span', 'ag-loading-label', label)); return loading;
  }
  function contextAdjustment(message) {
    return message?.context_compaction || message?.workflow?.context_compactions?.at(-1) || message?.context_usage?.compactions?.at(-1) || null;
  }
  function renderReplyBody(message) {
    const body = make('div', 'ag-reply-body'), timeline=isNativeReply(message)?replyTimeline(message):[];
    const english=message.reply_language==='en';
    const adjustment=contextAdjustment(message);
    if (adjustment) {
      const notice=make('p','ag-context-compacted',english?adjustment.stage==='runtime'?'Context automatically compacted':'Context prepared':adjustment.stage==='runtime'?'本轮上下文已自动压缩':'本轮上下文已整理');
      notice.title=english?`About ${adjustment.before_tokens?.toLocaleString('en-US')} → ${adjustment.after_tokens?.toLocaleString('en-US')} tokens; original chat history preserved.`:`处理前约 ${adjustment.before_tokens?.toLocaleString('zh-CN')} → 处理后约 ${adjustment.after_tokens?.toLocaleString('zh-CN')} Token；原聊天记录保留。`;
      notice.setAttribute('role','status');body.append(notice);
    }
    const operations=renderUnplacedOperations(message,message.reply_key || message.id);
    if (operations) body.append(operations);
    if (timeline.length) {
      const updates=validInterimReplies(message.interim_replies), operations=replyOperations(message);
      const content=typeof message.content==='string'?message.content:'', key=message.reply_key || message.id;
      const protocol=message.native_protocol || message.native_stream?.protocol;
      if (protocol==='chat_completions' && content && message.status!=='failed' && !timeline.some(item=>item.source==='answer')) {
        const last=timeline.at(-1); if(last?.kind==='text') {last.source='answer';last.id='answer';}
      }
      let pending=[],hasAnswer=false;
      const flush=()=>{if(pending.length){body.append(markdownBody(pending.join('\n\n'),'ag-message-text'));pending=[];}};
      for (const entry of timeline) {
        if (entry.kind==='text') {
          if(entry.source==='answer')hasAnswer=true;
          const text=entry.source==='answer'?content:updates.find(item=>item.id===entry.id)?.text;
          if(typeof text==='string' && text.trim())pending.push(text);
        } else {
          const group=operations.filter(item=>entry.call_ids.includes(item.call_id));
          if(!group.length)continue;
          flush();body.append(renderOperations(message,`${key}:${entry.id}`,{operations:group,inline:true}));
        }
      }
      if(!hasAnswer && content.trim())pending.push(content);
      flush();
    } else if (isNativeReply(message)) {
      const text = typeof message.content === 'string' ? message.content : '';
      const streamed = message.answer_check?.status==='corrected_with_limits' ? [] : validInterimReplies(message.interim_replies).filter(update =>
        /(?:^|-)native-\d+$/.test(update.id) && update.text.trim() !== text.trim());
      body.append(markdownBody([...streamed.map(update=>update.text),text].filter(value=>value.trim()).join('\n\n'),'ag-message-text'));
    } else if (message.reply_parts?.length) {
      for (const part of message.reply_parts) {
        if (message.reply_parts.length > 1) body.append(make('p', 'ag-research-note', part.title));
        const text = markdownBody(part.text, 'ag-message-text'); text.dataset.replyPartId = part.id; body.append(text);
      }
    } else body.append(markdownBody(typeof message.content === 'string' ? message.content : '', 'ag-message-text'));
    if (message.status === 'failed' && message.transport_retry?.status === 'exhausted') {
      const failure = [...body.querySelectorAll('.ag-message-text p')].find(node => node.textContent.includes('自动重连 5 次仍失败'));
      if (failure) { failure.classList.add('ag-failure-text','ag-reconnect-exhausted'); failure.setAttribute('role','alert'); }
      else { const note=make('p','ag-failure-text ag-reconnect-exhausted','自动重连 5 次仍失败，请稍后再试。'); note.setAttribute('role','alert'); body.append(note); }
    }
    if (message.status === 'streaming' && ![...body.querySelectorAll('.ag-message-text')].some(node => node.textContent.trim())) {
      for (const empty of [...body.querySelectorAll('.ag-message-text')]) empty.remove();
      const loading=processingLabel(message.processing_stage?.stage,english) || message.loading_label || '正在回复';
      body.append(renderReplyLoading(english?({'正在发送':'Sending','等待回复':'Waiting for reply','正在回复':'Replying'}[loading] || loading):loading));
    }
    return body;
  }
  function isNativeReply(message) {
    return ['responses','chat_completions'].includes(message.native_protocol || message.native_stream?.protocol || message.analysis_run?.native_stream?.protocol)
      || validInterimReplies(message.interim_replies).some(update=>/(?:^|-)native-\d+$/.test(update.id));
  }
  function renderReportCheck(message) {
    const receipt = message.analysis_run?.assertion_check;
    if (!receipt || receipt.scope !== 'report_actual_sources') return null;
    const details=make('details','ag-task-section'), summary=make('summary','ag-task-section-title','报告结论与原文核对');
    details.append(summary); rememberDetails(details,`${message.id}:report-check`);
    const checks=Array.isArray(receipt.checks)?receipt.checks.slice(0,96):[];
    const count=status=>checks.filter(c=>c.status===status).length;
    details.append(make('p','ag-research-note',`检测到 ${Number(receipt.assertion_total)||0} 条断言，完成核对 ${Number(receipt.assessed_assertions)||0} 条；有原文支持 ${count('supported')} 条，依据不足 ${count('insufficient')} 条，与原文冲突 ${count('contradicted')} 条。撤回了 ${Number(receipt.withdrawn_paragraphs)||0} 段未获支持的内容。`));
    if(receipt.failure)details.append(make('p','ag-research-note','部分核对未完成，相关表述已按依据不足处理。'));
    for(const check of checks){
      const item=make('details','ag-task-section');item.append(make('summary','ag-task-section-title',({supported:'有原文支持',insufficient:'依据不足',contradicted:'与原文冲突'})[check.status]||'待核对'));
      if(typeof check.assertion_text==='string')item.append(make('p','ag-research-note',check.assertion_text));
      if(typeof check.reason==='string')item.append(make('p','ag-research-note',check.reason));
      for(const ref of Array.isArray(check.references)?check.references.slice(0,3):[]){
        if(typeof ref.quote==='string')item.append(make('blockquote','ag-research-note',ref.quote));
        const url=publicSourceURL(ref.path);if(url){const link=make('a','ag-research-url','查看所引原文');link.href=url;link.target='_blank';link.rel='noopener noreferrer';item.append(link);}
      }
      details.append(item);
    }
    details.append(make('p','ag-skill-read-note','这是辅助模型对检测到的断言所作的判断，可能遗漏或误判。没有改变知识页的人工审核状态，也不代表功能、市场或真实成本已验证。'));
    return details;
  }
  async function resumeReply(jobId) {
    const id=state.roomId, room=state.room;
    if(!id || !room || active(room.status) || state.sending.has(id))return;
    saveDraft();state.sending.add(id);const epoch=++state.epoch;renderComposer();renderMessages(room);notice('');
    try{
      const response=await api(`/api/chat/rooms/${encodeURIComponent(id)}/jobs/${encodeURIComponent(jobId)}/resume`,{method:'POST',body:'{}'});
      state.listRevision++;if(response.room)upsertRoom(response.room);
      if(state.roomId===id && state.epoch===epoch){state.epoch++;renderRoom(response.room,true);}
    }catch(error){if(state.roomId===id)notice(`续接未完成：${error.message}`,true);}
    finally{state.sending.delete(id);renderComposer();if(state.roomId===id && state.room)renderMessages(state.room);schedulePoll(300);}
  }
  function renderProposal(proposal, room) {
    const card = make("section", "ag-proposal-card"), header = make("div", "ag-proposal-heading");
    const current = proposal.id === room.active_proposal_id && proposal.status === "awaiting_confirmation";
    const status = proposal.status === "confirmed" ? "已确认" : proposal.status === "superseded" || proposal.status === "awaiting_confirmation" && !current ? "已更新" : current ? "待确认" : "状态待确认";
    card.dataset.proposalId = proposal.id;
    header.append(make("strong", "", proposal.title || "项目方案"), make("span", `ag-proposal-state${current ? " ag-proposal-awaiting" : ""}`, status));
    card.append(header);
    if (proposal.goal) card.append(make("p", "ag-proposal-goal", `目标：${proposal.goal}`));
    card.append(markdownBody(typeof proposal.content === "string" ? proposal.content : "方案内容未记录。", "ag-proposal-content"));
    if (proposal.execution_options?.learning === true) {
      const maxPages = Number(proposal.execution_options.max_pages);
      const limit = Number.isInteger(maxPages) && maxPages > 0 ? `每个成员最多 ${maxPages} 页；` : "";
      card.append(make("p", "ag-proposal-learning-scope", `确认后将采集资料并更新所选子库草稿；${limit}不自动发布。此范围来自已保存的方案。`));
    }
    if (current) {
      const actions = make("div", "ag-proposal-actions"), confirm = make("button", "ag-button ag-primary", "确认方案并开始协作");
      confirm.type = "button"; confirm.dataset.proposalId = proposal.id;
      confirm.disabled = active(room.status) || state.sending.has(room.id);
      if (state.sending.has(room.id)) confirm.textContent = "提交中…";
      confirm.addEventListener("click", () => confirmProposal(proposal.id));
      actions.append(confirm, make("p", "ag-proposal-note", "确认后才会建立任务群、邀请成员并开始分派。需要调整时，直接在下方输入修改意见。")); card.append(actions);
    } else card.append(make("p", "ag-proposal-note", status === "已更新" ? "这份方案已被更新，不能再确认。请查看最新方案，或继续补充需求。" : status === "已确认" ? "方案已确认；实际协作进展与回复见后续任务群。" : "方案状态尚未确认，暂不能开始协作。"));
    return card;
  }
  async function confirmProposal(proposalId) {
    const room = state.room, id = state.roomId;
    const proposal = (room?.proposals || []).find((item) => item.id === proposalId);
    if (!id || !room || room.id !== id || active(room.status) || state.sending.has(id)) return;
    if (!proposal || room.active_proposal_id !== proposalId || proposal.status !== "awaiting_confirmation") { notice("这份方案已更新或已确认，请查看最新方案。", true); return; }
    saveDraft(); state.sending.add(id); const epoch = ++state.epoch; renderComposer(); renderMessages(room); notice("");
    try {
      const response = await api(`/api/chat/rooms/${encodeURIComponent(id)}/messages`, { method: "POST", body: JSON.stringify({ content: "确认方案并开始协作", confirm_proposal_id: proposal.id }) });
      state.listRevision++; if (response.room) upsertRoom(response.room);
      if (state.roomId === id && state.view === "room" && state.epoch === epoch) {
        state.epoch++; resetLearningControls();
        if (response.room) renderRoom(response.room, true); else await selectRoom(id);
      }
    } catch (error) {
      if (state.roomId === id && state.epoch === epoch) notice(`方案确认未完成：${error.message} 请先核对最新方案和任务状态，避免重复提交。`, true);
    } finally {
      state.sending.delete(id); renderComposer();
      if (state.roomId === id && state.room && state.view === "room") renderMessages(state.room);
      schedulePoll(300);
    }
  }
  function renderTaskGroup(group, room) {
    const section = make("section", "ag-task-group"), header = make("header", "ag-task-group-heading");
    section.dataset.roundId = group.round_id || group.id || "";
    section.setAttribute("aria-label", `任务群：${group.title || "当前任务"}`);
    const status = ({ queued: "等待开始", running: "进行中", completed: "已完成", failed: "未完整完成" })[group.status] || "状态待确认";
    header.append(make("span", "ag-task-group-label", "主 Agent 创建的任务群"), make("h4", "", group.title || "当前任务"), make("span", `ag-task-group-status${group.status === "failed" ? " ag-group-failed" : ""}`, status));
    const members = make("div", "ag-members ag-task-group-members"); members.setAttribute("aria-label", "本任务实际参与成员");
    for (const id of new Set(Array.isArray(group.members) ? group.members.filter((entry) => typeof entry === "string" && entry) : [])) members.append(make("span", `ag-member${id === "central" ? " ag-central" : ""}`, id === "central" ? "主 Agent" : agentName(id)));
    if (!members.childElementCount) members.append(make("span", "ag-muted", "主 Agent 正在安排成员"));
    section.append(header, members);
    const messages = make("div", "ag-task-group-messages"); section.append(messages);
    const finalReply = [...(room?.messages || [])].reverse().find((message) => message.role === "assistant" && message.agent_id === "central" && message.phase === "summary" && message.round_id === (group.round_id || group.id) && message.id);
    if (finalReply) {
      const jump = make("button", "ag-text-button ag-final-jump", finalReply.status === "failed" || finalReply.result_scope === "partial" ? "查看主 Agent 已有汇总 ↓" : "查看主 Agent 最终答复 ↓");
      jump.type = "button";
      jump.addEventListener("click", () => {
        const reply = [...messages.querySelectorAll("[data-message-id]")].find((node) => node.dataset.messageId === finalReply.id);
        if (reply) { reply.scrollIntoView({ block: "start", behavior: "auto" }); reply.focus({ preventScroll: true }); }
      }); header.append(jump);
    }
    return { section, messages };
  }
  function renderContextUsage(message, key) {
    const receipt = message.context_usage;
    if (!receipt?.enabled) return null;
    const detail = make('details', 'ag-task-section ag-context-usage'), heading = make('summary', 'ag-task-section-title', '本轮上下文');
    detail.append(heading); rememberDetails(detail, `${key}:context`);
    const body = make('div', 'ag-learning-receipt-body');
    const reply = receipt.reply || {}, summary = receipt.summary || {};
    body.append(make('p', '', receipt.total_calls===0
      ? (message.response_origin==='host_memory_read'?'直接读取当前任务要求，回复链未调用模型、摘要或补查。':'本轮回复由宿主处理，回复链未调用模型。')
      : `输入 ${reply.input_tokens == null ? '约 ' + receipt.input_tokens_estimated : reply.input_tokens} tokens · 输入预算 ${receipt.budget ?? '未提供'} · 输出预留 ${receipt.output_reserve ?? '未提供'}`));
    if (reply.output_tokens != null) body.append(make('p', '', `回复输出 ${reply.output_tokens} tokens${reply.cached_tokens == null ? '' : ' · 缓存读取 ' + reply.cached_tokens}`));
    if(receipt.selection)body.append(make('p','ag-research-note',`已按本轮预算节选资料：选取前约 ${receipt.selection.before_tokens.toLocaleString('zh-CN')} → 选取后约 ${receipt.selection.after_tokens.toLocaleString('zh-CN')} Token；选材预算 ${receipt.selection.budget_tokens.toLocaleString('zh-CN')} Token。此记录表示资料选取，不表示模型窗口已满。`));
    body.append(make('p', 'ag-research-note', `本轮模型调用 ${receipt.total_calls ?? 1} 次，含补查与摘要；累计输入 ${receipt.total_input_tokens == null ? '约 ' + receipt.total_input_tokens_estimated : receipt.total_input_tokens} tokens。估算与后端实测分别记录。`));
    const status = {not_needed:'本轮无需更新摘要',generated:'已生成摘要',manual_correction_active:'使用你的摘要修正，暂停自动摘要调用',failed_using_previous_and_originals:'摘要未成功，沿用旧摘要和原消息',skipped_budget:'摘要输入超预算，本轮保留原消息',cooldown_using_originals:'摘要暂缓重试，本轮沿用原消息'};
    body.append(make('p', 'ag-research-note', (status[summary.status] || '摘要状态未提供') + (receipt.summary_persistence ? ' · ' + ({saved:'已保存',stale:'版本已变化，未覆盖新状态',rejected:'来源校验未通过，未保存',unchanged:'未更新'})[receipt.summary_persistence.status] : '') + (summary.calls ? ` · 摘要调用 ${summary.model_ms || 0} ms` : '')));
    if(receipt.requirement_conflicts?.length)body.append(make('p','ag-memory-conflict','本任务存在尚未解决的要求冲突，可以在“记忆”中查看原消息并选择。'));
    const names = {project_memory:'项目续聊记录',task_goal:'任务目标',task_summary:'任务摘要',manual_correction:'用户摘要修正',requirement_state:'当前要求与变更',requirement:'用户要求',recent:'近期原文',recall:'历史检索',pending:'未摘要原文',personal:'个人偏好',user_profile:'个人资料',wiki:'Wiki 正文',templates:'模板',skills:'Skill',tools:'补查结果',available_roles:'角色目录',read_only_research:'调研资料',earlier_member_replies:'成员交接'};
    const list = make('ul');
    for (const item of receipt.included || []) list.append(make('li', '', `${names[item.key.split(':')[0]] || '上下文资料'} · 约 ${item.tokens} tokens${item.truncated ? ' · 已节选' : ''}${item.source_id ? ' · 消息 ' + item.source_id : ''}`));
    body.append(list);
    if (receipt.omitted?.length || receipt.personal_omitted?.length) body.append(make('p', 'ag-research-note', `省略 ${(receipt.omitted || []).length} 项无关、重复或超预算材料；个人记忆排除 ${(receipt.personal_omitted || []).length} 项无关、过期或其他范围条目。原聊天记录仍可回查。`));
    detail.append(body); return detail;
  }
  function messageDetails(content, key) {
    let records=content.querySelector('.ag-message-details-body');
    if(!records){const details=make('details','ag-message-details');records=make('div','ag-message-details-body');
      details.append(make('summary','ag-message-details-title','回复详情'),records);content.append(details);rememberDetails(details,key);}
    return records;
  }
  function renderReplyTiming(message) {
    if(message.role!=='assistant' || ![undefined,'completed'].includes(message.status) || !message.timing)return null;
    const timing=message.timing, valid=value=>Number.isFinite(value)&&value>=0;
    const first=valid(timing.request_first_text_ms)?timing.request_first_text_ms:null;
    const total=[timing.response_completed_ms,timing.request_total_ms,timing.request_to_answer_ms].find(valid);
    const seconds=value=>valid(value)?(value/1000).toFixed(2)+' 秒':'未记录';
    const line=make('div','ag-reply-timing',`首字 ${seconds(first)} · 总用时 ${seconds(total)}`);
    line.title='从服务收到本轮问题开始计时：首字为首次返回正文，总用时为本条回答完成；包含排队和模型等待。';
    return line;
  }
  function renderMessages(room, forceBottom = false) {
    const submission = state.submissions?.get(room.id);
    const allMessages = conversationMessages(room), limit = state.visibleMessages?.get(room.id) || 60;
    const messages = allMessages.slice(-limit), hiddenCount = Math.max(0, allMessages.length - messages.length) + (room.message_offset || 0);
    const signature = JSON.stringify([room.id, messages, hiddenCount, room.live_reply, room.delegations || [], room.task_groups || [], room.proposals || [], room.active_proposal_id, room.status, state.sending?.has(room.id),submission,state.unconfirmed?.get(room.id)]);
    if (signature === state.feedSignature && !forceBottom) return;
    state.feedSignature = signature;
    const feed = $("feed"), nearBottom = forceBottom || feed.scrollHeight - feed.scrollTop - feed.clientHeight < 110;
    const position = feed.scrollTop, focusedTask = document.activeElement?.dataset?.taskKey;
    const fragment = document.createDocumentFragment(), shownRounds = new Set();
    if (hiddenCount) {
      const earlier = make('button', 'ag-text-button ag-earlier-messages', `查看更早的对话（还有 ${hiddenCount} 条）`);
      earlier.type = 'button';
      earlier.addEventListener('click', async () => {
        const height = feed.scrollHeight, top = feed.scrollTop;
        earlier.disabled = true;
        try {
          const nextLimit = limit + 60;
          const expanded = room.message_offset ? await api(`/api/chat/rooms/${encodeURIComponent(room.id)}?message_limit=${nextLimit >= room.message_count ? 0 : Math.min(20000, nextLimit)}`) : room;
          if (state.room?.id !== room.id) return;
          state.visibleMessages ||= new Map(); state.visibleMessages.set(room.id, nextLimit);
          renderRoom(expanded);
          feed.scrollTop = top + feed.scrollHeight - height;
        } catch (error) { notice(error.message, true); }
        finally { earlier.disabled = false; }
      });
      fragment.append(earlier);
    }
    const visibleRounds = new Set(messages.map(message => message.round_id).filter(Boolean));
    const groups = new Map((Array.isArray(room.task_groups) ? room.task_groups : []).filter((group) => group && (group.round_id || group.id)
      && (!hiddenCount || visibleRounds.has(group.round_id || group.id) || (group.round_id || group.id) === room.active_job_id))
      .map((group) => [group.round_id || group.id, group])), containers = new Map();
    function groupContainer(roundId) {
      if (!groups.has(roundId)) return fragment;
      if (!containers.has(roundId)) {
        const rendered = renderTaskGroup(groups.get(roundId), room); fragment.append(rendered.section); containers.set(roundId, rendered.messages);
      }
      return containers.get(roundId);
    }
    for (const [messageIndex, message] of messages.entries()) {
      const container = groupContainer(message.round_id);
      if (message.role === "system" && message.event_origin === "host" && ["group_started", "member_joined", "delegation", "work_started", "error"].includes(message.event_kind)) {
        const progress = renderProgressMessage(message, room); if (progress) { container.append(progress); continue; }
      }
      const user = message.role === "user", system = message.role === "system", central = message.agent_id === "central";
      const article = make("article", `ag-message${user ? " ag-user" : ""}${central ? " ag-central-message" : ""}${message.status === "failed" ? " ag-message-failed" : ""}${system ? " ag-system-message" : ""}`);
      const english=message.reply_language==='en';article.lang=english?'en':'zh-CN';
      article.dataset.messageId = message.id || "";
      if (message.reply_key) article.dataset.replyKey = message.reply_key;
      if (central && message.phase === "summary") { article.classList.add("ag-final-answer"); article.setAttribute("tabindex", "-1"); }
      const name = user ? english?'You':"你" : message.response_origin === 'host_video_status' ? '视频进度' : message.video_submission_id ? '视频接口' : central && room.mode === "orchestrated" ? english?'Main Agent':"主 Agent" : message.agent_name || (system ? english?'Conversation notice':"会话提示" : agentName(message.agent_id));
      const avatar = make("span", "ag-avatar", user ? english?'You':"你" : central ? "◎" : system ? "·" : [...name][0] || "A"); avatar.setAttribute("aria-hidden", "true");
      const content = make("div", "ag-message-content"), meta = make("div", "ag-message-meta");
      meta.append(make("strong", "", name));
      if (message.video_submission_id) meta.append(make('span','ag-summary-label','生成视频'));
      if (message.role === 'assistant') {
        const stage = make('span', 'ag-summary-label ag-interim-state ag-response-stage', replyStageLabel(message));
        stage.hidden = !stage.textContent; meta.append(stage);
      }
      if (user && message.round_id && (room.delegations || []).some((task) => task.round_id === message.round_id && task.kind === "web_learning")) meta.append(make("span", "ag-summary-label", "自主联网学习"));
      if (message.phase === "summary" || (central && room.mode === "group")) meta.append(make("span", "ag-summary-label", central ? room.mode === "orchestrated" ? "协作汇总" : "中央汇总" : depth(agent(message.agent_id)) === 1 ? "行业汇总" : "分支汇总"));
      else if (message.event_kind === "result") meta.append(make("span", "ag-summary-label", depth(agent(message.agent_id)) === 1 ? "模块回复" : "成员回复"));
      if (message.result_scope === "partial") meta.append(make("span", "ag-failed-label", english?'Partial result':"部分结果"));
      if (message.status === "failed") meta.append(make("span", "ag-failed-label", english?'Incomplete':"未完成"));
      if (message.status === 'cancelled') meta.append(make('span','ag-research-state',english?'Stopped':'已停止'));
      if (message.send_unconfirmed) meta.append(make('span','ag-failed-label',english?'Send unconfirmed': '发送未确认'));
      if (message.created_at) meta.append(make("time", "", date(message.created_at)));
      const proposal = message.role === "assistant" && central && message.phase === "proposal" ? (Array.isArray(room.proposals) ? room.proposals : []).find((item) => item.id === message.proposal_id && (!item.message_id || item.message_id === message.id)) : null;
      const text = typeof message.content === "string" ? message.content : "";
      content.append(meta);
      content.append(proposal ? renderProposal(proposal, room) : message.role === "assistant" && (message.status !== "failed" || isNativeReply(message)) ? renderReplyBody(message) : make("div", "ag-message-text" + (message.status==='failed'?' ag-failure-text':''), text));
      if(message.status==='failed' && /^[a-f0-9]{32}$/.test(message.recoverable_job_id || '')){
        if(message.processing_stage?.detail)content.append(make('p','ag-research-note','上次停在：'+message.processing_stage.detail));
      }
      const downloads = message.role === 'assistant' && renderReportArtifacts(message);
      if (downloads) content.append(downloads);
      const timing=renderReplyTiming(message);
      if(timing)content.append(timing);
      article.append(avatar, content); container.append(article);
      if (room.mode === "orchestrated" && user && message.round_id && !shownRounds.has(message.round_id)) {
        const tasks = renderDelegations(room, message.round_id);
        if (tasks) { container.append(tasks); shownRounds.add(message.round_id); }
      }
    }
    for (const roundId of groups.keys()) groupContainer(roundId);
    if (!messages.length && !groups.size) fragment.append(make("div", "ag-chat-empty", room.purpose === "primary" ? "想弄懂什么，直接聊。比如：教我 AI 产品思维，拿这个知识库举例。我们一次聊一个点，你随时可以打断、追问或反驳。" : room.mode === "orchestrated" ? "先聊需求，方案确认后开始协作。普通问题由主 Agent 直接回答；项目需求先调研和给出方案。你可以继续调整，确认方案后才会建立任务群。无需新建会话或选择成员。" : room.mode === "group" ? "大家已加入会话。发送第一个问题，专业 Agent 与所属分支依次回答，中央 Agent 最后汇总。" : "会话已建立。发送一个问题，开始与这个知识库 Agent 交流。"));
    feed.replaceChildren(fragment);
    if(typeof window!=='undefined')window.openWikiTools?.render();
    if (focusedTask) [...feed.querySelectorAll("summary[data-task-key]")].find((summary) => summary.dataset.taskKey === focusedTask)?.focus({ preventScroll: true });
    if (nearBottom) feed.scrollTop = feed.scrollHeight; else feed.scrollTop = position;
  }
  const hasLearningPrefix = (content) => /^\/学习(?:\s|$)/u.test(content.trim());
  function resetLearningControls() {
    // Both choices are per turn. Never persist them with drafts or restore them silently.
    $("research").checked = false; $("learning").checked = false; $("learning-pages").value = "2"; $("learning-options").open = false;
  }
  function researchRequested() {
    const room = state.room, primary = room && (room.purpose === "primary" || room.id === state.primaryRoomId);
    return Boolean(primary && $("research").checked && !hasLearningPrefix($("message").value));
  }
  function learningRequested() {
    return state.room?.mode === "orchestrated" && ($("learning").checked || hasLearningPrefix($("message").value));
  }
  function renderLearningControls(room, busy) {
    const automatic = room?.mode === "orchestrated", prefix = automatic && hasLearningPrefix($("message").value);
    const primary = room && (room.purpose === "primary" || room.id === state.primaryRoomId);
    if (prefix) $("research").checked = false;
    const requested = automatic && ($("learning").checked || prefix), status = state.learningStatus;
    $("research-controls").hidden = !primary;
    $("research").disabled = !primary || Boolean(busy) || prefix;
    $("research-controls").classList.toggle("ag-learning-enabled", researchRequested());
    $("research-description").textContent = prefix ? "当前使用 /学习 指令；移除指令后可选择只查询，不写入知识库。" : "本轮只查阅公开资料并回答，不写入知识库；也可以直接提供网页链接。";
    $("learning-controls").hidden = !automatic;
    $("learning-label").textContent = primary ? "学习并更新草稿" : "本轮自主联网学习";
    $("learning").disabled = !automatic || Boolean(busy) || status?.enabled === false;
    $("learning-prefix").hidden = !prefix;
    const maxPages = Math.min(5, Math.max(1, Math.trunc(count(status?.max_pages_per_agent) || 5)));
    $("learning-pages").max = String(maxPages);
    $("learning-pages").disabled = !requested || Boolean(busy);
    $("learning-description").hidden = !primary && !requested;
    $("learning-description").textContent = primary ? "先生成学习方案，你确认后才采集资料并更新知识草稿；发布仍需审核。" : "子 Agent 自主选题、发现公开资料并更新自己的知识草稿；中央采用仍需审核发布。";
    $("learning-provider").hidden = !requested && status?.enabled !== false;
    $("learning-controls").classList.toggle("ag-learning-enabled", requested);
    const provider = status?.search_available ? "已配置搜索服务，具体采集方式以回执为准" : "官方资料自主发现 · 无需提供链接";
    $("learning-provider").textContent = status?.enabled === false ? "当前自主学习未启用，请检查采集配置后重试。" : state.learningStatusError ? "暂未读到采集能力状态，发送时由服务核对。默认每个 Agent 最多 2 页。" : `${provider} · 每 Agent 最多 ${maxPages} 页${status?.max_pages_per_round ? ` · 每轮最多 ${count(status.max_pages_per_round)} 页` : ""}`;
  }
  function composerContext(room) {
    // The last reply's input measures one request. Totals include other calls
    // (tools, checks, summaries) and cannot measure an active context window.
    const message = (room?.messages || []).findLast(item => item.role === 'assistant' && item.phase !== 'acknowledgement');
    const receipt = message?.context_usage || {}, native = message?.native_stream?.usage;
    const usage = receipt.reply || (Array.isArray(native) ? native.at(-1) : null) || {};
    const valid = value => typeof value === 'number' && Number.isFinite(value) && value >= 0 ? value : null;
    const actual = valid(usage.input_tokens), estimate = valid(receipt.input_tokens_estimated);
    const host = receipt.total_calls === 0;
    const input = host ? null : actual ?? estimate;
    const window = valid(receipt.context_window ?? receipt.window);
    const pending=Boolean(room && (active(room.status) || state.sending.has(room.id)));
    const live=state.liveReplies?.get(room?.id) || room?.live_reply;
    const current=pending && live?.job_id===room?.active_job_id?live?.context_compaction:null;
    return {message, receipt, input, output: valid(usage.output_tokens), window: window > 0 ? window : null,
      estimated: !host && actual === null && estimate !== null, host,
      percent: !host && input !== null && window > 0 ? Math.round(input / window * 100) : null,
      pending,current};
  }
  function contextSummaryText(receipt) {
    const statuses = {not_needed:'本轮无需更新摘要', generated:'已生成任务摘要',
      manual_correction_active:'使用你的摘要修正', failed_using_previous_and_originals:'摘要未成功，沿用旧摘要和原消息',
      skipped_budget:'摘要输入超预算，保留原消息', cooldown_using_originals:'摘要暂缓重试，沿用原消息'};
    const status = receipt.summary?.status;
    if (!status) return null;
    const persistence = {saved:'已保存', stale:'版本已变化，未覆盖', rejected:'来源校验未通过，未保存', unchanged:'未更新'}[receipt.summary_persistence?.status];
    return (statuses[status] || '摘要状态未识别') + (persistence ? ' · ' + persistence : '');
  }
  function renderComposerContext(room) {
    const meter = $('context-meter');
    if (!meter) return;
    if (state.contextMeterRoom !== room?.id) { meter.open = false; state.contextMeterRoom = room?.id; state.contextMeterSignature = ''; }
    const snapshot = composerContext(room), {message, receipt, input, window, estimated, host, percent, pending} = snapshot;
    const signature = JSON.stringify([room?.id, message?.id, message?.agent_id, message?.model, message?.created_at, receipt, input, snapshot.output, pending,snapshot.current]);
    if (signature === state.contextMeterSignature) return;
    state.contextMeterSignature = signature;
    const number = value => value.toLocaleString('zh-CN'), body = $('context-body'); body.replaceChildren();
    const label = host ? '最近一轮未调用回复模型' : input === null ? '尚无输入用量回执'
      : `${estimated ? '初始输入估算' : '最近一次输入'}${percent === null ? ' · 窗口未知' : ` · ${estimated ? '约 ' : ''}${percent}% 配置窗口`}`;
    const visibleLabel=pending?`${label} · 本轮更新中，保留已有用量`:label;
    $('context-toggle').title = '上下文 · ' + visibleLabel;
    $('context-toggle').setAttribute('aria-label', '查看上下文用量：' + visibleLabel);
    meter.dataset.level = percent === null ? 'unknown' : percent >= 80 ? 'high' : 'normal';
    meter.dataset.estimated = String(estimated);
    $('context-fill').style.strokeDasharray = `${Math.min(100, Math.max(0, percent ?? 0))} 100`;
    body.append(make('p', 'ag-context-caption', message ? `${agentName(message.agent_id)}${message.model ? ' · ' + message.model : ''}${message.created_at ? ' · ' + date(message.created_at) : ''}` : '发送消息后，由实际回执更新。'));
    if (pending) {
      body.append(make('p', 'ag-context-pending', '本轮处理中，保留已有用量，收到本轮模型回执后更新；发送消息不会清空会话上下文。'));
      if(snapshot.current)body.append(make('p','ag-context-note',`本轮${snapshot.current.stage==='runtime'?'压缩':'整理'}回执：处理前约 ${number(snapshot.current.before_tokens)} → 处理后约 ${number(snapshot.current.after_tokens)} Token；可用输入预算 ${number(snapshot.current.budget_tokens)} Token。`));
      if(message)body.append(make('p','ag-context-caption','以下为上一轮记录，不代表本轮用量。'));
    }
    if (host) body.append(make('p', 'ag-context-reading', '最近一轮由宿主直接处理，未调用回复模型。'));
    else {
      body.append(make('p', 'ag-context-reading', input === null ? '输入用量尚未提供' : `${estimated ? '约 ' : ''}${number(input)}${window ? ' / ' + number(window) : ''} Token`));
      body.append(make('p', 'ag-context-caption', `${estimated ? '初始选材估算' : '最近一次回复调用的输入回执'}${window ? ' · 配置窗口' : ' · 未提供窗口大小'}`));
      if (percent !== null) body.append(make('p', 'ag-context-percent', `${estimated ? '约 ' : ''}${percent}% 输入占用`));
      if (snapshot.output !== null) body.append(make('p', 'ag-context-note', `该次调用输出 ${number(snapshot.output)} Token。`));
      if (window) body.append(make('p', 'ag-context-note', '窗口大小来自本地配置，尚未向模型服务校验。'));
    }
    const settings = [];
    if (typeof receipt.budget === 'number' && receipt.budget > 0) settings.push(`选材输入预算 ${number(receipt.budget)}`);
    if (typeof receipt.output_reserve === 'number' && receipt.output_reserve > 0) settings.push(`输出预留 ${number(receipt.output_reserve)}`);
    if (settings.length && !host) body.append(make('p', 'ag-context-note', settings.join(' · ') + ' Token'));
    const adjustment=contextAdjustment(message);
    if(adjustment)body.append(make('p','ag-context-note',`${pending?'上一轮':'本轮'}${adjustment.stage==='runtime'?'压缩':'整理'}记录：处理前约 ${number(adjustment.before_tokens)} → 处理后约 ${number(adjustment.after_tokens)} Token；原聊天记录保留。`));
    if(receipt.selection)body.append(make('p','ag-context-note',`${pending?'上一轮':'本轮'}曾按预算节选资料，选取后约 ${number(receipt.selection.after_tokens)} Token；选材预算与模型窗口上限分别计算。`));
    if(receipt.conversation)body.append(make('p','ag-context-note',`连续会话保留 ${receipt.conversation.message_count} 条历史，已压缩 ${receipt.conversation.compaction_count} 次。达到可用输入上限时才压缩；输出和协议另有预留。`));
    const summary = contextSummaryText(receipt);
    if (summary) body.append(make('p', 'ag-context-note', summary));
    if (receipt.omitted?.length) body.append(make('p', 'ag-context-note', `本轮省略 ${receipt.omitted.length} 项无关、重复或超预算材料，原聊天记录保留。`));
    if (estimated) body.append(make('p', 'ag-context-note', '估算包含初始选材；工具续接后的输入量需等待模型回执。'));
    body.append(make('p', 'ag-context-note', '这里显示用于续聊的记忆；回复正文只展示对话、进展和实际操作。'));
    const usage = make('button', 'ag-text-button ag-context-usage-link', '查看累计消耗'); usage.type = 'button';
    usage.addEventListener('click', () => { meter.open = false; state.memoryView = 'usage'; openMemory(); }); body.append(usage);
  }
  function bindComposerContext() {
    const meter = $('context-meter');
    if (!meter) return;
    const fitPopover = () => {
      if (!meter.open) return;
      const popover = meter.querySelector('.ag-context-popover');
      if (!popover) return;
      const top = Math.max(0, $('dialog')?.getBoundingClientRect().top || 0,
        document.querySelector('.ws-header')?.getBoundingClientRect().bottom || 0) + 12;
      const available = popover.getBoundingClientRect().bottom - top;
      popover.style.maxHeight = `${Math.max(80, Math.min(400, window.innerHeight * .55, available))}px`;
    };
    meter.addEventListener('toggle', fitPopover);
    window.addEventListener('resize', fitPopover, {passive:true});
    window.addEventListener('scroll', fitPopover, {passive:true});
    document.addEventListener('pointerdown', event => { if (meter.open && !meter.contains(event.target)) meter.open = false; });
    document.addEventListener('keydown', event => {
      if (event.key === 'Escape' && meter.open) { event.preventDefault(); event.stopPropagation(); meter.open = false; $('context-toggle').focus(); }
    });
  }
  function videoMessageIntent(content, selected = false, recentVideo = false) {
    const text = content.trim().toLowerCase();
    if (!text) return 'chat';
    if (/^(?:(?:先|暂时|现在|暂)?(?:不要|别|不用|不想|不需要|不必|不是|不生成)|停止|取消|不是让你生成)|^(?:please\s+)?(?:do not|don't|stop|cancel)\b|(?:这句话|这段话|提示词|prompt).{0,12}(?:什么意思|解释|翻译|优化)|^(?:解释|翻译|介绍|写代码|帮我改)/.test(text)) return 'chat';
    if (/(?:生成|制作).{0,20}(?:视频|短片|动画)(?:需要|要多久|的(?:原理|方法|步骤|提示词)|提示词)|^(?:可以|能不能|能|你能).{0,6}(?:生成|制作)视频[吗嘛？?。\s]*$|^(?:视频生成|生成视频)(?:失败)?(?:是什么|怎么办|如何|怎么)/.test(text)) return 'chat';
    if (/(?:视频|短片|动画)(?:生成)?(?:应用|软件|系统|平台|网站|接口|功能|工具)|(?:解释|翻译|优化|改写|检查).{0,20}(?:提示词|prompt)|^(?:继续|所有的|全部)[。！!\s]*$/.test(text)) return 'chat';
    const create = /^(?:(?:请|帮我|给我|麻烦|现在|再|重新|继续|能不能|可以|能|一下)\s*)*(?:生成|制作|做|重做)(?!的).{0,40}(?:视频|短片|动画)|^(?:please\s+)?(?:generate|create|make)\b.{0,70}\b(?:video|clip|animation)\b/.test(text);
    const topic = /视频|生成任务|渲染|video|render|\bjob\b|[a-f0-9]{8}-[a-f0-9-]{27,}/.test(text);
    const progress = /进度|状态|生成好|完成了|做好了|成功了|失败了|还没好|还没完|到哪[一了]|还(?:要|需).{0,6}(?:多久|多长)|为什么.{0,8}(?:慢|没|久)|等.{0,8}(?:久|分钟)|(?:好|完|完成)(?:了)?[吗没嘛]|\b(?:status|progress|ready|done|finished|completed|failed)\b|how much longer/.test(text);
    if (!create && progress && (topic || recentVideo)) return 'status';
    if (create) return 'generate';
    const question = /[?？]|(?:吗|嘛|呢)[。！!\s]*$|什么|为什么|怎么|如何|能否|是否|多少|哪里|哪[个里些]|多久|有没有|^(?:你好|您好|谢谢|好的|收到|明白|在吗|帮我|查一下|查查|检查|搜索|查询|找一下|把.{0,15}(?:视频|文件)|服务器|所有的|全部|发给我|发我|播放|打开|下载|列出)|^(?:hi|hello|thanks|thank you|ok|what|why|how|when|where|who|is|are|can|could|would|check|find|search)\b/.test(text);
    return selected && !question ? 'generate' : 'chat';
  }
  function composerIntent(content = $('message').value) {
    let recent = false;
    for (const message of [...(state.room?.messages || [])].reverse()) {
      if (message.role === 'assistant' && ['host_video_submission','host_video_status'].includes(message.response_origin)) { recent = true; break; }
      if (message.role === 'user') { recent = !!(message.video_submission_id || message.video_status_query); break; }
    }
    return videoMessageIntent(content, state.sendModes?.get(state.roomId) === 'video', recent);
  }
  function renderComposer() {
    if(typeof window!=='undefined')window.openWikiTools?.renderDraft();
    const room = state.room, busy = state.roomId && state.sending.has(state.roomId);
    const waiting = !room || active(room.status) || busy;
    if($('stop-reply')) {
      $('stop-reply').hidden = !(room?.can_stop_reply && active(room.status));
      $('stop-reply').disabled = Boolean(state.stoppingReply);
      $('stop-reply').textContent = state.stoppingReply ? '正在停止…' : '停止等待';
    }
    const selectedVideo = state.sendModes?.get(state.roomId) === 'video', intent = composerIntent();
    const video = intent === 'generate', statusQuery = intent === 'status';
    renderLearningControls(room, waiting);
    const learning = !video && learningRequested(), research = !video && researchRequested();
    const primary = room && (room.purpose === "primary" || room.id === state.primaryRoomId);
    $("message").disabled = !room;
    $("send").disabled = Boolean(waiting) || !$("message").value.trim() || (learning && state.learningStatus?.enabled === false);
    $("send").textContent = waiting ? "发送" : statusQuery ? "查询视频进度" : video ? "发送提示词" : learning ? primary ? "生成学习方案" : "开始学习" : research ? "查询并回答" : "发送";
    $("compose-hint").textContent = room && (active(room.status) || busy) ? "这一轮正在进行，可以先写好下一条消息。" : statusQuery ? "查询已有视频任务，不会重新生成；连接异常会在 8 秒内返回。" : video ? "仅本次发送用于生成视频，成功提交后返回普通对话。" : selectedVideo ? "本条识别为普通对话，不会提交视频生成。" : learning ? primary ? "先生成待确认的学习方案，确认后才采集并更新草稿。" : "本轮会采集公开资料并更新专业 Agent 的知识草稿。" : research ? "本轮查询公开资料；过时知识按自动复查设置核对，明确要求不更新时保留原文。" : "⌘ / Ctrl + Enter 发送 · 需要查证时再联网";
    if ($('send-mode')) {
      $('send-mode').value = selectedVideo ? 'video' : 'chat'; $('send-mode').disabled = !!waiting;
      $('message-form').dataset.sendMode = video ? 'video' : 'chat';
      $('video-settings').hidden = !selectedVideo;
      $('message').placeholder = selectedVideo ? '描述本次想生成的视频；也可以直接提问或查询进度…' : '直接聊，也可以把 PDF、Word 或笔记拖到这里…';
      if(video){$('research-controls').hidden=true;$('learning-controls').hidden=true;}
    }
    renderComposerContext(room);
  }
  function renderRoom(room, forceBottom = false) {
    if (state.view !== "room" || room.id !== state.roomId) return;
    const unresolved=state.unconfirmed?.get(room.id);
    if(unresolved?.length) {
      const retained=unresolved.filter(pending=>!(room.messages || []).some(message=>message.role==='user' && message.content===pending.content
        && !(pending.known_message_ids || []).includes(message.id)));
      if(retained.length!==unresolved.length) {
        if(retained.length)state.unconfirmed.set(room.id,retained);else state.unconfirmed.delete(room.id);
        persistView();
      }
    }
    const live = state.room?.live_reply;
    if (active(room.status) && live?.job_id === room.active_job_id && (!room.live_reply || room.live_reply.revision < live.revision)) room.live_reply = live;
    state.room = room;
    const primary = room.purpose === "primary" || room.id === state.primaryRoomId;
    const { group: latest, pendingGroup, discussion, confirmed } = currentChatContext(room);
    const pendingTitle = confirmed?.title || confirmed?.goal || "正在组建任务群";
    const awaiting = (room.proposals || []).some((proposal) => proposal.id === room.active_proposal_id && proposal.status === "awaiting_confirmation");
    $("conversation-title").textContent = primary ? pendingGroup ? pendingTitle : discussion ? "主 Agent" : latest ? latest.title || "当前任务" : "主 Agent" : room.title || "历史会话";
    $("conversation-mode").textContent = primary ? pendingGroup ? "方案已确认 · 等待组建任务群" : discussion ? awaiting ? "方案待确认" : "先聊需求，方案确认后开始协作" : latest ? "当前任务成员" : "先聊需求，方案确认后开始协作" : `历史记录 · ${modeName(room.mode)}`;
    $("return-primary").hidden = primary;
    $("message").placeholder = primary ? awaiting ? "对方案有调整意见？直接告诉主 Agent…" : "直接聊，也可以把 PDF、Word 或笔记拖到这里…" : "继续这段历史对话，或返回主 Agent 沟通新需求…";
    $("orchestration-note").hidden = room.mode !== "orchestrated";
    $("conversation").classList.toggle("ag-simple-conversation", Boolean(primary && discussion && !awaiting));
    renderMembers(room); renderMessages(room, forceBottom); renderComposer();
    const status = $("turn-status"); status.hidden = !active(room.status) && room.status !== "failed";
    status.classList.toggle("ag-turn-failed", room.status === "failed");
    let currentName = typeof room.current_agent === "string" ? room.current_agent : room.current_agent?.name;
    if (currentName && agent(currentName)) currentName = agentName(currentName);
    $("turn-label").textContent = room.status === "queued" ? pendingGroup ? "方案已确认，正在等待开始协作…" : "正在等待本地模型…" : room.status === "running" ? discussion ? room.live_reply?.text ? "正在回复…" : "正在读取相关经验…" : room.mode === "orchestrated" ? `${currentName || "主 Agent"} 正在处理本轮任务，成员的进度与回复会持续显示在本群。` : `${currentName || "Agent"} 正在回答。` : room.status === "failed" ? "上一轮未完整完成，已保留实际回复和失败信息。你可以继续发送消息。" : "";
    if(turnLanguage(room)==='en')$('turn-label').textContent=room.status==='queued'?'Waiting to start…':room.status==='running'?room.live_reply?.text?'Replying…':'Preparing reply…':room.status==='failed'?'The previous turn was incomplete. Its reply and error details are preserved; you can continue chatting.':'';
    if(active(room.status) && processingLabel(room.live_reply?.processing_stage?.stage))$('turn-label').textContent=processingLabel(room.live_reply.processing_stage.stage,turnLanguage(room)==='en')+'…';
    watchRoomStream(room);
    renderStreamNotice(room);
    if (document.body?.dataset?.workspace) window.dispatchEvent(new CustomEvent("openwiki:chat-state", { detail: room }));
  }
  function stopRoomStream() {
    state.replyStream?.close(); state.replyStream = null; state.replyStreamKey = null; state.streamConnected = false;
    if (state.streamReconnect?.timer) clearTimeout(state.streamReconnect.timer);
    state.streamReconnect = null;
    if ($('stream-notice')) $('stream-notice').hidden = true;
  }
  function renderLiveReply(reply) {
    const room = state.room;
    if (!room || !active(room.status) || reply?.job_id !== room.active_job_id || typeof reply.text !== "string" || reply.text.length > 64000) return;
    if (room.live_reply && reply.revision <= room.live_reply.revision) return;
    room.live_reply = reply;
    renderComposerContext(room);
    renderStreamNotice(room);
    const feed = $("feed"), nearBottom = feed.scrollHeight - feed.scrollTop - feed.clientHeight < 110;
    const key = JSON.stringify([reply.job_id, reply.agent_id || 'central', '']);
    const message = conversationMessages(room).findLast(item => item.reply_key === key);
    const article = [...feed.querySelectorAll('[data-message-id]')].findLast(node => node.dataset.replyKey === key);
    const body = article?.querySelector('.ag-reply-body');
    if (message && body) {
      article.dataset.messageId = message.id || '';
      body.replaceWith(renderReplyBody(message));
      const stage = article.querySelector('.ag-response-stage');
      if (stage) { stage.textContent = replyStageLabel(message); stage.hidden = !stage.textContent; }
      if (nearBottom) feed.scrollTop = feed.scrollHeight;
    } else if (message) renderMessages(room);
    const english=turnLanguage(room)==='en';
    $('turn-label').textContent=(processingLabel(reply.processing_stage?.stage,english) || (english?'Replying':'正在回复'))+'…';
    if (document.body?.dataset?.workspace) window.dispatchEvent(new CustomEvent("openwiki:chat-stream", { detail: reply }));
  }
  function watchRoomStream(room) {
    if (!$("dialog").open || !active(room.status) || !room.active_job_id || typeof EventSource === "undefined") {
      stopRoomStream(); return;
    }
    const limit = Math.min(20000, state.visibleMessages?.get(room.id) || 60);
    const key = `${room.id}:${room.active_job_id}:${limit}`;
    if (key === state.replyStreamKey) return;
    stopRoomStream();
    const reconnect = {key, attempt:0, waiting:false, exhausted:false, timer:null};
    state.streamReconnect = reconnect; state.replyStreamKey = key;
    const belongs = () => state.streamReconnect === reconnect && state.roomId === room.id
      && state.room?.active_job_id === room.active_job_id && active(state.room?.status) && $("dialog").open;
    const connect = () => {
    if (!belongs()) return;
    reconnect.timer=null;
    const cursor=Number.isInteger(state.room?.live_reply?.native_seq)?state.room.live_reply.native_seq:0;
    const source = new EventSource(`/api/chat/rooms/${encodeURIComponent(room.id)}/events?job_id=${encodeURIComponent(room.active_job_id)}&after=${cursor}&message_limit=${limit}`);
    state.replyStream = source;
    const current = () => belongs() && state.replyStream === source;
    source.addEventListener("open", () => { if (current()) { state.streamConnected = true; reconnect.waiting=false; renderStreamNotice(state.room); } });
    source.addEventListener("room", (event) => {
      if (!current()) return;
      try { const value = JSON.parse(event.data); if (value.id === room.id) renderRoom(value); } catch { /* Polling keeps recovery available. */ }
    });
    source.addEventListener("reply", (event) => {
      if (!current()) return;
      try { renderLiveReply(JSON.parse(event.data)); } catch { /* Never interpret malformed event content as HTML. */ }
    });
    source.addEventListener('agent',event=>{
      if(!current())return;
      try{renderNativeAgentEvent(JSON.parse(event.data));}catch{ /* Canonical snapshots recover malformed or missed transport events. */ }
    });
    source.addEventListener("done", () => { if (current()) { stopRoomStream(); schedulePoll(100); } });
    source.addEventListener("error", () => {
      if (!current()) return;
      source.close(); state.replyStream=null; state.streamConnected=false;
      if (reconnect.attempt >= 5) { reconnect.exhausted=true; reconnect.waiting=false; renderStreamNotice(state.room); schedulePoll(300); return; }
      reconnect.attempt++; reconnect.waiting=true; renderStreamNotice(state.room); schedulePoll(300);
      reconnect.timer=setTimeout(connect,Math.min(8000,1000*2**(reconnect.attempt-1)));
    });
    };
    connect();
  }
  function renderStreamNotice(room) {
    const note=$('stream-notice'); if(!note)return;
    const reconnect=state.streamReconnect, native=room?.live_reply?.transport_retry;
    const exhausted=Boolean(reconnect?.exhausted), waiting=Boolean(reconnect?.waiting);
    const english=turnLanguage(room)==='en';
    const text=english?(exhausted?'The live connection failed after 5 retries. Your reply is preserved; please try again later.'
      :waiting?`Live connection interrupted. Reconnecting (${reconnect.attempt}/5)…`
      :native?.status==='retrying'?native.retry_policy==='until_cancelled'?`Model connection interrupted. Retrying (${native.attempt}); you can stop waiting.`:`Model connection interrupted. Reconnecting (${native.attempt}/5)…`:''):exhausted?'实时连接自动重连 5 次仍失败，请稍后再试。已有回复已保留。'
      : waiting?`实时连接已中断，正在重连，第 ${reconnect.attempt}/5 次…`
      : native?.status==='retrying'?native.retry_policy==='until_cancelled'?`模型连接暂时不可用，正在自动重试（第 ${native.attempt} 次）；可随时停止等待。`:`模型连接已中断，正在重连，第 ${native.attempt}/5 次…`:'';
    note.hidden=!text;note.classList.toggle('ag-connection-error',exhausted);
    note.setAttribute('role',exhausted?'alert':'status');
    if(note.textContent!==text)note.textContent=text;
  }
  function renderNativeAgentEvent(event) {
    const room=state.room,prior=room?.live_reply;
    if(!room || !active(room.status) || event.job_id!==room.active_job_id || !Number.isInteger(event.seq)
      || event.seq<1 || event.seq<=(prior?.native_seq || 0) || !Number.isInteger(event.revision)
      || !['responses','chat_completions'].includes(event.protocol))return;
    const reply={...(prior || {text:'',updates:[]}),job_id:event.job_id,agent_id:event.agent_id,agent_name:event.agent_name,
      turn_id:event.turn_id,revision:event.revision,native_seq:event.seq,native_protocol:event.protocol,
      updates:(prior?.updates || []).map(item=>({...item})),operations:replyOperations(prior || {}).map(item=>({...item})),
      timeline:validReplyTimeline(prior?.timeline)};
    if(event.origin==='host_context') {
      if(event.type!=='agent.context.compacted' || !['before_tokens','after_tokens','budget_tokens'].every(k=>Number.isInteger(event[k])&&event[k]>0&&event[k]<=10000000)
        || event.after_tokens>=event.before_tokens || event.after_tokens>event.budget_tokens)return;
      if(event.stage!==undefined && event.stage!=='runtime')return;
      reply.context_compaction={before_tokens:event.before_tokens,after_tokens:event.after_tokens,budget_tokens:event.budget_tokens,...(event.stage?{stage:event.stage}:{})};
      renderLiveReply(reply);return;
    }
    if(event.origin==='host_transport') {
      const waiting=event.retry_policy==='until_cancelled' && event.max_attempts===null;
      const bounded=event.retry_policy===undefined && event.max_attempts===5;
      if(!['agent.transport.retrying','agent.transport.restored'].includes(event.type) || !Number.isInteger(event.attempt)
        || event.attempt<1 || !Number.isSafeInteger(event.attempt) || !waiting && event.attempt>5 || !(waiting || bounded))return;
      const ids=event.replace_ids || [];
      if(!Array.isArray(ids) || ids.length>32 || ids.some(id=>typeof id!=='string' || !/^[a-z0-9-]{1,32}$/.test(id)))return;
      if(event.replace_answer!==undefined && typeof event.replace_answer!=='boolean'
        || event.delay_ms!==undefined && (!Number.isInteger(event.delay_ms) || event.delay_ms<0 || event.delay_ms>(waiting?30000:8000)))return;
      const retrying=event.type==='agent.transport.retrying';
      reply.transport_retry={attempt:event.attempt,max_attempts:event.max_attempts,...(waiting?{retry_policy:'until_cancelled'}:{}),status:retrying?'retrying':'restored'};
      if(retrying){reply.updates=reply.updates.filter(item=>!ids.includes(item.id));if(event.replace_answer)reply.text='';
        reply.timeline=reply.timeline.filter(entry=>!(entry.source==='update' && ids.includes(entry.id) || event.replace_answer && entry.source==='answer'));}
      renderLiveReply(reply);return;
    }
    if (event.origin==='host_tool' && ['agent.tool.started','agent.tool.completed'].includes(event.type)) {
      if (!['server_files','wiki_search','web_read','web_search','visual_browser','profit_calculate','file_search','file_read','audio_transcribe','video_analyze','code_interpreter','image_analyze','image_generate','connector_search','connector_read','research_review'].includes(event.name)
        || typeof event.call_id!=='string' || !event.call_id || event.call_id.length>200)return;
      let operation=reply.operations.find(item=>item.call_id===event.call_id);
      if (operation && operation.name!==event.name)return;
      if (!operation) {if(reply.operations.length>=32)return;operation={call_id:event.call_id,name:event.name,status:'running'};reply.operations.push(operation);}
      if (typeof event.target==='string')operation.target=operationTarget(event.name,event.target);
      if (event.type==='agent.tool.completed') {
        operation.status=typeof event.status==='string'?event.status:'unknown';
        operation.elapsed_ms=event.elapsed_ms;
        if(typeof event.failure_detail==='string')operation.failure_detail=event.failure_detail.slice(0,200);
      }
    }
    if(['response.output_text.delta','chat.completion.content.delta'].includes(event.type)) {
      if(typeof event.delta!=='string' || event.delta.includes('\0') || event.delta.length>4096)return;
      if(event.type==='response.output_text.delta' && event.phase==='final_answer')reply.text+=event.delta;
      else if(event.type==='chat.completion.content.delta' || event.phase==='commentary') {
        if(typeof event.update_id!=='string' || !/^[a-z0-9-]{1,32}$/.test(event.update_id))return;
        let update=reply.updates.find(item=>item.id===event.update_id);
        if(!update){if(reply.updates.length>=32)return;update={id:event.update_id,title:'Agent 回复',text:'',status:'streaming'};reply.updates.push(update);}
        update.text+=event.delta;
      } else return;
    } else if(event.type==='response.output_item.done' && event.phase==='commentary') {
      const update=reply.updates.find(item=>item.id===event.update_id);if(update)update.status='completed';
    }
    if(reply.text.length>64000 || reply.updates.reduce((n,u)=>n+u.text.length,0)>40000)return;
    recordReplyTimeline(reply,event);
    renderLiveReply(reply);
    if(event.type==='agent.tool.started')$('turn-label').textContent='Agent 正在调用'+({web_read:'网页读取',visual_browser:'浏览器',web_search:'搜索',research_review:'多来源证据核对',wiki_search:'知识检索',profit_calculate:'计算器',code_interpreter:'Python',file_search:'附件检索',file_read:'文档读取',audio_transcribe:'音频转写',video_analyze:'视频分析',image_analyze:'图片识别',image_generate:'图片生成',connector_search:'连接搜索',connector_read:'连接读取'}[event.name] || '工具')+'…';
  }
  async function selectRoom(id, initialRoom = null) {
    stopRoomStream();
    saveDraft(); state.view = "room"; state.roomId = id; state.room = null; state.preferredRoomId = id; persistView();
    resetLearningControls();
    const epoch = ++state.epoch; state.feedSignature = "";
    $("conversation").hidden = false; $("message").value = state.drafts.get(id) || "";
    $("return-primary").hidden = id === state.primaryRoomId;
    $("conversation-title").textContent = state.rooms.find((room) => room.id === id)?.title || "正在读取会话…";
    $("conversation-mode").textContent = ""; $("members").replaceChildren(); $("turn-status").hidden = true;
    $("feed").replaceChildren(make("p", "ag-chat-empty", "正在读取会话…"));
    notice(""); renderRooms(); renderComposer();
    try {
      const room = initialRoom || await api(`/api/chat/rooms/${encodeURIComponent(id)}`);
      if (state.epoch === epoch && state.roomId === id) { renderRoom(room); $("feed").scrollTop = state.feedPositions.has(id) ? state.feedPositions.get(id) : $("feed").scrollHeight; $("message").focus({ preventScroll: true }); }
    } catch (error) { if (state.epoch === epoch) notice(error.message, true); }
  }
  function upsertRoom(room) {
    const index = state.rooms.findIndex((item) => item.id === room.id);
    if (index >= 0) state.rooms[index] = room; else state.rooms.unshift(room);
    renderRooms();
  }
  async function refreshDirectory() {
    const revision = ++state.listRevision;
    const results = await Promise.all([api("/api/agents"), api("/api/chat/rooms"), api("/api/web-learning/status").catch(() => null)]);
    if (revision !== state.listRevision) return;
    state.agents = results[0].agents || []; state.rooms = results[1].rooms || []; state.loaded = true;
    state.learningStatus = results[2]; state.learningStatusError = !results[2];
    window.dispatchEvent(new Event('openwiki:agents'));
    if ($("templates-dialog").open && !agent(state.templateSpace)) {
      renderTemplatePicker();
      if (state.templateSpace) loadTemplates();
    }
    if ($("skills-dialog").open && !agent(state.skillSpace)) {
      renderSkillPicker();
      if (state.skillSpace) loadSkills();
    }
    renderRooms(); if (state.room) { renderMembers(state.room); renderComposer(); }
  }
  function schedulePoll(delay = 2000) {
    clearTimeout(state.timer);
    if ($("dialog").open) state.timer = setTimeout(poll, delay);
  }
  async function poll() {
    if (state.polling || !$("dialog").open) { schedulePoll(); return; }
    if (document.hidden) { schedulePoll(15000); return; }
    state.polling = true;
    const id = state.view === "room" ? state.roomId : null, epoch = state.epoch, revision = ++state.listRevision;
    try {
      const refreshList = $("history-dialog").open || !state.lastRoomListAt || Date.now() - state.lastRoomListAt >= 30000;
      const [data, room] = await Promise.all([refreshList ? api("/api/chat/rooms") : Promise.resolve(null), id && !state.streamConnected ? api(`/api/chat/rooms/${encodeURIComponent(id)}`) : Promise.resolve(null)]);
      if (data && revision === state.listRevision) { state.rooms = data.rooms || []; state.lastRoomListAt = Date.now(); renderRooms(); }
      if (room && id === state.roomId && epoch === state.epoch) renderRoom(room);
      if (state.failures && $("dialog").open) notice("");
      state.failures = 0;
    } catch (error) {
      state.failures++;
      if ($("dialog").open && epoch === state.epoch) notice(`暂时无法刷新会话：${error.message}`, true);
    } finally { state.polling = false; schedulePoll(state.streamConnected || !active(state.room?.status) ? 8000 : Math.min(15000, 2000 * (state.failures + 1))); }
  }
  async function openMainChat() {
    saveDraft();
    if (!$("dialog").open) $("dialog").showModal();
    if ($("history-dialog").open) $("history-dialog").close();
    const epoch = ++state.epoch;
    state.view = "room"; state.roomId = null; state.room = null;
    $("conversation").hidden = false; $("conversation-title").textContent = "主 Agent";
    $("conversation-mode").textContent = "正在连接…"; $("return-primary").hidden = true;
    $("members").replaceChildren(); $("turn-status").hidden = true; $("message").value = "";
    $("feed").replaceChildren(make("p", "ag-chat-empty", "正在连接主 Agent…")); notice(""); renderComposer();
    try {
      await viewStorage;
      if (state.epoch !== epoch || !$("dialog").open) return;
      // The conversation is usable as soon as it arrives. The member directory
      // and history list fill independently instead of holding up the composer.
      void refreshDirectory().catch(error => { if (state.epoch === epoch) notice(error.message, true); });
      const response = await api("/api/chat/primary", { method: "POST", body: "{}" });
      if (state.epoch === epoch && $("dialog").open) {
        const room = response.room || response;
        if (!room.id) throw new Error("服务没有返回主 Agent 会话编号，请重新打开主 Agent 重试。");
        state.primaryRoomId = room.id; upsertRoom(room);
        await selectRoom(room.id, room);
        if (document.body?.dataset?.workspace) $("feed").scrollTop = $("feed").scrollHeight;
      }
    } catch (error) { if (state.epoch === epoch) { $("conversation-mode").textContent = "连接未完成"; $("return-primary").hidden = false; notice(`${error.message} 可点击“返回主 Agent”重试。`, true); } }
    schedulePoll();
  }
  launch.addEventListener("click", openMainChat);
  bindComposerContext();
  import('/agent-tools.js').then(module=>module.initializeTools({getRoom:()=>state.room,api,notice})).catch(()=>notice('附件与工具配置界面加载失败，请刷新页面。',true));
  import('/server-operations.js').then(module=>module.initializeServerOperations({getRoom:()=>state.room,api,notice})).catch(()=>notice('服务器操作确认界面加载失败，请刷新页面。',true));
  $('memory-open').addEventListener('click',openMemory);
  $('memory-close').addEventListener('click',()=>$('memory-dialog').close());
  $('memory-dialog').addEventListener('close',()=>{state.memoryEpoch++;$('memory-refresh').disabled=false;});
  $('memory-refresh').addEventListener('click',()=>loadMemory());
  $('memory-agent').addEventListener('change',()=>loadMemory());
  for(const view of ['tasks','profile','projects','personal','usage'])$('memory-'+view).addEventListener('click',()=>{state.memoryView=view;if(state.memoryData)renderMemory(state.memoryData);});
  $("close").addEventListener("click", () => $("dialog").close());
  $("dialog").addEventListener("close", () => { $("context-meter").open = false; saveDraft(); state.epoch++; clearTimeout(state.timer); if ($("templates-dialog").open) $("templates-dialog").close(); if ($("skills-dialog").open) $("skills-dialog").close(); if ($("history-dialog").open) $("history-dialog").close(); if($('memory-dialog').open)$('memory-dialog').close(); });
  $("templates-open").addEventListener("click", () => {
    state.templateSpace = defaultTemplateSpace(); renderTemplatePicker();
    if (!$("templates-dialog").open) $("templates-dialog").showModal();
    loadTemplates();
  });
  $("templates-close").addEventListener("click", () => $("templates-dialog").close());
  $("templates-dialog").addEventListener("close", () => { state.templateEpoch++; $("templates-refresh").disabled = false; });
  $("template-agent").addEventListener("change", () => { $("template-search").value = ""; loadTemplates($("template-agent").value); });
  $("template-search").addEventListener("input", () => { if (state.templateData) renderTemplateList(state.templateData.data, state.templateData.space); });
  $("templates-refresh").addEventListener("click", () => loadTemplates());
  $("skills-open").addEventListener("click", () => {
    if (!agent(state.skillSpace)) state.skillSpace = defaultTemplateSpace();
    renderSkillPicker();
    if (!$("skills-dialog").open) $("skills-dialog").showModal();
    loadSkills();
  });
  $("skills-close").addEventListener("click", () => $("skills-dialog").close());
  $("skills-dialog").addEventListener("close", () => { state.skillEpoch++; $("skills-refresh").disabled = false; });
  $("skill-agent").addEventListener("change", () => { $("skill-search").value = ""; loadSkills($("skill-agent").value); });
  $("skill-search").addEventListener("input", () => { if (state.skillData) renderSkillList(state.skillData.data, state.skillData.space); });
  $("skills-refresh").addEventListener("click", () => loadSkills());
  $("history-open").addEventListener("click", () => { renderRooms(); if (!$("history-dialog").open) $("history-dialog").showModal(); });
  $("history-close").addEventListener("click", () => $("history-dialog").close());
  $("return-primary").addEventListener("click", openMainChat);
  $("refresh").addEventListener("click", async () => {
    $("refresh").disabled = true; const epoch = state.epoch;
    try { await refreshDirectory(); if (state.epoch === epoch) notice(""); if (state.view === "room" && state.epoch === epoch) await selectRoom(state.roomId); }
    catch (error) { if (state.epoch === epoch) notice(error.message, true); }
    finally { $("refresh").disabled = false; schedulePoll(); }
  });
  $("message").addEventListener("input", () => { saveDraft(); renderComposer(); });
  $('send-mode').addEventListener('change',()=>{
    state.sendModes.set(state.roomId,$('send-mode').value);
    if($('send-mode').value==='video')resetLearningControls();
    persistView();renderComposer();
  });
  $("research").addEventListener("change", () => { if ($("research").checked) $("learning").checked = false; renderComposer(); });
  $("learning").addEventListener("change", () => { if ($("learning").checked) $("research").checked = false; renderComposer(); });
  $("learning-pages").addEventListener("input", renderComposer);
  $("message").addEventListener("keydown", (event) => {
    if ((event.metaKey || event.ctrlKey) && event.key === "Enter" && !event.isComposing && !$("send").disabled) { event.preventDefault(); $("message-form").requestSubmit(); }
  });
  $('stop-reply').addEventListener('click', async () => {
    const room=state.room, jobId=room?.active_job_id;
    if(!room?.can_stop_reply || !active(room.status) || !jobId || state.stoppingReply)return;
    state.stoppingReply=true;renderComposer();
    try {
      const response=await api(`/api/chat/rooms/${encodeURIComponent(room.id)}/jobs/${encodeURIComponent(jobId)}/stop`,{method:'POST',body:'{}'});
      if(state.roomId===room.id)renderRoom(response.room);
    } catch(error) { notice(error.message,true); }
    finally { state.stoppingReply=false;renderComposer();schedulePoll(100); }
  });
  $("message-form").addEventListener("submit", async (event) => {
    event.preventDefault(); const id = state.roomId, intent = composerIntent(), video = intent === 'generate', statusQuery = intent === 'status', content = video ? $("message").value : $("message").value.trim();
    if (!id || !state.room || active(state.room.status) || state.sending.has(id) || !content.trim()) return;
    if (!video && hasLearningPrefix(content) && state.room.mode !== "orchestrated") { notice("请在主 Agent 自动协作会话中使用 /学习，由主 Agent 逐层交给专业成员。", true); return; }
    const fileIds=window.openWikiTools?.attachments(id) || [];
    if(video && fileIds.length){notice('生成视频只发送消息文字，请先移除附件。',true);return;}
    const learning = !video && !statusQuery && learningRequested(), research = !video && !statusQuery && researchRequested(), maxPages = Number($("learning-pages").value);
    if (learning && state.learningStatus?.enabled === false) { notice("当前自主学习未启用，请检查采集配置后重试。", true); return; }
    if (learning && (!Number.isInteger(maxPages) || maxPages < 1 || maxPages > Number($("learning-pages").max))) { $("learning-options").open = true; $("learning-pages").focus(); notice("请选择有效的每 Agent 采集页数，范围为 1 至 " + $("learning-pages").max + " 页。", true); return; }
    saveDraft(); state.sending.add(id); const epoch = ++state.epoch;
    let videoRequest;
    if(video){
      videoRequest=state.videoRequests.get(id);
      if(!videoRequest || videoRequest.content!==content){videoRequest={content,id:crypto.randomUUID().replaceAll('-','')};state.videoRequests.set(id,videoRequest);}
    }
    const submission={id:String(epoch)+'-'+Date.now(),content,intent,loading_label:statusQuery?'正在查询视频进度':video?'正在提交视频提示词':'正在发送',created_at:new Date().toISOString(),
      known_message_ids:(state.room.messages || []).filter(message=>message.role==='user' && message.content===content).map(message=>message.id)};
    state.submissions.set(id,submission);
    $("message").value = ""; state.drafts.delete(id); persistView();
    renderComposer(); renderMessages(state.room,true); notice("");
    $("message").focus({preventScroll:true});
    try {
      // Save the retry key before dispatching an external side effect.
      if(video)await persistView(true);
      const hotspotContext = !video && !statusQuery && state.room.purpose === 'primary' ? window.openWikiHotspots?.context() || {} : {};
      const payload = video ? {content,video_generation:true,request_id:videoRequest.id} : { content, learning, research, max_pages: learning ? maxPages : 2, file_ids:fileIds, ...hotspotContext };
      const response = await api(`/api/chat/rooms/${encodeURIComponent(id)}/messages`, { method: "POST", body: JSON.stringify(payload) });
      state.videoRequests.delete(id);state.sendModes.set(id,'chat');
      if(!video)window.openWikiTools?.sent(id,fileIds);
      state.submissions.delete(id); persistView(); state.listRevision++;
      if (response.room) upsertRoom(response.room);
      if (state.roomId === id && state.view === "room") {
        state.epoch++;
        resetLearningControls();
        if (response.room) renderRoom(response.room, true); else await selectRoom(id);
      }
    } catch (error) {
      const visible=state.roomId===id && state.view==='room';
      const draft=visible?$("message").value:state.drafts.get(id) || '';
      if (!draft) {
        state.drafts.set(id,content);
        if (visible) $("message").value=content;
      } else {
        state.unconfirmed ??= new Map();
        state.unconfirmed.set(id,[...(state.unconfirmed.get(id) || []),submission]);
      }
      if (visible) notice(error.code === 'release_draining' && error.accepted === false
        ? '正在安全发布，这条消息尚未受理。输入已保留，发布完成后可以重新发送。'
        : `消息未确认发送：${error.message} 原文已保留，请先刷新核对是否已收到，避免重复发送。`, true);
    }
    finally { state.submissions.delete(id); state.sending.delete(id); persistView(); renderComposer(); if (state.room) renderMessages(state.room); schedulePoll(300); }
  });
  $("dialog").addEventListener("close", () => { stopRoomStream(); clearTimeout(state.timer); });
  window.addEventListener("pagehide", () => { saveDraft(); stopRoomStream(); });
  document.addEventListener("openwiki:select", (event) => { if (event.detail?.spaceId) state.graphSpace = event.detail.spaceId; });
  window.addEventListener("federation:changed", () => { if ($("dialog").open) refreshDirectory().catch((error) => notice(error.message, true)); });
  renderRooms(); renderComposer();
  function mentionAgent(identifier, range = null) {
    const member = agent(identifier), input = $("message");
    if (!member || input.disabled) return false;
    const token = member.id === 'central' ? '' : '@' + member.name;
    const replacement = token && !input.value.includes(token) ? token + ' ' : '';
    if (range && Number.isInteger(range.start) && Number.isInteger(range.end)
      && range.start >= 0 && range.end >= range.start && range.end <= input.value.length) {
      input.setRangeText(replacement, range.start, range.end, 'end');
    } else if (replacement) {
      input.setRangeText(replacement, input.selectionStart, input.selectionEnd, 'end');
    }
    input.dispatchEvent(new Event('input', { bubbles: true })); input.focus({preventScroll:true});
    return true;
  }
  function setupAgentPicker() {
    const input=$('message'),form=$('message-form'),buttons={},cache=new Map();
    const controls=make('div','ag-compose-pickers');
    for(const [kind,label,symbol] of [['agents','员工','@'],['skills','技能','/']]) {
      const button=make('button','ag-agent-picker-button',label);
      button.id=kind==='agents'?'ag-agent-picker-open':'ag-skill-picker-open';button.type='button';button.disabled=input.disabled;
      button.setAttribute('aria-label',kind==='agents'?'选择员工，或输入 @':'选择技能，或输入 /');
      button.setAttribute('aria-expanded','false');button.setAttribute('aria-controls','ag-agent-picker');
      button.append(make('kbd','',symbol));controls.append(button);buttons[kind]=button;
    }
    form.querySelector('.ag-compose-footer').prepend(controls);
    const menu=make('section','ag-agent-picker');menu.id='ag-agent-picker';menu.hidden=true;
    const header=make('div','ag-agent-picker-heading'),title=make('strong'),total=make('span','ag-agent-picker-total');
    const closeButton=make('button','ag-agent-picker-close','×');closeButton.type='button';closeButton.setAttribute('aria-label','收起选择菜单');
    header.append(title,total,closeButton);
    const list=make('div','ag-agent-picker-list');list.id='ag-agent-picker-list';list.setAttribute('role','listbox');
    const empty=make('p','ag-agent-picker-empty');empty.setAttribute('role','status');empty.hidden=true;
    const retry=make('button','ag-text-button','重新读取技能');retry.type='button';retry.hidden=true;
    const search=make('input','ag-agent-picker-search');search.type='search';
    const scope=make('p','ag-agent-picker-scope');scope.hidden=true;
    const hint=make('p','ag-agent-picker-hint','↑ ↓ 选择 · Enter 确认 · Esc 收起');
    menu.append(header,scope,list,empty,retry,search,hint);form.prepend(menu);
    let kind='agents',mode=null,range=null,rows=[],selected=-1,query='',composing=false,roomId=state.roomId;
    const commands=new Set(['学习','记住','忘记','学习进度','收录','沉淀','采用','回退','发布经验']);
    const escape=value=>value.replace(/[.*+?^${}()|[\]\\]/g,'\\$&');
    function skillOwners() {
      if(state.room?.mode==='direct')return (state.room.participants || []).slice(0,1);
      const mentioned=state.agents.filter(member=>member.id!=='central' && [member.name,member.id].some(value=>
        new RegExp('@'+escape(value)+'(?![A-Za-z0-9_-])').test(input.value)));
      return mentioned.length?mentioned.map(member=>member.id):['central'];
    }
    function trigger() {
      if(input.selectionStart!==input.selectionEnd)return null;
      const before=input.value.slice(0,input.selectionStart);
      // Emails, paths, URLs, fractions and code samples are not menu invocations.
      if((before.match(/`/g)||[]).length%2)return null;
      const match=before.match(/(?:^|\s)([@/])([\p{L}_-][\p{L}\p{N}_ -]{0,49}|)$/u);
      if(!match || match[1]==='/' && commands.has(match[2].trim().split(/\s+/)[0]))return null;
      if(match[1]==='@' && state.agents.some(member=>[member.name,member.id].some(value=>match[2].startsWith(value+' '))))return null;
      return {kind:match[1]==='@'?'agents':'skills',start:before.length-match[2].length-1,end:input.selectionStart,query:match[2]};
    }
    function activeInput(){return mode==='button'?search:input;}
    function close(focus=false) {
      menu.hidden=true;mode=null;range=null;rows=[];query='';
      Object.values(buttons).forEach(button=>button.setAttribute('aria-expanded','false'));
      for(const field of [input,search])for(const attribute of ['aria-controls','aria-expanded','aria-activedescendant','aria-autocomplete','aria-haspopup'])field.removeAttribute(attribute);
      if(focus)input.focus({preventScroll:true});
    }
    function select(index,scroll=false) {
      selected=index;
      rows.forEach((row,i)=>row.node.setAttribute('aria-selected',String(i===selected && !row.disabled)));
      const current=rows[selected];
      if(current && !current.disabled){activeInput().setAttribute('aria-activedescendant',current.node.id);if(scroll)current.node.scrollIntoView({block:'nearest'});}
      else activeInput().removeAttribute('aria-activedescendant');
    }
    function choose(index) {
      const row=rows[index];if(!row || row.disabled || input.disabled)return;
      const replace=range,selectionKind=kind;close();
      if(selectionKind==='agents'){mentionAgent(row.item.id,replace);return;}
      // Use the existing explicit Skill invocation understood by the host.
      const token='$'+row.item.id;
      const duplicate=new RegExp('(?:^|\\s)'+escape(token)+'(?![A-Za-z0-9_-])').test(input.value);
      input.setRangeText(duplicate?'':token+' ',replace.start,replace.end,'end');
      input.dispatchEvent(new Event('input',{bubbles:true}));input.focus({preventScroll:true});
    }
    function fit() {
      const top=form.getBoundingClientRect().top,bound=$('dialog').querySelector('.ag-dialog-header').getBoundingClientRect().bottom;
      menu.style.maxHeight=Math.max(120,Math.min(440,top-Math.max(bound,0)-10))+'px';
    }
    function loadSkillCatalog(owners) {
      const key=owners.join(','),previous=cache.get(key);
      if(previous && (previous.pending || Date.now()-previous.time<60000))return previous;
      const entry={pending:true,time:Date.now(),items:[],error:null};cache.set(key,entry);
      Promise.all(owners.map(id=>api(`/api/spaces/${encodeURIComponent(id)}/skills`))).then(results=>{
        const catalogs=results.map(result=>{
          if(!Array.isArray(result.skills))throw new Error('技能目录格式不完整');
          return result.skills.filter(item=>item && /^[a-z0-9][a-z0-9-]*$/.test(item.id));
        });
        entry.items=(catalogs[0] || []).filter(item=>catalogs.every(items=>items.some(other=>other.id===item.id))).map(item=>({
          ...item,status:catalogs.every(items=>items.find(other=>other.id===item.id)?.status==='ready')?'ready':'conflict'
        }));
      }).catch(()=>{entry.error='技能目录暂时未能读取，请重试。';}).finally(()=>{
        entry.pending=false;entry.time=Date.now();
        if(!menu.hidden && kind==='skills' && skillOwners().join(',')===key)render(query);
      });
      return entry;
    }
    function render(value='') {
      query=value;rows=[];selected=-1;list.replaceChildren();retry.hidden=true;
      const terms=value.toLocaleLowerCase().trim().split(/\s+/).filter(Boolean),groups=new Map(),normalized=value.toLocaleLowerCase().trim();
      title.textContent=kind==='agents'?'选择员工':'选择技能';
      menu.setAttribute('aria-label',kind==='agents'?'员工目录':'技能目录');list.setAttribute('aria-label',kind==='agents'?'可选择的员工':'可选择的技能');
      search.placeholder=kind==='agents'?'搜索员工名称或职责…':'搜索技能名称或用途…';search.setAttribute('aria-label',kind==='agents'?'搜索员工':'搜索技能');
      scope.hidden=kind!=='skills';
      let entries=[],message='';
      if(kind==='agents') {
        entries=orderedAgents().map(item=>({item,name:item.id==='central'?'主 Agent':item.name.replace(/ Agent$/,''),
          group:item.id==='central'?'通用':(agent(industryId(item))?.name || '其他').replace(/ Agent$/,''),description:item.description || '在当前对话中咨询'}));
        message=state.loaded?'没有匹配的员工，换个名称或职责试试。':'正在读取员工目录…';
      } else {
        const owners=skillOwners(),data=loadSkillCatalog(owners);
        scope.textContent=(owners.length>1?'所选员工的共同技能':(agent(owners[0])?.name || '主 Agent')+'的技能')+' · 按规范处理任务，外部执行工具尚未接入';
        entries=data.items.map(item=>({item,name:item.display_name || item.name || item.id,group:item.status==='ready'?'可用技能':'需要修复',description:item.status==='ready'?item.description || '按技能规范处理当前任务':'文件校验未通过，暂不可选',disabled:item.status!=='ready'}));
        message=data.pending?'正在读取技能目录…':data.error || (data.items.length?'没有匹配的技能，换个名称或用途试试。':owners.length>1?'所选员工暂时没有共同的技能。':'这位员工还没有已导入的技能。');
        retry.hidden=!data.error;
      }
      const score=entry=>{const name=entry.name.toLocaleLowerCase(),id=entry.item.id.toLocaleLowerCase();return !normalized?0:name===normalized || id===normalized?100:name.startsWith(normalized)?80:name.includes(normalized)?60:id.includes(normalized)?30:0;};
      entries.sort((a,b)=>Number(!!a.disabled)-Number(!!b.disabled) || score(b)-score(a));
      for(const entry of entries) {
        const text=[entry.name,entry.item.id,entry.description,entry.group,...(Array.isArray(entry.item.keywords)?entry.item.keywords:[])].join(' ').toLocaleLowerCase();
        if(!terms.every(term=>text.includes(term)))continue;
        if(!groups.has(entry.group))groups.set(entry.group,[]);groups.get(entry.group).push(entry);
      }
      for(const [name,entries] of groups) {
        const group=make('div','ag-agent-picker-group');group.setAttribute('role','group');group.setAttribute('aria-label',name);
        const heading=make('div','ag-agent-picker-group-title',name+'（'+entries.length+'）');heading.setAttribute('aria-hidden','true');group.append(heading);
        for(const entry of entries) {
          const index=rows.length,node=make('div','ag-agent-picker-option');node.id='ag-agent-option-'+index;node.setAttribute('role','option');
          if(entry.disabled)node.setAttribute('aria-disabled','true');
          node.append(make('span','ag-agent-picker-name',entry.name),make('span','ag-agent-picker-description',entry.description));node.title=entry.description;
          node.addEventListener('pointerdown',event=>{if(event.button===0)event.preventDefault();});node.addEventListener('click',()=>choose(index));
          node.addEventListener('pointermove',()=>{if(!entry.disabled)select(index);});rows.push({...entry,node});group.append(node);
        }
        list.append(group);
      }
      empty.hidden=rows.length>0;empty.textContent=message;
      total.textContent=rows.filter(row=>!row.disabled).length+(kind==='agents'?' 位':' 项');
      select(rows.findIndex(row=>!row.disabled));list.scrollTop=0;fit();
    }
    function open(nextKind,source,currentRange) {
      if(input.disabled || state.sendModes?.get(state.roomId)==='video')return;
      close();kind=nextKind;mode=source;range=currentRange;menu.hidden=false;buttons[kind].setAttribute('aria-expanded','true');search.hidden=source!=='button';
      const field=activeInput();field.setAttribute('aria-controls',list.id);field.setAttribute('aria-expanded','true');field.setAttribute('aria-autocomplete','list');field.setAttribute('aria-haspopup','listbox');
      render(currentRange?.query || '');
      if(source==='button'){search.value='';search.focus({preventScroll:true});}
    }
    function sync() {
      if(state.sendModes?.get(state.roomId)==='video'){close();return;}
      if(composing)return;
      const current=trigger();
      if(current){if(mode!=='trigger' || kind!==current.kind)open(current.kind,'trigger',current);else{range=current;render(current.query);}}
      else if(mode==='trigger')close();
    }
    function keyboard(event) {
      if(menu.hidden || event.isComposing || composing || event.keyCode===229)return;
      if(['ArrowDown','ArrowUp'].includes(event.key)) {
        event.preventDefault();event.stopImmediatePropagation();
        const selectable=rows.map((row,i)=>row.disabled?-1:i).filter(i=>i>=0),position=selectable.indexOf(selected);
        select(selectable[(position+(event.key==='ArrowDown'?1:-1)+selectable.length)%(selectable.length||1)] ?? -1,true);
      } else if((event.key==='Enter' && !event.shiftKey && !event.altKey) || (event.key==='Tab' && selected>=0 && !event.shiftKey)) {
        event.preventDefault();event.stopImmediatePropagation();choose(selected);
      } else if(event.key==='Escape'){event.preventDefault();event.stopImmediatePropagation();close(true);}
      else if(event.key==='Tab')close();
    }
    input.addEventListener('input',sync);input.addEventListener('focus',()=>{if(mode==='button')close();});
    $('send-mode')?.addEventListener('change',()=>close());
    input.addEventListener('compositionstart',()=>{composing=true;});input.addEventListener('compositionend',()=>{composing=false;sync();});
    input.addEventListener('click',()=>{if(mode==='trigger')sync();});
    input.addEventListener('keyup',event=>{if(['ArrowLeft','ArrowRight','Home','End'].includes(event.key) && mode==='trigger')sync();});
    input.addEventListener('keydown',keyboard,true);search.addEventListener('keydown',keyboard);search.addEventListener('input',()=>render(search.value));
    for(const [nextKind,button] of Object.entries(buttons))button.addEventListener('click',()=>{
      if(!menu.hidden && kind===nextKind){close(true);return;}
      const current=trigger();
      open(nextKind,'button',current?{start:current.start,end:current.end}:{start:input.selectionStart,end:input.selectionStart});
    });
    closeButton.addEventListener('click',()=>close(true));
    retry.addEventListener('click',()=>{cache.delete(skillOwners().join(','));render(query);});
    document.addEventListener('pointerdown',event=>{
      if(mode==='trigger' && event.target.closest('button[type="submit"]')?.form===form)return;
      if(!menu.hidden && !menu.contains(event.target) && !controls.contains(event.target) && event.target!==input)close();
    });
    form.addEventListener('submit',event=>{if(!menu.hidden && mode==='trigger'){event.preventDefault();event.stopImmediatePropagation();choose(selected);return;}close();},true);
    $('dialog').addEventListener('close',()=>close());window.addEventListener('resize',()=>{if(!menu.hidden)fit();});
    window.addEventListener('openwiki:agents',()=>{if(!menu.hidden)render(query);});
    window.addEventListener('federation:changed',()=>{cache.clear();if(!menu.hidden && kind==='skills')render(query);});
    window.addEventListener('openwiki:chat-state',event=>{if(event.detail?.id!==roomId){roomId=event.detail?.id;close();}});
    new MutationObserver(()=>{Object.values(buttons).forEach(button=>{button.disabled=input.disabled;});if(input.disabled)close();}).observe(input,{attributes:true,attributeFilter:['disabled']});
  }
  window.openWikiChat = { open: openMainChat, renderBody: markdownBody, mention: mentionAgent };
  setupAgentPicker();
})();
