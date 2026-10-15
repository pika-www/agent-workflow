"""Copy a large immutable model over parallel SSH streams, then verify SHA-256."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import shlex
import subprocess
import sys
import time

SOURCE = Path(__file__).resolve().parents[2] / 'openwiki-runtime/models/blobs/sha256-dec52a44569a2a25341c4e4d3fee25846eed4f6f0b936278e3a3c900bb99d37c'
HOST = 'winfield@192.168.1.12'
BASE = '/home/winfield/services/weiming'
DIGEST = SOURCE.name.removeprefix('sha256-')
RECEIVER = '''import sys,pathlib,hashlib,json,os
path=pathlib.Path(sys.argv[1]);size=int(sys.argv[2]);path.parent.mkdir(parents=True,exist_ok=True)
temp=path.with_suffix('.partial');h=hashlib.sha256();remaining=size
with temp.open('wb') as f:
 while remaining:
  b=sys.stdin.buffer.read(min(1048576,remaining))
  if not b: raise RuntimeError('short SSH stream')
  f.write(b);h.update(b);remaining-=len(b)
 f.flush();os.fsync(f.fileno())
temp.replace(path)
print(json.dumps({'bytes':size,'sha256':h.hexdigest()}))
'''


def main():
    size = SOURCE.stat().st_size
    count = 12
    chunk = (size + count - 1) // count
    started = time.monotonic()
    def send(index):
        start = index * chunk
        length = min(chunk, size - start)
        path = BASE + f'/downloads/qwen-transfer/chunk-{index:02d}'
        command = 'python3 -c ' + shlex.quote(RECEIVER) + ' ' + shlex.quote(path) + ' ' + str(length)
        process = subprocess.Popen(['ssh', '-T', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes',
                                    '-o', 'ServerAliveInterval=20', HOST, command],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        digest = hashlib.sha256()
        try:
            with SOURCE.open('rb') as source:
                source.seek(start)
                remaining = length
                while remaining:
                    block = source.read(min(1024 * 1024, remaining))
                    if not block:
                        raise RuntimeError('short source file')
                    process.stdin.write(block)
                    digest.update(block)
                    remaining -= len(block)
            process.stdin.close()
            output, error = process.stdout.read(), process.stderr.read()
            if process.wait() != 0:
                raise RuntimeError(error.decode()[-2000:])
            result = json.loads(output)
            assert result == {'bytes': length, 'sha256': digest.hexdigest()}
            return {'chunk': index, **result}
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait()
    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as executor:
        futures = [executor.submit(send, n) for n in range(count)]
        for future in concurrent.futures.as_completed(futures):
            print(json.dumps(future.result()), flush=True)
    finish = '''import pathlib,hashlib,os,json
b=pathlib.Path(%r);dst=b/'project/openwiki-runtime/models/blobs'/('sha256-'+%r);tmp=dst.with_suffix('.assembling');h=hashlib.sha256()
with tmp.open('wb') as out:
 for i in range(12):
  with (b/('downloads/qwen-transfer/chunk-%%02d'%%i)).open('rb') as f:
   while True:
    block=f.read(4194304)
    if not block:break
    out.write(block);h.update(block)
 out.flush();os.fsync(out.fileno())
assert h.hexdigest()==%r,h.hexdigest()
assert tmp.stat().st_size==%d
tmp.chmod(0o600);tmp.replace(dst)
print(json.dumps({'sha256':h.hexdigest(),'bytes':dst.stat().st_size,'verified':True}))
''' % (BASE, DIGEST, DIGEST, size)
    subprocess.run(['ssh', '-o', 'BatchMode=yes', HOST, 'python3 -c ' + shlex.quote(finish)], check=True)
    print(json.dumps({'elapsed_seconds': round(time.monotonic() - started, 2)}), flush=True)


if __name__ == '__main__':
    main()
