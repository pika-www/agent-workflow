"""Private ASR worker; arguments come exclusively from the validated host tool."""
import json
from pathlib import Path
import sys
from .audio_video import transcribe_sync
def main():
    path,begin,end,language,output=sys.argv[1:]
    result=transcribe_sync(Path(path),float(begin),float(end),language)
    dest=Path(output);dest.write_text(json.dumps(result,ensure_ascii=False));dest.chmod(0o600)
if __name__=='__main__':main()
