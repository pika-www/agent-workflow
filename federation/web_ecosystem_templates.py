"""Curated mainstream web/cross-platform recipes, authored locally.

This module only returns template definitions. It never downloads dependencies,
runs a scaffold, or implies the target SDK has passed a build. Official projects
and documentation were checked on 2026-10-03; versions belong to each target
project's own lockfile, not an invented shared dependency matrix.
"""
from __future__ import annotations

import json
from textwrap import dedent


def _text(value):
    return dedent(value).strip() + "\n"


def _json(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def build_web_ecosystem_templates(pack_factory):
    """Build independent pack dictionaries using specialist_catalog._pack."""
    packs = []

    def add(identifier, name, framework, keywords, description, filename, body,
            rules, checks, recipe, references, extra=None):
        files = dict(extra or {})
        files["SCAFFOLD.md"] = _text(recipe)
        pack = pack_factory(
            identifier, name, framework, keywords, description, filename, _text(body),
            ["官方文档与仓库核对日期：2026-10-03；本包是本项目原创适配的源码与脚手架扩展配方。",
             "本包未安装目标框架 SDK、未构建完整工程、未做模拟器或真机验收；不能把文件存在当成运行成功。"] + rules,
            checks + ["记录实际框架版本、锁文件、构建输出与目标平台结果；未执行项明确标记"],
            "先阅读 SCAFFOLD.md，在对应官方脚手架工程中应用本包；保留已有依赖、配置与人工修改。"
            "这里的 DEMO 草稿只保存在当前页面内存，刷新或离开页面会丢失；没有后台、登录、支付或发布。",
            references=references, extra=files)
        packs.append(pack)

    add(
        "nextjs-app", "Next.js App Router 页面与交互", "nextjs",
        ["next.js", "nextjs", "next js", "app router", "服务端组件", "react 服务端渲染"],
        "为 React 全栈页面保留服务端入口，并用独立 Client Component 实现本地草稿交互。",
        "app/page.tsx", """
        import DraftForm from './ui/draft-form';

        export default function Page() {
          return <main><h1>DEMO 页面草稿</h1><DraftForm /></main>;
        }
        """,
        ["App Router 的页面和布局默认可作为 Server Components；只有需要状态和事件的模块添加 'use client'。",
         "客户端模块不放服务端凭证；传给客户端的 props 须满足框架序列化要求。",
         "本例不调用接口、不实现 Server Action；不得将内存草稿状态写成后端提交成功。"],
        ["app/layout.tsx 保留 html/body 根布局", "交互边界与服务端入口分开", "空白输入不能生成草稿", "页面和键盘路径有实际验收"],
        """
        # Next.js 接入配方

        适用：Next.js App Router + React + TypeScript，根目录采用 app/。
        先使用官方 create-next-app 创建新工程并选择 TypeScript、App Router；脚手架与 Node 版本按官方安装页核对，保留锁文件。
        例如 `npx create-next-app@latest demo-next`，交互时选择 App Router；本包没有执行该命令。
        如果选择 src/ 布局，将本包 app/ 整体映射为 src/app/，不要同时建立两套路由。
        把页面、ui/draft-form.tsx 合入工程；已有 app/layout.tsx 时合并其内容，保留字体、元数据与全局样式。
        本包的最小布局可用于空白工程，不应覆盖既有布局。按生成的 package.json 运行 build/lint（若有）。
        不包含 package.json、锁文件、鉴权、数据库或部署配置，不能单独作为完整工程运行。
        """,
        ["https://nextjs.org/docs/app/getting-started/server-and-client-components",
         "https://nextjs.org/docs/app/getting-started/installation", "https://github.com/vercel/next.js"],
        extra={
            "app/layout.tsx": _text("""
                import type { ReactNode } from 'react';

                export default function RootLayout({ children }: { children: ReactNode }) {
                  return <html lang="zh-CN"><body>{children}</body></html>;
                }
            """),
            "app/ui/draft-form.tsx": _text("""
                'use client';

                import { useState, type FormEvent } from 'react';

                export default function DraftForm() {
                  const [title, setTitle] = useState('');
                  const [message, setMessage] = useState('尚未生成本地草稿');
                  function preview(event: FormEvent<HTMLFormElement>) {
                    event.preventDefault();
                    const value = title.trim();
                    setMessage(value ? `DEMO 本地草稿：${value}` : '请输入非空白标题');
                  }
                  return (
                    <form onSubmit={preview}>
                      <label htmlFor="draft-title">草稿标题</label>
                      <input id="draft-title" value={title} required maxLength={80}
                        onChange={(event) => { setTitle(event.target.value); setMessage('内容已更改，尚未生成草稿'); }} />
                      <button type="submit" disabled={!title.trim()}>生成本地草稿</button>
                      <p role="status">{message}</p>
                    </form>
                  );
                }
            """),
        })

    add(
        "nuxt-app", "Nuxt 4 Vue 页面与路由", "nuxt",
        ["nuxt", "nuxt.js", "nuxtjs", "vue 服务端渲染", "nuxt4", "nuxt 4"],
        "采用 Nuxt 4 app/ 目录与 Vue 3 组合式 API 的内存草稿页面。",
        "app/pages/index.vue", """
        <script setup lang="ts">
        import { computed, ref } from 'vue';

        const title = ref('');
        const ready = computed(() => title.value.trim().length > 0);
        const message = ref('尚未生成本地草稿');
        function preview() {
          const value = title.value.trim();
          message.value = value ? `DEMO 本地草稿：${value}` : '请输入非空白标题';
        }
        </script>

        <template>
          <main>
            <h1>DEMO Nuxt 草稿</h1>
            <form @submit.prevent="preview">
              <label for="draft-title">草稿标题</label>
              <input id="draft-title" v-model="title" required maxlength="80"
                @input="message = '内容已更改，尚未生成草稿'" />
              <button type="submit" :disabled="!ready">生成本地草稿</button>
              <p role="status">{{ message }}</p>
            </form>
          </main>
        </template>
        """,
        ["本包按 Nuxt 4 app/pages 布局；旧 Nuxt 3 项目应先核对目录配置，不能照搬迁移。",
         "使用路由页面时，app/app.vue 通过 NuxtPage 展示当前页面。",
         "组件 setup 阶段不访问 window/localStorage；需要浏览器能力时明确客户端时机与 hydration 一致性。"],
        ["首页路由解析到 app/pages/index.vue", "app.vue 渲染 NuxtPage", "服务端和首次客户端渲染状态一致", "更新输入后旧成功提示会失效"],
        """
        # Nuxt 接入配方

        在官方 Nuxt 4 脚手架工程中合入 app/pages/index.vue，保留工程自己的 package.json 与锁文件。
        新工程可参考官方安装说明运行 `npm create nuxt@latest demo-nuxt`；此处只保存配方，没有运行。
        使用 app/ 目录；已有 app/app.vue、nuxt.config.ts 时合并而非覆盖。
        最小 nuxt.config.ts 保持 SSR；如目标工程需要 SPA，需要另行分析渲染与 SEO 要求。
        按目标工程生成的 build/typecheck 命令验收；未包含依赖和部署配置，不能独立运行。
        """,
        ["https://nuxt.com/docs/4.x/directory-structure/app/pages",
         "https://nuxt.com/docs/4.x/directory-structure/app/app", "https://github.com/nuxt/nuxt"],
        extra={"app/app.vue": "<template><NuxtPage /></template>\n",
               "nuxt.config.ts": "export default defineNuxtConfig({ ssr: true });\n"})

    add(
        "svelte-component", "Svelte 5 与 SvelteKit 页面", "svelte",
        ["svelte", "sveltekit", "svelte kit", "svelte5", "svelte 5", "runes"],
        "使用 Svelte 5 runes 与 SvelteKit 文件路由的本地草稿页面。",
        "src/routes/+page.svelte", """
        <script lang="ts">
          let title = $state('');
          let message = $state('尚未生成本地草稿');
          const ready = $derived(title.trim().length > 0);
          function preview(event: SubmitEvent) {
            event.preventDefault();
            const value = title.trim();
            message = value ? `DEMO 本地草稿：${value}` : '请输入非空白标题';
          }
        </script>

        <svelte:head><title>DEMO Svelte 草稿</title></svelte:head>
        <main>
          <h1>DEMO Svelte 草稿</h1>
          <form onsubmit={preview}>
            <label for="draft-title">草稿标题</label>
            <input id="draft-title" bind:value={title} required maxlength="80"
              oninput={() => { message = '内容已更改，尚未生成草稿'; }} />
            <button type="submit" disabled={!ready}>生成本地草稿</button>
            <p role="status">{message}</p>
          </form>
        </main>
        """,
        ["使用 Svelte 5 $state/$derived 与事件属性；不要把旧 $: 状态示例与 runes 模式混用。",
         "+page.svelte 属于 SvelteKit 路由约定；纯 Svelte/Vite 工程需改放组件目录并显式挂载。",
         "本例不使用 form actions、不写服务端文件；页面内存草稿刷新即失效。"],
        ["Svelte 编译器和 SvelteKit 版本来自同一工程锁文件", "非空白校验与禁用状态一致", "检查首次渲染与输入事件", "执行 svelte-check 与目标工程 build"],
        """
        # Svelte 接入配方

        使用官方 Svelte CLI `npx sv create demo-svelte` 创建 SvelteKit 工程，选择 TypeScript；该命令未执行。
        合入 src/routes/+page.svelte，保留 CLI 生成的 svelte.config、vite.config、app.html 和适配器配置。
        本包选择 SvelteKit 路由承载 Svelte 5 组件，不等同于只有 App.svelte 的 Vite SPA。
        在该工程执行其 check/build 脚本；部署适配器由运行平台确定。本包没有包含适配器、依赖或锁文件。
        """,
        ["https://svelte.dev/docs/svelte/$state", "https://svelte.dev/docs/svelte/$derived",
         "https://svelte.dev/docs/cli/sv-create", "https://github.com/sveltejs/svelte"],
        extra={"FRAMEWORK_SCOPE.json": _json({"component_syntax": "Svelte 5 runes", "routing": "SvelteKit", "route": "/", "page": "src/routes/+page.svelte", "dependency_owner": "official-scaffold-lockfile", "sdk_build_status": "not-run"})})

    add(
        "astro-content", "Astro 内容页面", "astro",
        ["astro", "astrojs", "内容站", "静态内容", "astro 内容"],
        "适合文档、资讯与内容网站的 Astro 页面和可复用布局，无需客户端框架脚本。",
        "src/pages/index.astro", """
        ---
        import SiteLayout from '../layouts/SiteLayout.astro';
        const notes = [
          { slug: 'demo-outline', title: 'DEMO 内容提纲', summary: '虚构占位：替换为已核对资料。' },
          { slug: 'demo-review', title: 'DEMO 审阅清单', summary: '虚构占位：记录来源与审阅状态。' },
        ];
        ---
        <SiteLayout title="DEMO 内容索引">
          <h1>DEMO 内容索引</h1>
          <p>示例仅演示结构，未包含真实文章或发布操作。</p>
          <ul>
            {notes.map((note) => <li id={note.slug}><h2>{note.title}</h2><p>{note.summary}</p></li>)}
          </ul>
        </SiteLayout>
        """,
        [".astro frontmatter 在构建或服务端执行，不是浏览器响应式状态。",
         "默认输出静态 HTML；确有交互需求时才选择 island 与客户端指令并安装对应集成。",
         "本包没有创建内容集合加载器、CMS 或 Markdown 渲染链；扩展时另行验证内容来源与路由。"],
        ["页面引用的布局文件存在", "动态文本默认按模板规则转义", "静态页面无无效占位文章链接", "构建产物中检查标题、语义结构与部署路径"],
        """
        # Astro 接入配方

        在官方 `npm create astro@latest` 创建的工程内合入 src/pages/index.astro 与 src/layouts/SiteLayout.astro。
        本包没有执行安装命令；保留生成的 astro.config、tsconfig、依赖和锁文件。
        此例是静态内容页面，可使用生成工程的 build 脚本。若改为按需渲染，先安装并配置目标适配器。
        TypeScript 内容检查应使用项目配置的 astro check（需要相应依赖）；构建成功不替代内容来源审核。
        """,
        ["https://docs.astro.build/en/basics/astro-components/", "https://docs.astro.build/en/basics/astro-pages/",
         "https://docs.astro.build/en/install-and-setup/", "https://github.com/withastro/astro"],
        extra={"src/layouts/SiteLayout.astro": _text("""
            ---
            interface Props { title: string; }
            const { title } = Astro.props;
            ---
            <!doctype html>
            <html lang="zh-CN">
              <head><meta charset="UTF-8" /><meta name="viewport" content="width=device-width, initial-scale=1" /><title>{title}</title></head>
              <body><main><slot /></main></body>
            </html>
            <style>main { max-width: 64rem; margin: 0 auto; padding: 1.5rem; font-family: system-ui, sans-serif; }</style>
        """)})

    add(
        "wechat-miniprogram", "微信原生小程序页面", "wechat",
        ["微信小程序", "微信原生", "wechat", "weixin", "小程序", "wxml", "wxss", "miniprogram"],
        "包含 app 配置和 JS/WXML/WXSS/JSON 页面四件套的微信原生小程序本地草稿示例。",
        "pages/draft/index.js", """
        Page({
          data: { title: '', ready: false, message: '尚未生成本地草稿' },
          onTitleInput(event) {
            const title = String(event.detail.value || '').slice(0, 80);
            this.setData({ title, ready: title.trim().length > 0, message: '内容已更改，尚未生成草稿' });
          },
          previewDraft() {
            const value = this.data.title.trim();
            this.setData({ message: value ? `DEMO 本地草稿：${value}` : '请输入非空白标题' });
          }
        });
        """,
        ["微信原生使用 Page、setData、WXML 与 WXSS；它不是 HTML/DOM 页面，不能直接复制浏览器组件。",
         "事件取 event.detail.value；路由在 app.json 声明且页面文件同名。",
         "本包没有 wx.request、登录、支付、云开发或持久化；需要这些能力时单独核对平台权限与后端契约。",
         "基础库、渲染器与开发者工具版本在实际工程中锁定并验证；示例不配置不存在的真实 AppID。"],
        ["app.json 中每个页面都能找到四件套", "输入事件与 bindinput、bindtap 方法名一致", "空白与长度边界在页面逻辑中有处理", "微信开发者工具预览与真机结果分别记录"],
        """
        # 微信原生小程序接入配方

        将 app.js、app.json、app.wxss 与 pages/ 放入微信开发者工具的新空白小程序项目根目录。
        本包不提供 project.config.json：使用开发者工具生成的配置与用户实际 AppID/测试能力，不填造假账号。
        已有 app.json 时把 pages/draft/index 合入 pages，而非覆盖原路由。页面仅操作内存，不需要网络域名或后台服务。
        首次显示尚未生成；输入空格不能生成；正常标题显示本地草稿；改动后旧提示失效。页面重建会重置状态。
        本次只对 JavaScript 做本地语法与受控行为测试，没有启动微信开发者工具、扫码、真机或发布。
        微信官方文档入口本次直连受限；结构另按官方 miniprogram-demo 当前仓库核对，不能声称基础库兼容性已验证。
        """,
        ["https://github.com/wechat-miniprogram/miniprogram-demo",
         "https://github.com/wechat-miniprogram/miniprogram-demo/blob/master/miniprogram/app.json",
         "https://developers.weixin.qq.com/miniprogram/dev/framework/structure.html"],
        extra={
            "app.js": "App({});\n",
            "app.json": _json({"pages": ["pages/draft/index"], "window": {"navigationBarTitleText": "DEMO 本地草稿"}}),
            "app.wxss": "page { background: #f7f8fc; color: #182033; }\n",
            "pages/draft/index.json": _json({"navigationBarTitleText": "DEMO 草稿", "usingComponents": {}}),
            "pages/draft/index.wxml": _text("""
                <view class="draft">
                  <text class="heading">DEMO 本地草稿</text>
                  <label for="draft-title">草稿标题</label>
                  <input id="draft-title" value="{{title}}" maxlength="80" placeholder="输入草稿标题"
                    bindinput="onTitleInput" />
                  <button disabled="{{!ready}}" bindtap="previewDraft">生成本地草稿</button>
                  <text class="message">{{message}}</text>
                  <text class="hint">仅当前页面内存保存，离开后不保留。</text>
                </view>
            """),
            "pages/draft/index.wxss": _text("""
                .draft { padding: 32rpx; }
                .heading, .message, .hint { display: block; margin-bottom: 24rpx; }
                .heading { font-size: 40rpx; font-weight: 600; }
                input { margin: 20rpx 0; padding: 16rpx; border: 1px solid #62708a; background: #fff; }
                .message { margin-top: 24rpx; }
                .hint { color: #536179; font-size: 26rpx; }
            """),
        })

    add(
        "uniapp-vue", "uni-app Vue 3 跨端页面", "uniapp",
        ["uni-app", "uniapp", "uni app", "uniapp vue", "跨端 vue", "多端 vue"],
        "采用 Vue 3 + TypeScript 的 uni-app CLI 页面，默认接入微信小程序目标，可按官方平台能力评估 H5 等目标。",
        "src/pages/draft/index.vue", """
        <script setup lang="ts">
        import { computed, ref } from 'vue';

        const title = ref('');
        const ready = computed(() => title.value.trim().length > 0);
        const message = ref('尚未生成本地草稿');
        function preview() {
          const value = title.value.trim();
          message.value = value ? `DEMO 本地草稿：${value}` : '请输入非空白标题';
        }
        </script>

        <template>
          <view class="draft">
            <text class="heading">DEMO uni-app 草稿</text>
            <label for="draft-title">草稿标题</label>
            <input id="draft-title" v-model="title" :maxlength="80" placeholder="输入草稿标题"
              @input="message = '内容已更改，尚未生成草稿'" />
            <button :disabled="!ready" @click="preview">生成本地草稿</button>
            <text class="message">{{ message }}</text>
            <text>仅当前页面内存保存。</text>
          </view>
        </template>

        <style scoped>
        .draft { padding: 32rpx; }
        .heading, .message { display: block; margin: 24rpx 0; }
        input { margin: 24rpx 0; padding: 16rpx; border: 1px solid #62708a; }
        </style>
        """,
        ["使用 uni-app Vue 3/Vite/TypeScript 官方预设，不能套用普通 Web Vite 的依赖集合。",
         "CLI 项目使用 src/；HBuilderX 可视化工程通常没有 src/ 前缀，迁移时先确认项目类型。",
         "页面用 view/text/input 与 uni-app API；各端能力和样式并非完全相同。",
         "uni-app 与 uni-app x 是不同技术路径，本包不声明适配 UTS 或 uni-app x。"],
        ["pages.json 的路由能解析到页面文件", "Vue 与 @dcloudio 编译器来自匹配的官方预设版本", "微信与 H5 的产物分别构建验收", "未设置真实 AppID 或配置外部服务"],
        """
        # uni-app Vue 3 接入配方

        官方 CLI TypeScript 预设：`npx degit dcloudio/uni-preset-vue#vite-ts demo-uni`。
        该命令未执行；实际使用时记录该预设的提交和依赖锁文件，避免不同 @dcloudio 包版本混搭。
        合入本包 src/pages/draft/index.vue；把 src/pages.json 中页面条目合入已有 pages 数组。
        src/main.ts 与 src/App.vue 仅供空白 CLI 工程参考，保留已有启动插件与全局样式。
        src/manifest.example.json 是需要合并到官方生成的 src/manifest.json 的字段示例，不是完整配置；appid 留空，不代表可发布。
        微信目标通常执行生成工程的 `npm run dev:mp-weixin` / `npm run build:mp-weixin`，H5 按其 h5 脚本。
        微信输出需在微信开发者工具与真机验证；其他小程序按各端脚本、AppID 与能力另验，不能因一次微信编译通过就声称全端可用。
        本包没有依赖、锁文件、完整 manifest 或 HBuilderX/微信工具，不能独立启动。
        """,
        ["https://uniapp.dcloud.net.cn/quickstart-cli.html", "https://github.com/dcloudio/uni-app",
         "https://github.com/dcloudio/uni-preset-vue/tree/vite-ts"],
        extra={
            "src/main.ts": _text("""
                import { createSSRApp } from 'vue';
                import App from './App.vue';
                export function createApp() {
                  const app = createSSRApp(App);
                  return { app };
                }
            """),
            "src/App.vue": "<script setup lang=\"ts\">\n// 页面由 pages.json 注册；这里保留应用级初始化位置。\n</script>\n<style>page { background: #f7f8fc; color: #182033; }</style>\n",
            "src/pages.json": _json({"pages": [{"path": "pages/draft/index", "style": {"navigationBarTitleText": "DEMO 草稿"}}]}),
            "src/manifest.example.json": _json({"name": "DEMO 草稿", "appid": "", "mp-weixin": {"appid": ""}}),
        })

    add(
        "taro-react", "Taro React 小程序页面", "taro",
        ["taro", "taro react", "跨端 react", "react 小程序", "react 微信小程序"],
        "采用 Taro 4 React + TypeScript 与跨端组件的页面配方，首选验证目标为微信小程序。",
        "src/pages/draft/index.tsx", """
        import { useState } from 'react';
        import { View, Text, Label, Input, Button } from '@tarojs/components';
        import './index.css';

        export default function DraftPage() {
          const [title, setTitle] = useState('');
          const [message, setMessage] = useState('尚未生成本地草稿');
          function preview() {
            const value = title.trim();
            setMessage(value ? `DEMO 本地草稿：${value}` : '请输入非空白标题');
          }
          return (
            <View className="draft">
              <Text className="heading">DEMO Taro 草稿</Text>
              <Label for="draft-title">草稿标题</Label>
              <Input id="draft-title" value={title} maxlength={80} placeholder="输入草稿标题"
                onInput={(event) => { setTitle(event.detail.value); setMessage('内容已更改，尚未生成草稿'); }} />
              <Button disabled={!title.trim()} onClick={preview}>生成本地草稿</Button>
              <Text className="message">{message}</Text>
              <Text>仅当前页面内存保存。</Text>
            </View>
          );
        }
        """,
        ["Taro React 使用 @tarojs/components 与 event.detail.value，不能当成 React DOM 事件模型。",
         "本包按 Taro 4 React/TypeScript 脚手架；CLI、运行时和插件版本须相互匹配。",
         "编译目标 weapp 为微信；H5、支付宝和抖音等目标需分别核对插件、API 与产物。",
         "应用配置使用 defineAppConfig，页面配置使用 definePageConfig；这些宏由 Taro 构建处理。"],
        ["app.config.ts 注册的页面存在", "page config 与页面同目录同名", "事件值来自 detail 而非 target", "记录 weapp 构建与微信运行结果，其他端单列"],
        """
        # Taro React 接入配方

        用官方 Taro CLI 创建项目，选择 React、TypeScript 和受支持的构建器；参考官方入门页。
        例如通过当前受支持的 @tarojs/cli 执行 taro init，再使用生成工程的 package.json 和锁文件；本包没有执行安装。
        合入 src/pages/draft/，把 app.config.ts 的 pages 项合并到原配置。src/app.tsx 仅供空白工程参考。
        本包没有 config/index.ts、各环境配置、Babel/构建器配置或依赖版本，必须由所选 CLI 生成并保留。
        微信目标执行生成工程的 build:weapp/dev:weapp；若生成脚本不同，以该工程脚本为准。
        构建输出目录由 config/index.ts 的 outputRoot 决定，导入微信开发者工具时使用该输出目录。
        本包原始 TSX 不能直接交给微信工具；未进行 Taro 编译、微信预览、扫码或发布。
        """,
        ["https://docs.taro.zone/docs/react-page", "https://docs.taro.zone/docs/app-config",
         "https://docs.taro.zone/docs/page-config", "https://github.com/NervJS/taro"],
        extra={
            "src/app.tsx": _text("""
                import type { PropsWithChildren } from 'react';
                export default function App({ children }: PropsWithChildren) {
                  return children;
                }
            """),
            "src/app.config.ts": _text("""
                export default defineAppConfig({
                  pages: ['pages/draft/index'],
                  window: { navigationBarTitleText: 'DEMO 草稿' }
                });
            """),
            "src/pages/draft/index.config.ts": "export default definePageConfig({ navigationBarTitleText: 'DEMO 草稿' });\n",
            "src/pages/draft/index.css": ".draft { padding: 32px; }\n.heading, .message { display: block; margin: 24px 0; }\n",
        })

    add(
        "expo-react-native", "React Native 与 Expo 页面", "expo",
        ["react native", "react-native", "reactnative", "expo", "expo app", "跨端原生", "rn app"],
        "适配 Expo blank TypeScript 工程的 React Native 本地草稿页面，并说明 Expo Router 工程的接入差异。",
        "App.tsx", """
        import { useState } from 'react';
        import { View, Text, TextInput, Pressable, StyleSheet, ScrollView } from 'react-native';

        export default function App() {
          const [title, setTitle] = useState('');
          const [message, setMessage] = useState('尚未生成本地草稿');
          const ready = title.trim().length > 0;
          function preview() {
            const value = title.trim();
            setMessage(value ? `DEMO 本地草稿：${value}` : '请输入非空白标题');
          }
          return (
            <ScrollView contentContainerStyle={styles.screen} keyboardShouldPersistTaps="handled">
              <View>
                <Text accessibilityRole="header" style={styles.heading}>DEMO Expo 草稿</Text>
                <Text>草稿标题</Text>
                <TextInput accessibilityLabel="草稿标题" value={title} maxLength={80} style={styles.input}
                  onChangeText={(value) => { setTitle(value); setMessage('内容已更改，尚未生成草稿'); }} />
                <Pressable accessibilityRole="button" accessibilityState={{ disabled: !ready }}
                  disabled={!ready} onPress={preview} style={[styles.button, !ready && styles.disabled]}>
                  <Text style={styles.buttonText}>生成本地草稿</Text>
                </Pressable>
                <Text accessibilityLiveRegion="polite" style={styles.message}>{message}</Text>
                <Text>仅当前页面内存保存。</Text>
              </View>
            </ScrollView>
          );
        }

        const styles = StyleSheet.create({
          screen: { flexGrow: 1, padding: 24, paddingTop: 56, backgroundColor: '#f7f8fc' },
          heading: { fontSize: 24, fontWeight: '600', marginBottom: 24 },
          input: { borderWidth: 1, borderColor: '#62708a', padding: 12, marginVertical: 16 },
          button: { backgroundColor: '#214fcc', padding: 16, borderRadius: 8 },
          disabled: { opacity: 0.5 },
          buttonText: { color: '#ffffff', textAlign: 'center' },
          message: { marginVertical: 16 }
        });
        """,
        ["React Native 使用 View/Text/TextInput 与 StyleSheet，不直接使用 HTML、CSS 文件或浏览器 DOM。",
         "Expo SDK 和 React Native 版本由官方脚手架配套，安装原生依赖时按 Expo 兼容机制处理。",
         "App.tsx 适用于 blank-typescript 入口；带 Expo Router 的默认工程需将该组件接入真实路由文件。",
         "固定 padding 只是示例布局；正式页面应接入现有 safe-area 方案，并验证键盘、字体缩放、屏幕阅读器和 iOS/Android 差异。"],
        ["入口与所选 Expo 模板一致", "空白输入和禁用态一致", "可访问标签与键盘遮挡在设备验证", "Web/Android/iOS 分别记录，不把 Web 预览视为真机通过"],
        """
        # Expo / React Native 接入配方

        本 App.tsx 针对官方 blank TypeScript 模板：`npx create-expo-app@latest demo-expo --template blank-typescript`。
        命令未执行；使用生成的 package.json、SDK 配套版本、app.json 和锁文件，保留生成的入口注册代码。
        当前默认 Expo 工程可能使用 Expo Router；这时应将 App 组件移到独立模块，由真实 src/app/ 或 app/ 路由导入，不能假设根 App.tsx 会被加载。
        在生成工程执行类型检查与 `npx expo start` 后，按目标环境检查页面；原生模块可能要求 development build。
        Web 预览不证明 iOS/Android 原生能力，模拟器不证明真机，Expo Go 不证明商店打包。此包未执行这些环境。
        应用显示只在内存生成草稿；不触发 EAS 云构建、更新推送、账号登录或商店发布。
        """,
        ["https://docs.expo.dev/get-started/create-a-project/", "https://docs.expo.dev/more/create-expo/",
         "https://docs.expo.dev/tutorial/create-your-first-app/", "https://github.com/expo/expo"],
        extra={"PLATFORMS.json": _json({"framework": "Expo / React Native", "entry_variant": "blank-typescript", "entry": "App.tsx", "targets_to_validate": ["android", "ios", "web"], "sdk_build_status": "not-run", "device_test_status": "not-run", "backend": None})})

    return packs
