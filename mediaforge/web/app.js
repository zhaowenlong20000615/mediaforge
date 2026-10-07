const $ = (s, root=document) => root.querySelector(s);
const root = $('#app');
const state = {tools:[],checks:[],files:[],uploads:new Map(),params:{},toolId:'image-process',owner:null,storage:{},templates:[],nav:'workbench',taskId:null,task:null,filter:'',search:'',offset:0,picked:new Set(),busy:false,connected:false,lastPoll:0,polling:false,renderKey:'',submitKey:null,sessionEpoch:0,viewVersion:0,queryVersion:0,uploadCounter:0,advanced:{}};
const labels = {accepted:'排队中',running:'处理中',succeeded:'已完成',partial:'部分完成',failed:'处理失败',cancelled:'已取消',recoverable:'可恢复'};
const cats = ['视频 / 音频','字幕 / 语音','PDF / Word','图片','批量'];
const bytes = n => n>=1024**3?(n/1024**3).toFixed(2)+' GB':n>=1024**2?(n/1024**2).toFixed(1)+' MB':n>=1024?(n/1024).toFixed(1)+' KB':n+' B';
const time = n => new Date(n*1000).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
const idKey = () => window.crypto?.randomUUID?.() || Array.from(window.crypto.getRandomValues(new Uint8Array(16)), x=>x.toString(16).padStart(2,'0')).join('');
function h(tag, attrs={}, ...kids) {
  const el=document.createElement(tag);
  for (const [key,val] of Object.entries(attrs)) {
    if (val===undefined || val===null || (val===false&&!key.startsWith('aria-'))) continue;
    if (key.startsWith('on')) el.addEventListener(key.slice(2).toLowerCase(),val);
    else if (key==='class') el.className=val;
    else if (key==='text') el.textContent=val;
    else if (key==='checked'||key==='disabled'||key==='hidden'||key==='selected') el[key]=Boolean(val);
    else if (key==='value') el.value=val;
    else el.setAttribute(key,key.startsWith('aria-')?String(val):val===true?'':String(val));
  }
  for (const kid of kids.flat(Infinity)) { if(kid!==null && kid!==undefined && kid!==false) el.append(kid instanceof Node?kid:document.createTextNode(String(kid))); }
  return el;
}
const button=(text,fn,cls='',attrs={})=>h('button',{type:'button',class:cls,onClick:fn,...attrs},text);
const tool=()=>state.tools.find(t=>t.id===state.toolId);
const nameOf=id=>state.tools.find(t=>t.id===id)?.name||id;
const badge=status=>h('span',{class:'tag '+({failed:'bad',partial:'warning',recoverable:'warning',running:'neutral',accepted:'neutral',cancelled:'neutral'}[status]||'')},labels[status]||status);
function toast(message) { const el=$('#notice');el.textContent=message;el.classList.add('visible');clearTimeout(toast.timer);toast.timer=setTimeout(()=>el.classList.remove('visible'),6500); }
function connection(ok) { state.connected=ok;const el=$('#connection');if(el){el.className='connection'+(ok?'':' offline');el.textContent=ok?'工作区已连接':'连接中断 · 正在重试';} }
function errorBlock(error) { return h('div',{class:'callout error',role:'alert'},h('strong',{},error.message||'操作失败'),error.action?h('p',{},error.action):null); }
async function api(path, options={}) {
  const epoch=state.sessionEpoch;const controller=new AbortController();const deadline=setTimeout(()=>controller.abort(),30000);
  let response;
  try { response=await fetch('./'+path,{credentials:'same-origin',...options,signal:controller.signal,headers:{...(options.body?{'Content-Type':'application/json'}:{}),...(options.headers||{})}}); }
  catch { if(epoch===state.sessionEpoch)connection(false);throw {message:'请求超时或无法连接工作区。',action:'任务可能仍在执行；保持本次参数重试会使用同一幂等键。'}; }
  finally {clearTimeout(deadline);}
  if(epoch!==state.sessionEpoch)throw {code:'stale_response'};
  let data;try{data=await response.json();}catch{connection(false);throw {message:'服务响应不完整。',action:'请稍后重试，已选文件会保留。'};}
  if(!response.ok){if(response.status===401&&state.owner){endSession(false);renderLogin('连接已过期，请重新输入令牌。');}throw data.error||{message:'请求未完成。'};}
  connection(true);return data;
}
const post=(path,data={})=>api(path,{method:'POST',body:JSON.stringify(data)});
async function action(fn) { try{await fn();}catch(e){if(e.code==='stale_response')return;toast([e.message,e.action].filter(Boolean).join(' '));} }
function persistFiles(){try{sessionStorage.setItem('mf_files',JSON.stringify({owner:state.owner,ids:state.files.map(f=>f.id)}));}catch{toast('浏览器未允许暂存文件列表；刷新页面后可从任务详情继续处理。');}}
function endSession(clear){
 state.sessionEpoch++;state.viewVersion++;const pending=[...state.uploads.values()];state.uploads.clear();
 for(const item of pending)item.xhr?.abort();
 state.owner=null;state.files=[];state.params={};state.advanced={};state.task=null;state.busy=false;state.picked.clear();state.submitKey=null;state.uploadCounter=0;
 if(clear){try{sessionStorage.removeItem('mf_files');}catch{}}
}

function navigate(nav,tid) { const hash=nav==='task'?'task/'+tid:nav;if(location.hash==='#'+hash)action(route);else location.hash=hash; }
function renderLogin(message='') {
 root.replaceChildren(h('main',{class:'login',id:'main'},
  h('section',{class:'login-intro'},brand(),h('h1',{},'让每一份素材，\n有清楚的去向。'),h('p',{},'音视频、字幕、文档与图片。\n统一处理，逐项确认，失败可以继续。'),h('small',{},'文件会存储在你连接的服务中，只有本工作区的授权用户可以访问。')),
  h('form',{class:'login-form',onSubmit:async e=>{e.preventDefault();const field=$('#access-token');const submit=$('#login-submit');submit.disabled=true;$('#login-error').textContent='';try{await post('api/session',{token:field.value.trim()});field.value='';await bootstrap();}catch(err){$('#login-error').textContent=[err.message,err.action].filter(Boolean).join(' ');submit.disabled=false;}}},
    h('h2',{},'连接你的工作区'),h('p',{},'输入工作区访问令牌。令牌由部署管理员提供，不会保存在浏览器本地存储中。'),
    h('label',{class:'field',for:'access-token'},'访问令牌',h('input',{id:'access-token',type:'password',autocomplete:'off',required:true,placeholder:'粘贴工作区令牌'})),
    h('div',{id:'login-error',class:'login-error',role:'alert'},message),h('button',{id:'login-submit',type:'submit',class:'primary'},'连接工作区 →'),
    h('p',{class:'muted'},'请确认地址属于你信任的本地或自托管服务。'))));
}
function brand(){return h('div',{class:'brand'},h('span',{class:'mark','aria-hidden':'true'},'MF'),h('div',{},h('strong',{},'MediaForge'),h('small',{},'媒体与文档工作台')));}
function shell(){
 const links=[['workbench','◫','工作台'],['tasks','≡','任务队列'],['templates','▤','参数模板'],['diagnostics','⌁','诊断'],['settings','⚙','设置']];
 root.replaceChildren(h('header',{class:'header'},brand(),h('div',{class:'header-right'},h('span',{id:'connection',class:'connection'},'工作区已连接'),button('退出',()=>action(async()=>{await api('api/session',{method:'DELETE'});endSession(true);renderLogin();}),'small'))),
  h('div',{class:'layout'},h('aside',{class:'sidebar'},h('nav',{'aria-label':'主导航'},links.map(([id,icon,name])=>h('a',{href:'#'+id,class:'nav-link'+((state.nav===id||state.nav==='task'&&id==='tasks')?' active':''),'aria-current':state.nav===id?'page':null},h('span',{class:'nav-icon','aria-hidden':'true'},icon),name))),h('div',{class:'sidebar-note'},'文件由当前服务处理。',h('br'),`保留 ${state.storage.retention_days||7} 天，可在设置中清理。`)),h('main',{id:'main',class:'main',tabindex:'-1'})));
}
function head(title,desc,extra=null,eyebrow='MEDIAFORGE / WORKSPACE') { return h('div',{class:'page-head'},h('div',{},h('div',{class:'eyebrow'},eyebrow),h('h1',{},title),h('p',{},desc)),extra); }
async function route(){
 if(!state.owner)return;
 const version=++state.viewVersion;
 const parts=location.hash.slice(1).split('/');state.nav=parts[0]||'workbench';state.taskId=parts[1];state.renderKey='';shell();
 const main=$('#main');
 try {
 if(state.nav==='workbench')renderWorkbench();
 else if(state.nav==='tasks') {main.append(head('任务队列','受理、执行、结果各有记录。筛选任务，查看详情，或将结果一起导出。'));renderTaskControls();await refreshTasks();}
 else if(state.nav==='task'&&state.taskId){main.append(h('div',{class:'loading'},'正在读取任务…'));await refreshDetail();}
 else if(state.nav==='diagnostics')await renderDiagnostics();
 else if(state.nav==='settings')await renderSettings();
 else if(state.nav==='templates')await renderTemplates();
 else navigate('workbench');
 }catch(error){if(version!==state.viewVersion||!state.owner||error.code==='stale_response')return;main.replaceChildren(head('页面暂时无法显示','已保存的文件和任务不会因此丢失。'),errorBlock(error),button('重新加载',()=>action(route),'primary'));}
}
function paramsFor(t=tool()) {
 if(!state.params[t.id])state.params[t.id]=Object.fromEntries(Object.entries(t.schema.properties).map(([k,p])=>[k,p.default??(p.type==='boolean'?false:'')]));
 return state.params[t.id];
}
function renderWorkbench(){
 const main=$('#main');main.replaceChildren(head('你的文件，现在开始处理。','选择工具、加入文件并设置参数。任务完成后，可以预览、下载或继续处理。',h('a',{class:'button-link',href:'#tasks'},'查看任务 →')),
 h('div',{class:'workspace'},h('aside',{class:'catalog','aria-label':'工具目录'},h('div',{class:'catalog-search'},h('label',{class:'visually-hidden',for:'tool-search'},'搜索工具'),h('input',{id:'tool-search',type:'search',placeholder:'搜索工具，例如 PDF',onInput:renderCatalog})),h('div',{id:'catalog-items'})),h('section',{id:'editor',class:'editor','aria-label':'处理工具'})));
 renderCatalog();renderEditor();
}
function renderCatalog(){
 const list=$('#catalog-items');if(!list)return;const q=($('#tool-search')?.value||'').toLowerCase();
 list.replaceChildren(...cats.map(cat=>{const tools=state.tools.filter(t=>t.category===cat&&(t.name+t.description).toLowerCase().includes(q));
 return tools.length?h('div',{class:'category'},h('h3',{},cat),tools.map(t=>button([h('span',{},t.name),!t.available?h('span',{class:'unavailable'},'需配置'):null],()=>{state.toolId=t.id;state.submitKey=null;renderCatalog();renderEditor();},'tool-button'+(state.toolId===t.id?' chosen':''),{'aria-pressed':state.toolId===t.id}))):null;}).filter(Boolean));
 if(!list.childNodes.length)list.append(h('p',{class:'muted'},'没有匹配工具。'));
}
function canRun(){
 const t=tool(),p=paramsFor();
 if(t.id==='office-convert'&&p.format!=='pdf'&&!state.files.some(f=>f.kind==='doc'))return state.checks.find(x=>x.id==='docx')?.available;
 return t.available;
}
function renderEditor(){
 const t=tool(),editor=$('#editor');if(!t||!editor)return;
 state.advanced[t.id] ||= {group:'',timeout:state.storage.timeout||1800,retries:0};
 const advanced=state.advanced[t.id];
 editor.replaceChildren(h('div',{class:'tool-head'},h('h2',{},t.name),h('p',{},t.description),t.note?h('p',{},t.note):null,h('span',{class:'tag'+(canRun()?'':' warning'),id:'tool-availability'},canRun()?'工具链可用':'工具链需要配置')));
 const form=h('form',{id:'task-form',onSubmit:submit});
 const fileInput=h('input',{id:'upload-input',type:'file',multiple:true,class:'visually-hidden',tabindex:'-1','aria-hidden':'true',onChange:e=>{enqueue([...e.target.files]);e.target.value='';}});
 const drop=h('div',{class:'drop',id:'drop',onDragover:e=>{e.preventDefault();drop.classList.add('over');},onDragleave:()=>drop.classList.remove('over'),onDrop:e=>{e.preventDefault();drop.classList.remove('over');enqueue([...e.dataTransfer.files]);}},
  fileInput,button('＋ 选择文件',()=>fileInput.click()),h('p',{},'也可以将文件拖到这里。文件会上传到当前工作区。'),h('small',{},`单文件上限 ${bytes(state.storage.max_file_bytes||0)} · ${t.combine?'按列表顺序组合处理':'每个文件独立处理'}`));
 form.append(h('section',{class:'section'},h('div',{class:'section-title'},h('h3',{},h('span',{class:'step'},'1'),'加入文件'),h('small',{},`${t.min_files}–${t.max_files} 个文件`)),drop,h('div',{class:'input-files',id:'input-files'})),
 h('section',{class:'section'},h('div',{class:'section-title'},h('h3',{},h('span',{class:'step'},'2'),'处理参数')),h('div',{class:'fields'},Object.entries(t.schema.properties).map(([key,spec])=>paramField(key,spec,t)))),
 h('details',{class:'advanced'},h('summary',{},'任务分组、超时与自动重试'),h('div',{class:'fields'},simpleField('任务分组','job-group','text',advanced.group,{maxlength:100,onInput:e=>{advanced.group=e.target.value;state.submitKey=null;}}),simpleField('最长处理时间（秒）','job-timeout','number',advanced.timeout,{min:1,max:7200,required:true,onInput:e=>{advanced.timeout=Number(e.target.value);state.submitKey=null;}}),simpleField('超时后自动重试次数','job-retries','number',advanced.retries,{min:0,max:3,required:true,onInput:e=>{advanced.retries=Number(e.target.value);state.submitKey=null;}}))),
 h('div',{id:'form-errors','aria-live':'polite'}),h('div',{class:'submit-bar'},button('保存为参数模板',saveTemplate,'small'),h('small',{},'完成后会核验文件结构；内容质量仍需你确认。'),h('button',{id:'create-task',type:'submit',class:'primary'},'创建任务 →')));
 editor.append(form);renderFiles();updateSubmit();
}
function simpleField(title,id,type,value,attrs={}){return h('label',{class:'field',for:id},title,h('input',{id,type,value,...attrs}));}
function paramField(key,spec,t){
 const vals=paramsFor(t),id='param-'+key;let input;
 const update=e=>{vals[key]=spec.type==='boolean'?e.target.checked:spec.type==='integer'||spec.type==='number'?(e.target.value===''?'':Number(e.target.value)):e.target.value;state.submitKey=null;updateSubmit();};
 if(spec.type==='boolean')return h('label',{class:'check-field field full'},h('input',{id,type:'checkbox',checked:vals[key],required:spec.const===true,onChange:update}),spec.title);
 if(spec.enum)input=h('select',{id,onChange:update},spec.enum.map(v=>h('option',{value:v,selected:vals[key]===v},v)));
 else input=h('input',{id,type:spec.format==='password'?'password':spec.type==='number'||spec.type==='integer'?'number':'text',value:vals[key],min:spec.minimum??(spec.exclusiveMinimum!==undefined?spec.exclusiveMinimum+.01:undefined),max:spec.maximum,step:spec.type==='number'?'any':spec.type==='integer'?1:undefined,minlength:spec.minLength,maxlength:spec.maxLength,required:t.schema.required.includes(key)||spec.type==='integer'||spec.type==='number',autocomplete:'off',onInput:update});
 return h('label',{class:'field'+(spec.type==='string'&&!spec.enum?' full':''),for:id},spec.title,input,spec.sensitive?h('small',{},'加密保存；不会出现在任务日志或模板中。'):null);
}
function updateSubmit(){
 const b=$('#create-task');if(!b)return;
 const allowed=canRun();b.disabled=state.busy||state.uploads.size>0||!state.files.length||!allowed;b.textContent=state.busy?'正在提交…':'创建任务 →';
 const el=$('#tool-availability');if(el){el.textContent=allowed?'工具链可用':'工具链需要配置';el.className='tag'+(allowed?'':' warning');}
 const errors=$('#form-errors');if(errors&&!allowed&&!errors.querySelector('[data-dependency]'))errors.replaceChildren(h('div',{class:'callout', 'data-dependency':'true'},'此工具的依赖尚未配置。',h('a',{href:'#diagnostics'},'查看诊断与安装说明 →')));
 else if(errors&&allowed&&errors.querySelector('[data-dependency]'))errors.replaceChildren();
}
function renderFiles(){
 const wrap=$('#input-files');if(!wrap)return;
 wrap.replaceChildren(...state.files.map((f,i)=>h('div',{class:'input-file'},h('span',{class:'file-icon','aria-hidden':'true'},f.kind.toUpperCase().slice(0,4)),h('div',{},h('div',{class:'file-name'},f.name),h('div',{class:'file-meta'},[bytes(f.size),f.width?`${f.width} × ${f.height}`:'',f.pages?`${f.pages} 页`:'',f.duration?`${f.duration.toFixed(1)} 秒`:'',f.streams?.length?`${f.streams.filter(s=>s.codec_type==='audio').length} 音轨 / ${f.streams.filter(s=>s.codec_type==='subtitle').length} 字幕轨`:'',f.encrypted?'有密码保护':'',f.frames>1?'动画：将处理首帧':'',!tool().accept.includes(f.kind)?'⚠ 类型不适合当前工具':''].filter(Boolean).join(' · '))),h('div',{class:'file-actions'},button('↑',()=>moveFile(i,-1),'',{'aria-label':'上移 '+f.name,disabled:i===0||state.uploads.size>0}),button('↓',()=>moveFile(i,1),'',{'aria-label':'下移 '+f.name,disabled:i===state.files.length-1||state.uploads.size>0}),button('移除',()=>{state.files.splice(i,1);state.submitKey=null;persistFiles();renderFiles();updateSubmit();},'small',{'aria-label':'移除 '+f.name})))),
 ...[...state.uploads.values()].map(u=>h('div',{class:'input-file'},h('span',{class:'file-icon'},'↑'),h('div',{},h('div',{class:'file-name'},u.name),h('div',{class:'file-meta'},!u.started?'等待上传…':u.progress<100?'正在上传 '+u.progress+'%':'上传完成，正在检查文件内容…'),h('progress',{value:u.progress,max:100,'aria-label':'上传 '+u.name})),button('取消上传',()=>{if(u.xhr)u.xhr.abort();else{state.uploads.delete(u.key);renderFiles();updateSubmit();}},'small'))));
}
function moveFile(i,delta){[state.files[i],state.files[i+delta]]=[state.files[i+delta],state.files[i]];state.files.forEach((f,j)=>f.clientOrder=j);state.uploadCounter=state.files.length;state.submitKey=null;persistFiles();renderFiles();}
function enqueue(files){
 if(!state.owner)return;
 // Stable ordinal follows user selection, never network completion order.
 for(const f of state.files)if(f.clientOrder===undefined)f.clientOrder=state.uploadCounter++;
 for(const file of files){
  if(state.files.length+state.uploads.size>=Math.min(tool().max_files,100)){toast('加入文件数量已达到此工具上限。');break;}
  if(file.size>state.storage.max_file_bytes||file.size===0){toast(file.name+' 为空或超过单文件限制。');continue;}
  const key=idKey();state.uploads.set(key,{key,file,name:file.name,progress:0,started:false,epoch:state.sessionEpoch,order:state.uploadCounter++});
 }
 renderFiles();updateSubmit();pumpUploads();
}
function pumpUploads(){
 if(!state.owner)return;
 let available=3-[...state.uploads.values()].filter(x=>x.started).length;
 for(const u of state.uploads.values()){
  if(u.started||available<=0)continue;available--;u.started=true;
  const xhr=new XMLHttpRequest();u.xhr=xhr;
  const current=()=>state.owner&&u.epoch===state.sessionEpoch&&state.uploads.get(u.key)===u;
  function finish(){state.uploads.delete(u.key);renderFiles();updateSubmit();pumpUploads();}
  xhr.open('POST','./api/files?name='+encodeURIComponent(u.file.name));xhr.responseType='json';xhr.timeout=600000;xhr.setRequestHeader('Content-Type','application/octet-stream');xhr.withCredentials=true;
  xhr.upload.onprogress=e=>{if(!current())return;u.progress=e.lengthComputable?Math.round(e.loaded/e.total*100):0;renderFiles();};
  xhr.onload=()=>{
   if(!current())return;
   if(xhr.status===401){endSession(false);renderLogin('连接已过期，请重新输入令牌。');return;}
   if(xhr.status>=200&&xhr.status<300&&xhr.response?.id){state.files.push({...xhr.response,clientOrder:u.order});state.files.sort((a,b)=>a.clientOrder-b.clientOrder);persistFiles();state.submitKey=null;connection(true);}
   else{const error=xhr.response?.error||{message:'文件上传失败。',action:'重新连接后重试。'};toast(u.name+'：'+error.message+' '+(error.action||''));}
   finish();
  };
  xhr.onerror=xhr.ontimeout=()=>{if(!current())return;connection(false);toast('上传中断：'+u.name+'。请重新选择该文件。');finish();};
  xhr.onabort=()=>{if(!current())return;toast('已停止上传 '+u.name);finish();};xhr.send(u.file);
 }
 renderFiles();updateSubmit();
}
async function submit(e){
 e.preventDefault();if(state.busy)return;const t=tool();const errors=$('#form-errors');errors.replaceChildren();
 if(state.files.length<t.min_files||state.files.length>t.max_files){errors.append(errorBlock({message:`请选择 ${t.min_files}–${t.max_files} 个文件。`}));return;}
 if(state.files.some(f=>!t.accept.includes(f.kind))){errors.append(errorBlock({message:'文件类型与当前工具不匹配。',action:'移除不匹配的文件，或选择对应工具。'}));return;}
 const epoch=state.sessionEpoch,view=state.viewVersion;const inputIds=state.files.map(f=>f.id);
 state.busy=true;state.submitKey ||= idKey();updateSubmit();
 try{
  const result=await post('api/tasks',{tool:t.id,file_ids:inputIds,params:{...paramsFor()},idempotency_key:state.submitKey,group:$('#job-group').value,timeout:Number($('#job-timeout').value),retries:Number($('#job-retries').value)});
  for(const [key,spec] of Object.entries(t.schema.properties))if(spec.sensitive)paramsFor(t)[key]='';
  if(epoch!==state.sessionEpoch)return;state.submitKey=null;state.files=state.files.filter(f=>!inputIds.includes(f.id));persistFiles();if(view===state.viewVersion)navigate('task',result.id);else toast('任务已创建，可在任务队列查看。');
 }catch(err){if(err.code==='stale_response')return;if(errors.isConnected)errors.replaceChildren(errorBlock(err));}
 finally{if(epoch===state.sessionEpoch){state.busy=false;updateSubmit();}}
}
async function saveTemplate(){
 const t=tool(),params={...paramsFor()};for(const[k,s]of Object.entries(t.schema.properties))if(s.sensitive)delete params[k];
 const name=window.prompt('模板名称',t.name+' · 常用参数');if(!name)return;
 await action(async()=>{await post('api/templates',{name,tool:t.id,params});toast('参数模板已保存。');});
}
function renderTaskControls(){
 $('#main').append(h('div',{class:'toolbar'},h('label',{class:'visually-hidden',for:'task-search'},'搜索任务'),h('input',{id:'task-search',type:'search',placeholder:'搜索工具、任务编号或分组',value:state.search,onInput:e=>{state.search=e.target.value;state.offset=0;clearTimeout(renderTaskControls.timer);renderTaskControls.timer=setTimeout(()=>action(refreshTasks),250);}}),h('label',{class:'visually-hidden',for:'status-filter'},'任务状态'),h('select',{id:'status-filter',onChange:e=>{state.filter=e.target.value;state.offset=0;state.picked.clear();action(refreshTasks);}},[['','全部状态'],...Object.entries(labels)].map(([k,v])=>h('option',{value:k,selected:state.filter===k},v))),button('导出所选结果',()=>exportTasks([...state.picked]),'',{id:'export-picked',disabled:!state.picked.size}),button('刷新',()=>action(refreshTasks),'small')),h('div',{id:'task-list'},h('p',{class:'loading'},'正在加载任务…')),h('div',{id:'task-pagination'}));
}
async function refreshTasks(){
 const version=state.viewVersion;const query=++state.queryVersion;const filters=new URLSearchParams({status:state.filter,search:state.search,limit:20,offset:state.offset}).toString();
 const data=await api('api/tasks?'+filters);
 if(state.nav!=='tasks'||version!==state.viewVersion||query!==state.queryVersion)return;
 const key=JSON.stringify(data);if(key===state.renderKey)return;state.renderKey=key;
 const list=$('#task-list');if(!list)return;
 if(!data.tasks.length)list.replaceChildren(h('div',{class:'empty'},h('h3',{},'这里还没有匹配的任务'),h('p',{},'任务会保留处理状态和结果。你可以调整筛选条件，或开始处理第一份文件。'),h('a',{href:'#workbench',class:'button-link'},'开始处理文件 →')));
 else {
  const rows=data.tasks.map(t=>{
    const pick=h('input',{type:'checkbox',checked:state.picked.has(t.id),'aria-label':'选择 '+nameOf(t.tool)+' '+t.id.slice(-6),onChange:e=>{e.target.checked?state.picked.add(t.id):state.picked.delete(t.id);$('#export-picked').disabled=!state.picked.size;}});
    const title=h('td',{},h('a',{class:'task-title',href:'#task/'+t.id},nameOf(t.tool)),h('span',{class:'task-sub'},(t.group_name||'未分组')+' · '+t.item_count+' 项'),h('span',{class:'task-sub'},t.id.slice(-12)));
    const progress=h('td',{class:'progress-cell'},h('div',{class:'task-progress'},h('span',{},t.stage),h('span',{},Math.round(t.progress)+'%')),h('progress',{value:t.progress,max:100,'aria-label':nameOf(t.tool)+'处理进度'}));
    return h('tr',{},h('td',{class:'pick'},pick),title,h('td',{},badge(t.status)),progress,h('td',{},h('small',{},time(t.created_at))));
  });
  list.replaceChildren(h('div',{class:'table-wrap'},h('table',{class:'task-table'},h('thead',{},h('tr',{},['选择','任务 / 分组','状态','处理进度','时间'].map(t=>h('th',{},t)))),h('tbody',{},rows))));
 }

 $('#task-pagination').replaceChildren(h('div',{class:'pagination'},h('span',{class:'muted'},`共 ${data.total} 个任务 · 第 ${Math.floor(state.offset/20)+1} 页`),h('div',{class:'buttons'},button('上一页',()=>{state.offset=Math.max(0,state.offset-20);action(refreshTasks);},'small',{disabled:state.offset===0}),button('下一页',()=>{state.offset+=20;action(refreshTasks);},'small',{disabled:state.offset+20>=data.total}))));
}
async function exportTasks(ids){
 if(!ids.length){toast('先选择有处理结果的任务。');return;}
 await action(async()=>{const t=await post('api/exports',{task_ids:ids,idempotency_key:idKey()});navigate('task',t.id);});
}
async function refreshDetail(){
 const id=state.taskId;const data=await api('api/tasks/'+id);if(state.nav!=='task'||state.taskId!==id)return;
 const key=JSON.stringify(data);if(key===state.renderKey)return;state.renderKey=key;state.task=data;
 const main=$('#main');const currentPreview=$('#preview-panel');
 const openItems=new Set([...main.querySelectorAll('details.item[open]')].map(x=>x.dataset.item));
 const paramsOpen=Boolean(main.querySelector('details[data-params][open]'));
 const existingLogs=$('#log-lines');const focused=document.activeElement;
 const focusText=main.contains(focused)?focused.textContent:null;const focusHref=focused?.closest('.result')?.querySelector('a')?.getAttribute('href');
 main.replaceChildren(head(nameOf(data.tool),'每个文件独立记录。处理完成后，请检查内容质量再交付。',h('a',{href:'#tasks',class:'button-link'},'← 任务队列'),'TASK / '+data.id.slice(-12)));
 main.append(h('div',{class:'summary-line'},badge(data.status),h('span',{},'创建于 '+time(data.created_at)),h('span',{},`${data.counts.succeeded} / ${data.item_count} 项完成`),h('span',{},data.group_name||'未分组')),
 h('div',{class:'task-progress'},h('strong',{},data.stage),h('span',{},Math.round(data.progress)+'%')),h('progress',{value:data.progress,max:100,'aria-label':'任务总进度'}));
 const actions=h('div',{class:'detail-actions'});
 if(['accepted','running'].includes(data.status))actions.append(button(data.cancel_requested?'正在停止…':'取消任务',()=>action(async()=>{await post('api/tasks/'+id+'/cancel');await refreshDetail();}),'danger',{disabled:data.cancel_requested}));
 if(['failed','partial','cancelled','recoverable'].includes(data.status))actions.append(button('重试未完成项',()=>action(async()=>{await post('api/tasks/'+id+'/resume');await refreshDetail();}),'primary'));
 if(data.outputs.length)actions.append(button('打包全部结果',()=>exportTasks([id])),button('用结果继续处理',()=>reuse(data.outputs)));
 actions.append(button('调整参数并创建新任务',()=>{state.toolId=data.tool;state.params[data.tool]={...data.params};state.files=data.inputs;persistFiles();state.submitKey=null;navigate('workbench');}));
 actions.append(button('复制任务编号',()=>action(async()=>{await navigator.clipboard.writeText(id);toast('任务编号已复制。');}),'small'));main.append(actions);
 if(data.error)main.append(errorBlock(data.error));
 if(['partial','cancelled','recoverable'].includes(data.status))main.append(h('div',{class:'callout info'},'已成功的项目和结果会保留。恢复时只处理其余项目。'));
 main.append(h('section',{class:'section'},h('h2',{},'处理结果'),data.outputs.length?h('div',{class:'result-list'},data.outputs.map(f=>h('div',{class:'result'},h('div',{},h('div',{class:'file-name'},f.name),h('div',{class:'file-meta'},[bytes(f.size),f.kind,f.width?`${f.width}×${f.height}`:'',f.pages?`${f.pages} 页`:'',f.duration?`${f.duration.toFixed(2)} 秒`:''].filter(Boolean).join(' · ')),h('small',{},'结构已核验 · 内容质量待确认')),h('div',{class:'result-actions'},button('预览',()=>action(()=>showPreview(f)),'small'),h('a',{class:'button-link',href:'./api/files/'+f.id+'/content',download:f.name},'下载'),button('继续处理',()=>reuse([f]),'small'))))):h('div',{class:'callout info'},['accepted','running'].includes(data.status)?'结果生成并核验后，会显示在这里。':'当前没有生成可用结果，请查看下方项目错误。')));
 if(currentPreview)main.append(currentPreview);
 main.append(h('section',{class:'section'},h('h2',{},'逐项记录'),data.items.map(item=>h('details',{class:'item','data-item':item.id,open:openItems.has(item.id)},h('summary',{},h('span',{},item.input_ids.map(fid=>data.inputs.find(f=>f.id===fid)?.name||fid).join(' ＋ ')),badge(item.status)),h('p',{},`累计尝试 ${item.attempt} 次 · 结果 ${item.output_ids.length} 个`),item.error?errorBlock(item.error):h('p',{},'此项没有错误记录。')))),
 h('details',{class:'section','data-params':'true',open:paramsOpen},h('summary',{},'查看使用的参数'),h('pre',{},JSON.stringify(data.params,null,2))),
 h('section',{class:'section'},h('div',{class:'section-title'},h('h2',{},'阶段日志'),button('读取日志',()=>action(async()=>{const log=await api('api/tasks/'+id+'/logs');$('#log-lines').replaceChildren(...log.events.map(e=>h('div',{class:'log'},time(e.time)+' · '+e.message)));}),'small')),h('div',{id:'log-lines',class:'muted'},'按需读取脱敏日志，不包含文件内容或密码。')));
 if(existingLogs?.querySelector('.log'))$('#log-lines').replaceWith(existingLogs);
 if(focusText){const match=[...main.querySelectorAll('button,a,summary')].find(x=>x.textContent===focusText&&(!focusHref||x.closest('.result')?.querySelector('a')?.getAttribute('href')===focusHref));match?.focus({preventScroll:true});}
}
function reuse(files){state.files=files.map((f,i)=>({...f,clientOrder:i}));state.uploadCounter=state.files.length;persistFiles();state.submitKey=null;toast('结果已加入输入列表，请选择下一步工具。');navigate('workbench');}
async function showPreview(f){
 const version=state.viewVersion;const data=await api('api/files/'+f.id+'/preview');if(version!==state.viewVersion)return;let panel=$('#preview-panel');if(!panel){panel=h('section',{class:'preview',id:'preview-panel'});$('#main').append(panel);}
 panel.replaceChildren(h('div',{class:'section-title'},h('h2',{},f.name),button('关闭预览',()=>panel.remove(),'small')),h('p',{class:'muted'},'请检查画面、声音或文字是否符合预期。'));
 const url='./api/files/'+f.id+'/content?inline=true';
 if(data.text!==undefined)panel.append(data.layout_preview===false?h('p',{class:'muted'},'文字预览不代表 Word 排版效果；请下载后核对。'):null,h('pre',{},data.text),data.truncated?h('small',{},'这里只显示前部分内容，完整结果请下载。'):null);
 else if(data.kind==='image')panel.append(h('img',{src:url,alt:'处理结果：'+f.name}));
 else if(data.kind==='video')panel.append(h('video',{src:url,controls:true,preload:'metadata'}));
 else if(data.kind==='audio')panel.append(h('audio',{src:url,controls:true,preload:'metadata'}));
 else if(data.kind==='pdf'){
  if(data.encrypted&&!data.pages)panel.append(errorBlock({message:'此 PDF 需要打开密码。',action:'先通过带密码参数的工具处理，再预览输出。'}));
  else {
   let page=1;const pageImage=h('img',{alt:'PDF 第 1 页',onError:()=>toast('此页预览失败。可下载文件，或在诊断页检查 PDF 渲染工具。')});
   const position=h('span',{'aria-live':'polite'});
   const previous=button('上一页',()=>{page--;draw();},'small');const next=button('下一页',()=>{page++;draw();},'small');
   function draw(){pageImage.src='./api/files/'+f.id+'/page?page='+page;pageImage.alt='PDF 第 '+page+' 页';position.textContent=page+' / '+data.pages+' 页';previous.disabled=page<=1;next.disabled=page>=data.pages;}
   panel.append(h('div',{class:'toolbar'},previous,position,next),pageImage);draw();
  }
 }
 else panel.append(h('p',{},'此格式需下载到对应应用中查看。'));
 panel.append(h('details',{},h('summary',{},'文件校验信息'),h('pre',{},JSON.stringify({sha256:f.sha256,verification:f.verification},null,2))));panel.scrollIntoView({behavior:'auto',block:'start'});
}
async function renderDiagnostics(){
 const version=state.viewVersion;const d=await api('api/doctor');if(version!==state.viewVersion)return;state.checks=d.checks;state.storage=d.storage;
 $('#main').replaceChildren(head('检查你的工具链','这里显示实际运行处理任务的服务环境。未配置的模型不会自动下载，缺失能力会明确停用。',button('重新检查',()=>action(async()=>{state.tools=(await api('api/tools')).tools;await renderDiagnostics();}))),
 h('div',{class:'summary-line'},h('span',{},d.server_platform.system+' / '+d.server_platform.architecture),h('span',{},d.worker_ready?'任务引擎运行中':'任务引擎未就绪'),h('span',{},`OCR 语言：${d.ocr_languages.join('、')||'未安装'}`)),
 h('div',{class:'diagnostics'},d.checks.map(c=>h('div',{class:'dependency'},h('div',{},h('strong',{},c.name),h('small',{},c.purpose),!c.available?h('code',{},c.install):null,Object.keys(c.details||{}).length?h('p',{class:'file-meta'},Object.entries(c.details).map(([k,v])=>k+': '+v).join(' · ')):null),h('div',{},h('span',{class:'tag'+(c.available?'':' warning')},c.available?'已配置':c.status==='broken'?'启动失败':'未配置'))))));
}
async function renderSettings(){
 const version=state.viewVersion;const me=await api('api/me');if(version!==state.viewVersion)return;const s=me.storage;state.storage=s;
 $('#main').replaceChildren(head('工作区设置','查看文件的实际存储位置、配额与保留期。所有入口使用同一个工作区的权限。'),
 h('div',{class:'settings-grid'},h('section',{class:'setting-block'},h('h2',{},'文件与存储'),h('dl',{},h('dt',{},'处理位置'),h('dd',{},'当前连接的服务'),h('dt',{},'已使用'),h('dd',{},bytes(s.used_bytes)),h('dt',{},'空间上限'),h('dd',{},bytes(s.quota_bytes)),h('dt',{},'单文件限制'),h('dd',{},bytes(s.max_file_bytes)),h('dt',{},'文件数量'),h('dd',{},s.files),h('dt',{},'默认保留'),h('dd',{},s.retention_days+' 天'))),
 h('section',{class:'setting-block'},h('h2',{},'任务执行'),h('dl',{},h('dt',{},'并行任务'),h('dd',{},s.concurrency),h('dt',{},'排队上限'),h('dd',{},s.max_pending),h('dt',{},'默认超时'),h('dd',{},s.timeout+' 秒')),h('p',{class:'muted'},'处理失败不会覆盖原文件。成功项可保留并继续使用，其他项可重试。'))),
 h('section',{class:'section setting-block'},h('h2',{},'清理历史文件'),h('p',{class:'muted'},'预览将列出可清理的文件数与空间。执行后不可恢复；正在执行任务需要的文件会保留。'),h('div',{class:'toolbar'},h('label',{class:'field',for:'cleanup-days'},'保留最近多少天',h('input',{id:'cleanup-days',type:'number',min:0,value:s.retention_days})),button('预览清理范围',()=>action(async()=>{const days=Number($('#cleanup-days').value);const data=await post('api/cleanup',{days,dry_run:true});$('#cleanup-result').replaceChildren(h('p',{},`可清理 ${data.files} 个文件、${data.tasks} 个任务，释放 ${bytes(data.bytes)}。`),button('确认清理这些文件',()=>{if(window.confirm(`清理 ${data.files} 个文件和 ${data.tasks} 个任务，释放 ${bytes(data.bytes)}？此操作不可恢复。`))action(async()=>{const r=await post('api/cleanup',{days,dry_run:false});toast(`已清理 ${r.files} 个文件。`);await renderSettings();});},'danger',{disabled:!data.files}));}))),h('div',{id:'cleanup-result'})),
 h('section',{class:'section setting-block'},h('h2',{},'访问与隐私'),h('p',{class:'muted'},'文件由当前服务处理，并非自动留在浏览器所在设备。请使用可信服务和 HTTPS。只有持有本工作区令牌的用户可以查看这些文件；请不要公开分享令牌。'),h('p',{class:'muted'},'每份结果需要人工确认内容质量。OCR、语音识别、复杂表格与版式转换尤其需要复核。')));
}
async function renderTemplates(){
 const version=state.viewVersion;const d=await api('api/templates');if(version!==state.viewVersion)return;state.templates=d.templates;
 $('#main').replaceChildren(head('参数模板','将常用参数保存下来，下一批文件可以直接复用。密码不会写入模板。'),d.templates.length?h('div',{},d.templates.map(t=>h('div',{class:'template-row'},h('div',{},h('h3',{},t.name),h('p',{},nameOf(t.tool))),h('div',{class:'result-actions'},button('应用模板',()=>{state.toolId=t.tool;state.params[t.tool]=t.params;state.submitKey=null;navigate('workbench');}),button('删除',()=>{if(window.confirm('删除参数模板“'+t.name+'”？'))action(async()=>{await api('api/templates/'+t.id,{method:'DELETE'});await renderTemplates();});},'small'))))):h('div',{class:'empty'},h('h3',{},'把常用设置留下来'),h('p',{},'在工作台选择工具并填写参数，点击“保存为参数模板”。'),h('a',{href:'#workbench',class:'button-link'},'去设置参数 →')));
}
async function bootstrap(){
 try {
  const me=await api('api/me');state.owner=me.owner;state.storage=me.storage;
  const [tools,doctor]=await Promise.all([api('api/tools'),api('api/doctor')]);state.tools=tools.tools;state.checks=doctor.checks;
  if(!tool())state.toolId='image-process';
  try{const stored=JSON.parse(sessionStorage.getItem('mf_files'));if(stored?.owner===state.owner)state.files=(await Promise.all(stored.ids.map(id=>api('api/files/'+id).catch(()=>null)))).filter(Boolean);}catch{}
  await route();
 }catch(e){state.owner=null;renderLogin(e.code==='unauthorized'?'':e.message||'暂时无法连接工作区。');}
}
$('.skip').addEventListener('click',e=>{e.preventDefault();$('#main')?.focus();$('#main')?.scrollIntoView();});
window.addEventListener('hashchange',()=>action(route));
setInterval(async()=>{
 if(!state.owner||state.polling||document.hidden)return;
 const interval=state.connected?2000:8000;if(Date.now()-state.lastPoll<interval)return;
 state.polling=true;state.lastPoll=Date.now();
 try{if(state.nav==='tasks')await refreshTasks();else if(state.nav==='task')await refreshDetail();else await api('api/me');}catch(e){if(e.code!=='unauthorized')connection(false);}finally{state.polling=false;}
},1000);
root.append(h('div',{class:'loading',role:'status'},'正在连接工作区…'));bootstrap();
