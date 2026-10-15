/** Current host configuration, separate from retrieved knowledge and past replies. */
import {createHash} from 'node:crypto';

export function runtimeCapabilities(options={}) {
  const policy=options.toolPolicy, files=policy?.services?.files;
  if (!policy?.tools_enabled || files?.implemented!==true || files.configured!==true
      || !['server','local'].includes(files.runtime_location)) return null;
  return {runtime_location:files.runtime_location, knowledge_scope:'current_agent',
    attachment_scope:'current_chat',
    path_import:files.local_import==='explicit-current-user-path-read-only',
    arbitrary_filesystem:files.runtime_location==='server' && policy.services?.server_files?.configured===true,
    account:policy.services?.server_files?.configured===true?policy.services.server_files.account:null,
    database_query:false, host_terminal:files.runtime_location==='server' && policy.services?.server_files?.configured===true};
}

export function runtimeCapabilityContext(options={}) {
  const facts=runtimeCapabilities(options);
  if (!facts) return '';
  return '\n当前宿主提供的运行与读取范围（配置事实，不代表已读取某个文件）：'
    +(facts.runtime_location==='server'?'当前后端运行在服务器；当前 Agent 知识库和聊天附件由服务器后端读取。'
      :'当前后端配置为本机运行；当前 Agent 可读取自己的知识库和本聊天附件。')
    +(facts.path_import?'其他文件可以由用户在“工具与连接”中用后端所在机器的路径明确导入，再通过聊天附件读取。':'')
    +(facts.arbitrary_filesystem?'服务器文件工具 server_files 已启用，可读取运行账号 '+facts.account+' 能访问的整个服务器文件系统；所有文件更改（包括删除和覆盖）及终端命令必须先提交具体申请，等待用户点击确认。没有管理员权限，不自动提权。未知路径时先 discover 获取实际目录，按类型查找用 find 的 kind 参数；只读检索无需再确认。目标足够开始时先查，不先索要路径或文件名；查后仍有歧义才让用户选候选。需要返回文件时用 attach 获得当前聊天附件链接，不是对外发送。先实际读工具再回答文件内容，pending_confirmation 不代表已执行；可用 history 查看确认后的真实回执。后台学习不继承文件操作权限。需要解析 PDF、Office 或提供媒体文件时，用 server_files 的 attach 操作取得当前聊天附件 ID 与下载 URL，再使用已接入的文档或媒体工具；不编造下载地址。除用户明确要求，不主动读取凭据或私钥，不把服务器私有内容发到公开搜索。':'没有任意宿主文件浏览、数据库直查或宿主终端工具。隔离代码沙箱不等于服务器终端。')
    +(Array.isArray(options.toolPolicy?.files)?'宿主登记的本会话可见附件数量：'+options.toolPolicy.files.length+'。附件不存在或不在本会话范围时不能读取；公开网页不能证明其归属。':'')
    +'询问读取能力时，先说明已接入的知识和附件，再说明其他文件的导入方式；不要笼统说无法读取服务器内容。'
    +'旧助手答复、Wiki 中其他产品的能力和网页资料不能覆盖本轮运行信息。';
}

export function runtimeCapabilityTurn(options={}) {
  if (options.analysis || options.researchContext || options.toolPolicy?.has_attachments) return null;
  const question=String(options.currentQuestion || '').replace(/\s+/g,'');
  // Only a capability question. Paths, quoted instructions and read requests
  // continue through the normal Agent; this route never pretends to read files.
  if (!/^(?:请问[，,]?)?(?:(?:你(?:们)?|主Agent|主智能体|智能体)(?:现在|目前|当前)?|(?:现在|目前|当前)你)?(?:能不能|可不可以|是否(?:能|可以)|可以|能)(?:直接)?(?:读取|访问|查看|读到|看到|看见|读|看)(?:我(?:的)?|这台|当前)?(?:服务器|服务端)(?:上|里|中)?(?:的)?(?:东西|内容|文件|数据|资料|知识库|聊天记录|上下文|学习结果)?(?:吗|么|呢)?[？?。]*$/iu.test(question)
      || !/(?:你|智能体|Agent|能不能|可不可以|是否|吗|么|呢|[？?])/iu.test(question)) return null;
  const facts=runtimeCapabilities(options);
  if (!facts) return null;
  const answer=facts.arbitrary_filesystem
    ?`可以。当前后端运行在服务器上，我可以通过服务器文件工具列目录、查找和读取 ${facts.account} 账号有权访问的文件，也能申请创建、编辑、复制、移动、删除文件和执行命令。\n\n所有文件更改及终端命令都会先在聊天界面展示具体操作，由你确认后执行；不会自动提权。直接说要找什么或要做什么即可；不知道路径时我会先自动查找，查到多个无法区分的候选再让你选。`
    :(facts.runtime_location==='server'
    ?'可以读取服务器上已接入当前 Agent 知识库的内容，以及当前聊天保存的附件。现在这个页面连接的就是服务器后端。'
    :'当前后端配置为本机运行，可以读取当前 Agent 的知识库和本聊天附件；这份配置不能证明已经连接了你所说的另一台服务器。')
    +'\n\n'+(facts.path_import?(facts.runtime_location==='server'
      ?'服务器上的其他文件，可以在“工具与连接”中用服务器路径明确导入，之后我就能通过聊天附件读取。'
      :'其他文件可以先下载或上传到当前系统，也可以在“工具与连接”中用后端所在机器的路径明确导入。'):'')
    +'聊天工具的读取范围不包含整个服务器文件系统、数据库直查或终端命令。';
  const digest=createHash('sha256').update(answer).digest('hex');
  return {answer,model:null,engine:'Host runtime capability catalog',response_origin:'host_runtime_capabilities',
    wiki_reads:[],template_reads:[],skill_reads:[],
    workflow:{status:'completed',runtime_capabilities:facts,receipts:[],observations:[],model_usage:[]},
    answer_check:{status:'not_needed',basis:'current_host_capability_catalog',calls:0,repair_count:0,
      original_answer_sha256:digest,final_answer_sha256:digest},
    timing:{model_ms:0,first_text_ms:null,chunks:0,input_chars:0}};
}

export function runtimeCapabilityInputs(options={}) {
  const text=runtimeCapabilityContext(options);
  // Evidence is valid only if these same host facts reached the answer model.
  if (!text || !(options.answerMessages || []).some(m=>m.role==='system'&&typeof m.content==='string'&&m.content.includes(text))) return [];
  return [{path:'host-runtime:current_turn',origin:'host_tool',text,claims:[],truncated:false,
    provided_sha256:createHash('sha256').update(text).digest('hex')}];
}
