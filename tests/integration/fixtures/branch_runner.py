"""Real runner process; only the paid Claude executable is replaced with a local fixture."""
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / "runner"))
import server
import uvicorn

server._SESSION_UIDS = False
server._SANDBOX_PER_SESSION = False
server._INTERNAL_KEY = ""
server.WORKSPACE_ROOT = os.environ["HARNESS_WORKSPACE"]
server._WS_MARKER_DIR = os.environ["HR_WS_MARKER_DIR"]
server.SPOOL_DIR = os.environ["HARNESS_SPOOL_DIR"]

SCRIPT = r'''
import json,re,sys,uuid
from pathlib import Path
prompt=sys.argv[1]
command=re.findall(r'COMMAND:(one|two|three|branch)',prompt)[-1]
p=Path('user.txt')
state={'command':command,'before':p.read_text() if p.exists() else None,
       'future':Path('future.txt').exists(), 'secret':Path('.harness/home/source-secret').exists(),
       'prompt':prompt}
if command != 'branch':
 p.write_text(command)
 secret=Path('.harness/home/source-secret');secret.parent.mkdir(parents=True,exist_ok=True);secret.write_text('synthetic-only')
 if command in ('two','three'):Path('future.txt').write_text(command)
text=json.dumps(state)
print(json.dumps({'type':'assistant','message':{'content':[{'type':'text','text':text}]}}),flush=True)
print(json.dumps({'type':'result','subtype':'success','is_error':False,'result':text,
 'session_id':str(uuid.uuid4()),'usage':{'input_tokens':1,'output_tokens':1}}),flush=True)
'''


def build(provider, auth, model, prompt, max_turns, cwd, env, **kwargs):
    return [sys.executable, "-c", SCRIPT, prompt]


server._build_claude = build
uvicorn.run(server.app, host="127.0.0.1", port=int(sys.argv[1]), log_level="warning")
