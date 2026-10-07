const {test,expect}=require('@playwright/test');
const AxeBuilder=require('@axe-core/playwright').default;
const fs=require('fs');const path=require('path');const crypto=require('crypto');
const fixture=path.resolve('var/audit-oct6');
const token=process.env.MF_BROWSER_TOKEN_FILE?fs.readFileSync(process.env.MF_BROWSER_TOKEN_FILE,'utf8').trim():'local-oct6-browser-fixture-only';
let taskId;
async function login(page){
 await page.goto('./');
 await page.getByLabel('访问令牌',{exact:true}).fill(token);
 await page.getByRole('button',{name:'连接工作区 →',exact:true}).click();
 await expect(page.getByRole('heading',{name:'你的文件，现在开始处理。'})).toBeVisible();
}
async function choose(page,names){await page.locator('input[type=file]').setInputFiles(names.map(n=>path.join(fixture,n)));await expect(page.locator('#create-task')).toBeEnabled();}
async function tool(page,name){await page.getByLabel('搜索工具',{exact:true}).fill(name);await page.getByRole('button',{name,exact:true}).click();}
async function finished(page){await expect(page.locator('.summary-line').getByText('已完成',{exact:true})).toBeVisible({timeout:90000});}
test.beforeEach(async({page})=>login(page));

test('上传、处理、下载校验、图片预览与可访问性',async({page})=>{
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await choose(page,['测试 输入.png']);await page.getByLabel('最大宽度（0 不限制）',{exact:true}).fill('80');
 await page.getByRole('button',{name:'创建任务 →',exact:true}).click();await finished(page);taskId=page.url().split('/').pop();
 await expect(page.locator('.result')).toContainText('80×48');
 const href=await page.getByRole('link',{name:'下载',exact:true}).getAttribute('href');
 const download=await page.request.get(href);expect(download.status()).toBe(200);
 const task=await (await page.request.get('./api/tasks/'+taskId)).json();
 expect(crypto.createHash('sha256').update(await download.body()).digest('hex')).toBe(task.outputs[0].sha256);
 await page.getByRole('button',{name:'预览',exact:true}).click();
 await expect(page.locator('#preview-panel img')).toBeVisible();
 await expect.poll(()=>page.locator('#preview-panel img').evaluate(x=>x.naturalWidth)).toBe(80);
 const audit=await new AxeBuilder({page}).withTags(['wcag2a','wcag2aa']).analyze();
 const significant=audit.violations.filter(v=>['critical','serious'].includes(v.impact));
 expect(significant.map(v=>({id:v.id,nodes:v.nodes.map(n=>n.target)}))).toEqual([]);
 await page.screenshot({path:path.join(fixture,'desktop-result.png'),fullPage:true});expect(errors).toEqual([]);
});

test('PDF 无效页码、调整参数、旋转预览与中文筛选',async({page})=>{
 await tool(page,'PDF 旋转');await choose(page,['三页.pdf']);await page.getByLabel('页码（留空为全部，如 1-3,5）',{exact:true}).fill('99');
 await page.getByRole('button',{name:'创建任务 →',exact:true}).click();
 await expect(page.locator('.summary-line').getByText('处理失败',{exact:true})).toBeVisible();
 await expect(page.getByRole('alert').first()).toContainText('页码范围无效');
 await page.getByRole('button',{name:'调整参数并创建新任务',exact:true}).click();
 await page.getByLabel('页码（留空为全部，如 1-3,5）',{exact:true}).fill('2');await page.getByRole('button',{name:'创建任务 →',exact:true}).click();await finished(page);
 await page.getByRole('button',{name:'预览',exact:true}).click();await page.locator('#preview-panel').getByRole('button',{name:'下一页',exact:true}).click();
 await expect.poll(()=>page.locator('#preview-panel img').evaluate(x=>x.complete&&x.naturalWidth>x.naturalHeight)).toBe(true);
 await page.getByRole('link',{name:'任务队列',exact:true}).click();await page.getByLabel('搜索任务',{exact:true}).fill('PDF 旋转');
 await page.getByLabel('任务状态',{exact:true}).selectOption('failed');
 await expect.poll(()=>page.locator('.task-table tbody tr').count()).toBeGreaterThan(0);
 await expect(page.locator('.task-table tbody')).toContainText('处理失败');expect(await page.locator('.task-table tbody .tag').allTextContents()).toEqual(expect.arrayContaining(['处理失败']));expect((await page.locator('.task-table tbody .tag').allTextContents()).every(x=>x==='处理失败')).toBe(true);
});

test('PDF 转 Word 生成文档和实际排版预览，预览可见',async({page})=>{
 await tool(page,'PDF 转 Word');await choose(page,['三页.pdf']);
 await page.getByRole('button',{name:'创建任务 →',exact:true}).click();await finished(page);
 const task=await(await page.request.get('./api/tasks/'+page.url().split('/').pop())).json();
 expect(task.outputs).toHaveLength(2);
 expect(task.outputs[0].kind).toBe('docx');expect(task.outputs[0].verification.rendered_numbers_preserved).toBe(true);
 const preview=page.locator('.result').filter({hasText:'document-preview.pdf'});
 await expect(preview).toContainText('Word 实际排版预览');
 await preview.getByRole('button',{name:'预览',exact:true}).click();
 await expect.poll(()=>page.locator('#preview-panel img').evaluate(x=>x.complete&&x.naturalWidth>0)).toBe(true);
 await expect(page.locator('#preview-panel')).toContainText('1 / 3 页');
});

test('并发上传按选择顺序排列，不按网络完成顺序',async({page})=>{
 await page.route('**/api/files?name=*',async route=>{
  const response=await route.fetch();
  if(decodeURIComponent(route.request().url()).includes('first.png'))await new Promise(r=>setTimeout(r,900));
  await route.fulfill({response});
 });
 await tool(page,'图片合成 PDF');
 await page.locator('input[type=file]').setInputFiles(['first.png','second.png'].map(name=>({name,mimeType:'image/png',buffer:fs.readFileSync(path.join(fixture,'测试 输入.png'))})));
 await expect(page.locator('#create-task')).toBeEnabled();
 await expect(page.locator('#input-files .file-name')).toHaveText(['first.png','second.png']);
 await page.getByRole('button',{name:'创建任务 →',exact:true}).click();await finished(page);
 const task=await(await page.request.get('./api/tasks/'+page.url().split('/').pop())).json();expect(task.inputs.map(f=>f.name)).toEqual(['first.png','second.png']);
});

test('慢响应不会覆盖新页面，窄屏保留导航且无横向溢出',async({page})=>{
 await page.route('**/api/templates',async route=>{const response=await route.fetch();await new Promise(r=>setTimeout(r,1000));await route.fulfill({response});});
 await page.getByRole('link',{name:'参数模板',exact:true}).click();await page.getByRole('link',{name:'设置',exact:true}).click();
 await expect(page.getByRole('heading',{name:'工作区设置',exact:true})).toBeVisible();
 await page.waitForTimeout(1300);await expect(page.getByRole('heading',{name:'工作区设置',exact:true})).toBeVisible();
 await page.setViewportSize({width:390,height:844});await page.getByRole('link',{name:'工作台',exact:true}).click();
 await expect(page.getByRole('navigation',{name:'主导航'}).getByRole('link')).toHaveCount(5);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
 await page.screenshot({path:path.join(fixture,'mobile-workbench.png'),fullPage:true});
});

test('断网有明确状态，重新连接后可恢复使用',async({page,context})=>{
 await context.setOffline(true);
 await expect(page.locator('#connection')).toContainText('连接中断',{timeout:20000});
 await context.setOffline(false);
 await expect(page.locator('#connection')).toHaveText('工作区已连接',{timeout:25000});
 await page.getByRole('link',{name:'任务队列',exact:true}).click();
 await expect(page.getByRole('heading',{name:'任务队列',exact:true})).toBeVisible();
});

test('退出后不再接收旧会话中的上传结果',async({page})=>{
 await page.route('**/api/files?name=*',async route=>{const response=await route.fetch();await new Promise(r=>setTimeout(r,1000));try{await route.fulfill({response});}catch{}});
 await page.locator('input[type=file]').setInputFiles(path.join(fixture,'测试 输入.png'));
 await expect(page.getByRole('button',{name:'取消上传',exact:true})).toBeVisible();
 await page.getByRole('button',{name:'退出',exact:true}).click();
 await expect(page.getByRole('heading',{name:'连接你的工作区',exact:true})).toBeVisible();
 await page.getByLabel('访问令牌',{exact:true}).fill(token);await page.getByRole('button',{name:'连接工作区 →',exact:true}).click();
 await expect(page.getByRole('heading',{name:'你的文件，现在开始处理。'})).toBeVisible();
 await page.waitForTimeout(1400);await expect(page.locator('#input-files .file-name')).toHaveCount(0);
 await expect(page.locator('#create-task')).toBeDisabled();
});

test('修改高级参数后不会错误复用上一次请求的幂等键',async({page})=>{
 await choose(page,['测试 输入.png']);let keys=[];
 await page.route('**/api/tasks',async route=>{
  if(route.request().method()!=='POST')return route.continue();
  keys.push(route.request().postDataJSON().idempotency_key);
  if(keys.length===1)return route.fulfill({status:400,contentType:'application/json',body:JSON.stringify({error:{message:'测试：请修改分组后重试'}})});
  return route.continue();
 });
 await page.getByRole('button',{name:'创建任务 →',exact:true}).click();await expect(page.getByRole('alert')).toContainText('测试：请修改分组后重试');
 await page.locator('summary').filter({hasText:'任务分组、超时与自动重试'}).click();
 await page.getByLabel('任务分组',{exact:true}).fill('新的分组');
 await page.getByRole('button',{name:'创建任务 →',exact:true}).click();await finished(page);
 expect(keys).toHaveLength(2);expect(keys[0]).not.toBe(keys[1]);
 await expect(page.locator('.summary-line')).toContainText('新的分组');
});
