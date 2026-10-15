/* Local AI reply workbench. Platform availability comes from the server, never from a UI toggle. */
(() => {
  "use strict";
  const topbar = document.querySelector(".topbar");
  if (!topbar || document.getElementById("replies-dialog")) return;
  const make = (tag, cls, text) => { const node = document.createElement(tag); if (cls) node.className = cls; if (text !== undefined) node.textContent = String(text); return node; };
  const button = (text, cls = "replies-button") => { const node = make("button", cls, text); node.type = "button"; return node; };
  const state = { data: null, loading: false, writing: false, settingsDirty: false, opener: null, epoch: 0, loadVersion: 0, polls: new Map(), finishedJobs: new Set() };
  const channels = { comment: "评论", private: "私信" };
  const defaultTone = "个人日常交流，简短自然、友好克制，不编造个人经历或承诺";
  const statusLabels = { pending: "等待处理", generating: "AI 正在生成", blocked: "待接通发送通道", handoff: "需要人工处理", error: "处理失败", test_completed: "测试生成完成", sent: "已发送" };
  const launch = button("AI 回复", "icon-btn replies-launch"); launch.id = "replies-launch"; launch.title = "抖音评论与私信 AI 回复工作台";
  (document.querySelector(".federation-toolbar") || topbar).append(launch);
  const dialog = make("dialog", "replies-dialog"); dialog.id = "replies-dialog"; dialog.setAttribute("aria-labelledby", "replies-title");
  const header = make("header", "replies-header"), heading = make("div"), title = make("h2", "", "抖音 AI 回复"); title.id = "replies-title";
  heading.append(make("p", "replies-eyebrow", "OPENWIKI · 评论与私信"), title);
  const close = button("×", "icon-btn replies-close"); close.setAttribute("aria-label", "关闭 AI 回复工作台"); header.append(heading, close);
  const body = make("div", "replies-body"), transport = make("section", "replies-transport"); transport.setAttribute("aria-label", "自动处理与平台收发状态");
  const transportTitle = make("strong", "", "正在读取处理状态…"); transportTitle.id = "replies-transport-title";
  const transportReason = make("p", "replies-muted"); transportReason.id = "replies-transport-reason";
  transport.append(transportTitle, transportReason, make("p", "replies-muted", "消息导入后按规则自动生成回复，无需逐条审核。导入不等于自动采集；真实平台收发必须由已接通的通道执行。"));
  const nativeEntry = make("a", "replies-link", "查看抖音 AI 分身 ↗"); nativeEntry.href = "https://creator.douyin.com/creator-micro/ai-application/ai-avatar"; nativeEntry.target = "_blank"; nativeEntry.rel = "noopener noreferrer";
  transport.append(nativeEntry, make("p", "replies-muted", "当前账号官方入口要求内测邀请码；本地工作台不代替开通。"));
  const notice = make("p", "replies-notice"); notice.id = "replies-notice"; notice.hidden = true; notice.setAttribute("role", "status"); notice.setAttribute("aria-live", "polite");
  const layout = make("div", "replies-layout"), side = make("div", "replies-side"), main = make("section", "replies-main"); main.setAttribute("aria-label", "消息与 AI 处理结果");

  const settingsSection = make("section", "replies-panel"), settingsHeading = make("div", "replies-panel-heading");
  const toggle = button("启用处理"); toggle.id = "replies-toggle"; toggle.setAttribute("aria-pressed", "false"); settingsHeading.append(make("h3", "", "自动回复规则"), toggle);
  const settingsForm = make("form"), settingsFields = make("fieldset", "replies-fields"); settingsForm.id = "replies-settings-form";
  const field = (parent, tag, id, labelText, options = {}) => { const label = make("label", "replies-label", labelText), input = make(tag); input.id = `replies-${id}`; label.htmlFor = input.id; Object.assign(input, options); parent.append(label, input); return input; };
  const tone = field(settingsFields, "input", "tone", "回复语气", { type: "text", value: defaultTone, maxLength: 240, autocomplete: "off" });
  const knowledge = field(settingsFields, "textarea", "knowledge", "回复依据与业务资料", { rows: 6, maxLength: 20000, placeholder: "填写你确认过的介绍、常见问题与答案。未提供的信息不会被当作已知事实。" });
  settingsFields.append(make("p", "replies-muted", "资料用于生成回复。无法根据已有信息回答的消息会标记原因；不会编造报价、承诺或账号信息。"));
  const saveSettings = button("保存规则", "replies-button replies-primary"); saveSettings.type = "submit"; saveSettings.id = "replies-save"; settingsFields.append(saveSettings); settingsForm.append(settingsFields); settingsSection.append(settingsHeading, settingsForm);

  const importSection = make("section", "replies-panel"); importSection.append(make("h3", "", "导入消息"), make("p", "replies-muted", "粘贴评论或私信以自动生成回复；这里不会主动读取抖音消息。测试消息仅用于本地验证。"));
  const importForm = make("form"), importFields = make("fieldset", "replies-fields"); importForm.id = "replies-import-form";
  const channel = field(importFields, "select", "channel", "消息类型");
  for (const [value, label] of Object.entries(channels)) { const option = make("option", "", label); option.value = value; channel.append(option); } channel.value = "comment";
  const account = field(importFields, "input", "account", "账号别名", { type: "text", required: true, maxLength: 160, autocomplete: "off", placeholder: "例如：ROS" });
  const sender = field(importFields, "input", "sender", "对方称呼", { type: "text", required: true, maxLength: 160, autocomplete: "off", placeholder: "填写消息发送者昵称" });
  const content = field(importFields, "textarea", "content", "消息原文", { required: true, rows: 4, maxLength: 8000, placeholder: "粘贴需要回复的评论或私信" });
  const context = field(importFields, "textarea", "context", "作品或对话上下文", { rows: 3, maxLength: 12000, placeholder: "选填，例如作品内容、前几轮对话" });
  const extra = make("details", "replies-extra"); extra.append(make("summary", "", "来源与去重信息（选填）"));
  const source = field(extra, "input", "source", "抖音来源链接", { type: "url", maxLength: 1200, placeholder: "抖音 HTTPS 页面，不含 ? 或 # 参数" });
  const externalId = field(extra, "input", "external-id", "平台消息 ID", { type: "text", maxLength: 240, autocomplete: "off", placeholder: "已知时填写，便于去重" }); importFields.append(extra);
  const testLabel = make("label", "replies-check"), isTest = make("input"); isTest.type = "checkbox"; isTest.checked = true; isTest.id = "replies-is-test"; testLabel.append(isTest, make("span", "", "测试消息（不会外发）")); importFields.append(testLabel);
  const importButton = button("导入并自动处理", "replies-button replies-primary"); importButton.type = "submit"; importButton.id = "replies-import"; importFields.append(importButton); importForm.append(importFields); importSection.append(importForm); side.append(settingsSection, importSection);

  const inboxHeading = make("div", "replies-inbox-heading"), summary = make("p", "replies-summary", "正在读取本地消息…"), refresh = button("刷新本地列表"); summary.id = "replies-summary"; refresh.id = "replies-refresh"; inboxHeading.append(summary, refresh);
  const filters = make("div", "replies-filters"); filters.setAttribute("role", "group"); filters.setAttribute("aria-label", "按消息类型筛选");
  let selectedFilter = "all"; const filterButtons = new Map();
  for (const [value, label] of [["all", "全部"], ...Object.entries(channels)]) { const item = button(label); item.dataset.channel = value; item.setAttribute("aria-pressed", String(value === selectedFilter)); item.addEventListener("click", () => { selectedFilter = value; renderInbox(); }); filterButtons.set(value, item); filters.append(item); }
  const inbox = make("div", "replies-inbox"); inbox.id = "replies-inbox"; main.append(inboxHeading, filters, inbox); layout.append(side, main); body.append(transport, notice, layout); dialog.append(header, body); document.body.append(dialog);

  function notify(message, error = false) { notice.textContent = message; notice.hidden = !message; notice.classList.toggle("replies-error", error); }
  function busy() {
    settingsFields.disabled = state.writing || state.loading; importFields.disabled = state.writing || state.loading;
    toggle.disabled = state.writing || state.loading || !state.data; refresh.disabled = state.writing || state.loading;
    saveSettings.textContent = state.writing ? "处理中…" : "保存规则";
    for (const item of inbox.querySelectorAll("button")) item.disabled = state.writing || state.loading || item.dataset.unavailable === "true";
    dialog.setAttribute("aria-busy", String(state.writing || state.loading));
  }
  async function api(path, options = {}) {
    const controller = new AbortController(), timer = setTimeout(() => controller.abort(), 20000);
    try {
      let response;
      try { response = await fetch(path, { cache: "no-store", ...options, signal: controller.signal, headers: { "Content-Type": "application/json", ...(options.headers || {}) } }); }
      catch { throw new Error(controller.signal.aborted ? "本地请求超时（20 秒）。输入已保留，请刷新核对后重试。" : "无法连接本地服务。输入已保留，请刷新核对后重试。"); }
      let data;
      try { data = await response.json(); } catch { throw new Error(`本地服务响应无法读取（HTTP ${response.status}）。输入已保留。`); }
      if (!response.ok) throw new Error(typeof data?.detail === "string" ? data.detail.slice(0, 500) : `操作未完成（HTTP ${response.status}），请检查输入。`);
      return data;
    } finally { clearTimeout(timer); }
  }
  function sourceLink(value) {
    try { const url = new URL(value); if (url.protocol !== "https:" || url.username || url.password || url.port || url.search || url.hash || /[?#\\\s]/.test(value) || !["creator.douyin.com", "www.douyin.com", "douyin.com"].includes(url.hostname)) return null;
      const link = make("a", "replies-link", "打开抖音来源 ↗"); link.href = url.href; link.target = "_blank"; link.rel = "noopener noreferrer"; return link;
    } catch { return null; }
  }
  const textValue = (value) => typeof value === "string" || typeof value === "number" ? String(value) : "";
  function renderInbox() {
    for (const [value, item] of filterButtons) item.setAttribute("aria-pressed", String(value === selectedFilter));
    const messages = Array.isArray(state.data?.messages) ? state.data.messages : [];
    const visible = messages.filter((item) => selectedFilter === "all" || item.channel === selectedFilter);
    const tests = messages.filter((item) => item.is_test === true).length;
    summary.textContent = `${messages.length} 条本地消息 · ${tests} 条测试消息 · 当前显示 ${visible.length} 条`;
    inbox.replaceChildren();
    if (!visible.length) inbox.append(make("p", "replies-empty", messages.length ? "当前类型没有本地消息。" : "还没有导入消息。填写左侧表单后，AI 会按当前规则处理。"));
    for (const message of visible) {
      const card = make("article", "replies-message"); card.dataset.messageId = textValue(message.id);
      const cardHeading = make("div", "replies-message-heading"), badges = make("div", "replies-badges");
      badges.append(make("span", "replies-badge", channels[message.channel] || "消息"));
      if (message.is_test === true) badges.append(make("span", "replies-badge replies-test", "测试 · 不外发"));
      // Display an externally confirmed sent state only when the transport is also reported ready.
      const label = message.status === "sent" && state.data?.transport?.ready !== true ? "发送状态待核对" : message.status_label || statusLabels[message.status] || "状态待核对";
      badges.append(make("span", "replies-badge", label)); cardHeading.append(badges);
      card.append(cardHeading, make("h4", "", `${message.account_label || "未记录账号"} · ${message.sender || "未记录称呼"}`), make("p", "replies-footnote", `导入：${message.received_at || message.created_at || "未记录"}${message.updated_at ? ` · 更新：${message.updated_at}` : ""}`));
      const original = make("section", "replies-original"); original.append(make("p", "replies-label-small", "消息原文"), make("p", "replies-literal", message.content || "未记录消息内容")); card.append(original);
      if (message.context) { const details = make("details", "replies-context"); details.append(make("summary", "", "作品或对话上下文"), make("p", "replies-literal", message.context)); card.append(details); }
      const answer = make("section", "replies-answer"); answer.append(make("p", "replies-label-small", "AI 回复"), make("p", "replies-literal", message.reply || (message.status === "generating" ? "模型正在生成，完成后会自动更新。" : "尚未生成回复。"))); card.append(answer);
      if (message.needs_human || message.reason) card.append(make("p", "replies-reason", `${message.needs_human ? "需要人工处理：" : "当前说明："}${message.reason || "现有资料不足，请补充真实依据。"}`));
      const metadata = message.generation_metadata || message.metadata || {}, model = textValue(metadata.model || metadata.model_name || metadata.generation_model), origin = textValue(metadata.engine || metadata.source || metadata.response_origin);
      card.append(make("p", "replies-footnote", `生成模型：${model || "未记录"}${origin ? ` · 来源：${origin}` : ""}`));
      const actions = make("div", "replies-actions");
      if (message.reply) { const copy = button("复制回复"); copy.addEventListener("click", async () => { try { if (!navigator.clipboard?.writeText) throw new Error("不可用"); await navigator.clipboard.writeText(String(message.reply)); notify("回复已复制。复制不会向抖音发送消息。"); } catch { notify("未能复制，请在 AI 回复文本中手动选择并复制。", true); } }); actions.append(copy); }
      if (message.status !== "generating" && message.id && message.status !== "sent") { const regenerate = button(message.reply ? "重新生成" : "生成回复"); regenerate.dataset.unavailable = String(state.data?.settings?.enabled !== true); regenerate.title = state.data?.settings?.enabled === true ? "重新运行 AI 生成，不代表消息已发送" : "自动处理已暂停，请先启用处理"; regenerate.addEventListener("click", () => generate(message.id)); actions.append(regenerate); }
      const link = sourceLink(message.source_url); if (link) actions.append(link); card.append(actions); inbox.append(card);
    }
    busy();
  }
  function render() {
    const settings = state.data?.settings || {}, ready = state.data?.transport?.ready === true;
    transportTitle.textContent = `${settings.enabled === true ? "自动回复规则已启用" : "自动回复处理已暂停"}；${ready ? "抖音消息收发已接通" : "抖音消息收发未接通"}`;
    transportReason.textContent = state.data?.transport?.reason || (ready ? "消息处理与发送结果以每条记录为准。" : "当前只能处理本地导入的消息，尚不能持续接收或向抖音发送回复。");
    toggle.textContent = settings.enabled === true ? "暂停处理" : "启用处理"; toggle.setAttribute("aria-pressed", String(settings.enabled === true));
    importButton.textContent = settings.enabled === true ? "导入并自动处理" : "导入并保存（处理已暂停）";
    if (!state.settingsDirty) { tone.value = settings.tone || defaultTone; knowledge.value = settings.knowledge || ""; }
    renderInbox();
  }
  function resumePolls() {
    if (!dialog.open) return;
    for (const message of state.data?.messages || []) if (message.generation_job_id && ["pending", "generating"].includes(message.status)) pollJob(message.generation_job_id);
  }
  async function load({ quiet = false } = {}) {
    const epoch = state.epoch, version = ++state.loadVersion;
    state.loading = true; busy(); if (!quiet) notify("正在读取本地消息…");
    try {
      const data = await api("/api/social/replies");
      if (!data || !Array.isArray(data.messages) || !data.settings) throw new Error("回复工作台响应不完整，请刷新重试。");
      if (epoch !== state.epoch || version !== state.loadVersion) return false;
      state.data = data; render(); resumePolls(); if (!quiet) notify(""); return true;
    } catch (error) { if (epoch === state.epoch && version === state.loadVersion) notify(error.message, true); return false; }
    finally { if (version === state.loadVersion) { state.loading = false; busy(); } }
  }
  function stopPolls() { state.epoch += 1; for (const entry of state.polls.values()) if (entry.timer) clearTimeout(entry.timer); state.polls.clear(); }
  function pollJob(id) {
    if (!id || !dialog.open || state.polls.has(id) || state.finishedJobs.has(id)) return;
    const epoch = state.epoch, entry = { timer: null }; state.polls.set(id, entry);
    const valid = () => dialog.open && epoch === state.epoch && state.polls.get(id) === entry;
    const tick = async () => {
      entry.timer = null; if (!valid()) return;
      try {
        const result = await api(`/api/jobs/${encodeURIComponent(id)}`); if (!valid()) return;
        const job = result?.job || result, status = job?.status;
        if (["completed", "succeeded", "done", "failed", "error", "cancelled", "canceled"].includes(status)) {
          state.polls.delete(id); state.finishedJobs.add(id);
          const reloaded = await load({ quiet: true }); if (epoch !== state.epoch) return;
          const failed = ["failed", "error", "cancelled", "canceled"].includes(status);
          notify(`${failed ? "AI 处理未完成，请查看消息说明。" : "AI 处理已完成，请查看回复和实际发送状态。"}${reloaded ? "" : "本地列表刷新失败，请稍后刷新。"}`, failed || !reloaded); return;
        }
        entry.timer = setTimeout(tick, 1500);
      } catch (error) { if (valid()) { state.polls.delete(id); notify(`任务状态暂时无法读取：${error.message} 可刷新本地列表继续核对。`, true); } }
    };
    entry.timer = setTimeout(tick, 500);
  }
  async function saveSettingsPatch(payload, savingDraft) {
    if (state.writing || state.loading || !state.data) return;
    state.writing = true; busy();
    try {
      const result = await api("/api/social/replies/settings", { method: "PATCH", body: JSON.stringify(payload) });
      if (savingDraft) state.settingsDirty = false;
      if (result?.settings && Array.isArray(result.messages)) { state.data = result; render(); resumePolls(); }
      else await load({ quiet: true });
      notify(savingDraft ? "自动回复规则已保存。平台收发状态请查看上方说明。" : payload.enabled ? "自动处理已启用；是否能够发送仍取决于平台通道。" : "自动处理已暂停。");
    } catch (error) { notify(error.message, true); }
    finally { state.writing = false; busy(); }
  }
  async function generate(id) {
    if (state.writing || state.loading || state.data?.settings?.enabled !== true) return;
    state.writing = true; busy();
    try {
      const result = await api(`/api/social/replies/messages/${encodeURIComponent(id)}/generate`, { method: "POST", body: "{}" });
      const reloaded = await load({ quiet: true });
      if (result?.job?.id) { state.finishedJobs.delete(result.job.id); pollJob(result.job.id); }
      notify(`已提交 AI 生成任务。${reloaded ? "" : "列表刷新失败，请稍后刷新核对。"}`, !reloaded);
    } catch (error) { notify(error.message, true); }
    finally { state.writing = false; busy(); }
  }
  for (const input of [tone, knowledge]) input.addEventListener("input", () => { state.settingsDirty = true; });
  settingsForm.addEventListener("submit", async (event) => { event.preventDefault(); const value = tone.value.trim(); if (!value) { notify("请填写回复语气。", true); tone.focus(); return; } await saveSettingsPatch({ tone: value, knowledge: knowledge.value.trim() }, true); });
  toggle.addEventListener("click", () => saveSettingsPatch({ enabled: state.data?.settings?.enabled !== true }, false));
  importForm.addEventListener("submit", async (event) => {
    event.preventDefault(); if (state.writing || state.loading || !state.data) return;
    if (!account.value.trim() || !sender.value.trim() || !content.value.trim()) { notify("请填写账号别名、对方称呼和消息原文。", true); (!account.value.trim() ? account : !sender.value.trim() ? sender : content).focus(); return; }
    if (source.value.trim() && !sourceLink(source.value.trim())) { notify("来源链接需要是抖音 HTTPS 页面地址，且不含查询参数、片段或登录信息。", true); source.focus(); return; }
    const payload = { channel: channel.value, account_label: account.value.trim(), sender: sender.value.trim(), content: content.value.trim(), context: context.value.trim(), source_url: source.value.trim(), external_id: externalId.value.trim(), is_test: isTest.checked === true };
    state.writing = true; busy();
    try {
      const result = await api("/api/social/replies/messages", { method: "POST", body: JSON.stringify(payload) });
      if (!result?.message?.id) throw new Error("服务未返回消息记录，请刷新核对后再重试。输入已保留。");
      content.value = ""; context.value = ""; sender.value = ""; source.value = ""; externalId.value = "";
      const reloaded = await load({ quiet: true });
      if (result.job?.id) pollJob(result.job.id);
      const outcome = result.created === false ? "这条消息已有记录，未重复导入。" : result.job?.id ? "消息已导入，AI 正在自动处理。" : "消息已导入；请查看处理状态。";
      notify(`${outcome}${payload.is_test ? "这是一条测试消息，不会外发。" : "是否已发送以实际结果为准。"}${reloaded ? "" : "列表刷新失败，请稍后刷新核对。"}`, !reloaded);
    } catch (error) { notify(error.message, true); }
    finally { state.writing = false; busy(); }
  });
  launch.addEventListener("click", async () => { if (dialog.open) return; state.opener = launch; dialog.showModal(); close.focus(); await load(); });
  refresh.addEventListener("click", () => { if (!state.writing && !state.loading) return load(); });
  close.addEventListener("click", () => dialog.close());
  dialog.addEventListener("cancel", (event) => { event.preventDefault(); dialog.close(); });
  dialog.addEventListener("close", () => { stopPolls(); if (state.opener?.isConnected) state.opener.focus(); });
})();
