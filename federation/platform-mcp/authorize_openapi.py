"""Interactive local OAuth entry. Secrets are never command-line arguments."""
import getpass
import os
from pathlib import Path
import subprocess
root=Path(__file__).resolve().parents[2]
runtime=root/'.runtime/platform-mcp'
print('需要你自己的抖音开放平台应用，且回调地址已允许 http://127.0.0.1:8787/callback。')
print('请在本机输入；不要把 Client Secret、Cookie 或授权码发到聊天。')
key=input('Client Key: ').strip()
secret=getpass.getpass('Client Secret（不回显）: ').strip()
if not key or not secret:raise SystemExit('未输入应用凭据，已取消。')
env={k:os.environ[k] for k in ('PATH','LANG','TZ') if k in os.environ}
env.update(DOUYIN_HOME=str(runtime/'private/douyin-openapi'),DOUYIN_CLIENT_KEY=key,DOUYIN_CLIENT_SECRET=secret)
subprocess.run([str(runtime/'bin/douyin'),'auth','login','--scope','user_info','--scope','item.comment','--listen','--callback-port','8787'],env=env,check=True)
