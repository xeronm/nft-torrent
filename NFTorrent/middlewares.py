import time
from collections import defaultdict
from dataclasses import dataclass
from typing import Optional

from starlette.middleware.base import (BaseHTTPMiddleware, DispatchFunction,
                                       RequestResponseEndpoint)
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp


@dataclass(frozen=True)
class StatisticTags:
    path: str
    method: str
    status: int


@dataclass
class StatisticMeasurements:
    count: int = 0
    duration: float = 0


class StatisticsStore(defaultdict):

    def __init__(self):
        super().__init__(StatisticMeasurements)

    def as_list(self):
        _timestamp = int(time.time() * 1000000)
        return [{'tags': k, 'fields': v, 'timestamp': _timestamp}
                for k, v in self.items()]


class StatisticsMiddleware(BaseHTTPMiddleware):

    def __init__(self, app: ASGIApp, stats_store: StatisticsStore = None, dispatch: Optional[DispatchFunction] = None):
        super().__init__(app, dispatch=dispatch)
        self._stats = stats_store

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        st = time.perf_counter()
        response = await call_next(request)

        path = request.scope['route'].path if 'route' in request.scope else ''
        key = StatisticTags(path=path, method=request.method, status=response.status_code)
        measurements = self._stats[key]
        measurements.count += 1
        measurements.duration += time.perf_counter() - st
        return response
