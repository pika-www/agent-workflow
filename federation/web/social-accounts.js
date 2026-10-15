/* Account preparation and saved read-only observations. No platform credentials enter this UI. */
(() => {
  "use strict";
  const topbar = document.querySelector(".topbar");
  if (!topbar || document.getElementById("social-dialog")) return;
  const make = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = String(text); return node; };
  const button = (text, cls = "social-button") => { const node = make("button", cls, text); node.type = "button"; return node; };
  const capabilities = { read: "读取内容与数据、辅助分析", publish: "确认后发布", comments: "评论管理", messages: "私信管理" };
  const applicationStatuses = { unknown: "尚未说明", not_created: "尚未创建应用", applied: "已提交申请，待审核", approved: "我已获批（尚未核验）" };
  const localPolicy = "本页管理接入准备与已保存的只读快照。平台 API 授权尚未完成；刷新仅重新读取本地记录，不会采集新的平台数据。";
  const state = { data: null, loading: false, saving: false, editor: null, opener: null };
  const launch = button("社交账号", "icon-btn social-launch"); launch.id = "social-launch";
  launch.title = "查看已保存的只读快照，管理六个平台的接入准备";
  const toolbar = document.querySelector(".federation-toolbar");
  if (toolbar) toolbar.append(launch); else topbar.append(launch);
  const dialog = make("dialog", "social-dialog"); dialog.id = "social-dialog"; dialog.setAttribute("aria-labelledby", "social-title");
  const header = make("header", "social-header"), heading = make("div");
  const title = make("h2", "", "社交账号中心"); title.id = "social-title";
  heading.append(make("p", "social-eyebrow", "OPENWIKI · 账号接入"), title);
  const close = button("×", "icon-btn social-close"); close.setAttribute("aria-label", "关闭社交账号中心");
  header.append(heading, close);
  const body = make("div", "social-body"), policy = make("p", "social-policy", localPolicy);
  policy.id = "social-policy";
  const summaryRow = make("div", "social-summary-row"), summary = make("p", "social-summary", "正在读取本地记录…"), refresh = button("刷新本地记录");
  refresh.title = "重新读取已保存的准备记录和快照，不会采集新的平台数据";
  summary.id = "social-summary"; refresh.id = "social-refresh"; summaryRow.append(summary, refresh);
  const notice = make("p", "social-notice"); notice.id = "social-notice"; notice.hidden = true; notice.setAttribute("role", "status"); notice.setAttribute("aria-live", "polite");
  const editor = make("section", "social-editor"); editor.id = "social-editor"; editor.hidden = true; editor.setAttribute("aria-labelledby", "social-editor-title");
  const editorTitle = make("h3"); editorTitle.id = "social-editor-title";
  const form = make("form"), fields = make("fieldset", "social-fields");
  const nameLabel = make("label", "social-label", "账号别名"), name = make("input"); name.id = "social-account-label"; name.type = "text"; name.required = true; name.maxLength = 60; name.autocomplete = "off"; name.placeholder = "例如：个人号、工作室号"; nameLabel.htmlFor = name.id;
  const statusLabel = make("label", "social-label", "开放平台应用申请状态"), status = make("select"); status.id = "social-application-status"; statusLabel.htmlFor = status.id;
  for (const [value, text] of Object.entries(applicationStatuses)) { const option = make("option", "", text); option.value = value; status.append(option); }
  const choices = make("fieldset", "social-choices"); choices.append(make("legend", "", "希望接入的功能（记录需求，不代表已开通）"));
  const checks = new Map();
  for (const [id, text] of Object.entries(capabilities)) { const label = make("label"), input = make("input"); input.type = "checkbox"; input.value = id; input.id = `social-capability-${id}`; checks.set(id, input); label.append(input, make("span", "", text)); choices.append(label); }
  const formNote = make("p", "social-muted", "这里只记录别名、申请进度和功能需求。无需填写密码、Cookie、密钥或 Token；申请获批也不等于账号授权完成。"); formNote.id = "social-form-note"; form.setAttribute("aria-describedby", formNote.id);
  const formActions = make("div", "social-form-actions"), save = button("保存准备记录", "social-button social-primary"), cancel = button("收起表单");
  save.type = "submit"; save.id = "social-save"; cancel.id = "social-cancel"; formActions.append(save, cancel);
  fields.append(nameLabel, name, statusLabel, status, choices, formNote, formActions); form.append(fields); editor.append(editorTitle, form);
  const grid = make("div", "social-grid"); grid.id = "social-providers";
  body.append(policy, summaryRow, notice, editor, grid); dialog.append(header, body); document.body.append(dialog);
  const chatActions = document.querySelector(".ag-header-actions");
  let chatLaunch;
  if (chatActions) { chatLaunch = button("社交账号", "ag-button"); chatLaunch.id = "social-chat-launch"; chatActions.prepend(chatLaunch); }

  function notify(text, error = false) { notice.textContent = text; notice.hidden = !text; notice.classList.toggle("social-error", error); }
  function busy() {
    fields.disabled = state.saving;
    refresh.disabled = state.loading || state.saving;
    save.textContent = state.saving ? "保存中…" : "保存准备记录";
    for (const item of grid.querySelectorAll("button")) item.disabled = state.saving || state.loading;
    dialog.setAttribute("aria-busy", String(state.loading || state.saving));
  }
  function officialLink(label, value) {
    try { const url = new URL(value); if (url.protocol !== "https:" || url.username || url.password) return null;
      const node = make("a", "social-link", label); node.href = url.href; node.target = "_blank"; node.rel = "noopener noreferrer"; return node;
    } catch { return null; }
  }
  async function api(path, options = {}) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
    const timeoutMessage = "本地服务请求超时（20 秒）。输入已保留；请刷新核对记录后再重试。";
    try {
      let response;
      try { response = await fetch(path, { cache: "no-store", ...options, signal: controller.signal, headers: { "Content-Type": "application/json", ...(options.headers || {}) } }); }
      catch { throw new Error(controller.signal.aborted ? timeoutMessage : "无法连接本地服务。输入已保留；请刷新核对记录后再重试。"); }
      let payload;
      try { payload = await response.json(); } catch { throw new Error(controller.signal.aborted ? timeoutMessage : `本地服务响应无法读取（HTTP ${response.status}）。输入已保留。`); }
      if (!response.ok) { const detail = payload?.detail; throw new Error(typeof detail === "string" ? detail.slice(0, 500) : `操作未完成（HTTP ${response.status}），请核对填写内容。`); }
      return payload;
    } finally { clearTimeout(timer); }
  }
  function showEditor(provider, account = null, opener = null) {
    if (state.saving || state.loading) return;
    state.editor = { provider, account, opener };
    editorTitle.textContent = `${account ? "编辑" : "添加"}${provider.name}账号准备记录`;
    name.value = account?.label || "";
    status.value = Object.hasOwn(applicationStatuses, account?.application_status) ? account.application_status : "unknown";
    const requested = account?.requested_capabilities || (provider.id === "douyin" ? ["read"] : Object.keys(capabilities));
    for (const [id, input] of checks) input.checked = requested.includes(id);
    editor.hidden = false; notify(""); name.focus();
  }
  function hideEditor() {
    const opener = state.editor?.opener; editor.hidden = true; state.editor = null;
    if (dialog.open) { if (opener?.isConnected) opener.focus(); else refresh.focus(); }
  }
  function renderSnapshot(snapshot) {
    const section = make("section", "social-snapshot");
    section.setAttribute("aria-label", "已保存的只读数据快照");
    const heading = make("div", "social-snapshot-heading");
    heading.append(make("h4", "", snapshot.account?.display_name || "账号名称未记录"), make("span", "social-snapshot-kind", "本地只读快照"));
    section.append(heading);
    if (snapshot.account?.account_identifier) section.append(make("p", "social-footnote", `账号标识：${snapshot.account.account_identifier}`));
    section.append(make("p", "social-footnote", `读取时间：${snapshot.captured_at || "未记录"}`));
    if (snapshot.capture_method === "creator_center_browser_read") section.append(make("p", "social-footnote", "读取方式：创作者中心页面读取"));
    const period = snapshot.period || {}, range = [period.start, period.end].filter(Boolean).join(" 至 ");
    section.append(make("p", "social-snapshot-period", `统计期：${[...new Set([period.label, range].filter(Boolean))].join(" · ") || "未记录；请以各指标说明为准"}`));
    const metrics = make("div", "social-snapshot-metrics");
    for (const metric of Array.isArray(snapshot.metrics) ? snapshot.metrics : []) {
      const item = make("div", "social-snapshot-metric");
      item.append(make("span", "social-metric-label", metric.label || "未命名指标"), make("strong", "social-metric-value", metric.display_value ?? "未记录"));
      if (metric.scope) item.append(make("span", "social-footnote", `口径：${metric.scope}`));
      metrics.append(item);
    }
    if (!metrics.children.length) metrics.append(make("p", "social-muted", "本次快照未包含统计指标。"));
    section.append(metrics);
    const works = Array.isArray(snapshot.works) ? snapshot.works : [], workDetails = make("details", "social-snapshot-works");
    workDetails.append(make("summary", "", `快照中的作品明细（${works.length} 项）`));
    if (!works.length) workDetails.append(make("p", "social-muted", "本次快照未包含作品明细，不代表账号没有作品。"));
    for (const work of works) {
      const item = make("div", "social-snapshot-work"); item.append(make("p", "social-work-description", work.description || "作品描述未记录"));
      const properties = [["发布时间", work.published_at], ["可见范围", work.visibility], ["形式", work.format], ["时长", work.duration]];
      for (const [label, value] of properties) if (value !== undefined && value !== null && value !== "") item.append(make("p", "social-footnote", `${label}：${value}`));
      workDetails.append(item);
    }
    section.append(workDetails);
    const sources = make("div", "social-snapshot-sources"); sources.append(make("p", "social-footnote", "读取来源"));
    for (const source of Array.isArray(snapshot.sources) ? snapshot.sources : []) { const link = officialLink(`${source.title || "创作者中心页面"} ↗`, source.url); if (link) sources.append(link); }
    if (sources.children.length === 1) sources.append(make("p", "social-footnote", "未记录可打开的 HTTPS 来源链接。"));
    section.append(sources, make("p", "social-footnote", "这些数据是读取时保存的页面快照，不会自动更新；不同口径的指标不直接相加。"));
    const limitations = Array.isArray(snapshot.limitations) ? snapshot.limitations : [];
    if (limitations.length) { const list = make("ul", "social-snapshot-limitations"); for (const item of limitations) list.append(make("li", "", item)); section.append(list); }
    return section;
  }
  function render() {
    const providers = state.data.providers, accounts = state.data.accounts;
    const observations = state.data.observations || {}, snapshots = Array.isArray(observations.snapshots) ? observations.snapshots : [], errors = Array.isArray(observations.errors) ? observations.errors : [];
    // Preparation is not verification: no self-reported state may produce a connected badge.
    summary.textContent = `${providers.length} 个平台 · ${accounts.length} 条准备记录 · ${snapshots.length} 份只读快照 · 0 个 API 已连接账号`;
    policy.textContent = localPolicy;
    grid.replaceChildren();
    for (const provider of providers) {
      const card = make("section", "social-provider"); card.dataset.providerId = provider.id;
      const providerSnapshots = snapshots.filter((snapshot) => snapshot.provider_id === provider.id), providerErrors = errors.filter((error) => error.provider_id === provider.id);
      const cardHeading = make("div", "social-provider-heading"), cardTitle = make("h3", "", provider.name);
      cardHeading.append(cardTitle, make("span", `social-badge${providerSnapshots.length ? " social-badge-snapshot" : ""}`, providerSnapshots.length ? "已有只读快照" : "未接通"));
      card.append(cardHeading, make("p", "social-muted", provider.description || ""));
      if (providerSnapshots.length) { card.append(make("p", "social-api-status", "API 未授权 · 未自动同步")); for (const snapshot of providerSnapshots) card.append(renderSnapshot(snapshot)); }
      for (const error of providerErrors) { const message = make("p", "social-observation-error", `本地快照读取失败：${error.message || "请核对保存的快照文件。"}`); message.setAttribute("role", "status"); card.append(message); }
      const links = make("div", "social-links"); const portal = officialLink("官方后台 ↗", provider.portal_url); if (portal) links.append(portal);
      for (const doc of provider.docs || []) { const link = officialLink(`${doc.label || "官方接入文档"} ↗`, doc.url); if (link) links.append(link); }
      card.append(links);
      const details = make("details", "social-details"); details.append(make("summary", "", "申请前提与能力范围"));
      const requirements = make("ul"); for (const requirement of provider.requirements || []) requirements.append(make("li", "", requirement)); details.append(requirements);
      const capabilityList = make("div", "social-capabilities");
      const availabilityLabels = { documented_application_required: "有官方文档，需申请与授权", limited: "受限开放", unverified: "尚未核实可用接口", planned: "官方规划中", available: "平台提供，需申请与授权", conditional: "按条件开放", restricted: "受限开放", unavailable: "未提供通用接入", unknown: "待官方核验" };
      for (const capability of provider.capabilities || []) { const row = make("div", "social-capability"); row.append(make("strong", "", capability.label || capabilities[capability.id] || "功能"), make("span", "social-muted", `${availabilityLabels[capability.availability] || "以平台审核和授权为准"}${capability.note ? `；${capability.note}` : ""}`)); capabilityList.append(row); }
      details.append(capabilityList);
      const verifyDate = provider.verify_date || provider.verified_date;
      if (verifyDate) details.append(make("p", "social-footnote", `接入资料核对日期：${verifyDate}；不代表已核验你的账号权限。`));
      card.append(details, make("p", "social-next", provider.next_step || "先核对平台要求，再完成应用申请和账号授权。"));
      const accountList = make("div", "social-account-list"), providerAccounts = accounts.filter((account) => account.provider_id === provider.id);
      if (!providerAccounts.length) accountList.append(make("p", "social-empty", "还没有准备记录。可为个人号、工作室号分别添加。"));
      for (const account of providerAccounts) {
        const row = make("div", "social-account"); row.dataset.accountId = account.id;
        const accountTitle = make("div", "social-account-heading"), edit = button("编辑"); edit.setAttribute("aria-label", `编辑${provider.name}账号 ${account.label}`);
        accountTitle.append(make("strong", "", account.label), edit);
        const statusText = account.status_label || "待完成应用申请与账号授权";
        row.append(accountTitle, make("p", "social-account-status", statusText.includes("未连接") ? statusText : `未连接 · ${statusText}`), make("p", "social-footnote", `申请状态（自行记录）：${applicationStatuses[account.application_status] || "尚未说明"}`));
        const wanted = (account.requested_capabilities || []).map((id) => capabilities[id]).filter(Boolean);
        row.append(make("p", "social-footnote", `需求：${wanted.join("、") || "尚未说明"}`));
        edit.addEventListener("click", () => showEditor(provider, account, edit)); accountList.append(row);
      }
      const add = button("＋ 添加账号准备记录"); add.dataset.providerId = provider.id; add.addEventListener("click", () => showEditor(provider, null, add));
      card.append(accountList, add); grid.append(card);
    }
  }
  async function refreshData({ quiet = false } = {}) {
    if (state.loading) return false;
    state.loading = true; busy(); if (!quiet) notify("正在读取本地准备记录与已保存快照…");
    try {
      const data = await api("/api/social/accounts");
      if (!Array.isArray(data.providers) || !Array.isArray(data.accounts)) throw new Error("准备记录响应不完整，请刷新重试。");
      state.data = data; render(); if (!quiet) notify(""); return true;
    } catch (error) { notify(error.message, true); if (!state.data) summary.textContent = "接入准备状态未能读取"; return false; }
    finally { state.loading = false; busy(); }
  }
  async function open(opener) {
    if (dialog.open) return;
    state.opener = opener || document.activeElement; dialog.showModal(); close.focus();
    if (!state.saving) await refreshData();
  }
  launch.addEventListener("click", () => open(launch));
  if (chatLaunch) chatLaunch.addEventListener("click", () => open(chatLaunch));
  close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); dialog.close(); });
  dialog.addEventListener("close", () => { if (state.opener?.isConnected) state.opener.focus(); });
  refresh.addEventListener("click", () => { if (!state.saving) return refreshData(); });
  cancel.addEventListener("click", () => { if (!state.saving) hideEditor(); });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (state.saving || state.loading || !state.editor) return;
    const label = name.value.trim(), requested = [...checks].filter(([, input]) => input.checked).map(([id]) => id);
    if (!label || label.length > 60) { notify("请填写 1 至 60 字的账号别名。", true); name.focus(); return; }
    if (!requested.length) { notify("请至少选择一个希望接入的功能。", true); checks.get("read").focus(); return; }
    const selection = state.editor, payload = { label, application_status: status.value, requested_capabilities: requested };
    if (!selection.account) payload.provider_id = selection.provider.id;
    state.saving = true; busy(); notify("正在保存本地准备记录…");
    try {
      const result = await api(selection.account ? `/api/social/accounts/${encodeURIComponent(selection.account.id)}` : "/api/social/accounts", { method: selection.account ? "PATCH" : "POST", body: JSON.stringify(payload) });
      hideEditor();
      const loaded = await refreshData({ quiet: true });
      const saved = result.created === false && !selection.account ? "同平台同别名的准备记录已存在；请使用“编辑”更新。" : "准备记录已保存。";
      notify(`${saved}平台 API 尚未连接，自动读取、发布、评论和私信均未接通。${loaded ? "" : "列表刷新失败，请点击“刷新本地记录”核对已保存记录。"}`, !loaded);
      if (dialog.open) refresh.focus();
    } catch (error) { notify(error.message, true); }
    finally { state.saving = false; busy(); }
  });
})();
