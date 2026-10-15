"""Open the existing local UI origin through a managed SSH connection."""
import json
import os
from pathlib import Path
import subprocess
import time
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / '.runtime/server-connection.json'
LABEL = 'com.winfield.weiming-server'


def main(check=False, no_open=False):
    config = json.loads(CONFIG.read_text(encoding='utf-8'))
    expected = config['instance']
    port = config.get('local_port', 18732)
    if not isinstance(expected, str) or not expected.startswith('/') or type(port) is not int or not 1024 <= port <= 65535:
        raise RuntimeError('服务器入口配置无效。')
    url = f'http://127.0.0.1:{port}'
    http = build_opener(ProxyHandler({}))

    def ready():
        try:
            with http.open(url + '/api/federation', timeout=15) as response:
                value = json.load(response)
            if value.get('instance') != expected:
                raise RuntimeError('本机端口上的知识库与服务器配置不匹配；未停止现有服务。')
            return True
        except (OSError, ValueError):
            return False

    connected = ready()
    if not connected and not check:
        plist = Path.home() / 'Library/LaunchAgents' / (LABEL + '.plist')
        domain = f'gui/{os.getuid()}'
        if not plist.is_file():
            raise RuntimeError('尚未安装服务器 SSH 入口，请查看 deploy/server/README.md。')
        loaded = subprocess.run(['/bin/launchctl', 'print', domain + '/' + LABEL], capture_output=True).returncode == 0
        command = (['/bin/launchctl', 'kickstart', domain + '/' + LABEL] if loaded else
                   ['/bin/launchctl', 'bootstrap', domain, str(plist)])
        subprocess.run(command, check=True)
        for _ in range(15):
            connected = ready()
            if connected:
                break
            time.sleep(1)
    if not connected:
        raise RuntimeError('服务器暂时不可达，请检查局域网和 SSH；未启用另一份本机数据库。')
    print('未明服务器已连接：' + url, flush=True)
    print('模型、会话与知识数据保存在 ' + config['host'] + ':' + expected, flush=True)
    if not check and not no_open:
        subprocess.run(['/usr/bin/open', url], check=False)
    return 0
