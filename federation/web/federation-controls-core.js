/* Additive controls for the unmodified OpenWiki visualizer layout. */
(() => {
  "use strict";
  const state = { data: null, selected: "central", tab: "ask", jobs: new Map(), polling: new Set(), answers: new Map(), drafts: new Map(), review: null, visited: new Set(), revision: 0, reviewRevision: 0, knowledgeRevision: 0 };
  const $ = (id) => document.getElementById(`fed-${id}`);
  const make = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = String(text); return node; };
  const number = (value) => Number.isFinite(Number(value)) ? Number(value) : 0;
  const output = (value) => typeof value === "string" ? value : value ? JSON.stringify(value, null, 2) : "";
  const knowledge = (space) => number(space?.knowledge_count ?? space?.page_count);
  const space = (id = state.selected) => id === "central" ? state.data?.central : state.data?.branches?.find((branch) => branch.id === id);
  const breadcrumb = (item) => (item?.breadcrumb?.length ? item.breadcrumb : [item?.name || "知识库"]).join(" › ");
  function orderedSpaces() {
    const items = [state.data?.central, ...(state.data?.branches || [])].filter(Boolean), result = [], seen = new Set();
    function visit(item) { if (seen.has(item.id)) return; seen.add(item.id); result.push(item); items.filter((child) => child.parent_id === item.id).forEach(visit); }
    items.filter((item) => !item.parent_id).forEach(visit); items.forEach(visit); return result;
  }
  const activeJob = (id) => [...state.jobs.values()].find((job) => job.space === id && ["queued", "running"].includes(job.status));
  const actionName = (action) => ({ learn: "分支学习", ask: "智能体问答", sync: "中央汇总" })[action] || "执行任务";
  const niceDate = (value) => { if (!value) return ""; const date = new Date(typeof value === "number" && value < 1e12 ? value * 1000 : value); return Number.isNaN(date.valueOf()) ? String(value) : date.toLocaleString("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }); };

  const toolbar = make("div", "federation-toolbar");
  const manage = make("button", "icon-btn", "知识库操作"), add = make("button", "icon-btn", "＋ 新增分支");
  manage.type = add.type = "button"; manage.id = "fed-manage"; add.id = "fed-add";
  manage.title = "管理当前知识库的资料、知识状态、学习、问答与发布"; add.title = "在行业或专业知识库下新增分支"; toolbar.append(manage, add);
  const topbar = document.querySelector(".topbar"); if (!topbar) return;
  topbar.insertBefore(toolbar, document.getElementById("live"));

  // This template is static application markup. All API/user values use textContent.
  const template = document.createElement("template");
  template.innerHTML = `
    <dialog class="fed-dialog" id="fed-dialog" aria-labelledby="fed-title">
      <div class="fed-dialog-header"><div><p class="fed-eyebrow">OPENWIKI · 行业知识网络</p><h2 id="fed-title">知识库操作</h2></div><button class="icon-btn" id="fed-close" type="button" aria-label="关闭知识库操作">×</button></div>
      <div class="fed-body">
        <p class="fed-intro">行业与专业分支各自学习资料，并有独立的 Agent；审核发布后，知识汇入中央智能体。</p>
        <div class="fed-space-line"><select id="fed-space" class="filter" aria-label="选择行业或专业知识库"></select><button class="fed-button primary" id="fed-main" type="button" disabled>汇总知识</button></div>
        <p class="fed-breadcrumb" id="fed-breadcrumb"></p><p class="fed-stats" id="fed-stats"></p>
        <nav class="fed-tabs" id="fed-tabs" aria-label="知识库管理功能"></nav>
        <p id="fed-notice" class="fed-notice" role="status" hidden></p>
        <section id="fed-sources-panel" hidden>
          <p class="fed-intro">资料只进入当前知识库分支。导入完成后，点击“开始学习”生成或更新分支知识。</p>
          <form id="fed-source-form"><label class="fed-file"><span class="fed-file-symbol" aria-hidden="true">↥</span><span class="fed-file-copy"><strong>选择本地资料文件</strong><span>.md / .txt · 单份不超过 80 KB</span></span><input id="fed-file" type="file" accept=".md,.txt,text/plain,text/markdown" aria-label="选择 Markdown 或 TXT 文件"></label><label class="fed-label" for="fed-filename">文件名</label><input id="fed-filename" required maxlength="160" placeholder="例如：专业研究.md"><label class="fed-label" for="fed-source-text">资料正文（也可直接粘贴）</label><textarea id="fed-source-text" rows="6" required maxlength="80000" placeholder="建议保留资料的标题、来源和日期。"></textarea><button class="fed-button primary fed-full" id="fed-source-submit" type="submit">导入到当前分支</button></form>
          <div class="fed-section-head"><h3>已导入资料</h3><span class="fed-micro" id="fed-source-count"></span></div><div class="fed-source-list" id="fed-source-list"></div>
        </section>
        <section id="fed-ask-panel"><p class="fed-intro" id="fed-ask-intro">问答读取知识副本，不会改写或发布正式知识。</p><form id="fed-ask-form"><label class="fed-label" for="fed-question">你的问题</label><textarea id="fed-question" rows="5" maxlength="6000" required placeholder="输入需要智能体回答的问题。"></textarea><button class="fed-button primary fed-full" id="fed-ask-submit" type="submit">发送问题</button></form><div id="fed-answers" aria-live="polite"></div></section>
        <section id="fed-health-panel" hidden aria-labelledby="fed-health-title">
          <div class="fed-section-head"><h3 id="fed-health-title">知识状态与来源追溯</h3><button class="fed-button" id="fed-health-reload" type="button">刷新状态</button></div>
          <p class="fed-intro">“已记录”只表示页面与已记录的来源版本一致，不代表内容事实正确，也不代表已核实互联网上的最新版本。旧页面没有追溯记录时显示“未追溯”。</p>
          <p class="fed-health-status" id="fed-health-status" role="status"></p>
          <div class="fed-health-summary" id="fed-health-summary" aria-label="当前 Agent 知识状态统计"></div>
          <p class="fed-micro fed-health-scope">来源列表中的 run_inputs 只代表该次学习的输入资料，不证明页面每条结论都来自这些资料；逐条事实与引用仍需核对。</p>
          <div class="fed-health-pages" id="fed-health-pages" aria-label="知识页面追溯详情"></div>
          <details class="fed-health-sources" id="fed-health-sources"><summary id="fed-health-source-count">已记录来源</summary><div id="fed-health-source-list"></div></details>
          <p class="fed-micro">状态仅在打开此页、切换知识库或点击刷新时读取。学习或资料变更后，请刷新核对；此面板不会批准或发布知识。</p>
        </section>
        <section id="fed-review-panel" hidden><div class="fed-section-head"><h3>审核当前知识快照</h3><button class="fed-button" id="fed-review-reload" type="button">重新加载</button></div><p class="fed-intro">请逐页检查事实、来源与适用范围。只有你点击批准，本次快照才会发布；后续变更需要重新审核。</p><div class="fed-review-health"><p class="fed-micro" id="fed-review-health-summary"></p><p class="fed-micro" id="fed-review-health-note"></p><button class="fed-button" id="fed-review-health-open" type="button">查看知识状态</button></div><div class="fed-empty" id="fed-review-empty" hidden>当前没有待发布知识。先在这个分支导入资料并完成学习。</div><div id="fed-review-content" hidden><div class="fed-review-summary"><strong id="fed-review-count"></strong><p id="fed-review-progress"></p><ul id="fed-review-list"></ul></div><label class="fed-label" for="fed-review-select">逐页核对正文</label><select id="fed-review-select"></select><pre class="fed-pre" id="fed-review-body" tabindex="0"></pre><p class="fed-path" id="fed-review-path"></p><label class="fed-approve"><input id="fed-approve" type="checkbox"><span>我已核对当前快照的全部页面，批准将这些知识发布到中央。</span></label><button class="fed-button primary fed-full" id="fed-publish" type="button" disabled>批准并发布当前快照</button><p class="fed-micro">发布成功后自动触发中央汇总。汇总由模型执行，可能需要数分钟。</p></div></section>
        <section class="fed-job" id="fed-job" aria-live="polite" hidden><div class="fed-job-head"><span class="fed-job-dot" id="fed-job-dot"></span><strong id="fed-job-title"></strong><span class="fed-job-state" id="fed-job-state"></span></div><p class="fed-micro" id="fed-job-message"></p><details id="fed-job-details"><summary>查看实际执行输出</summary><pre class="fed-pre" id="fed-job-output"></pre></details></section>
      </div>
    </dialog>
    <dialog class="fed-dialog fed-new-dialog" id="fed-new-dialog" aria-labelledby="fed-new-title"><div class="fed-dialog-header"><div><p class="fed-eyebrow">OPENWIKI · 行业知识网络</p><h2 id="fed-new-title">新增知识库分支</h2></div><button class="icon-btn" id="fed-new-close" type="button" aria-label="关闭新增分支">×</button></div><div class="fed-body"><p class="fed-intro">选择所属知识库，建立下一级独立分支和对应 Agent。选择中央可新增行业；选择行业或专业可继续细分。</p><form id="fed-new-form"><label class="fed-label" for="fed-new-parent">所属知识库</label><select id="fed-new-parent" required></select><p class="fed-micro" id="fed-new-depth-note">分支最多细分到第 6 层，每一层都有独立知识库与 Agent。</p><label class="fed-label" for="fed-new-name">分支名称</label><input id="fed-new-name" maxlength="40" required placeholder="例如：前端、App、后端、运维、测试"><label class="fed-label" for="fed-new-description">这个分支关注什么</label><textarea id="fed-new-description" rows="3" maxlength="300" placeholder="描述这个分支需要积累的知识范围。"></textarea><p class="fed-notice error" id="fed-new-error" role="alert" hidden></p><button class="fed-button primary fed-full" id="fed-new-submit" type="submit">创建分支与 Agent</button></form></div></dialog>`;
  document.body.append(template.content);

  async function api(path, options = {}) {
    let response; try { response = await fetch(path, { cache: "no-store", ...options, headers: { "Content-Type": "application/json", ...(options.headers || {}) } }); }
    catch { throw new Error("无法连接本地服务。请确认启动窗口仍在运行，再重新打开知识库操作。"); }
    let body; try { body = await response.json(); } catch { throw new Error(`服务响应无法读取（HTTP ${response.status}）。`); }
    if (!response.ok) { const detail = body.detail || body.error || body.message; throw new Error(typeof detail === "string" ? detail : output(detail) || `操作未完成（HTTP ${response.status}）。`); }
    return body;
  }
  function notify(message, error = false) { $("notice").textContent = message; $("notice").hidden = !message; $("notice").classList.toggle("error", error); }
  function changed() { window.dispatchEvent(new Event("federation:changed")); }
  function saveDraft() { state.drafts.set(state.selected, { filename: $("filename").value, text: $("source-text").value, question: $("question").value }); }
  function restoreDraft() { const draft = state.drafts.get(state.selected) || {}; $("filename").value = draft.filename || ""; $("source-text").value = draft.text || ""; $("question").value = draft.question || ""; $("file").value = ""; }

  async function refresh() {
    const data = await api("/api/federation"); state.data = data;
    for (const item of data.jobs || []) {
      state.jobs.set(item.id, { ...state.jobs.get(item.id), ...item });
      if (["queued", "running"].includes(item.status)) poll(item.id);
      if (item.action === "ask" && item.status === "completed") rememberAnswer(item);
    }
    const spaces = orderedSpaces();
    $("space").replaceChildren(...spaces.map((item) => { const option = make("option", "", breadcrumb(item)); option.value = item.id; return option; }));
    if (!space()) state.selected = "central";
    $("space").value = state.selected; renderHeader(); renderJob();
    if ($("dialog").open) renderAnswers();
  }
  function renderHeader() {
    const selected = space(); if (!selected) return;
    const central = state.selected === "central";
    manage.textContent = `${central ? "中央" : selected.name} · 知识库操作`;
    manage.title = `${breadcrumb(selected)} · 资料、知识状态、学习、问答与发布`;
    manage.classList.toggle("fed-active-job", Boolean(activeJob(state.selected)));
    $("title").textContent = selected.name;
    $("breadcrumb").textContent = breadcrumb(selected);
    $("main").textContent = central ? "汇总知识" : "开始学习";
    const hasPublished = (state.data.branches || []).some((branch) => number(branch.published_count) > 0);
    $("main").disabled = Boolean(activeJob(state.selected)) || (central ? !hasPublished : !number(selected.source_count));
    const industries = (state.data.branches || []).filter((branch) => branch.parent_id === "central" || (!branch.parent_id && !branch.depth)).length;
    $("stats").textContent = central ? `${knowledge(selected)} 页综合知识 · ${industries} 个行业 · ${(state.data.branches || []).length - industries} 个专业分支` : `${number(selected.source_count)} 份资料 · ${knowledge(selected)} 页知识 · ${number(selected.pending_count)} 页待审核${number(selected.child_count) ? ` · ${number(selected.child_count)} 个子分支` : ""}`;
    $("ask-intro").textContent = central ? "综合参考已审核汇入的行业与专业知识。问答读取隔离副本，不会改写或发布正式知识。" : "参考当前分支的独立知识。问答读取隔离副本，不会改写或发布正式知识。";
    $("source-submit").textContent = `导入到${selected.name}`;
    $("ask-submit").disabled = Boolean(activeJob(state.selected));
    if (central && !["ask", "health"].includes(state.tab)) state.tab = "ask";
    renderTabs();
  }
  function renderTabs() {
    const tabs = state.selected === "central" ? [["ask", "跨行业提问"], ["health", "知识状态"]] : [["sources", "资料"], ["ask", "分支提问"], ["health", "知识状态"], ["review", "审核发布"]];
    $("tabs").replaceChildren(...tabs.map(([id, title]) => { const button = make("button", `fed-tab${state.tab === id ? " active" : ""}`, title); button.type = "button"; button.setAttribute("aria-current", state.tab === id ? "page" : "false"); button.addEventListener("click", async () => { state.tab = id; notify(""); renderTabs(); if (id === "review" && !state.review) await loadReview(); if (id === "sources") await loadSources(); if (id === "health") await loadKnowledgeHealth(); }); return button; }));
    for (const id of ["sources", "ask", "health", "review"]) $(`${id}-panel`).hidden = state.tab !== id;
  }
  async function selectSpace(id) {
    if (!space(id)) return;
    saveDraft(); state.selected = id; state.tab = state.tab === "health" ? "health" : id === "central" ? "ask" : "sources"; state.review = null; state.visited.clear(); state.revision++; state.reviewRevision++; state.knowledgeRevision++;
    $("approve").checked = false; $("space").value = id; restoreDraft(); notify(""); renderHeader(); renderJob(); renderAnswers();
    if ($("dialog").open && state.tab === "health") await loadKnowledgeHealth();
    else if (id !== "central" && $("dialog").open) await loadSources();
  }
  function knowledgeSourceURL(value) {
    if (typeof value !== "string" || /[\u0000-\u0020\u007f]/u.test(value)) return null;
    try {
      const url = new URL(value);
      return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null;
    } catch { return null; }
  }
  function knowledgeReasonText(reason) {
    const codes = {
      no_learning_record: "没有学习追溯记录（历史页面未自动认定为已追溯）", metadata_unreadable: "追溯记录无法读取，请检查元数据",
      page_changed_after_learning: "页面在学习后发生修改，当前正文尚未建立对应追溯", learning_inputs_unavailable: "该次学习没有可用的输入来源记录",
      invalid_source_record: "来源记录格式无效", input_not_verified_at_learning: "学习时输入资料未通过完整性核对",
      source_missing: "已记录的来源缺失", source_conflict: "来源版本或完整性冲突", source_version_changed: "当前来源版本与学习时记录的版本不同",
      source_check_time_unknown: "来源核查日期未记录，需要复核", source_review_due: "来源核查已到复核期",
      invalid_web_url: "网络来源地址无效", web_index_hash_conflict: "网络来源索引与文件哈希不一致", web_content_version_missing: "网络来源缺少内容版本",
      superseded_source_still_in_inputs: "已替代的旧来源仍存在于输入资料中", duplicate_web_source_identity: "网络来源身份重复",
      published_origin_unknown: "发布快照的上游来源不明", publication_manifest_missing: "发布快照清单缺失",
      published_snapshot_hash_conflict: "发布快照与登记哈希不一致", published_provenance_unavailable: "已发布知识缺少可用追溯记录",
      web_index_unreadable: "网络来源索引无法读取",
    };
    if (typeof reason === "string") return Object.hasOwn(codes, reason) ? codes[reason] : reason;
    if (!reason || typeof reason !== "object" || Array.isArray(reason)) return "";
    const text = [reason.message, reason.reason, reason.text].find((value) => typeof value === "string" && value);
    return text || (typeof reason.code === "string" ? Object.hasOwn(codes, reason.code) ? codes[reason.code] : reason.code : "");
  }
  function renderKnowledgeEvidence(source) {
    const row = make("div", "fed-health-evidence");
    const label = make("p", "fed-source-name", source.name || "未命名来源");
    row.append(label);
    const sourceStatus = ({ available: "文件可读取", missing: "来源缺失", conflict: "来源冲突", current: "记录版本一致", changed: "来源版本已变化" })[source.status] || "来源状态未记录";
    const freshness = ({ current: "未到复核期", review_due: "待复核", unknown: "核查日期未记录" })[source.freshness] || "核查日期未记录";
    const kind = ({ web: "网络资料", local: "本地资料", published: "已发布知识" })[source.kind] || source.kind || "类型未记录";
    row.append(make("p", "fed-source-meta", `${kind} · ${sourceStatus} · ${freshness}`));
    row.append(make("p", "fed-health-id", `来源 ID：${source.source_id || "未记录"}`), make("p", "fed-health-id", `来源版本 SHA-256：${source.version || "未记录"}`));
    if (source.current_version) row.append(make("p", "fed-health-id", `当前来源版本 SHA-256：${source.current_version}`));
    if (source.current_name && source.current_name !== source.name) row.append(make("p", "fed-source-meta", `当前来源名称：${source.current_name}`));
    if (source.space_id) row.append(make("p", "fed-source-meta", `所属知识库：${source.space_id}`));
    row.append(make("p", "fed-source-meta", `记录的核查时间：${source.checked_at || "未记录"}`));
    if (typeof source.url === "string" && source.url) {
      const url = knowledgeSourceURL(source.url), link = make(url ? "a" : "span", "fed-health-url", source.url);
      if (url) { link.href = url; link.target = "_blank"; link.rel = "noopener noreferrer"; }
      row.append(link);
    }
    if (source.upstream_space_id || source.upstream_page_id || source.upstream_version) {
      row.append(make("p", "fed-health-id", `上游知识库：${source.upstream_space_id || "未记录"}`),
        make("p", "fed-health-id", `上游页面 ID：${source.upstream_page_id || "未记录"}`),
        make("p", "fed-health-id", `上游版本 SHA-256：${source.upstream_version || "未记录"}`));
    }
    const reasons = (Array.isArray(source.reasons) ? source.reasons : []).map(knowledgeReasonText).filter(Boolean);
    if (reasons.length) { const list = make("ul", "fed-health-reasons"); reasons.forEach((reason) => list.append(make("li", "", reason))); row.append(list); }
    return row;
  }
  function renderKnowledgeHealth(data) {
    const labels = { current: "已记录", stale: "待更新", untracked: "未追溯", review_due: "待复核" };
    const pages = Array.isArray(data.pages) ? data.pages.filter((item) => item && typeof item === "object" && !Array.isArray(item)) : [];
    const sources = Array.isArray(data.sources) ? data.sources.filter((item) => item && typeof item === "object" && !Array.isArray(item)) : [];
    const summary = data.summary && typeof data.summary === "object" ? data.summary : {};
    const statuses = pages.map((page) => Object.hasOwn(labels, page.status) ? page.status : "untracked");
    const counters = [["total", "全部页面"], ...Object.entries(labels)].map(([key, title]) => {
      const fallback = key === "total" ? pages.length : statuses.filter((value) => value === key).length;
      const value = typeof summary[key] === "number" && Number.isFinite(summary[key]) && summary[key] >= 0 ? summary[key] : fallback;
      const card = make("div", `fed-health-metric fed-health-${key}`);
      card.append(make("strong", "", value), make("span", "", title)); return card;
    });
    $("health-summary").replaceChildren(...counters);
    $("health-pages").replaceChildren(...(pages.length ? pages.map((page, index) => {
      const status = statuses[index], card = make("details", "fed-health-page"), heading = make("summary", "fed-health-heading");
      heading.append(make("span", "", page.title || page.path || "未命名知识页"), make("span", `fed-health-badge fed-health-${status}`, labels[status]));
      card.append(heading);
      const body = make("div", "fed-health-page-body");
      body.append(make("p", "fed-health-id", `页面路径：${page.path || "未记录"}`), make("p", "fed-health-id", `稳定页面 ID：${page.page_id || "未记录"}`), make("p", "fed-health-id", `页面版本 SHA-256：${page.version || "未记录"}`));
      if (page.recorded_version && page.recorded_version !== page.version) body.append(make("p", "fed-health-id", `学习时页面版本 SHA-256：${page.recorded_version}`));
      if (page.run_id || page.recorded_at) body.append(make("p", "fed-source-meta", `学习记录：${page.run_id || "未记录"} · ${page.recorded_at || "时间未记录"}`));
      const reasons = (Array.isArray(page.reasons) ? page.reasons : []).map(knowledgeReasonText).filter(Boolean);
      const defaults = { current: "页面与已记录的来源版本一致；内容事实仍需核对。", stale: "页面或来源记录需要更新，请核对版本变化。", untracked: "没有可用的页面来源追溯记录，不能据此判断版本一致。", review_due: "来源核查记录待复核，请核对日期与适用范围。" };
      const reasonList = make("ul", "fed-health-reasons");
      (reasons.length ? reasons : [defaults[status]]).forEach((reason) => reasonList.append(make("li", "", reason))); body.append(reasonList);
      const evidence = Array.isArray(page.evidence) ? page.evidence.filter((item) => item && typeof item === "object" && !Array.isArray(item)) : [];
      body.append(make("h4", "", `记录的来源 · ${evidence.length}`));
      if (evidence.length) evidence.forEach((source) => body.append(renderKnowledgeEvidence(source)));
      else body.append(make("p", "fed-micro", "这页没有可展示的来源版本记录；旧数据不会自动视为已追溯。"));
      card.append(body); return card;
    }) : [make("p", "fed-empty", "当前知识库还没有知识页面。已有资料和知识页面是不同的记录。") ]));
    $("health-source-count").textContent = `已记录来源 · ${sources.length}`;
    $("health-source-list").replaceChildren(...(sources.length ? sources.map(renderKnowledgeEvidence) : [make("p", "fed-empty", "当前没有已记录的来源。") ]));
    $("health-status").classList.remove("error");
    $("health-status").textContent = `${space()?.name || state.selected} · 已读取本次状态快照${data.checked_at ? ` · 检查时间：${data.checked_at}` : ""}`;
    if (typeof data.metadata_error === "string" && data.metadata_error) { $("health-status").textContent += ` · 追溯记录异常：${data.metadata_error}`; $("health-status").classList.add("error"); }
  }
  async function loadKnowledgeHealth() {
    const id = state.selected, revision = ++state.knowledgeRevision;
    $("health-reload").disabled = true; $("health-status").classList.remove("error"); $("health-status").textContent = "正在读取知识状态与来源版本…";
    $("health-summary").replaceChildren(); $("health-pages").replaceChildren(); $("health-source-list").replaceChildren(); $("health-source-count").textContent = "已记录来源";
    try {
      const data = await api(`/api/spaces/${encodeURIComponent(id)}/knowledge-health`);
      if (id !== state.selected || revision !== state.knowledgeRevision || state.tab !== "health" || !$("dialog").open) return;
      if (!data || typeof data !== "object" || data.space_id !== id || !Array.isArray(data.pages)) throw new Error("知识状态响应与当前知识库不一致，请刷新重试。");
      renderKnowledgeHealth(data);
    } catch (error) {
      if (id === state.selected && revision === state.knowledgeRevision && state.tab === "health" && $("dialog").open) { $("health-status").textContent = error.message || "知识状态读取失败，请刷新重试。"; $("health-status").classList.add("error"); }
    } finally { if (revision === state.knowledgeRevision) $("health-reload").disabled = false; }
  }
  async function loadSources() {
    const id = state.selected, revision = ++state.revision; if (id === "central") return;
    try { const data = await api(`/api/spaces/${encodeURIComponent(id)}/sources`); if (id !== state.selected || revision !== state.revision) return;
      const sources = data.sources || []; $("source-count").textContent = `${sources.length} 份`;
      $("source-list").replaceChildren(...(sources.length ? sources.map((source) => { const row = make("div", "fed-source"); row.append(make("p", "fed-source-name", source.name), make("p", "fed-source-meta", `${number(source.bytes)} 字节${source.modified_at ? ` · ${niceDate(source.modified_at)}` : ""}`)); return row; }) : [make("p", "fed-empty", "尚未导入资料。这个分支还没有可学习的原始内容。") ]));
    } catch (error) { if (id === state.selected) notify(error.message, true); }
  }
  async function loadReview() {
    const id = state.selected, revision = ++state.reviewRevision; if (id === "central") return;
    $("review-reload").disabled = true; $("publish").disabled = true;
    try { const review = await api(`/api/spaces/${encodeURIComponent(id)}/review`); if (id !== state.selected || revision !== state.reviewRevision) return;
      state.review = review; state.visited.clear(); $("approve").checked = false; renderReviewKnowledge(review.knowledge);
      const pending = knowledge(space()) > 0 && number(space()?.pending_count) > 0, pages = review.pages || [];
      $("review-empty").hidden = pending; $("review-content").hidden = !pending;
      $("review-count").textContent = `本次快照 ${pages.length} 页 · ${number(space()?.pending_count)} 页发生变更`;
      $("review-select").replaceChildren(...pages.map((page, index) => { const option = make("option", "", `${index + 1}. ${page.title || page.path}`); option.value = page.path; return option; })); renderReviewPage();
    } catch (error) { if (id === state.selected) notify(error.message, true); }
    finally { if (revision === state.reviewRevision) $("review-reload").disabled = false; }
  }
  function renderReviewKnowledge(health) {
    const summary = health?.summary;
    if (!summary || typeof summary !== "object" || Array.isArray(summary)) {
      $("review-health-summary").textContent = "当前审核快照没有可展示的知识追溯统计。";
      $("review-health-note").textContent = "请在知识状态中核对旧页面与来源记录；缺少追溯不自动认定为版本一致。";
      return;
    }
    const labels = { current: "已记录", stale: "待更新", untracked: "未追溯", review_due: "待复核" };
    const counts = Object.fromEntries(Object.keys(labels).map((key) => [key, Math.max(0, number(summary[key]))]));
    $("review-health-summary").textContent = `审核快照的知识状态：${Object.entries(labels).map(([key, title]) => `${title} ${counts[key]} 页`).join(" · ")}`;
    $("review-health-note").textContent = `${counts.stale || counts.untracked || counts.review_due ? "存在待更新、未追溯或待复核页面，请查看知识状态后结合正文审核。" : "已记录只表示页面与记录的来源版本一致，事实仍需人工核对。"} 来源版本在审核后发生变化时，需要重新加载审核快照。`;
  }
  function renderReviewPage() { const page = state.review?.pages?.find((item) => item.path === $("review-select").value); if (page) { $("review-body").textContent = page.body || "（页面暂无正文）"; $("review-body").scrollTop = 0; $("review-path").textContent = page.path; state.visited.add(page.path); } renderReviewProgress(); }
  function renderReviewProgress() { const pages = state.review?.pages || []; $("review-progress").textContent = `已打开 ${state.visited.size} / ${pages.length} 页，请核对全部正文后批准。`; $("review-list").replaceChildren(...pages.map((page) => make("li", state.visited.has(page.path) ? "visited" : "", `${state.visited.has(page.path) ? "✓" : "○"} ${page.title || page.path}`))); $("publish").disabled = !pages.length || !state.review?.token || state.visited.size !== pages.length || !$("approve").checked || Boolean(activeJob(state.selected)); }

  function rememberAnswer(job) { const answers = state.answers.get(job.space) || []; if (!answers.some((answer) => answer.id === job.id)) answers.unshift({ id: job.id, question: job.question || "智能体回答", output: output(job.answer) || output(job.output) || "任务完成，但服务没有返回回答正文。", created_at: job.created_at }); answers.sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || ""))); state.answers.set(job.space, answers); }
  function renderAnswers() { $("answers").replaceChildren(...(state.answers.get(state.selected) || []).map((answer) => { const article = make("article", "fed-answer"); article.append(make("h3", "", answer.question), make("pre", "fed-pre", answer.output)); return article; })); }
  function renderJob() {
    const jobs = [...state.jobs.values()].filter((job) => job.space === state.selected).sort((a, b) => String(b.created_at || "").localeCompare(String(a.created_at || "")));
    const job = jobs.find((item) => ["queued", "running"].includes(item.status)) || jobs[0]; $("job").hidden = !job; $("ask-submit").disabled = Boolean(activeJob(state.selected));
    if (!job) return;
    $("job-title").textContent = actionName(job.action); $("job-state").textContent = ({ queued: "等待执行", running: "正在执行", completed: "已完成", failed: "未完成" })[job.status] || job.status;
    $("job-dot").className = `fed-job-dot ${job.status}`;
    $("job-message").textContent = job.status === "queued" ? "任务已进入队列，正在等待模型。" : job.status === "running" ? "模型正在处理，可能需要数分钟。这里显示实际执行状态，请保持服务运行。" : job.status === "failed" ? output(job.error) || "任务未完成，请检查执行输出。" : job.action === "ask" ? "回答已生成，正式知识库未被问答修改。" : "本次模型任务已结束。请核对生成内容，完成不代表事实审核通过。";
    const text = output(job.output) || output(job.error); $("job-output").textContent = text; $("job-details").hidden = !text;
  }
  async function submitJob(action, question) {
    const id = state.selected; if (activeJob(id)) { notify("当前空间已有任务执行，请等待完成后再提交。"); return; }
    $("main").disabled = $("ask-submit").disabled = true;
    try { const result = await api("/api/jobs", { method: "POST", body: JSON.stringify({ action, space: id, ...(question ? { question } : {}) }) }); if (!result.id) throw new Error("服务未返回任务编号，请刷新核对后再试。");
      state.jobs.set(result.id, { ...result, space: result.space || id, action: result.action || action, question: question || result.question }); poll(result.id);
      if (id === state.selected) notify(`${actionName(action)}任务已提交，完成后会更新这里的实际结果。`); renderJob();
    } catch (error) { if (id === state.selected) notify(error.message, true); } finally { renderHeader(); }
  }
  function poll(id) {
    if (state.polling.has(id)) return; state.polling.add(id); let errors = 0;
    async function tick() {
      try { const job = await api(`/api/jobs/${encodeURIComponent(id)}`); const merged = { ...state.jobs.get(id), ...job }; state.jobs.set(id, merged); errors = 0; renderHeader(); renderJob();
        if (["completed", "failed"].includes(job.status)) { state.polling.delete(id); if (job.action === "ask" && job.status === "completed") { rememberAnswer(merged); if (job.space === state.selected) renderAnswers(); }
          await refresh(); changed();
          if (job.space === state.selected) { if (job.action !== "ask") { state.review = null; $("approve").checked = false; if (state.tab === "review") await loadReview(); if (state.tab === "sources") await loadSources(); } notify(job.status === "failed" ? `${actionName(job.action)}未完成：${output(job.error) || "请检查执行输出。"}` : `${actionName(job.action)}已完成。${job.action === "ask" ? "回答在问题下方。" : "请查看原版知识页面并核对内容。"}`, job.status === "failed"); } return;
        }
        setTimeout(tick, 2000);
      } catch (error) { errors++; if (errors >= 5) { state.polling.delete(id); if (state.jobs.get(id)?.space === state.selected) notify(`暂时无法获取任务状态：${error.message} 任务可能仍在运行，请重新打开知识库操作核对。`, true); return; } setTimeout(tick, 2000); }
    }
    setTimeout(tick, 500);
  }

  manage.addEventListener("click", async () => { $("dialog").showModal(); try { await refresh(); if (state.selected !== "central" && state.tab === "sources") await loadSources(); if (state.tab === "review") await loadReview(); if (state.tab === "health") await loadKnowledgeHealth(); } catch (error) { notify(error.message, true); } });
  $("close").addEventListener("click", () => $("dialog").close());
  $("dialog").addEventListener("close", () => { saveDraft(); state.knowledgeRevision++; $("health-reload").disabled = false; });
  $("space").addEventListener("change", () => selectSpace($("space").value));
  $("main").addEventListener("click", () => submitJob(state.selected === "central" ? "sync" : "learn"));
  $("review-reload").addEventListener("click", () => { state.review = null; loadReview(); });
  $("review-health-open").addEventListener("click", () => { state.tab = "health"; renderTabs(); loadKnowledgeHealth(); });
  $("health-reload").addEventListener("click", loadKnowledgeHealth);
  $("review-select").addEventListener("change", renderReviewPage); $("approve").addEventListener("change", renderReviewProgress);
  $("file").addEventListener("change", async (event) => { const file = event.target.files[0], id = state.selected; if (!file) return; if (!/\.(md|txt)$/i.test(file.name)) { notify("请选择 .md 或 .txt 文本文件。", true); return; } if (file.size > 80000) { notify("单份资料最多 80000 个 UTF-8 字节，请拆分后导入。", true); return; } try { const body = await file.text(); if (id !== state.selected) return; if (new TextEncoder().encode(body).length > 80000) { notify("单份资料超过 80000 个 UTF-8 字节，请拆分后导入。", true); return; } $("filename").value = file.name; $("source-text").value = body; saveDraft(); notify("文件已读入表单。核对后点击导入保存。"); } catch { if (id === state.selected) notify("无法读取文件，请改用粘贴资料。", true); } });
  $("source-form").addEventListener("submit", async (event) => { event.preventDefault(); const id = state.selected, filename = $("filename").value.trim(), text = $("source-text").value; if (id === "central") return; if (!/\.(md|txt)$/i.test(filename) || !text.trim()) { notify("请填写 .md / .txt 文件名和资料正文。", true); return; } if (new TextEncoder().encode(text).length > 80000) { notify("单份资料最多 80000 个 UTF-8 字节，请拆分后导入。", true); return; } $("source-submit").disabled = true;
    try { await api(`/api/spaces/${encodeURIComponent(id)}/sources`, { method: "POST", body: JSON.stringify({ filename, text }) }); if (id === state.selected) { $("filename").value = $("source-text").value = $("file").value = ""; saveDraft(); notify("资料已导入。点击“开始学习”整理当前分支知识。"); } await refresh(); if (id === state.selected) await loadSources(); changed(); } catch (error) { if (id === state.selected) notify(error.message, true); } finally { $("source-submit").disabled = false; }
  });
  $("ask-form").addEventListener("submit", (event) => { event.preventDefault(); const question = $("question").value.trim(); if (question) { saveDraft(); submitJob("ask", question); } });
  $("publish").addEventListener("click", async () => { const review = state.review, id = state.selected; if (!review?.token || !review.pages?.length || state.visited.size !== review.pages.length || !$("approve").checked) return; $("publish").disabled = true;
    try { const result = await api(`/api/spaces/${encodeURIComponent(id)}/publish`, { method: "POST", body: JSON.stringify({ token: review.token }) }); if (result.job?.id) { state.jobs.set(result.job.id, { ...result.job, space: result.job.space || "central", action: result.job.action || "sync" }); poll(result.job.id); } if (id === state.selected) { state.review = null; $("approve").checked = false; notify(`已批准并发布 ${number(result.published_count)} 个页面。${result.job?.id ? "中央汇总已进入队列，选择中央空间可查看进度。" : "请选择中央空间，点击汇总知识。"}`); } await refresh(); if (id === state.selected) await loadReview(); changed(); } catch (error) { if (id === state.selected) { notify(`发布未完成：${error.message}`, true); renderReviewProgress(); } }
  });
  add.addEventListener("click", async () => {
    $("new-error").hidden = true; $("new-submit").disabled = true; $("new-dialog").showModal();
    try {
      await refresh();
      $("new-parent").replaceChildren(...orderedSpaces().map((item) => { const limited = number(item.depth) >= 6; const option = make("option", "", `${breadcrumb(item)}${item.id === "central" ? "（新增行业）" : limited ? "（已达层级上限）" : ""}`); option.value = item.id; option.disabled = limited; return option; }));
      $("new-parent").value = space(state.selected) ? state.selected : "central"; renderParentChoice(); $("new-name").focus();
    } catch (error) { $("new-error").textContent = error.message; $("new-error").hidden = false; }
  });
  function renderParentChoice() {
    const limited = number(space($("new-parent").value)?.depth) >= 6;
    $("new-submit").disabled = limited;
    $("new-depth-note").textContent = limited ? "当前分支已达第 6 层，无法继续细分。请选择一个较上层的所属知识库。" : "分支最多细分到第 6 层，每一层都有独立知识库与 Agent。";
  }
  $("new-parent").addEventListener("change", renderParentChoice);
  $("new-close").addEventListener("click", () => $("new-dialog").close());
  $("new-form").addEventListener("submit", async (event) => { event.preventDefault(); const name = $("new-name").value.trim(), description = $("new-description").value.trim(), parent_id = $("new-parent").value; if (!name || !parent_id || number(space(parent_id)?.depth) >= 6) return; $("new-submit").disabled = true; $("new-error").hidden = true;
    try { const response = await api("/api/branches", { method: "POST", body: JSON.stringify({ name, description, parent_id }) }); const branch = response.branch || response; $("new-dialog").close(); $("new-form").reset(); await refresh(); if (branch.id) await selectSpace(branch.id); changed(); $("dialog").showModal(); await loadSources(); notify(`“${name}”的独立知识库与 Agent 已建立。导入资料即可开始学习，也可从 Agent 聊天中选择它。`); } catch (error) { $("new-error").textContent = error.message; $("new-error").hidden = false; } finally { $("new-submit").disabled = false; }
  });
  document.addEventListener("openwiki:select", (event) => { const id = event.detail?.spaceId; if (id && space(id) && id !== state.selected) selectSpace(id); });
  refresh().catch((error) => { manage.title = error.message; });
})();
