"""Local frontend recipes built on documented open-source frameworks and tools.

These are integration samples, not downloaded upstream scaffolds. The ordinary
Agent library owns publication, source hashes, learned rules and safe upgrades.
"""
from textwrap import dedent


def _text(value):
    return dedent(value).strip() + "\n"


CSS_REFERENCE = "https://developer.mozilla.org/en-US/docs/Web/CSS/Guides/Cascading_variables/Using_custom_properties"
MOTION_REFERENCE = "https://developer.mozilla.org/en-US/docs/Web/CSS/Reference/At-rules/@media/prefers-reduced-motion"

STYLE_HTML = _text('''
    <!doctype html>
    <html lang="zh-CN">
    <head>
      <meta charset="utf-8">
      <meta name="viewport" content="width=device-width, initial-scale=1">
      <title>DEMO 响应式样式模板</title>
      <link rel="stylesheet" href="styles.css">
    </head>
    <body>
      <main class="demo-shell" aria-labelledby="demo-title">
        <h1 id="demo-title">DEMO 项目看板</h1>
        <p>虚构演示；链接仅跳转本页说明，不发出业务请求。</p>
        <div class="demo-grid">
          <article class="demo-card">
            <h2>待验证的样式</h2>
            <p>调整窗口宽度，使用 Tab 检查焦点，并在系统设置中减少动画。</p>
            <a class="demo-action" href="#demo-notes">查看模板说明</a>
          </article>
          <article class="demo-card" id="demo-notes" tabindex="-1">
            <h2>模板说明</h2>
            <p>真实颜色、文字、间距和断点以项目设计规范为准。</p>
          </article>
        </div>
      </main>
    </body>
    </html>
''')

CSS_STYLES = _text('''
    :root {
      --demo-brand: #173b86;
      --demo-ink: #172033;
      --demo-paper: #ffffff;
      --demo-canvas: #f2f5fb;
      --demo-space: 1rem;
      --demo-radius: .75rem;
    }
    *, *::before, *::after { box-sizing: border-box; }
    body { margin: 0; color: var(--demo-ink); background: var(--demo-canvas); font-family: system-ui, sans-serif; line-height: 1.6; }
    .demo-shell { width: min(100% - 2rem, 64rem); margin-inline: auto; padding-block: clamp(1rem, 4vw, 3rem); }
    .demo-grid { display: grid; gap: var(--demo-space); grid-template-columns: minmax(0, 1fr); }
    .demo-card { min-width: 0; overflow-wrap: anywhere; padding: calc(var(--demo-space) * 1.5); border: 1px solid #a4aec2; border-radius: var(--demo-radius); background: var(--demo-paper); }
    .demo-action { display: inline-flex; min-height: 2.75rem; align-items: center; padding: .5rem 1rem; color: #fff; background: var(--demo-brand); border-radius: .375rem; text-underline-offset: .2em; transition: transform 160ms ease; }
    .demo-action:hover { transform: translateY(-1px); }
    .demo-action:focus-visible, .demo-card:focus-visible { outline: 3px solid var(--demo-brand); outline-offset: 4px; }
    @media (min-width: 48rem) { .demo-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (prefers-reduced-motion: reduce) { .demo-action { transition: none; } .demo-action:hover { transform: none; } }
''')

LESS_TOKENS = _text('''
    @brand: #173b86;
    @ink: #172033;
    @canvas: #f2f5fb;
    @space: 1rem;
    @radius: .75rem;
    @wide: 48rem;
''')

LESS_MIXINS = _text('''
    @import (reference) "tokens.less";
    .focus-ring() { outline: 3px solid @brand; outline-offset: 4px; }
    .card-surface() { padding: (@space * 1.5); border: 1px solid #a4aec2; border-radius: @radius; background: #fff; }
''')

LESS_STYLES = _text('''
    @import (reference) "tokens.less";
    @import (reference) "mixins.less";
    *, *::before, *::after { box-sizing: border-box; }
    body { margin: 0; color: @ink; background: @canvas; font-family: system-ui, sans-serif; line-height: 1.6; }
    .demo-shell { width: calc(100% - 2rem); max-width: 64rem; margin-inline: auto; padding-block: clamp(1rem, 4vw, 3rem); }
    .demo-grid { display: grid; gap: @space; grid-template-columns: minmax(0, 1fr); }
    .demo-card { .card-surface(); min-width: 0; overflow-wrap: anywhere; &:focus-visible { .focus-ring(); } }
    .demo-action {
      display: inline-flex; min-height: 2.75rem; align-items: center; padding: .5rem 1rem;
      color: #fff; background: @brand; border-radius: .375rem; text-underline-offset: .2em;
      transition: transform 160ms ease;
      &:hover { transform: translateY(-1px); }
      &:focus-visible { .focus-ring(); }
    }
    @media (min-width: @wide) { .demo-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (prefers-reduced-motion: reduce) { .demo-action { transition: none; &:hover { transform: none; } } }
''')

SCSS_TOKENS = _text('''
    $brand: #173b86 !default;
    $ink: #172033 !default;
    $canvas: #f2f5fb !default;
    $space: 1rem !default;
    $radius: .75rem !default;
    $wide: 48rem !default;
''')

SCSS_MIXINS = _text('''
    @use "tokens";
    @mixin focus-ring { outline: 3px solid tokens.$brand; outline-offset: 4px; }
    @mixin card-surface { padding: tokens.$space * 1.5; border: 1px solid #a4aec2; border-radius: tokens.$radius; background: #fff; }
''')

SCSS_STYLES = _text('''
    @use "tokens";
    @use "mixins";
    *, *::before, *::after { box-sizing: border-box; }
    body { margin: 0; color: tokens.$ink; background: tokens.$canvas; font-family: system-ui, sans-serif; line-height: 1.6; }
    .demo-shell { width: min(100% - 2rem, 64rem); margin-inline: auto; padding-block: clamp(1rem, 4vw, 3rem); }
    .demo-grid { display: grid; gap: tokens.$space; grid-template-columns: minmax(0, 1fr); }
    .demo-card { @include mixins.card-surface; min-width: 0; overflow-wrap: anywhere; &:focus-visible { @include mixins.focus-ring; } }
    .demo-action {
      display: inline-flex; min-height: 2.75rem; align-items: center; padding: .5rem 1rem;
      color: #fff; background: tokens.$brand; border-radius: .375rem; text-underline-offset: .2em;
      transition: transform 160ms ease;
      &:hover { transform: translateY(-1px); }
      &:focus-visible { @include mixins.focus-ring; }
    }
    @media (min-width: tokens.$wide) { .demo-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); } }
    @media (prefers-reduced-motion: reduce) { .demo-action { transition: none; &:hover { transform: none; } } }
''')

COMBINATION_GUIDE = _text('''
    # 框架与样式组合

    本文件是接入说明，命令未由模板自动执行。先读取目标项目 package.json、锁文件和现有构建配置。
    框架层（Angular / Vue / React）与样式层（CSS / Less / SCSS）可以组合；不应因选择一个样式包丢失已明确的框架。

    ## Angular + SCSS
    - 新项目使用官方 Angular CLI：`ng new demo-app --standalone --style=scss --routing=false --ssr=false`，版本由目标项目明确选择并锁定。
    - 将 angular-ts 的组件 TS/HTML 放入 CLI 生成的 src/app；从 frontend-scss 选择布局规则并复制 _tokens.scss、_mixins.scss 和 styles.scss。
    - 全局 body 等规则放在 src/styles.scss；组件规则放入 demo-contact.component.scss，Component 的 styleUrl 指向该文件。
    - 若组件内使用 tokens 或 mixins，也在该文件顶部明确 @use 并修正相对路径。保留 CLI 原来的配置和测试入口。

    ## Vue + Less
    - 在现有 Vue + Vite 项目安装并锁定开发依赖 `less`（例如经确认后执行 `npm install --save-dev less`）。
    - 保留模板的 tokens.less 与 mixins.less；在 Vue 单文件组件中使用 `<style scoped lang="less">` 并按位置导入所需模块。
    - body 等全局规则单独放在 src/styles.less，由 main.ts 导入；scoped 组件样式不要承担全局重置。
    - 不需要在浏览器引入 less.js，不启用 JavaScript 求值；浏览器收到的应为构建后的 CSS。

    ## React / Vue + SCSS 或原生 CSS
    - SCSS 由目标构建器支持的 Dart Sass 依赖编译；选择并锁定 `sass` 或项目已使用的 `sass-embedded`，不额外重复安装两套。
    - React 入口可 `import './styles.scss'`；Vue 可使用 `<style lang="scss">`。组件隔离遵循项目已有 CSS Modules / scoped 约定。
    - 原生 CSS 直接 import / link。CSS 自定义属性用于运行时主题，不能替代媒体查询条件中的预处理变量。

    ## App、跨端与小程序
    - React Native 原生界面使用 StyleSheet / style 对象与原生 View、Text 等组件；这些 CSS/DOM 演示只可作为设计令牌参考，不能直接粘贴运行。Flutter、SwiftUI、Compose 同样需要转换为对应原生布局和主题。
    - uni-app / Taro 按其目标平台与实际构建工具编译样式；H5 支持的选择器、Grid、媒体查询或 rem 不代表小程序和原生渲染端也支持。
    - 微信原生页面应输出 WXSS，Less/SCSS 需先由选定工具编译，再核对 WXSS 支持范围、rpx/px 单位、组件样式隔离和目标基础库。不要把网页的 body/:root 或浏览器焦点规则无条件搬过去。
    - 跨端差异在平台样式文件或条件编译中处理，并对实际目标端分别验收。

    ## 验收
    模板示例使用同一套 demo-* 类。实际接入需重新检查类名、变量路径、暗色主题、窄屏溢出、键盘焦点和减少动画；文件存在不代表目标项目已安装依赖或构建成功。
''')


def build_frontend_specialties(pack):
    """Build fresh catalog records through the shared, provenance-aware pack API."""
    angular = pack(
        "angular-ts", "Angular + TypeScript standalone 组件", "angular",
        ["angular", "anglar", "angular-ts", "standalone", "安古拉"],
        "接入官方 Angular CLI 工程的独立组件、HTML、CSS 与 bootstrap/config 示例；不是完整 Angular 工作区。",
        "src/app/demo-contact.component.ts", _text('''
            import { ChangeDetectionStrategy, Component, signal } from '@angular/core';

            @Component({
              selector: 'demo-contact',
              standalone: true,
              changeDetection: ChangeDetectionStrategy.OnPush,
              templateUrl: './demo-contact.component.html',
              styleUrl: './demo-contact.component.css',
            })
            export class DemoContactComponent {
              readonly status = signal('虚构演示，仅保存在本组件内存中。');

              save(event: Event, email: string): void {
                event.preventDefault();
                this.status.set(`已在本地检查 ${email.trim()}，未发送业务请求。`);
              }
            }
        '''),
        ["使用官方 Angular CLI 创建工作区，保持 Angular/CLI/TypeScript/Node 版本兼容；此包不提供 package.json 或完整构建配置。",
         "组件、模板与样式独立文件；standalone、signal 和 OnPush 写法须与目标 Angular 版本相符。",
         "模板变量和值通过绑定处理，不拼接 HTML；原生 required/email 校验不替代服务端验证。",
         "接入既有工程时保留 app.config 的路由、HTTP 和运行模式 providers，不以空配置覆盖真实工程。",
         "可与 frontend-scss / frontend-less 配方组合，统一选择的样式扩展名及相对路径。"],
        ["CLI 项目与依赖版本已核对", "bootstrap 的组件选择器在入口 HTML 存在", "TS 中 templateUrl/styleUrl 对应实际文件",
         "键盘、标签、校验与 live status 已验证", "已运行目标工程 ng build/ng test 并记录结果，或明确未执行"],
        "先按 INTEGRATION.md 创建/检查官方 CLI 工程，再接入 src/ 下的文件。示例只有本地表单回显，无路由、真实API、登录或发布能力。",
        references=("https://angular.dev/guide/components", "https://angular.dev/api/platform-browser/bootstrapApplication",
                    "https://angular.dev/tools/cli/setup-local", "https://angular.dev/reference/versions"),
        extra={
            "src/app/demo-contact.component.html": _text('''
                <main class="demo-shell" aria-labelledby="demo-title">
                  <h1 id="demo-title">DEMO 联系方式</h1>
                  <form (submit)="save($event, emailInput.value)">
                    <label for="demo-email">电子邮箱</label>
                    <input #emailInput id="demo-email" name="email" type="email" autocomplete="email" required aria-describedby="demo-help">
                    <p id="demo-help">例如 demo@example.invalid，仅演示本地校验。</p>
                    <button type="submit">检查输入</button>
                    <p role="status" aria-live="polite">{{ status() }}</p>
                  </form>
                </main>
            '''),
            "src/app/demo-contact.component.css": _text('''
                :host { --demo-brand: #173b86; display: block; color: #172033; font: 1rem/1.6 system-ui, sans-serif; }
                *, *::before, *::after { box-sizing: border-box; }
                .demo-shell { width: min(100% - 2rem, 40rem); margin-inline: auto; padding-block: 2rem; }
                form { display: grid; gap: .75rem; }
                input, button { width: 100%; min-height: 2.75rem; padding: .5rem .75rem; font: inherit; }
                button { color: #fff; background: var(--demo-brand); border: 1px solid transparent; border-radius: .375rem; transition: transform 160ms ease; }
                button:hover { transform: translateY(-1px); }
                input:focus-visible, button:focus-visible { outline: 3px solid var(--demo-brand); outline-offset: 4px; }
                @media (min-width: 48rem) { button { width: max-content; } }
                @media (prefers-reduced-motion: reduce) { button { transition: none; } button:hover { transform: none; } }
            '''),
            "src/app/app.config.ts": _text('''
                import type { ApplicationConfig } from '@angular/core';
                // Minimal example only. Preserve providers produced by the target CLI.
                export const appConfig: ApplicationConfig = { providers: [] };
            '''),
            "src/main.ts": _text('''
                import { bootstrapApplication } from '@angular/platform-browser';
                import { DemoContactComponent } from './app/demo-contact.component';
                import { appConfig } from './app/app.config';

                bootstrapApplication(DemoContactComponent, appConfig)
                  .catch((error: unknown) => console.error(error));
            '''),
            "src/index.html": _text('''
                <!doctype html>
                <html lang="zh-CN"><head><meta charset="utf-8"><title>DEMO Angular 表单</title>
                <base href="/"><meta name="viewport" content="width=device-width, initial-scale=1"></head>
                <body><demo-contact></demo-contact></body></html>
            '''),
            "INTEGRATION.md": _text('''
                # 接入现有开源 Angular 工具链

                这是一套本地编写的组件配方，不是从 Angular 仓库下载的完整脚手架，也没有声称已完成 Angular AOT 构建。
                先按 Angular 官方兼容表选择 CLI、Angular、TypeScript 和 Node 版本，并保留目标项目锁文件。
                新工作区可用已安装且选定版本的官方 CLI：`ng new demo-app --standalone --style=css --routing=false --ssr=false`。

                1. 将 demo-contact.component.ts/html/css 放入 src/app，不覆盖已有业务组件。
                2. 在全新演示项目，参考本包 main.ts 和 index.html，将根组件改为 DemoContactComponent 与 demo-contact 选择器；既有产品可直接导入 standalone 组件。
                3. app.config.ts 仅展示 ApplicationConfig 结构。保留 CLI 已生成的 providers（包括目标版本的运行模式）；不应直接用空数组替换现有配置。
                4. 保留 CLI 的 package.json、angular.json、tsconfig 和测试配置；示例没有这些文件，直接在本模板目录执行 ng serve 不会启动完整工程。
                5. 在真实工作区执行 ng build 与其测试命令并记录结果；当前模板目录检查不代替完整编译、运行或浏览器验收。

                如选择 SCSS，参考 COMBINATIONS.md 同步组件的 styleUrl、文件扩展名和模块路径。
            '''),
            "COMBINATIONS.md": COMBINATION_GUIDE,
        })
    styles = []
    for identifier, name, framework, filename, content, modules, examples, references in (
        ("frontend-css", "原生 CSS 主题与响应式布局", "css", "styles.css", CSS_STYLES, {},
         "直接在浏览器打开 demo.html，使用 styles.css。CSS 自定义属性可以在运行时继承与覆盖；48rem 媒体查询使用字面断点，不在条件中使用 var()。",
         (CSS_REFERENCE, MOTION_REFERENCE)),
        ("frontend-less", "Less 模块与响应式布局", "less", "styles.less", LESS_STYLES,
         {"tokens.less": LESS_TOKENS, "mixins.less": LESS_MIXINS},
         "使用目标项目已安装且锁定的 Less 编译器执行 lessc styles.less styles.css，再打开 demo.html；Vue + Vite 接入见 COMBINATIONS.md。Less 的 @import (reference) 是有效 Less 模块导入，不是 Sass 的旧导入机制。",
         ("https://lesscss.org/features/", "https://lesscss.org/usage/", MOTION_REFERENCE)),
        ("frontend-scss", "SCSS 模块与响应式布局", "scss", "styles.scss", SCSS_STYLES,
         {"_tokens.scss": SCSS_TOKENS, "_mixins.scss": SCSS_MIXINS},
         "使用目标项目已安装且锁定的 Dart Sass 执行 sass styles.scss styles.css，再打开 demo.html。本包只使用 @use 和命名空间；Sass 的 SCSS 花括号语法与缩进 .sass 语法不是相同文件格式。",
         ("https://sass-lang.com/documentation/at-rules/use/", "https://sass-lang.com/documentation/cli/dart-sass/", MOTION_REFERENCE)),
    ):
        extra = dict(modules, **{"demo.html": STYLE_HTML, "COMBINATIONS.md": COMBINATION_GUIDE})
        styles.append(pack(
            identifier, name, framework, [framework, "sass" if framework == "scss" else framework, "样式", "响应式", "主题", "布局"],
            "可组合到框架工程的样式层：主题变量、网格布局、键盘焦点和减少动画，附本地 HTML 演示。",
            filename, content,
            ["框架选择与样式选择分开记录；按实际任务组合，不把 CSS/Less/SCSS 当作独立应用框架。",
             "编译期变量与 CSS 运行时自定义属性有不同作用；跟随已锁定依赖与既有构建配置。",
             "保持 focus-visible 可见，不通过移除 outline 隐藏焦点；减少动画偏好下关闭位移动画。",
             "全局规则只在全局入口加载，组件隔离依据实际 scoped/CSS Modules 约定。",
             "不使用远程 CDN 或浏览器运行预处理器；Less/SCSS 先由项目工具链编译。",
             "React Native 需要转换为 StyleSheet，微信原生需要经过预处理与兼容检查的 WXSS；不能直接复用网页 DOM/CSS。跨端边界见 COMBINATIONS.md。"],
            ["变量和模块导入可解析", "HTML 中类名与样式对应", "窄屏无横向内容溢出", "键盘焦点清晰可见",
             "减少动画时无模板位移动画", "编译与浏览器检查记录真实存在，未执行项明确标注"],
            examples, references=references, extra=extra))
    return [angular, *styles, *_ecosystem_styles_and_components(pack)]


def _ecosystem_styles_and_components(pack):
    """Optional styling/component-library layers, separate from app frameworks."""
    tailwind = pack(
        "frontend-tailwind", "Tailwind CSS 工具类与构建接入", "tailwind",
        ["tailwind", "tailwindcss", "工具类", "utility css"],
        "使用 Tailwind CSS v4 工具类构建响应式界面，按框架选择 Vite 或 PostCSS 接入。",
        "demo.html", _text('''
            <!doctype html>
            <html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
            <title>DEMO Tailwind 界面</title><link rel="stylesheet" href="styles.css"></head>
            <body class="bg-slate-100 text-slate-900">
              <main class="mx-auto max-w-5xl px-4 py-8" aria-labelledby="demo-title">
                <h1 id="demo-title" class="text-2xl font-bold">DEMO 工具类样式</h1>
                <p class="my-4">虚构演示；需由 Vite/Tailwind 构建生成 CSS。</p>
                <div class="grid gap-4 md:grid-cols-2">
                  <article class="rounded-xl border border-slate-300 bg-white p-6">
                    <h2 class="text-xl font-semibold">可访问的响应式卡片</h2>
                    <a href="#demo-notes" class="mt-4 inline-flex min-h-11 items-center rounded-md bg-demo-brand px-4 text-white underline underline-offset-4 transition-transform hover:-translate-y-0.5 focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-demo-brand motion-reduce:transform-none motion-reduce:transition-none">查看说明</a>
                  </article>
                  <section id="demo-notes" class="rounded-xl border border-slate-300 bg-white p-6" tabindex="-1">
                    <h2 class="text-xl font-semibold">DEMO 说明</h2><p>样式构建与组件业务逻辑分别验收。</p>
                  </section>
                </div>
              </main>
            </body></html>
        '''),
        ["本配方对应 Tailwind v4；已有 v3 项目应先查迁移文档，不能直接混用配置。",
         "将 @tailwindcss/vite 插件合并到现有 Vite 插件数组，保留 Vue/React 等插件和原项目配置。",
         "Next.js 使用 @tailwindcss/postcss 并保留现有 PostCSS 配置；Nuxt/Angular 依官方框架指南接入，不能套用 Vite 配置覆盖其工具链。",
         "工具类字符串保持可静态发现；由业务值切换完整类名，不拼接不完整类名。",
         "本包为普通 CSS 入口，不通过 Less/SCSS 预处理 Tailwind v4；各样式方案依据项目选择独立入口。"],
        ["Tailwind 主版本和插件版本兼容", "既有框架插件未丢失", "生产构建包含实际使用类名", "焦点、窄屏和减少动画已验证"],
        "在已有 Vite 工程中选择并锁定 tailwindcss 与 @tailwindcss/vite（安装示例 npm install -D tailwindcss @tailwindcss/vite），合并插件后让页面加载 styles.css。这里只交付接入文件，未安装包或生成生产 CSS。",
        references=("https://tailwindcss.com/docs/installation/using-vite", "https://tailwindcss.com/docs/installation/framework-guides/nextjs", "https://tailwindcss.com/docs/compatibility"),
        extra={
            "styles.css": _text('''
                @import "tailwindcss";
                @theme { --color-demo-brand: #173b86; }
            '''),
            "vite.plugin.ts": _text('''
                import tailwindcss from '@tailwindcss/vite';
                // Merge this plugin into the existing plugins array.
                // Keep existing vue(), react() and project-specific plugins.
                export const demoTailwindPlugin = tailwindcss();
            '''),
            "postcss.config.mjs": _text('''
                // Next.js / PostCSS example. Merge with any existing plugins.
                export default { plugins: { '@tailwindcss/postcss': {} } };
            '''),
            "INTEGRATION.md": _text('''
                # Tailwind 接入边界

                vite.plugin.ts 导出一个插件实例；在真实 vite.config.ts 的 plugins 数组追加它，不能替换整个配置。
                Vue/React 项目把 demo.html 的结构适配到其组件，React 将 class 改为 className。
                此入口使用 Tailwind v4 CSS @import/@theme，不是 Sass 的旧 @import。不要将 styles.css 改为 SCSS 来处理 Tailwind。
                Next.js 改用 @tailwindcss/postcss：安装并锁定 tailwindcss、@tailwindcss/postcss、postcss，合并 postcss.config.mjs，并在 app/globals.css 引入 Tailwind。不要给 Next.js 新增 Vite 插件。
                Nuxt、Angular CLI 不直接使用这里的独立 Vite 配置；应跟随各框架/Tailwind 官方指南选择其支持的接入方式，保留已有构建配置。
                先核对目标浏览器与 Tailwind 主版本，随后在实际项目构建并检查类名生成。当前文件不是完整独立脚手架。
            '''),
        })
    bootstrap = pack(
        "frontend-bootstrap", "Bootstrap 响应式栅格与组件样式", "bootstrap",
        ["bootstrap", "bootstrap5", "栅格", "响应式组件"],
        "复用 Bootstrap 5 的预编译 CSS、栅格和按钮类；避免为纯样式页面引入不需要的 JS 插件。",
        "demo.html", _text('''
            <!doctype html>
            <html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
            <title>DEMO Bootstrap 界面</title></head>
            <body class="bg-body-tertiary">
              <main class="container py-4" aria-labelledby="demo-title">
                <h1 id="demo-title" class="h2 mb-3">DEMO 响应式栅格</h1>
                <div class="row g-3">
                  <div class="col-12 col-md-6"><article class="card h-100"><div class="card-body">
                    <h2 class="card-title h4">虚构卡片</h2><p class="card-text">Bootstrap 样式由项目依赖导入。</p>
                    <a class="btn btn-primary demo-action" href="#demo-notes">查看说明</a>
                  </div></article></div>
                  <div class="col-12 col-md-6"><section id="demo-notes" class="card h-100" tabindex="-1"><div class="card-body">
                    <h2 class="card-title h4">样式说明</h2><p class="card-text">链接只定位本页；没有业务请求。</p>
                  </div></section></div>
                </div>
              </main>
              <script type="module" src="./main.ts"></script>
            </body></html>
        '''),
        ["先核对并锁定 Bootstrap 5 主版本与实际依赖；本例导入预编译 CSS，不复制 Bootstrap 源码。",
         "保持容器、row、col 嵌套关系，不能只给单列添加断点就假定整体布局适配。",
         "纯 CSS 演示无需 Bootstrap JS；模态框/下拉/提示等交互应按官方依赖及生命周期单独接入。",
         "React/Vue 业务组件由对应框架拥有 DOM 和状态，避免同时使用会竞争同一 DOM 的插件。"],
        ["Bootstrap CSS 在入口真实导入", "移动与桌面列宽正确", "按钮文字对比与焦点清晰", "仅加载实际需要的插件与依赖"],
        "在 Vite 等支持 CSS 模块导入的现有工程安装并锁定 bootstrap（例如 npm install bootstrap），使用 main.ts 的导入；demo.html 需由构建器服务，直接双击不会编译 TypeScript。组件配方未执行依赖安装。",
        references=("https://getbootstrap.com/docs/5.3/getting-started/vite/", "https://getbootstrap.com/docs/5.3/layout/grid/"),
        extra={
            "main.ts": _text('''
                import 'bootstrap/dist/css/bootstrap.min.css';
                import './overrides.css';
                // This CSS-only recipe needs no Bootstrap JavaScript plugins.
            '''),
            "overrides.css": _text('''
                .demo-action { min-height: 2.75rem; display: inline-flex; align-items: center; }
                .demo-action:focus-visible { outline: 3px solid #173b86; outline-offset: 4px; }
                @media (prefers-reduced-motion: reduce) { .demo-action { transition: none; } }
            '''),
            "INTEGRATION.md": _text('''
                # Bootstrap 与框架组合

                Vue / React 在应用入口导入 Bootstrap CSS；demo.html 的结构适配到组件（React 用 className）。
                Angular 可在现有全局样式构建配置中纳入依赖里的预编译 CSS，不复制本包 main.ts 作为 Angular bootstrap。
                自定义 overrides.css 放在 Bootstrap CSS 之后。若已有设计系统，先评估 Bootstrap 的全局样式影响。
                本例有意不使用 Bootstrap 源 Sass，故不需要 Sass 的旧 @import，也不声称完成其模块化迁移。
            '''),
        })
    element = pack(
        "frontend-element-plus", "Vue 3 + Element Plus 表单组件", "element-plus",
        ["element plus", "element-plus", "elementplus", "饿了么组件"],
        "将 Element Plus 组件接入现有 Vue 3 工程，提供本地草稿输入与状态反馈。",
        "DemoElementForm.vue", _text('''
            <script setup lang="ts">
            import { ref } from 'vue'
            import { ElButton, ElInput } from 'element-plus'
            const draftName = ref('')
            const status = ref('虚构演示：只保存在组件内存中。')
            function saveDraft() {
              if (!draftName.value.trim()) return
              status.value = `本地草稿：${draftName.value.trim()}；未提交服务端。`
            }
            </script>

            <template>
              <section class="demo-panel" aria-labelledby="demo-title">
                <h1 id="demo-title">DEMO Element Plus</h1>
                <label for="demo-draft-name">草稿名称</label>
                <ElInput id="demo-draft-name" v-model="draftName" placeholder="虚构草稿名称" />
                <ElButton type="primary" :disabled="!draftName.trim()" @click="saveDraft">记录本地草稿</ElButton>
                <p role="status" aria-live="polite">{{ status }}</p>
              </section>
            </template>

            <style scoped>
            .demo-panel { display: grid; gap: 1rem; max-width: 36rem; margin-inline: auto; padding: 1rem; }
            </style>
        '''),
        ["只组合 Vue 3 模板，不把 Element Plus 当成 React/Angular 组件库。",
         "本例手动导入组件、全局引入库 CSS，避免默认依赖未配置的自动导入插件。",
         "依据目标版本检查 Vue peerDependencies、构建和语言服务；已有项目版本与锁文件优先。",
         "按钮仅修改内存状态；接真实 API 时补加载、错误、权限和重复提交处理。"],
        ["Vue 3 与 Element Plus 版本兼容", "组件和库 CSS 均有入口", "标签关联到真实输入控件", "空值、键盘和状态反馈检查通过"],
        "在已有 Vue 3 工程安装并锁定 element-plus，导入 DemoElementForm.vue 并在入口导入 element-plus/dist/index.css；本包未安装依赖或启动组件。",
        references=("https://element-plus.org/en-US/guide/quickstart",),
        extra={"INTEGRATION.md": _text('''
            # Element Plus 接入

            安装示例：npm install element-plus。实际版本由目标 Vue 工程兼容要求决定并写入锁文件。
            main.ts 全局导入 `element-plus/dist/index.css`；在父 Vue 组件直接导入并渲染 DemoElementForm。
            本例已显式导入 ElButton / ElInput，不需要 app.use 或自动导入插件；若改为按需样式加载，跟随库官方方案配置并构建验证。
            可与 Less / SCSS 组合维护本地组件外层布局；库内部主题令牌与覆盖方式须核对目标版本，不能靠大量全局 !important 硬覆盖。
        ''')})
    antd = pack(
        "frontend-ant-design", "React + Ant Design 交互组件", "ant-design",
        ["ant design", "ant-design", "antd", "蚂蚁设计"],
        "复用 Ant Design 的输入与按钮组件，保留 React 状态和可访问标签。",
        "DemoAntDesignForm.tsx", _text('''
            'use client';

            import { useState } from 'react';
            import { Button, Input, Space } from 'antd';

            export default function DemoAntDesignForm() {
              const [name, setName] = useState('');
              const [status, setStatus] = useState('虚构演示：尚未记录草稿。');
              return (
                <section aria-labelledby="demo-title" style={{ maxWidth: '36rem', margin: 'auto', padding: '1rem' }}>
                  <h1 id="demo-title">DEMO Ant Design</h1>
                  <Space orientation="vertical" style={{ width: '100%' }}>
                    <label htmlFor="demo-name">草稿名称</label>
                    <Input id="demo-name" value={name} onChange={(event) => setName(event.target.value)} />
                    <Button type="primary" disabled={!name.trim()} onClick={() => setStatus(`本地草稿：${name.trim()}；未提交服务端。`)}>记录本地草稿</Button>
                    <p role="status" aria-live="polite">{status}</p>
                  </Space>
                </section>
              );
            }
        '''),
        ["本配方使用 React 的 antd 包，不混入面向其他框架的同名组件实现。",
         "按目标 React/antd peerDependencies 与锁文件选择版本，不盲目升级已有项目。",
         "本例使用 Ant Design 6 的 Space orientation；仍使用 v5 的项目按对应 API 调整为 direction，保留其已锁定版本。",
         "样式和主题使用所选主版本的官方机制，不把旧版 Less 变量覆盖方式直接套到新版。",
         "保留可访问标签和真实状态回执，演示按钮不表示数据已持久化。"],
        ["React 与 antd 兼容", "TSX 已在目标工程编译", "禁用与键盘焦点可用", "主题/SSR 策略与目标项目一致"],
        "在 React + TypeScript 项目安装并锁定 antd，将此 TSX 组件导入 App。示例命令 npm install antd 不由模板自动执行。",
        references=("https://ant.design/docs/react/use-with-vite/", "https://ant.design/docs/react/customize-theme/",
                    "https://ant.design/components/space/", "https://5x.ant.design/components/space/",
                    "https://ant.design/docs/react/use-with-next/"),
        extra={"INTEGRATION.md": _text('''
            # Ant Design 接入

            沿用现有 React + TypeScript 工程，安装并锁定 antd 后由 App 导入 DemoAntDesignForm。
            本示例按 Ant Design 6 使用 `Space orientation="vertical"`。v5 项目依其版本文档改用 `direction="vertical"`，不要为复制本模板强制升级已有依赖。
            如需 ConfigProvider 主题、全局 reset 样式或 SSR，按目标主版本官方文档独立配置；本例不改这些全局设置。
            组件含 useState 和事件处理，首行 `'use client';` 声明 Next.js App Router 的客户端边界；服务端 page.tsx 可以导入并渲染它，无需把整个页面或布局改为客户端组件。
            Next.js App Router 的全局 SSR 样式另按官方说明接入：核对版本并锁定 `@ant-design/nextjs-registry`，在现有 `app/layout.tsx` 的 body 内以 `AntdRegistry` 包裹 children，导入路径为 `@ant-design/nextjs-registry`。
            保留已有布局、ConfigProvider、主题、认证上下文和 registry 配置；已集成时复用，避免重复包裹。Pages Router 使用对应的样式提取方案，不直接套用 App Router 布局代码。
            官方接入说明：https://ant.design/docs/react/use-with-next/ 。客户端声明只建立组件边界，不能替代 SSR 样式收集和水合验证。
            组件库是附加层，不能代替 React 应用入口、路由、构建配置或业务鉴权。
            真实接口接入前补充请求中、失败和重复提交控制。源码片段检查不代表库类型检查、浏览器运行或生产构建通过。
        ''')})
    mui = pack(
        "frontend-mui", "React + Material UI 主题与组件", "mui",
        ["mui", "material ui", "material-ui", "materialui"],
        "使用 Material UI 与 Emotion 默认样式引擎提供主题、输入和状态展示。",
        "DemoMuiForm.tsx", _text('''
            'use client';

            import { useState } from 'react';
            import { Button, Stack, TextField, ThemeProvider, Typography, createTheme } from '@mui/material';

            const theme = createTheme({ palette: { primary: { main: '#173b86' } } });

            export default function DemoMuiForm() {
              const [name, setName] = useState('');
              const [status, setStatus] = useState('虚构演示：草稿仅保存在内存中。');
              return (
                <ThemeProvider theme={theme}>
                  <Stack component="section" spacing={2} aria-labelledby="demo-title" sx={{ maxWidth: 576, mx: 'auto', p: 2 }}>
                    <Typography id="demo-title" component="h1" variant="h5">DEMO Material UI</Typography>
                    <TextField id="demo-name" label="草稿名称" value={name} onChange={(event) => setName(event.target.value)} helperText="请填写虚构演示名称" />
                    <Button variant="contained" disabled={!name.trim()} onClick={() => setStatus(`本地草稿：${name.trim()}；未提交服务端。`)}>记录本地草稿</Button>
                    <Typography role="status" aria-live="polite">{status}</Typography>
                  </Stack>
                </ThemeProvider>
              );
            }
        '''),
        ["使用 @mui/material 与其默认 Emotion 引擎，依赖安装范围遵循官方文档和当前 React 版本。",
         "已有应用应复用自己的 ThemeProvider 与主题；本例局部主题仅用于独立演示。",
         "TextField 的 label/id/help 文案应保留，颜色变化后重新验证对比与错误状态。",
         "SSR 样式收集、服务端与客户端边界根据目标框架单独配置，不能仅凭本文件保证水合成功。"],
        ["MUI/React/Emotion 依赖兼容", "输入标签与辅助文字正确关联", "主题与现有全局配置协调", "真实目标工程编译和交互检查有记录"],
        "在 React + TypeScript 工程按官方说明安装并锁定 @mui/material @emotion/react @emotion/styled；由 App 导入 DemoMuiForm。本配方没有自动安装或执行组件。",
        references=("https://mui.com/material-ui/getting-started/installation/", "https://mui.com/material-ui/customization/theming/",
                    "https://mui.com/material-ui/integrations/nextjs/"),
        extra={"INTEGRATION.md": _text('''
            # Material UI 接入

            安装示例：npm install @mui/material @emotion/react @emotion/styled。
            先核对目标项目 React 主版本、MUI 的 peerDependencies 和官方安装页的兼容说明，再写入锁文件。
            在已有应用中复用其 ThemeProvider，避免重复全局重置。演示组件通过 useState 管理本地草稿，没有存储接口。
            组件首行 `'use client';` 为 useState、事件处理和局部 createTheme 建立客户端边界；Next.js App Router 的服务端 page.tsx 可以直接导入并渲染它，不必将整个页面或布局设为客户端。
            Next.js App Router 的 SSR 样式按官方集成页核对并锁定 `@mui/material-nextjs` 与 `@emotion/cache`，在现有 `app/layout.tsx` 的 body 内用 `AppRouterCacheProvider` 包裹 children。
            provider 导入使用与目标 Next.js 版本匹配且已安装包实际导出的入口，例如 Next.js 15 对应 `@mui/material-nextjs/v15-appRouter`；不要把示例入口直接用于其他主版本。
            保留既有布局、ThemeProvider、主题、Emotion 缓存选项和 CSS 层设置，已集成时复用；将本例局部主题替换为已有主题，避免重复全局 provider 或重置。
            官方接入说明：https://mui.com/material-ui/integrations/nextjs/ 。Pages Router 按其单独章节接入，组件的客户端声明不能替代样式缓存、SSR 和水合检查。
        ''')})
    return [tailwind, bootstrap, element, antd, mui]
