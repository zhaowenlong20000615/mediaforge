import errno
import sqlite3


class ForgeError(Exception):
    def __init__(self, code, message, action='', status=400, retryable=False):
        super().__init__(message)
        self.code, self.message, self.action = code, message, action
        self.status, self.retryable = status, retryable

    def payload(self):
        return {'code': self.code, 'message': self.message, 'action': self.action,
                'retryable': self.retryable}


def safe_error(exc):
    if isinstance(exc, ForgeError):
        return exc.payload()
    if getattr(exc,'errno',None) in {errno.ENOSPC,getattr(errno,'EDQUOT',-1)} or getattr(exc,'sqlite_errorcode',None)==sqlite3.SQLITE_FULL:
        return ForgeError('storage_full','存储空间不足，处理暂时无法继续。','清理存储空间后恢复任务；已完成结果会保留。',507,True).payload()
    return ForgeError('processing_failed', '处理未完成。',
                      '检查文件是否损坏或格式不兼容；保留任务编号以便排查。').payload()
