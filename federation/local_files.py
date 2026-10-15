"""Explicit human-selected local imports. The Agent only receives attachment IDs."""
from pathlib import Path
import os
import stat
from .tool_files import FORMATS,MAX_BYTES,MAX_MEDIA_BYTES,AUDIO_FORMATS,VIDEO_FORMATS,put_file

PRIVATE_NAMES={'.ssh','.aws','.azure','.gnupg','.codex','.env','private','keychains','cookies','login data','local state','credentials','secrets'}
def permitted(path):
    names=[p.lower() for p in path.parts]
    return not any(p in PRIVATE_NAMES or p.startswith('.env.') for p in names) and not any(p.endswith(('.pem','.key','.p12','.pfx','.keystore')) for p in names)

def explicit_path(value):
    if not isinstance(value,str) or len(value)>2000 or '\0' in value:raise ValueError('本地路径无效')
    path=Path(value).expanduser()
    if not path.is_absolute() or '..' in path.parts or not permitted(path):raise ValueError('请选择明确的资料路径；凭据目录不作为附件导入')
    for parent in [path,*path.parents]:
        if parent.is_symlink():raise ValueError('本地资料路径不能通过符号链接读取')
    if not path.exists():raise ValueError('本地资料不存在')
    if not str(path).startswith(str(Path.home())+os.sep):raise ValueError('本地导入范围为当前用户目录')
    return path

def import_local(store,room_id,value):
    selected=explicit_path(value)
    candidates=sorted(selected.iterdir()) if selected.is_dir() else [selected]
    chosen=[];skipped=[]
    for path in candidates:
        if path.is_symlink() or not path.is_file() or not permitted(path) or path.suffix.lower() not in FORMATS:
            skipped.append(path.name);continue
        if len(chosen)>=8:skipped.append(path.name);continue
        chosen.append(path)
    if not chosen:raise ValueError('所选位置没有可导入的资料文件')
    # Validate every file before mutating the room. O_NOFOLLOW closes the common
    # symlink replacement race at open; directories are never recursively read.
    bodies=[];total=0
    for path in chosen:
        limit=MAX_MEDIA_BYTES if path.suffix.lower() in AUDIO_FORMATS|VIDEO_FORMATS else MAX_BYTES
        fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>limit:raise ValueError('本地资料超出附件大小限制')
            raw=stream.read(limit+1)
        total+=len(raw)
        if len(raw)>limit or total>100_000_000:raise ValueError('单次本地导入总量超过100MB')
        bodies.append((path.name,raw))
    return {'files':[put_file(store,room_id,name,raw) for name,raw in bodies],
        'skipped_count':len(skipped),'note':'只读复制到本聊天；目录只读取当前层、最多8份支持格式的文件。源文件不会修改。'}
