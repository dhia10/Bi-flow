"""Small orchestration state record: updated before and after each run."""
from pathlib import Path
from datetime import datetime,timezone
import json

def write_state(path,status,**details):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    previous={}
    if path.exists():
        try:previous=json.loads(path.read_text(encoding='utf-8'))
        except (ValueError,OSError):pass
    previous.update({'agent':'intelligent_etl_agent','status':status,
                     'updated_at_utc':datetime.now(timezone.utc).isoformat(),**details})
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(previous,indent=2,default=str),encoding='utf-8')
    tmp.replace(path)
    return str(path)
