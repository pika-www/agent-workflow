# 本项目的设计与表达约定

用户已指出：当前界面、以后生成的产品界面，以及回答和文档的排版都有过重的 AI 模板感。设计或撰写这些内容前，读取 [设计与表达约定.md](设计与表达约定.md)。

- 从具体用户任务和真实内容组织页面，先确定主要操作、内容顺序和阅读宽度，再处理视觉风格。
- 不默认套用大标语、装饰英文、等尺寸卡片、满屏边框、发光图标和同权重按钮。确有任务或品牌理由时才能采用。
- 短回答使用自然段直接说明结果；只有真实比较或对应关系才用表格，只有独立主题才用标题。不要每段粗体、编号和重述结论。
- 保留现有安全边界、历史、数据和进行中的任务。回复正文与源码预览分开处理，Markdown 必须继续净化。
- 界面改动要查看真实浏览器中的结果；涉及排版时检查桌面和窄屏。验证能说明行为正确，视觉是否合意仍以用户反馈为准。
- `federation-controls.js` 和 `federation-controls.css` 是构建文件；修改源文件后执行 `node federation/build-observatory.mjs`，不要只编辑构建文件。

Skill 的固定交付目录仍为 `/Users/winfield/Documents/projects/skill/<skill-name>/`。文件交付不等于安装授权。

## 代码与运行数据的位置

- Mac 保留本项目源码、测试脚本、开发依赖与 Git 历史；模型、知识正文、聊天上下文、记忆、学习任务和学习结果由 `winfield@192.168.1.12` 保存和处理。
- 运行项目在服务器 `/home/winfield/services/weiming/project`。实时知识数据在其 `openwiki-federation` 目录，也可从 `/home/winfield/knowledge-base/实时数据` 访问同一份数据；独立 Obsidian 库在 `/home/winfield/knowledge-base/未明知识库`。
- 后续正式知识和学习操作直接通过服务器 API 或 SSH 执行。本机入口使用 `.runtime/server-connection.json` 连接服务器；不要删除这个标记来重新启动一套本地正式数据。
- 本机开发测试使用显式的临时数据目录。部署按改动同步源码，保留服务器实时数据、私有配置、进行中的任务及历史，不用本机目录覆盖或删除服务器数据。
- `/home/winfield/knowledge-base/原Mac数据` 和 `项目知识原件` 是归档，不会自动回写到实时知识库。具体入口和恢复说明见 `deploy/server/README.md`。
