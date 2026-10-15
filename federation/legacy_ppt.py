"""Read binary PowerPoint text records only; never execute macros or embedded objects."""
import struct
import olefile

def extract_slides(path):
    with olefile.OleFileIO(path) as document:
        if not document.exists('PowerPoint Document'):raise ValueError('旧版PPT已加密或格式无法读取')
        raw=document.openstream('PowerPoint Document').read(20_000_001)
    if len(raw)>20_000_000:raise ValueError('旧版PPT记录容量过大')
    output=[];seen=set();count=0
    def records(data,depth=0,collect=None):
        nonlocal count
        if depth>32:raise ValueError('旧版PPT记录嵌套过深')
        offset=0
        while offset+8<=len(data):
            options,kind,length=struct.unpack_from('<HHI',data,offset);offset+=8;count+=1
            if length>len(data)-offset or count>200000:raise ValueError('旧版PPT记录无效')
            payload=data[offset:offset+length];offset+=length
            if kind in {1006,1008,4080} and options&15==15:
                # Slide and note containers, plus persisted text lists. Master
                # placeholders are not user slide content.
                if kind==4080 and options>>4==2:continue
                text=[];records(payload,depth+1,text)
                value='\n'.join(text)
                if value.strip() and value not in seen:
                    output.append({'label':('幻灯片文本' if kind!=1008 else '演讲备注')+f' {len(output)+1}','text':value});seen.add(value)
            elif options&15==15:records(payload,depth+1,collect)
            elif collect is not None and kind in {4000,4008}:
                collect.append(payload.decode('utf-16-le' if kind==4000 else 'cp1252',errors='replace').replace('\r','\n'))
    records(raw)
    if not output:raise ValueError('旧版PPT没有可读取的文本记录；请使用PPTX或PDF')
    return output
