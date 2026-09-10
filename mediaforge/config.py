"""Runtime configuration; secrets never enter source or release artifacts."""
from dataclasses import dataclass
from pathlib import Path
import os


@dataclass(frozen=True)
class Settings:
    data: Path
    host: str = '127.0.0.1'
    port: int = 18081
    max_file_bytes: int = 512 * 1024 * 1024
    quota_bytes: int = 10 * 1024**3
    max_pending: int = 100
    concurrency: int = 2
    timeout: int = 1800
    retention_days: int = 7
    secure_cookie: bool = False
    max_outputs: int = 500

    @classmethod
    def load(cls):
        return cls(
            data=Path(os.getenv('MEDIAFORGE_DATA', '~/.mediaforge')).expanduser().resolve(),
            host=os.getenv('MEDIAFORGE_HOST', '127.0.0.1'),
            port=int(os.getenv('MEDIAFORGE_PORT', '18081')),
            max_file_bytes=int(os.getenv('MEDIAFORGE_MAX_FILE_BYTES', str(512 * 1024**2))),
            quota_bytes=int(os.getenv('MEDIAFORGE_QUOTA_BYTES', str(10 * 1024**3))),
            max_pending=int(os.getenv('MEDIAFORGE_MAX_PENDING', '100')),
            concurrency=max(1, min(8, int(os.getenv('MEDIAFORGE_CONCURRENCY', '2')))),
            timeout=int(os.getenv('MEDIAFORGE_TIMEOUT', '1800')),
            retention_days=int(os.getenv('MEDIAFORGE_RETENTION_DAYS', '7')),
            secure_cookie=os.getenv('MEDIAFORGE_SECURE_COOKIE', '0') == '1',
        )
