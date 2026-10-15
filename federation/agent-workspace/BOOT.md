# 服务启动检查

以下检查由 API 生命周期实际执行；不执行本文中的 shell 命令或模型生成的操作。

- check: files
- check: memory
- check: recovery

files：验证当前 Agent 的身份、行为、工作约定与引导文件可读取，路径没有符号链接或越界。
memory：核对个人资料及长期记忆的同步来源，生成本次启动的文件版本回执。
recovery：记录后台 active_run、pending_run 和待恢复任务状态；恢复仍交由原有调度器，不自行重放任务。

未知检查标记报告为不支持，不静默执行。检查失败保留回执，并阻止使用损坏的文件生成回复。
