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
    return ForgeError('processing_failed', '处理未完成。',
                      '检查文件是否损坏或格式不兼容；保留任务编号以便排查。').payload()
