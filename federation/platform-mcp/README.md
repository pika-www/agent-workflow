# 平台内容与评论 MCP

已接入未明的对话工具和「工具与连接 → 平台 MCP」。热点榜单服务继续独立运行；这里提供搜索、内容详情和评论读取。只有明确的平台信息查询才预选平台工具，普通聊天不会因此触发采集。

| 平台 | 固定版本来源 | 对话中开放的功能 | 2026-10-10 验证结果 |
| --- | --- | --- | --- |
| B站 | [L-Chris/bilibili-mcp](https://github.com/L-Chris/bilibili-mcp) | 视频搜索、详情、字幕、评论 | MCP 握手通过；未登录实际读到搜索结果、视频详情、3 条热门评论及部分子回复。字幕未实测 |
| 抖音 | [pazwusimple-netizen/douyin-mcp](https://github.com/pazwusimple-netizen/douyin-mcp) | 搜索、视频详情、评论、子评论、用户信息、用户作品 | MCP 握手通过；检查确认缺少有效登录，内容读取待登录验证 |
| 百度贴吧 | [xwh-01/dsh-mediacrawler](https://github.com/xwh-01/dsh-mediacrawler) + [NanmiCoder/MediaCrawler](https://github.com/NanmiCoder/MediaCrawler) | 搜索、帖子详情及评论 | MCP 握手、依赖和独立 Chrome 深度检查通过；真实帖子读取待登录验证 |
| 抖音开放接口 | [LIghtJUNction/douyin](https://github.com/LIghtJUNction/douyin) | 授权状态、用户信息、授权范围内的评论和回复 | 本机 Rust 编译、MCP 握手通过；授权状态确认为未授权，需开发者应用 |

完整提交号记录在 `sources.lock.json`。来源代码保留在项目 `.runtime/platform-mcp/sources/`，未修改上游源码。Python 依赖分别安装在 `envs/`；Rust 编译器、工具链和二进制均在同一个项目运行目录，不修改 shell PATH。主应用仍使用原来的 `.venv`。

## 登录

在页面点击「工具与连接」，找到「平台 MCP」：

- **B站**：点击「登录 B站」，在本页用哔哩哔哩 App 扫二维码并确认。部分公开信息不登录也能读取。
- **抖音、百度贴吧**：点击对应登录按钮，在新打开的独立 Chrome 窗口里点击平台的登录入口并扫码。完成后保存到本项目，不使用个人 Chrome 的已有浏览器资料。
- **抖音开放接口**：需要自己的开发者应用及对应权限，普通扫码无法替代。把应用回调配置为 `http://127.0.0.1:8787/callback`，在项目根目录运行以下命令，按本机交互提示输入 Client Key / Secret 并完成 OAuth：

```sh
.venv/bin/python federation/platform-mcp/authorize_openapi.py
```

Secret 不回显，也不放入命令行参数。Cookie、Token 和浏览器登录资料仅保存在已被 Git 忽略的 `.runtime/platform-mcp/private/`；不要把它们发送到聊天。登录窗口超时或关闭可以重新点击登录。保存过凭据不代表仍然有效，具体结果以实际调用为准。

## 调用与返回范围

宿主的 `platform_tools` 列出各平台允许的工具和参数，`platform_read` 执行读取；离线或关闭工具时不可调用。对话中可以直接说「找一下 B站关于招聘软件的视频，并看看热门评论」或「看看这个抖音视频的评论」。模型不能传入 Cookie、Token、任意本地路径或打开上游写入工具。

本次开放搜索与读取，没有把发评论、私信、点赞等写入动作开放给对话。贴吧每次最多取 3 帖、每帖 20 条评论；其他工具限制单页大小，长结果有截断标记。返回的子回复只是接口提供的部分，不能据此宣称读完全部评论。缺少登录、超时或接口异常都有独立状态，不能当作「没有评论」。每次读取都有最长时间限制，并清理本次子进程。

MediaCrawler 采用非商业学习许可证；贴吧这一路仅作为个人学习研究接入。上游完整许可证随源码保留，不能把安装成功解释成可直接用于商业采集。抖音 OpenAPI 包装器的许可为 AGPL-3.0-or-later；它是开源客户端，底层调用官方接口，并非抖音官方发布的 MCP。

## 复现与检查

当前电脑已完成安装，无需重复执行。新环境要求 Python 3.12 和 Chrome；需要抖音开放接口时还要求 Cargo。固定依赖安装命令（在项目根目录使用 Python 3.12 执行）：

```sh
python3.12 federation/platform-mcp/setup.py --build-openapi
.runtime/platform-mcp/envs/bilibili/bin/python federation/platform-mcp/probe.py
```

安装脚本保留已有来源目录，不覆盖用户修改；它不会自动更新到最新分支，也不会进行账号登录。`--build-openapi` 使用已有 Cargo 或本项目已安装的 Rust；新机器缺少 Rust 时需先准备编译器。依赖锁文件分别对应四个 Python 环境。

本次服务加载、依赖检查、真实只读调用和界面截图保存在 `outputs/platform-mcp-install-20261010/`。MCP 启动检查不等于真实账号读取成功，登录后的抖音和贴吧仍需继续做一次真实查询确认。
