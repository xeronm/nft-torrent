import time
from dataclasses import dataclass
from typing import Optional

from starlette.middleware.base import (BaseHTTPMiddleware, DispatchFunction,
                                       RequestResponseEndpoint)
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp
from NFTorrent.modelsbase import MeasurementStore


@dataclass(frozen=True)
class StatisticTags:
    path: str
    method: str
    status: int


@dataclass
class StatisticMeasurement:
    count: int = 0
    duration: float = 0


class StatisticsStore(MeasurementStore):

    def __init__(self):
        super().__init__('NFTorrentHTTP', StatisticMeasurement)


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
