from dataclasses import dataclass
from enum import Enum
from typing import Any


@dataclass
class TonlibClientResult:
    task_id: str
    method: str
    elapsed_time: float
    params: Any | None = None
    result: Any | None = None
    exception: Exception | None = None
    liteserver_info: Any | None = None


class TonlibWorkerMsgType(Enum):
    TASK_RESULT = 0
    LAST_BLOCK_UPDATE = 1
    ARCHIVAL_UPDATE = 2
