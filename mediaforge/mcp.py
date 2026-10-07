"""Standard MCP over stdio; authenticated API access, no competing local workers."""
from pathlib import Path
from functools import lru_cache
import os
from mcp.server.fastmcp import FastMCP
from .client import Client,resource_id
from .errors import ForgeError

mcp=FastMCP('MediaForge',instructions='先发现工具与检查依赖；只处理用户授权的文件。提交后查询任务，核实实际输出，内容质量仍需人工确认。')


@lru_cache(maxsize=1)
def client():return Client(*_connection)

_connection=(None,None)


def scoped_path(value,output=False):
    key='MEDIAFORGE_OUTPUT_ROOTS' if output else 'MEDIAFORGE_LOCAL_ROOTS'
    defaults=str(Path.cwd()/'outputs') if output else str(Path.cwd())
    roots=[Path(x).expanduser().resolve() for x in os.getenv(key,defaults).split(os.pathsep) if x]
    path=Path(value).expanduser().resolve()
    if not any(path.is_relative_to(root) for root in roots):raise ValueError('文件不在 MCP 配置允许的本地目录内。')
    if path.suffix.lower() in {'.token','.pem','.key'} or path.name.startswith('.env') or any(part in {'.git','credentials','.credentials','admin.token','secret.key','.ssh'} for part in path.parts):raise ValueError('MCP 不处理凭证或版本控制文件。')
    return path


@mcp.tool()
def discover_operations() -> dict:
    """列出工具、参数 JSON Schema、输入类型和依赖可用性。"""
    return client().request('GET','api/tools')


@mcp.tool()
def diagnose_workspace() -> dict:
    """检查依赖、模型、CPU/GPU、OCR语言、配额；没有模型时不要提交 ASR。"""
    return client().request('GET','api/doctor')


@mcp.tool()
def upload_file(path: str) -> dict:
    """将用户明确选择的本地文件上传到授权工作区，返回用于后续任务的文件 ID。"""
    return client().upload(scoped_path(path))


@mcp.tool()
def create_processing_task(operation: str, file_ids: list[str], params: dict,
                           idempotency_key: str, group: str = '', timeout: int = 1800, retries: int = 0) -> dict:
    """受理任务，不代表处理完成；参数遵守 discover_operations 返回的 schema。"""
    task=client().request('POST','api/tasks',json={'tool':operation,'file_ids':file_ids,'params':params,'idempotency_key':idempotency_key,'group':group,'timeout':timeout,'retries':retries})
    return {k:task[k] for k in ['id','status','stage','counts','output_ids']}


@mcp.tool()
def get_task_status(task_id: str) -> dict:
    """简明查询任务状态、阶段、进度、逐项统计和错误；终态并不代替内容质量确认。"""
    task=client().request('GET','api/tasks/'+resource_id(task_id,'task'))
    return {k:task[k] for k in ['id','tool','status','stage','progress','counts','output_ids','error','cancel_requested']}


@mcp.tool()
def get_task_details(task_id: str) -> dict:
    """按需读取逐项状态、输入元数据和输出校验信息，不返回服务器文件路径或密码。"""
    return client().request('GET','api/tasks/'+resource_id(task_id,'task'))


@mcp.tool()
def get_task_logs(task_id: str) -> dict:
    """单独获取脱敏阶段日志，用于失败排障。"""
    return client().request('GET','api/tasks/'+resource_id(task_id,'task')+'/logs')


@mcp.tool()
def list_tasks(status: str = '', search: str = '', limit: int = 20, offset: int = 0) -> dict:
    """按状态或搜索词分页查询当前授权工作区。"""
    return client().request('GET','api/tasks',params={'status':status,'search':search,'limit':limit,'offset':offset})


@mcp.tool()
def cancel_task(task_id: str) -> dict:
    """请求停止工作进程；继续查询直到 cancelled 后才算取消完成。"""
    task=client().request('POST','api/tasks/'+resource_id(task_id,'task')+'/cancel')
    return {'id':task['id'],'status':task['status'],'cancel_requested':task['cancel_requested']}


@mcp.tool()
def resume_task(task_id: str) -> dict:
    """恢复失败、部分成功、已取消或重启中断任务；保留已成功项目。"""
    task=client().request('POST','api/tasks/'+resource_id(task_id,'task')+'/resume')
    return {'id':task['id'],'status':task['status'],'counts':task['counts']}


@mcp.tool()
def preview_result(file_id: str) -> dict:
    """获取当前工作区结果的预览信息；文本预览有长度上限。"""
    c=client();result=c.request('GET','api/files/'+resource_id(file_id,'file')+'/preview')
    result['download_url']=c.base+'/api/files/'+file_id+'/content'
    result['authorization_required']=True
    return result


@mcp.tool()
def download_result(file_id: str, output_path: str) -> dict:
    """下载到 MCP 配置允许的输出目录；拒绝覆盖已有文件。"""
    return client().download(file_id,scoped_path(output_path,True))


@mcp.tool()
def export_results(task_ids: list[str], idempotency_key: str) -> dict:
    """创建 ZIP 打包任务，查询到 succeeded 后核实并下载其结果。"""
    return client().request('POST','api/exports',json={'task_ids':task_ids,'idempotency_key':idempotency_key})


def main(server=None,token_file=None):
    global _connection
    _connection=(server,token_file);client.cache_clear()
    mcp.run(transport='stdio')
if __name__=='__main__':main()
