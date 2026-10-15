"""Recreate project-local runtimes from pinned upstream commits and lockfiles."""
import argparse
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

code=Path(__file__).resolve().parent
root=code.parents[1]
runtime=root/'.runtime/platform-mcp'

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--build-openapi',action='store_true',help='Build the Rust provider using an installed cargo')
    options=parser.parse_args()
    if sys.version_info<(3,12):raise SystemExit('Use Python 3.12 or newer; the main app environment is unchanged.')
    for source in json.loads((code/'sources.lock.json').read_text()):
        target=runtime/'sources'/source['id']
        if target.exists():continue  # Preserve local changes and prior versions.
        repo=source['repository'].removeprefix('https://github.com/')
        request=urllib.request.Request('https://codeload.github.com/'+repo+'/zip/'+source['commit'],headers={'User-Agent':'Weiming-MCP-Setup'})
        raw=urllib.request.urlopen(request,timeout=60).read(60000000)
        target.mkdir(parents=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            for item in archive.infolist():
                parts=Path(item.filename).parts[1:]
                if not parts or item.is_dir():continue
                if '..' in parts or item.external_attr>>16 & 0o170000 == 0o120000:raise ValueError('Unsafe archive entry')
                dest=target.joinpath(*parts);dest.parent.mkdir(parents=True,exist_ok=True);dest.write_bytes(archive.read(item))
    for name in ('bilibili','douyin-reader','mediacrawler-mcp','mediacrawler'):
        env=runtime/'envs'/name
        if not (env/'bin/python').exists():subprocess.run([sys.executable,'-m','venv',str(env)],check=True)
        subprocess.run([str(env/'bin/python'),'-m','pip','install','-r',str(code/(name+'.lock.txt'))],check=True)
        if name=='mediacrawler-mcp':subprocess.run([str(env/'bin/python'),'-m','pip','install','--no-deps',str(runtime/'sources'/name)],check=True)
        subprocess.run([str(env/'bin/python'),'-m','pip','check'],check=True)
    if options.build_openapi:
        cargo=shutil.which('cargo') or str(runtime/'rust/cargo/bin/cargo')
        env=os.environ.copy()
        if str(runtime) in cargo:env.update(CARGO_HOME=str(runtime/'rust/cargo'),RUSTUP_HOME=str(runtime/'rust/toolchains'))
        subprocess.run([cargo,'build','--release','--locked','--manifest-path',str(runtime/'sources/douyin-openapi/Cargo.toml')],check=True,env=env)
        (runtime/'bin').mkdir(exist_ok=True)
        shutil.copy2(runtime/'sources/douyin-openapi/target/release/douyin',runtime/'bin/douyin')
    print('Installed locally. Run probe.py to record MCP discovery; login remains a user action.')

if __name__=='__main__':main()
