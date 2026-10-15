#!/usr/bin/env python3
"""Create a new native Obsidian shell without changing old knowledge or existing notes."""
from pathlib import Path
import json
import shutil
import time

ROOT = Path(__file__).resolve().parents[1]
VAULT = Path('/Users/winfield/Documents/Obsidian/未明知识库')
files = {}

def note(path, content):
    files[path] = content.strip() + '\n'

def config(path, data):
    files['.obsidian/' + path] = json.dumps(data, ensure_ascii=False, indent=2) + '\n'

note('00 开始/未明.md', '''---
cssclasses:
  - weiming-home
tags:
  - 导航
---

![[99 附件/未明天体仪.jpg]]

<p class="weiming-kicker">A PERSONAL OBSERVATORY · 私人知识观测站</p>

# 循着微光，抵达未知。

有些答案，需要寻找。\n有些发现，只需要出发。

[[00 开始/星图.canvas|展开探索地图 ↗]]　 · 　[[00 开始/探索路线|循着一条线索 →]]　 · 　[[03 收件箱/收件箱|留下一个念头 ＋]]

---

## 每个领域，都是一扇门。

> [!horizon-build] 01 / 构筑之境
> **[[01 知识领域/互联网与软件/互联网与软件|互联网与软件 ↗]]**
> 在逻辑与想象之间，建造新的可能。

> [!horizon-story] 02 / 叙事之境
> **[[01 知识领域/影视与内容/影视与内容|影视与内容 ↗]]**
> 让尚未发生的世界，先在故事里诞生。

> [!horizon-flow] 03 / 流转之境
> **[[01 知识领域/电商与零售/电商与零售|电商与零售 ↗]]**
> 循着需求与价值，发现万物的联系。

> [!horizon-order] 04 / 秩序之境
> **[[01 知识领域/企业经营/企业经营|企业经营 ↗]]**
> 看见个体之外，那些无形的协作。

## 今夜，先接住一束信号。

> [!signal] 一个表单的隐秘秩序
> 从 [[01 知识领域/互联网与软件/前端/HTML 约束验证|HTML 约束验证]] 出发，看看一个看似简单的输入框，如何藏着规则、反馈与边界。
> 
> 这组内容保留原有的**修正草稿、尚未发布**状态。阅读与收藏不会把它变成已审核知识。

[[04 日常手记/手记索引|我的手记]]　 / 　[[00 开始/使用指南|如何使用这座观测站]]　 / 　[[90 迁移记录/迁移说明|知识从哪里来]]

<div class="weiming-colophon">未明 / OBSIDIAN　　不必一次读懂世界。今天，发现一点就好。</div>
''')
note('00 开始/探索路线.md', '''---
tags: [导航, 探索]
cssclasses: [weiming-note]
---
# 顺着线索，再走远一点。

这些路线只连接已有页面。尚未有知识的领域仍是入口，等待你留下内容。

## 01 · 一个表单的隐秘秩序

[[01 知识领域/互联网与软件/前端/HTML 约束验证|HTML 约束验证]] → [[01 知识领域/互联网与软件/前端/违反状态类型|违反状态类型]] → [[01 知识领域/互联网与软件/前端/Constraint Validation API 方法|Constraint Validation API 方法]] → [[01 知识领域/互联网与软件/前端/CSS 验证相关伪类|CSS 验证相关伪类]]

读完后留一个问题：**规则的作用，是阻止错误，还是帮助人理解边界？**

## 02 · 让一个想法变得可触摸

[[01 知识领域/互联网与软件/UI-UX 设计师/UI-UX 设计师|UI/UX 设计师]] → [[01 知识领域/互联网与软件/前端/前端|前端]] → [[01 知识领域/互联网与软件/测试/测试|测试]]

这是一条领域巡游路线。试着为每一步写下一件你希望弄懂的事。

## 03 · 一个故事的远行

[[01 知识领域/影视与内容/编剧策划/编剧策划|编剧策划]] → [[01 知识领域/影视与内容/视觉设计/视觉设计|视觉设计]] → [[01 知识领域/影视与内容/后期制作/后期制作|后期制作]] → [[01 知识领域/影视与内容/内容运营/内容运营|内容运营]]

一个故事在哪一刻，真正变成另一个人的记忆？

> [!abstract]- 当你愿意偏离路线
> 有些门没有上锁，只是需要多看一眼。
> 
> [[00 开始/第零号观测室|进入第零号观测室 ↗]]

[[00 开始/未明|← 回到观测台]]
''')
note('00 开始/第零号观测室.md', '''---
tags: [探索, 问题]
cssclasses: [weiming-note]
---
# 第零号观测室

**欢迎走到地图之外。**

这里暂时没有答案，只有几对值得并置的坐标。

## 规则 × 叙事

当 [[01 知识领域/互联网与软件/前端/HTML 约束验证|规则]] 与 [[01 知识领域/影视与内容/编剧策划/编剧策划|故事]] 相遇：一条限制，能否反而创造更多可能？

## 体验 × 流转

从 [[01 知识领域/互联网与软件/UI-UX 设计师/UI-UX 设计师|交互设计]] 走向 [[01 知识领域/电商与零售/客户服务/客户服务|客户服务]]：人真正需要的，是否总是他开口要求的东西？

## 个体 × 秩序

把 [[01 知识领域/企业经营/组织人力/组织人力|组织人力]] 与 [[01 知识领域/影视与内容/内容运营/内容运营|内容运营]] 放在一起：一群人如何形成共同的语言？

这些连线是**思考邀请**，不是已验证的知识结论。任选一个问题，在新笔记里写下你的理解，再加上它的来源。

[[03 收件箱/收件箱|留下一张问题卡 →]]　 · 　[[00 开始/未明|返回观测台]]
''')
note('03 收件箱/收件箱.md', '''---
tags: [导航]
---
# 留下一个念头

还没有归属的线索，先放在这里。

- 用 **⌘N** 新建一篇笔记，默认保存在本文件夹。
- 用命令面板的「插入模板」，选择 [[98 模板/问题卡|问题卡]] 或 [[98 模板/知识笔记|知识笔记]]。
- 写下自己的判断，再用 `[[` 连接相关笔记。确认归属后，拖到左侧对应领域文件夹。

来源链接、尚未确认的推测、待核验的问题，都可以先记下来；整理时再区分它们。

[[00 开始/未明|← 回到观测台]]
''')
note('04 日常手记/手记索引.md', '''---
tags: [导航]
---
# 你走过的路，会发光。

在左侧功能栏打开**今天的日记**，或按 **⌘P** 搜索「日记」。新日记会放在这里，并使用 [[98 模板/每日手记|每日手记模板]]。

写下今天看见的一件事、想到的一个问题、想再回访的一篇笔记。

[[00 开始/未明|← 回到观测台]]
''')
note('98 模板/知识笔记.md', '''---
created: "{{date:YYYY-MM-DD}}"
status: 待整理
tags: [知识]
sources: []
---
# {{title}}

## 我想解决的问题

## 我的理解

## 依据与来源

- 来源：
- 核验日期：

## 仍不确定的部分

## 相关笔记
''')
note('98 模板/问题卡.md', '''---
created: "{{date:YYYY-MM-DD}}"
status: 待探索
tags: [问题]
---
# {{title}}

## 什么让我好奇

## 我目前的猜想

## 可以从哪里寻找证据

## 与哪些笔记有关
''')
note('98 模板/来源笔记.md', '''---
created: "{{date:YYYY-MM-DD}}"
tags: [来源]
source_url: ""
author: ""
accessed: "{{date:YYYY-MM-DD}}"
---
# {{title}}

## 来源信息

## 原文要点

## 我的解释

## 支持哪些笔记
''')
note('98 模板/每日手记.md', '''---
date: "{{date:YYYY-MM-DD}}"
tags: [手记]
---
# {{date:YYYY-MM-DD}} · 今日微光

## 今天发现了什么

## 一个还没有答案的问题

## 值得再回访

[[00 开始/未明|回到观测台]]
''')
note('00 开始/使用指南.md', '''---
tags: [导航]
---
# 这是一座真正的 Obsidian 知识库

所有知识都是这个 Vault 内的本地 Markdown 文件。你可以直接编辑、链接、移动和备份它们。

## 从这里开始

| 想做什么 | 操作 |
| --- | --- |
| 回到首页 | 左侧书签 → 未明 · 观测台；或 ⌘O 输入「未明」 |
| 探索地图 | 打开 [[00 开始/星图.canvas|星图 Canvas]]，双击卡片阅读对应笔记 |
| 查看真实链接网络 | 左侧功能栏的关系图谱，或 ⌘P 搜索「关系图谱」 |
| 找一篇笔记 | ⌘O 输入标题；全文搜索使用左侧放大镜 |
| 建立双向链接 | 编辑时输入两个左方括号 `[[`，选择另一篇笔记 |
| 偶然发现 | ⌘P 搜索「漫游笔记」 |
| 开始写作 | ⌘N；新笔记进入 [[03 收件箱/收件箱|收件箱]] |
| 切换阅读与编辑 | ⌘E |
| 记录今天 | 左侧日记按钮，或 ⌘P 搜索「日记」 |
| 插入格式 | ⌘P 搜索「插入模板」 |

## 文件如何组织

- **00 开始**：首页、Canvas 地图、探索路线和使用指南。
- **01 知识领域**：四个领域及其专业分支，包含已有知识。
- **02 来源档案**：原始资料与来源线索。
- **03 收件箱**：暂时没有归属的笔记。
- **04 日常手记**：每日观察与回访线索。
- **90 迁移记录**：旧单库资料、导入说明与可核对的来源映射。
- **98 模板**：四种可复用笔记格式。
- **99 附件**：图片等本地附件。

## 知识的状态也要保留

有些导入内容带着 `corrected-draft` 与 `unpublished` 属性。这表示它仍是未发布草稿。换一个阅读工具，不会让它自动通过审核。

原来的 OpenWiki 网页和 Agent 服务仍在原项目中。**本 Vault 是一次独立导入，编辑不会自动同步回旧系统；旧系统新增的学习内容也不会自动写进本 Vault。** 如果继续使用旧 Agent 学习，应先核对来源与版本，再将确认的内容整理进来。

目前使用 Obsidian 自带功能与本地 CSS 外观，没有依赖社区插件。使用与打开文件不需要启动旧网页或本地模型。Vault 尚未配置云同步。

## 外观

本地外观片段位于 `.obsidian/snippets/weiming-observatory.css`。可在设置 → 外观 → CSS 代码片段中开关。首页使用本地生成的天体仪插图，知识正文仍可正常编辑。

官方说明：[Vault](https://obsidian.md/help/Getting+started/Create+a+vault) · [内部链接](https://obsidian.md/help/links) · [CSS 代码片段](https://obsidian.md/help/snippets)

[[00 开始/未明|← 回到观测台]]
''')

config('app.json', {
 'alwaysUpdateLinks':True, 'newLinkFormat':'absolute', 'useMarkdownLinks':False,
 'attachmentFolderPath':'99 附件', 'newFileLocation':'folder','newFileFolderPath':'03 收件箱',
 'defaultViewMode':'preview','showInlineTitle':False,'propertiesInDocument':'hidden',
 'readableLineLength':True, 'strictLineBreaks':False, 'showLineNumber':False
})
config('appearance.json', {'theme':'moonstone','accentColor':'#8b7854','baseFontSize':16,
 'enabledCssSnippets':['weiming-observatory'], 'cssTheme':'',
 'textFontFamily':'PingFang SC, -apple-system, sans-serif',
 'monospaceFontFamily':'SFMono-Regular, Menlo, monospace'})
config('core-plugins.json', ['file-explorer','global-search','switcher','graph','backlink','canvas','outgoing-link','tag-pane','properties','page-preview','daily-notes','templates','note-composer','command-palette','editor-status','bookmarks','outline','word-count','file-recovery','random-note'])
config('community-plugins.json', [])
config('daily-notes.json', {'folder':'04 日常手记','format':'YYYY-MM-DD','template':'98 模板/每日手记','autorun':False})
config('templates.json', {'folder':'98 模板','dateFormat':'YYYY-MM-DD','timeFormat':'HH:mm'})
config('bookmarks.json', {'items':[{'type':'file','ctime':int(time.time()*1000),'path':p,'title':t} for p,t in [
 ('00 开始/未明.md','未明 · 观测台'),('00 开始/星图.canvas','探索星图'),('00 开始/探索路线.md','顺着线索'),('03 收件箱/收件箱.md','灵感收件箱'),('04 日常手记/手记索引.md','日常手记')]]})
config('graph.json', {'search':'-path:"98 模板" -path:"90 迁移记录" -path:"99 附件"', 'showTags':False,'showAttachments':False,'hideUnresolved':True,'showOrphans':True,
 'colorGroups':[{'query':'path:"01 知识领域/'+name+'"','color':{'a':1,'rgb':int(color,16)}} for name,color in [('互联网与软件','78927f'),('影视与内容','b19770'),('电商与零售','769ba3'),('企业经营','b88e75')]],
 'nodeSizeMultiplier':1.1,'lineSizeMultiplier':1,'centerStrength':0.35,'repelStrength':10,'linkStrength':1,'linkDistance':160})

# Native JSON Canvas. File nodes link to notes; lines describe the directory structure.
nodes=[{'id':'title','type':'text','x':-390,'y':-370,'width':780,'height':180,'text':'# 未明 · 知识星图\n\n循着微光，抵达未知。\n\n双击卡片进入笔记。连线表示领域归属与阅读路线，不表示已验证的因果关系。','color':'#8b7854'},
 {'id':'home','type':'file','file':'00 开始/未明.md','x':-210,'y':-80,'width':420,'height':240}]
edges=[]
realms=[('software','互联网与软件','构筑之境',-850,-120,'#78927f'),('content','影视与内容','叙事之境',470,-120,'#b19770'),('commerce','电商与零售','流转之境',-850,380,'#769ba3'),('business','企业经营','秩序之境',470,380,'#b88e75')]
for ident,name,label,x,y,color in realms:
 nodes.append({'id':ident,'type':'file','file':f'01 知识领域/{name}/{name}.md','x':x,'y':y,'width':380,'height':340,'color':color})
 edges.append({'id':'home-'+ident,'fromNode':'home','fromSide':'left' if x<0 else 'right','toNode':ident,'toSide':'right' if x<0 else 'left','toEnd':'none','color':color,'label':label})
nodes.extend([
 {'id':'thread','type':'file','file':'00 开始/探索路线.md','x':-210,'y':380,'width':420,'height':340,'color':'#8b7854'},
 {'id':'validation','type':'file','file':'01 知识领域/互联网与软件/前端/HTML 约束验证.md','x':-850,'y':850,'width':420,'height':290},
 {'id':'question','type':'text','x':-210,'y':850,'width':420,'height':220,'text':'## 把问题留下来\n\n你看到的两篇笔记之间，有没有一条尚未命名的联系？\n\n[[03 收件箱/收件箱|留下一个念头 →]]'},
 {'id':'note','type':'file','file':'04 日常手记/手记索引.md','x':470,'y':850,'width':380,'height':230}
])
edges.extend([{'id':'home-thread','fromNode':'home','fromSide':'bottom','toNode':'thread','toSide':'top','label':'从一条路线出发'}, {'id':'software-validation','fromNode':'software','fromSide':'bottom','toNode':'validation','toSide':'top','label':'已有知识 · 前端草稿'}, {'id':'thread-question','fromNode':'thread','fromSide':'bottom','toNode':'question','toSide':'top','label':'留下问题'}])
files['00 开始/星图.canvas']=json.dumps({'nodes':nodes,'edges':edges},ensure_ascii=False,indent=2)+'\n'

css=ROOT/'scripts/obsidian-weiming.css'
files['.obsidian/snippets/weiming-observatory.css']=css.read_text()

# Refuse overwrites, including app-written configuration from an already open vault.
for relative in files:
 if (VAULT/relative).exists(): raise SystemExit('Refusing to overwrite: '+str(VAULT/relative))
asset=VAULT/'99 附件/未明天体仪.jpg'
if asset.exists(): raise SystemExit('Refusing to overwrite: '+str(asset))
for relative,content in files.items():
 p=VAULT/relative; p.parent.mkdir(parents=True,exist_ok=True); p.write_text(content)
asset.parent.mkdir(parents=True,exist_ok=True)
shutil.copy2(ROOT/'federation/web/assets/observatory-astrolabe-v2.jpg',asset)
print(json.dumps({'vault':str(VAULT),'authoredFiles':len(files),'localAttachment':str(asset)},ensure_ascii=False))
