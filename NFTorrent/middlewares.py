import time
from dataclasses import dataclass

from starlette.middleware.base import BaseHTTPMiddleware, DispatchFunction, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp
from user_agents import parse

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


@dataclass(frozen=True)
class UserStatisticTag:
    path: str
    country: str
    device: str
    device_model: str
    browser: str
    browser_ver: str
    os: str


@dataclass
class UserStatisticMeasurement:
    count: int = 0


class StatisticsStore(MeasurementStore):

    def __init__(self):
        super().__init__("NFTorrentHTTP", StatisticMeasurement)


class UserStatisticsStore(MeasurementStore):

    def __init__(self):
        super().__init__("NFTorrentHTTPUsers", UserStatisticMeasurement)


class StatisticsMiddleware(BaseHTTPMiddleware):

    def __init__(self, app: ASGIApp, stats_store: StatisticsStore = None, dispatch: DispatchFunction | None = None):
        super().__init__(app, dispatch=dispatch)
        self._stats = stats_store

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        st = time.perf_counter()
        response = await call_next(request)

        path = request.scope["route"].path if "route" in request.scope else ""
        key = StatisticTags(path=path, method=request.method, status=response.status_code)
        meas: StatisticMeasurement = self._stats[key]
        meas.count += 1
        meas.duration += time.perf_counter() - st
        return response


class UserStatisticsMiddleware(BaseHTTPMiddleware):

    def __init__(self, app: ASGIApp, stats_store: UserStatisticsStore = None, dispatch: DispatchFunction | None = None):
        super().__init__(app, dispatch=dispatch)
        self._stats = stats_store

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)

        user_agent = parse(request.headers.get("user-agent", ""))
        path = request.scope["route"].path if "route" in request.scope else ""
        key = UserStatisticTag(
            path=path,
            browser=user_agent.browser.family,
            browser_ver=user_agent.browser.version_string,
            device=user_agent.device.family,
            device_model=user_agent.device.model,
            os=user_agent.os.family,
            country=request.headers.get("x-country-code", None),
        )
        meas: StatisticMeasurement = self._stats[key]
        meas.count += 1

        return response
