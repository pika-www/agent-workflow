"""Local UI/UX handoff recipes; these do not create remote design-tool files.

The existing Agent library owns persistence, learned rules and safe revisions.
The JSON structures are project-local examples, not a Figma or token-tool format.
"""
import csv
import io
import json
from textwrap import dedent


def _text(value):
    return dedent(value).strip() + "\n"


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


REFERENCES = (
    "https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html",
    "https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum.html",
    "https://www.w3.org/WAI/WCAG22/Understanding/focus-visible",
    "https://www.w3.org/WAI/WCAG22/Understanding/focus-not-obscured-minimum",
    "https://developer.apple.com/design/human-interface-guidelines/layout",
    "https://developer.apple.com/design/human-interface-guidelines/accessibility",
    "https://m3.material.io/foundations/",
)


def _state_matrix():
    rows = [
        ["initial", "首次进入", "显示标题和输入提示", "保留导航顺序", "未输入不请求", "输入后 editing"],
        ["editing", "输入修改", "保留输入并清除过期成功信息", "保持输入焦点", "不自动提交", "提交后 loading 或 validation_error"],
        ["validation_error", "必填或格式不符", "字段旁说明具体修复方式", "聚焦首个错误并关联错误文本", "不发送无效请求", "修改后 editing"],
        ["loading", "有效提交", "显示处理中并抑制重复提交", "保留焦点并播报状态", "同一操作只有一个在途请求", "按真实结果转 success 或 server_error"],
        ["success", "服务端确认完成", "展示实际回执及后续动作", "温和播报成功不强制抢焦点", "确认版本或回执后才成功", "继续编辑后 editing"],
        ["empty", "成功查询但无数据", "解释空态并给可用下一步", "下一步可键盘到达", "空数组不等于请求失败", "创建或刷新后 loading"],
        ["server_error", "请求失败", "保留用户输入和重试入口", "错误可读不只变色", "超时不宣称一定失败需核对幂等回执", "确认可重试后 loading"],
        ["offline", "当前无网络", "标明本地状态与同步状态", "状态变化可被感知", "不承诺已经保存到服务端", "联网后用户确认重试"],
        ["forbidden", "身份或权限不足", "解释不可用范围及合法下一步", "错误说明不依赖禁用按钮提示", "由后端校验权限", "权限恢复后重新获取"],
    ]
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(["screen_id", "state_id", "触发", "界面反馈", "焦点与辅助技术", "数据契约", "退出条件"])
    writer.writerows(["DEMO-UI-001", *row] for row in rows)
    return stream.getvalue(), [row[0] for row in rows]


PLATFORMS = _text("""
    # DEMO 响应式与平台适配约定

    这是待按项目验证的设计交接，不是已完成的浏览器、开发者工具或真机测试。

    | 场景 | 布局与内容约定 | 实际验收记录 |
    | --- | --- | --- |
    | Web 窄屏 | 单列；操作区换行；长文本不断章截义；320 CSS px 宽度检查内容与操作 | 待测 |
    | Web 宽屏 | 内容最大宽度；辅助说明可并列；DOM 阅读顺序与视觉顺序一致 | 待测 |
    | 放大与字体 | 200% 文本与 400% 缩放分别检查；不要锁定正文高度；必要二维内容单独说明 | 待测 |
    | iOS / iPadOS | 保留系统安全区、Dynamic Type、原生导航与返回方式；使用平台尺寸单位 | 待测 |
    | Android | 使用当前项目 Material / Compose / View 组件，检查系统字体缩放、返回与窗口变化 | 待测 |
    | 微信小程序 | 重新映射 WXML/WXSS 与无障碍属性；检查安全区、原生导航及基础库版本 | 待测 |
    | Flutter / React Native | 将语义 token 映射原生样式和语义树；不能直接粘贴 Web CSS 或 ARIA | 待测 |

    48rem 是随本 DEMO 提供的布局断点，不是通用设备标准；断点应由内容开始拥挤的位置确定。
    Web 的 px/rem、iOS 的 pt、Android 的 dp/sp、小程序的 rpx 不作一比一数值复制。
    WCAG 2.2 AA 的 2.5.8 对 Web 指针目标要求至少 24×24 CSS px 或符合所列例外；
    本 DEMO 普通控件采用 3rem 最小尺寸作为局部设计选择，不声称所有平台规范相同。
    状态区不只依赖颜色：错误有文本，加载有状态名；减少动画设置下停用非必要过渡。
    完成前记录窄屏、长中文/英文、键盘、屏幕阅读器、深浅色和平台真实截图/测试结果。
""")


def _token_data():
    return {
        "example_only": True, "design_id": "DEMO-DS-001", "schema": "local-uiux-tokens-v1",
        "description": "项目自定义语义 token 示例；不是 Figma 导出，也不是已认证的交换格式。",
        "themes": {
            "light": {"canvas": "#f3f5fa", "surface": "#ffffff", "text": "#172033",
                      "muted": "#4b5563", "action": "#173b86", "on-action": "#ffffff",
                      "error": "#a21b27", "border": "#64748b", "focus": "#173b86"},
            "dark": {"canvas": "#0b1220", "surface": "#172033", "text": "#f8fafc",
                     "muted": "#cbd5e1", "action": "#bed3ff", "on-action": "#10213e",
                     "error": "#ffadb5", "border": "#94a3b8", "focus": "#bed3ff"},
        },
        "space": {"1": "0.25rem", "2": "0.5rem", "3": "0.75rem", "4": "1rem", "6": "1.5rem", "8": "2rem"},
        "radius": {"control": "0.5rem", "card": "0.75rem"},
        "type": {"body-size": "1rem", "body-line": "1.6", "title-size": "1.5rem"},
        "layout": {"content-max": "64rem", "control-min": "3rem"},
        "motion": {"feedback": "120ms"},
        "contrast_pairs": [{"foreground": "text", "background": "surface", "minimum": 4.5},
                           {"foreground": "muted", "background": "surface", "minimum": 4.5},
                           {"foreground": "on-action", "background": "action", "minimum": 4.5},
                           {"foreground": "error", "background": "surface", "minimum": 4.5},
                           {"foreground": "focus", "background": "surface", "minimum": 3}],
        "verification": {"application_visual_review": "not_run", "assistive_technology": "not_run",
                         "platform_devices": "not_run", "figma_file_created": False},
    }


def _token_css(tokens):
    def colors(theme):
        return ["  --demo-color-" + key + ": " + value + ";" for key, value in tokens["themes"][theme].items()]
    lines = ["/* DEMO local token mapping; production names and platform adapters need review. */", ":root {", "  color-scheme: light;"]
    lines.extend(colors("light"))
    for category in ("space", "radius", "type", "layout", "motion"):
        lines.extend("  --demo-" + category + "-" + key + ": " + value + ";" for key, value in tokens[category].items())
    lines.extend(["}", '[data-theme="dark"] {', "  color-scheme: dark;", *colors("dark"), "}"])
    return "\n".join(lines) + "\n" + _text("""
        *, *::before, *::after { box-sizing: border-box; }
        body { margin: 0; color: var(--demo-color-text); background: var(--demo-color-canvas); font: var(--demo-type-body-size)/var(--demo-type-body-line) system-ui, sans-serif; }
        .demo-shell { width: min(calc(100% - 2rem), var(--demo-layout-content-max)); margin-inline: auto; padding-block: var(--demo-space-8); }
        h1 { font-size: var(--demo-type-title-size); }
        .demo-grid { display: grid; grid-template-columns: minmax(0, 1fr); gap: var(--demo-space-4); }
        .demo-card { min-width: 0; overflow-wrap: anywhere; padding: var(--demo-space-6); border: 1px solid var(--demo-color-border); border-radius: var(--demo-radius-card); background: var(--demo-color-surface); }
        .demo-muted { color: var(--demo-color-muted); }
        .demo-error { color: var(--demo-color-error); }
        .demo-field { display: grid; gap: var(--demo-space-2); }
        .demo-input { width: 100%; min-height: var(--demo-layout-control-min); padding: var(--demo-space-3); border: 1px solid var(--demo-color-border); border-radius: var(--demo-radius-control); color: var(--demo-color-text); background: var(--demo-color-surface); font: inherit; }
        .demo-input[aria-invalid="true"] { border-color: var(--demo-color-error); }
        .demo-button { display: inline-flex; align-items: center; justify-content: center; min-height: var(--demo-layout-control-min); min-width: var(--demo-layout-control-min); max-width: 100%; overflow-wrap: anywhere; padding: var(--demo-space-3) var(--demo-space-4); border: 2px solid transparent; border-radius: var(--demo-radius-control); color: var(--demo-color-on-action); background: var(--demo-color-action); font: inherit; text-align: center; transition: transform var(--demo-motion-feedback); }
        .demo-button:active { transform: translateY(1px); }
        .demo-button:disabled { cursor: not-allowed; }
        .demo-button:focus-visible, .demo-input:focus-visible { outline: 3px solid var(--demo-color-focus); outline-offset: 3px; }
        @media (min-width: 48rem) { .demo-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
        @media (prefers-reduced-motion: reduce) { .demo-button { transition: none; } .demo-button:active { transform: none; } }
        @media (forced-colors: active) { .demo-button { border-color: ButtonText; } }
    """)


DEMO_HTML = _text('''
    <!doctype html>
    <html lang="zh-CN" data-theme="light">
    <head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
    <title>DEMO 组件状态样本</title><link rel="stylesheet" href="tokens.css"></head>
    <body><main class="demo-shell"><h1>DEMO 组件状态样本</h1>
      <p>静态交接样本，不提交数据。将 html 的 data-theme 改成 dark 可查看另一套 token。</p>
      <div class="demo-grid">
        <section class="demo-card" aria-labelledby="field-title"><h2 id="field-title">输入错误样本</h2>
          <div class="demo-field"><label for="demo-name">项目名称</label>
            <input class="demo-input" id="demo-name" type="text" required aria-invalid="true" aria-describedby="demo-help demo-error">
            <span class="demo-muted" id="demo-help">样本仅演示字段与说明关联。</span>
            <span class="demo-error" id="demo-error">错误样本：请填写项目名称。</span></div>
        </section>
        <section class="demo-card" aria-labelledby="status-title"><h2 id="status-title">加载状态样本</h2>
          <button class="demo-button" type="button" disabled>保存中（演示）</button>
          <p role="status" aria-live="polite">这里只展示加载文案，没有正在执行的请求。</p>
          <a class="demo-button" href="#sample-notes">查看交接说明</a>
        </section>
      </div>
      <section class="demo-card" id="sample-notes" tabindex="-1"><h2>交接说明</h2>
        <p>键盘顺序跟随文档顺序；错误和加载态固定显示。实际行为、恢复与结果见 components.json。</p>
      </section>
    </main></body></html>
''')


def build_uiux_templates(pack):
    state_csv, state_ids = _state_matrix()
    tokens = _token_data()
    return [
        pack("uiux-screen-handoff", "UI 页面、交互与开发交接", "uiux-handoff",
             ["UI", "UX", "UI/UX", "界面设计", "页面设计", "交互", "原型", "线框", "设计交接", "用户流程", "wireframe", "handoff"],
             "把页面目标、信息层级、状态、响应式、平台差异与验收条件交给前端、App 和测试；不冒充实际设计工具成品。",
             "HANDOFF.md", _text("""
                # DEMO-UI-001 页面设计交接（草案）

                页面：项目草稿页；目标用户与用户证据：待确认；业务目标：填写草稿并理解保存结果。
                原型/Figma链接：未创建；输入需求版本：待确认；设计负责人：待确认；开发接受：待确认。

                ## 信息层级与流程
                1. 一级为当前任务标题和主要操作，二级为输入与结果，三级为帮助说明。
                2. 进入 → 编辑 → 校验 → 请求中 → 实际成功或可恢复错误。
                3. 离开有未保存变更时说明保留/放弃方式；不要暗中丢弃输入。
                4. API、保存范围、权限和幂等回执由后端明确；未接接口只能称本地草稿。

                ## 交付对照
                | 对象 | 文件/约定 | 开发承接 | 验收证据 |
                | --- | --- | --- | --- |
                | 页面与元素 | screen-spec.json 的 screen_id、element_id | 前端/App 确认命名和布局映射 | 待实现 |
                | 交互状态 | state-matrix.csv 覆盖正常和失败路径 | 后端确认数据事实，客户端映射 | 待测试 |
                | 响应式与平台 | RESPONSIVE_PLATFORM.md | 按目标平台适配单位、导航、语义 | 待截图/设备 |
                | 色彩与组件 | uiux-design-system 的语义 token 与组件契约 | 保留已有产品风格，优先复用现有组件 | 待设计走查 |

                ## 设计复核与修改
                避免只画成功态；检查文案过长、空内容、弱网、权限变化及键盘路径。
                Web 正文通常按 WCAG 1.4.3 的 4.5:1 检查；大字号条件、例外须按原文判断。
                焦点须可见且不被固定层完全遮住；状态/错误不能只靠颜色表达。
                所有需求假设、来源版本、弃用理由和变更影响写入评审记录；事实不足保留待确认。
                学习产生的规则由本 Agent 的 LEARNED_RULES.md 维护；替换现有品牌或组件需有当前项目依据。
             """),
             ["先读取现有产品样式、用户任务与已批准组件，保留原有视觉语言。",
              "交接必须包含页面、元素ID、状态转移、内容边界及可检查的接受条件。",
              "Figma链接、用户研究与测试结果有真实产物才填写，不把模板当成已创建的设计文件。",
              "区分Web、原生App和小程序的平台能力，按目标平台适配导航、键盘和辅助技术。"],
             ["需求、设计和实现版本可对应", "正常/空/加载/错误/离线/权限状态与恢复齐全",
              "响应式、长文本、字体放大与焦点已实测或标明待测", "交接有前端/App/后端/测试承接及证据",
              "保留现有风格并记录有依据的变更"],
             "先替换 DEMO 页面目标和元素；逐项对齐 JSON、CSV、交接表。只有取得真实链接、实现和测试回执才修改待确认/未运行状态。",
             references=REFERENCES,
             extra={"screen-spec.json": _json({
                 "example_only": True, "screen_id": "DEMO-UI-001", "name": "项目草稿页",
                 "status": "draft", "design_artifact_url": None, "design_artifact_created": False,
                 "requirements_version": "待确认", "platform": "待确认 Web / iOS / Android / 微信小程序",
                 "elements": [{"element_id": "page-title", "role": "heading", "content": "DEMO 项目草稿"},
                              {"element_id": "name-input", "role": "textbox", "label": "项目名称", "required": True,
                               "constraints": {"max_length": None, "business_rule": "待后端确认"}},
                              {"element_id": "save-action", "role": "button", "label": "保存草稿"},
                              {"element_id": "result-status", "role": "status", "content": "依据真实请求状态填写"}],
                 "reading_order": ["page-title", "name-input", "save-action", "result-status"],
                 "keyboard_order": ["name-input", "save-action"], "states": state_ids,
                 "handoff": {"frontend": "布局与语义", "app": "平台适配", "backend": "数据与错误约定", "testing": "状态和可访问性"},
                 "acceptance": [{"id": "DEMO-AC-01", "scenario": "失败保留输入并提供恢复方式", "status": "not_run"},
                                {"id": "DEMO-AC-02", "scenario": "键盘路径与可见焦点一致", "status": "not_run"}],
                 "open_questions": ["目标平台和已有组件版本？", "保存接口与成功证据是什么？"]}),
                    "state-matrix.csv": state_csv, "RESPONSIVE_PLATFORM.md": PLATFORMS}),
        pack("uiux-design-system", "设计系统、Token 与组件规范", "uiux-design-system",
             ["设计系统", "design system", "token", "设计变量", "组件规范", "组件库", "视觉规范", "主题", "深色", "色板", "design tokens"],
             "提供独立语义 token、深浅主题CSS映射、组件行为契约与静态HTML样本，供现有框架适配和维护。",
             "tokens.json", _json(tokens),
             ["先盘点已有设计变量与组件；语义命名优于按具体颜色命名，避免无依据重做品牌。",
              "tokens.json 为本地结构；接入 Figma、Style Dictionary 或平台主题前按实际工具格式转换验证。",
              "每个组件记录视觉状态、键盘/辅助技术行为、内容边界、恢复条件和开发映射。",
              "检查实际前景背景配对、焦点与系统高对比度；模板值不代表整个应用已经符合标准。",
              "改动token时记录版本、受影响组件、兼容映射与回退方案；学习规则保存在本库LEARNED_RULES.md。"],
             ["两种主题的语义token与CSS引用一致", "组件包含默认/焦点/禁用/加载/错误契约",
              "颜色之外仍有文本和语义区分状态", "实际项目的键盘、屏幕阅读器与缩放验证有记录",
              "平台适配和旧token迁移有明确映射"],
             "把 tokens.json 作为本地设计约定，并与 tokens.css 一起审阅。demo.html 是可手动打开的静态样本，不会保存数据，也不表示已经在 Figma 或真实应用中创建组件。",
             references=REFERENCES,
             extra={"tokens.css": _token_css(tokens), "demo.html": DEMO_HTML,
                    "components.json": _json({
                        "example_only": True, "system_id": "DEMO-DS-001", "version": "draft-v1",
                        "components": [
                            {"id": "primary-action", "web_element": "button", "label": "使用动作动词，不用图标代替可读名称",
                             "tokens": ["action", "on-action", "focus"],
                             "states": ["default", "hover", "pressed", "focus", "disabled", "loading"],
                             "keyboard": "使用原生button支持Enter/Space；链接使用a，不伪装角色",
                             "loading": "抑制重复请求，保留可感知状态；若禁用导致焦点丢失需修复",
                             "disabled": "不可操作原因用可阅读文本解释，不能只靠悬浮提示",
                             "content": "长标签可换行；不固定会裁切文字的高度",
                             "implementation_status": "not_integrated"},
                            {"id": "text-field", "web_element": "input", "label": "持久可见label关联id",
                             "tokens": ["text", "surface", "border", "error", "focus"],
                             "states": ["default", "focus", "disabled", "readonly", "error"],
                             "keyboard": "跟随文档顺序；错误不陷住键盘焦点",
                             "error": "错误文本使用aria-describedby关联，aria-invalid标记实际错误",
                             "content": "placeholder不替代label；限制由业务契约决定",
                             "implementation_status": "not_integrated"}],
                        "migration": {"from_version": None, "renamed_tokens": [], "affected_components": [],
                                      "rollback": "保留前一版token与组件映射", "approval": "pending_review"},
                        "verification": {"visual": "not_run", "screen_reader": "not_run", "devices": "not_run"}}),
                    "COMPONENT_GUIDE.md": _text("""
                        # DEMO 设计系统接入与维护

                        tokens.json 使用本项目自定义结构。tokens.css 是等值 Web 映射；修改主题颜色和尺寸时同步两个文件。
                        使用现有 React/Vue/Angular 组件库时先映射它的主题API，不覆盖已有组件的全部CSS。
                        原生 SwiftUI/Compose/Flutter/React Native 必须转换颜色、排版与空间token并验证平台语义；CSS不能直接运行。
                        微信小程序按实际WXSS与基础库能力改写；ARIA、rem、浏览器焦点规则不可原样假定支持。
                        demo.html 可以手动打开查看静态错误与加载样本，设置 html 的 data-theme=dark 切换主题。
                        样本没有网络、提交、状态切换或真实保存功能；JSON列出的是需要实现的组件契约。

                        维护时先记录现有视觉基线、版本及使用方；新增token说明用途和边界，弃用token保留迁移映射。
                        深浅色分别检查正文/表面、按钮文字/按钮背景、错误/表面等实际配对；透明、渐变、悬浮遮罩需在合成后测量。
                        常规文字以4.5:1为局部目标；大字号等例外按WCAG原文区分，不把此处色值检查当作整页合规证明。
                        可见焦点、键盘路径、触控目标、200%文本、400%缩放、系统强制颜色、减少动画要实际复核。
                        Native还需Dynamic Type/字体缩放、安全区与平台返回交互；Web的rem/px与pt、dp/sp、rpx不直接复制。
                        最终交接附实际截图、组件实现位置、测试结果和未覆盖项。Figma文件只在真实创建后提供链接。
                    """)}),
    ]
