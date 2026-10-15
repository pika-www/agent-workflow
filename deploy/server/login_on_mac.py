"""Interactive Mac login, then copy only the selected platform's credentials."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
HOST = 'winfield@192.168.1.12'
DEST = '/home/winfield/services/weiming/project/.runtime/platform-mcp/private'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('provider', choices=('douyin', 'tieba'))
    args = parser.parse_args()
    if sys.platform != 'darwin':
        raise SystemExit('请在 Mac 上运行此登录入口。')
    config = json.loads((ROOT / '.runtime/server-connection.json').read_text())
    if config.get('host') != HOST:
        raise SystemExit('服务器配置与此迁移记录不匹配。')
    runtime = ROOT / '.runtime/platform-mcp'
    env = 'douyin-reader' if args.provider == 'douyin' else 'mediacrawler'
    subprocess.run([str(runtime / 'envs' / env / 'bin/python'), str(ROOT / 'federation/platform-mcp/login.py'), args.provider], check=True)
    status = json.loads((runtime / 'private' / (args.provider + '-login-status.json')).read_text())
    if status.get('state') != 'saved':
        raise SystemExit('登录未完成，服务器凭据未更改。')
    names = ['douyin-cookies.txt'] if args.provider == 'douyin' else ['tieba-cookies.json', 'tieba-login.json']
    for name in names:
        source = runtime / 'private' / name
        if source.is_symlink() or source.stat().st_mode & 0o077:
            raise SystemExit('登录文件权限不正确。')
        subprocess.run(['scp', '-q', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', str(source), HOST + ':' + DEST + '/' + name + '.incoming'], check=True)
    program = '''import pathlib,shutil,time
root=pathlib.Path(%r)
for name in %r:
 path=root/name; incoming=root/(name+'.incoming')
 if path.exists():shutil.copy2(path,root/(name+'.before-'+str(time.time_ns())))
 incoming.chmod(0o600);incoming.replace(path)
''' % (DEST, names)
    subprocess.run(['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', HOST, 'python3 -'], input=program.encode(), check=True)
    print('登录凭据已通过 SSH 保存到服务器，请回到原页面继续；平台仍可能要求重新验证。')


if __name__ == '__main__':
    main()
