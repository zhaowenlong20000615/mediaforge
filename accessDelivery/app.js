'use strict';
const $=s=>document.querySelector(s);
const make=(tag,text,cls)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(cls)e.className=cls;return e;};
let config;
function message(text,failed=false){const n=$('#notice');n.textContent=text;n.hidden=false;n.className=failed?'notice failure':'notice';}
function commandBlock(title,value){const b=make('div',undefined,'commandBlock');b.append(make('h3',title));const pre=make('pre',value);const copy=make('button','复制');copy.type='button';copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(value);message('已复制。请先替换目录和凭证文件路径。');}catch{message('复制失败，请选中下方内容手动复制。',true);}});b.append(pre,copy);return b;}
function renderCommands(){const os=$('#platform').value;const area=$('#commands');area.replaceChildren();for(const c of config.commands)area.append(commandBlock(c.title,c[os]||c.any||''));const mcp=config.mcp[os]||config.mcp.any;$('#mcpConfig').replaceChildren(commandBlock('MCP 配置模板',JSON.stringify(mcp,null,2)));}
async function download(file,button){
 button.disabled=true;const original=button.textContent;button.textContent='正在校验下载…';
 try{
  const url=new URL(file.url,location.href);if(url.origin!==location.origin)throw new Error('下载地址不属于当前项目，已停止。');
  const headers={};const token=$('#accessToken').value.trim();if(token)headers.Authorization='Bearer '+token;
  if(config.authStorageKey&&!token){const current=localStorage.getItem(config.authStorageKey);if(current)headers.Authorization='Bearer '+current;}
  const response=await fetch(url,{headers,credentials:'same-origin',redirect:'error',cache:'no-store'});
  if(response.status===401||response.status===403){$('#authArea').hidden=false;$('#accessToken').focus();throw new Error('请先在本项目登录，或填写该项目已有的访问令牌，再点击下载。工作台凭证不能代替项目授权。');}
  if(!response.ok)throw new Error('下载未完成（HTTP '+response.status+'），请稍后重试。');
  const bytes=await response.arrayBuffer();if(bytes.byteLength!==file.size)throw new Error('文件大小不符，未保存文件，请重试。');
  const digest=[...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(x=>x.toString(16).padStart(2,'0')).join('');if(digest!==file.sha256)throw new Error('文件校验失败，未保存文件，请联系项目维护者。');
  const object=URL.createObjectURL(new Blob([bytes],{type:'application/zip'}));const a=make('a');a.href=object;a.download=file.name;document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(object),30000);$('#accessToken').value='';message('下载文件校验通过。解压后按安装步骤继续；下载完成不代表设备已配对。');
 }catch(e){message(e.message||'下载失败，请重试。',true);}finally{button.disabled=false;button.textContent=original;}
}
async function start(){
 try{
  const response=await fetch('./manifest.json',{cache:'no-store'});if(!response.ok)throw new Error('安装说明暂时不可用，请刷新重试。');config=await response.json();document.title=config.title+' · 下载与接入';
  $('#brand').textContent=config.title;$('#title').textContent=config.title+'，从这里接入。';$('#description').textContent=config.description;$('#projectHome').href=config.home;$('#authHome').href=config.home;$('#projectHome').textContent='打开'+config.title;$('#runtime').textContent=config.runtime;$('#scope').textContent=config.scope;$('#authHelp').textContent=config.authHelp;$('#version').textContent='客户端 '+config.clientVersion+' · 源码 '+config.clientCommit.slice(0,12);
  for(const [id,items] of [['steps',config.steps],['checks',config.checks],['limits',config.limits]]){const target=$('#'+id);for(const t of items)target.append(make('li',t));}
  for(const f of config.files){const article=make('article',undefined,'downloadRow');const body=make('div');body.append(make('h3',f.label),make('p',f.description),make('small',(f.size/1048576).toFixed(1)+' MB · SHA-256 校验 · '+f.verification));const btn=make('button','下载接入包','primary');btn.type='button';btn.addEventListener('click',()=>download(f,btn));const details=make('details');details.append(make('summary','文件名称与校验值'),make('code',f.name+'\n'+f.sha256));body.append(details);article.append(body,btn);$('#downloads').append(article);}
  $('#skillText').textContent=config.skillSummary;$('#skillPath').textContent=config.skillPath;renderCommands();$('#platform').addEventListener('change',renderCommands);$('#loading').hidden=true;$('#content').hidden=false;const section=location.hash.slice(1);if(['download','install','cli','mcp','skill'].includes(section))document.getElementById(section).scrollIntoView({block:'start'});
 }catch(e){message(e.message,true);$('#loading').textContent='无法加载项目交付信息。';}
}
start();
