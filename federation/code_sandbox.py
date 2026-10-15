"""Run Python in an OS-enforced, network-free, disposable workspace."""
import asyncio
import json
import os
from pathlib import Path
import shutil
import signal
import sys
import uuid
from .tool_files import get_file, parse_ids, put_file, FORMATS

WORKER = '''import os,resource,sys,traceback
resource.setrlimit(resource.RLIMIT_CPU,(25,25))
resource.setrlimit(resource.RLIMIT_FSIZE,(12000000,12000000))
resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
resource.setrlimit(resource.RLIMIT_NPROC,(256,256))
import matplotlib
matplotlib.use('Agg')
try:
 code=sys.stdin.read(20001)
 if len(code)>20000: raise ValueError('代码超过20000字符')
 exec(compile(code,'<agent-code>','exec'),{'__name__':'__main__'})
except BaseException:
 traceback.print_exc(limit=4)
 sys.exit(1)
'''

def sandbox_status():
    from .linux_sandbox import available
    return (sys.platform=='darwin' and bool(shutil.which('sandbox-exec'))) or available()

def profile(directory, python):
    # Do not grant reads of the project, home directory, credentials or other rooms.
    roots={str(Path(sys.base_prefix).resolve()),str(Path(sys.prefix).resolve()),str(Path(python).resolve().parent.parent),
           '/System/Library','/usr/lib','/usr/share','/Library/Fonts','/private/var/db/timezone'}
    literal=lambda s:json.dumps(s,ensure_ascii=False)
    roots.add(str(directory.resolve()))
    exclusions=['(require-not (subpath '+literal(r)+'))' for r in roots]
    parents={str(p) for r in roots for p in Path(r).parents}
    exclusions+=['(require-not (literal '+literal(r)+'))' for r in parents]
    exclusions+=['(require-not (literal '+literal(r)+'))' for r in ['/dev/null','/dev/random','/dev/urandom']]
    return '\n'.join(['(version 1)','(allow default)','(deny network*)',
        '(deny file-read-data (require-all '+' '.join(exclusions)+'))',
        '(deny file-write* (require-all (require-not (subpath '+literal(str(directory.resolve()))+')) (require-not (literal "/dev/null"))))',
        '(deny process-exec (require-not (subpath '+literal(str(Path(sys.base_prefix).resolve()))+')))',
        '(deny mach-lookup)', '(deny process-info* (require-not (target self)))'])

async def run_code(store,room_id,code,file_ids='',timeout=30):
    if not sandbox_status(): raise ValueError('本机未提供受支持的操作系统沙箱；未在宿主裸跑代码')
    if not code.strip() or len(code)>20000 or '\0' in code: raise ValueError('代码为空或超过预算')
    directory=store._safe(store.base,'code-runs/'+uuid.uuid4().hex)
    directory.mkdir(parents=True,mode=0o700)
    for fid in parse_ids(file_ids):
        item,path=get_file(store,room_id,fid)
        target=directory/(fid+Path(item['name']).suffix.lower())
        shutil.copyfile(path,target);target.chmod(0o400)
    worker=directory/'worker.py';worker.write_text(WORKER);worker.chmod(0o600)
    policy=directory/'sandbox.sb';policy.write_text(profile(directory,sys.executable));policy.chmod(0o600)
    env={'PATH':'/usr/bin:/bin','HOME':str(directory),'TMPDIR':str(directory),'MPLCONFIGDIR':str(directory/'mpl-cache'),
         'LANG':'en_US.UTF-8','PYTHONIOENCODING':'utf-8','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'}
    from . import linux_sandbox
    container=None
    isolation='macOS Seatbelt'
    command=['/usr/bin/sandbox-exec','-f',str(policy),sys.executable,'-I','-B',str(worker)]
    if linux_sandbox.available():
        command,container=linux_sandbox.command(directory,sys.executable,['-I','-B',worker],env,python=True)
        isolation='Linux Docker (no network, read-only runtime)'
    process=await asyncio.create_subprocess_exec(*command,
        cwd=directory,env=env,start_new_session=True,stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.PIPE)
    async def bounded(stream):
        data=bytearray()
        while True:
            block=await stream.read(4096)
            if not block: return bytes(data)
            data.extend(block)
            if len(data)>24000: raise ValueError('代码输出超过24000字节')
    initial_size=sum(p.stat().st_size for p in directory.iterdir() if p.is_file())
    async def monitor():
        while process.returncode is None:
            size=0;count=0
            for path in directory.rglob('*'):
                count+=1
                if path.is_file() and not path.is_symlink():size+=path.stat().st_size
                if count>2000 or size>initial_size+32_000_000:raise ValueError('代码生成文件超过容量预算')
            await asyncio.sleep(.2)
    async def communicate():
        process.stdin.write(code.encode());await process.stdin.drain();process.stdin.close()
        watching=asyncio.create_task(monitor())
        reading=asyncio.ensure_future(asyncio.gather(bounded(process.stdout),bounded(process.stderr)))
        try:
            done,_=await asyncio.wait([watching,reading],return_when=asyncio.FIRST_COMPLETED)
            if watching in done:await watching
            stdout,stderr=await reading
            await process.wait();return stdout,stderr
        finally:
            watching.cancel();reading.cancel()
            await asyncio.gather(watching,reading,return_exceptions=True)
    try:
        stdout,stderr=await asyncio.wait_for(communicate(),timeout)
    except (asyncio.TimeoutError,asyncio.CancelledError,ValueError) as exc:
        if process.returncode is None:
            os.killpg(process.pid,signal.SIGKILL)
        await process.wait()
        if isinstance(exc,asyncio.CancelledError): raise
        return {'status':'failed','error':'代码执行超过时间或输出预算，已停止进程','artifacts':[],'isolation':isolation}
    finally:
        await asyncio.shield(linux_sandbox.remove(container))
    artifacts=[]
    for path in sorted(directory.iterdir()):
        if path.is_symlink() or not path.is_file() or path==worker or path==policy or path.name[:32] in parse_ids(file_ids): continue
        if path.suffix.lower() in FORMATS and 0<path.stat().st_size<=10_000_000 and len(artifacts)<8:
            artifacts.append(put_file(store,room_id,path.name,path.read_bytes(),generated=True))
    return {'status':'completed' if process.returncode==0 else 'failed','exit_code':process.returncode,
            'stdout':stdout.decode('utf-8',errors='replace')[:12000],'stderr':stderr.decode('utf-8',errors='replace')[:4000],
            'artifacts':artifacts,'isolation':isolation,'network':False,'note':'文件名为附件ID加扩展名；输出保存到当前工作目录。'}
