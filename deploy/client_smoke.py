"""CLI, standard MCP and cookie-auth checks against the deployed service."""
import asyncio
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from PIL import Image
import httpx
from mcp import ClientSession,StdioServerParameters
from mcp.client.stdio import stdio_client
from mediaforge.client import Client
from mediaforge.dependencies import verified_binary


async def main():
    url=sys.argv[1];tokenfile=sys.argv[2];report=Path(sys.argv[3]);root=Client(url,tokenfile)
    evidence={'server':url,'checks':{}}
    expected={'secure_cookie','cookie_me','logout_revoked','cli_real_resize','cli_download','cli_failed_exit',
              'mcp_initialize','mcp_tools','mcp_real_resize','mcp_preview','mcp_credential_rejected'}
    evidence['version']=root.request('GET','version')
    with tempfile.TemporaryDirectory(prefix='mf-live-client-') as d:
        folder=Path(d);account=root.request('POST','api/workspaces',json={'name':'client-smoke'})
        key=folder/'workspace.token';key.write_text(account['token']);key.chmod(0o600)
        client=Client(url,key);image=folder/'input.png';Image.new('RGB',(160,100),'navy').save(image)
        try:
            with httpx.Client(base_url=url,trust_env=False,timeout=15) as browser:
                login=browser.post(url+'/api/session',json={'token':account['token']})
                evidence['checks']['secure_cookie']=login.status_code==200 and 'secure' in login.headers['set-cookie'].lower() and 'httponly' in login.headers['set-cookie'].lower()
                evidence['checks']['cookie_me']=browser.get(url+'/api/me').status_code==200
                browser.delete(url+'/api/session')
                evidence['checks']['logout_revoked']=browser.get(url+'/api/me').status_code==401
            def cli(*args):
                return subprocess.run([sys.executable,'-m','mediaforge','--server',url,'--token-file',str(key),'--json',*args],text=True,capture_output=True,timeout=60)
            r=cli('tasks','create','image-process',str(image),'--param','width=40','--wait')
            task=json.loads(r.stdout);evidence['checks']['cli_real_resize']=r.returncode==0 and task['outputs'][0]['width']==40
            download=folder/'output.png';r=cli('files','download',task['outputs'][0]['id'],'--output',str(download));evidence['checks']['cli_download']=r.returncode==0 and Image.open(download).size==(40,25)
            ffmpeg=verified_binary('ffmpeg')
            if not ffmpeg:raise SystemExit('A working ffmpeg is required to generate synthetic smoke fixtures')
            movie=folder/'silent.mp4';subprocess.run([ffmpeg,'-v','error','-y','-f','lavfi','-i','color=c=red:s=64x64:d=1','-c:v','libx264',str(movie)],capture_output=True,check=True)
            r=cli('tasks','create','audio-extract',str(movie),'--wait');evidence['checks']['cli_failed_exit']=r.returncode==4 and json.loads(r.stdout)['status']=='failed'
            parameters=StdioServerParameters(command=sys.executable,args=['-m','mediaforge.mcp'],env={**os.environ,'MEDIAFORGE_URL':url,'MEDIAFORGE_TOKEN_FILE':str(key),'MEDIAFORGE_LOCAL_ROOTS':str(folder),'MEDIAFORGE_OUTPUT_ROOTS':str(folder/'outputs')})
            async with stdio_client(parameters) as (read,write):
                async with ClientSession(read,write) as session:
                    init=await session.initialize();tools=await session.list_tools()
                    evidence['checks']['mcp_initialize']=init.serverInfo.name=='MediaForge'
                    evidence['checks']['mcp_tools']=len(tools.tools)>=13
                    result=await session.call_tool('upload_file',{'path':str(image)})
                    uploaded=result.structuredContent or json.loads(result.content[0].text)
                    result=await session.call_tool('create_processing_task',{'operation':'image-process','file_ids':[uploaded['id']],'params':{'width':50},'idempotency_key':'client-smoke-resize'})
                    created=result.structuredContent or json.loads(result.content[0].text)
                    finished=await asyncio.to_thread(client.wait,created['id'],60)
                    evidence['checks']['mcp_real_resize']=finished['status']=='succeeded' and finished['outputs'][0]['width']==50
                    preview=await session.call_tool('preview_result',{'file_id':finished['outputs'][0]['id']})
                    evidence['checks']['mcp_preview']=not preview.isError
                    denied=await session.call_tool('upload_file',{'path':str(key)})
                    evidence['checks']['mcp_credential_rejected']=denied.isError
        finally:
            evidence['cleanup']=client.request('POST','api/cleanup',json={'days':0,'dry_run':False})
            evidence['passed']=set(evidence['checks'])==expected and all(evidence['checks'].values()) and not evidence['cleanup'].get('dry_run',True)
            report.write_text(json.dumps(evidence,ensure_ascii=False,indent=2)+'\n')
            print(json.dumps(evidence['checks'],ensure_ascii=False))
    if not evidence['passed']:raise SystemExit(1)

if __name__=='__main__':asyncio.run(main())
