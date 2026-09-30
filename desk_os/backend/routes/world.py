"""航班与地震。"""

from fastapi import APIRouter
from pydantic import BaseModel

from backend.earthquakes import get_earthquakes
from backend.flights import flight_settings, get_flights, get_route, save_flight_settings

router = APIRouter()


class FlightSettingsIn(BaseModel):
    max_draw: int | None = None
    warm_max: int | None = None
    route_draw: int | None = None


@router.get("/api/flights/settings")
def api_flight_settings():
    """绘制、补航线、画面航线的上限。空值表示不设上限。"""
    return flight_settings()


@router.put("/api/flights/settings")
def api_flight_settings_put(body: FlightSettingsIn):
    dump = getattr(body, "model_dump", None) or body.dict
    return save_flight_settings(dump(exclude_unset=True))


@router.get("/api/flights")
def api_flights():
    """附近空中的飞机。OpenSky 失败时返回上一份数据，不抛到主页。"""
    return get_flights()


@router.get("/api/earthquakes")
def api_earthquakes():
    """最近一小时全球地震。USGS 失败时返回上一份数据，不抛到主页。"""
    return get_earthquakes()


@router.get("/api/flights/route")
def api_flight_route(callsign: str = "", lat: float | None = None, lon: float | None = None):
    """一架飞机的起飞、降落城市。没有航线时字段为空。"""
    return get_route(callsign, lat, lon)
