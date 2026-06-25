from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlencode
from urllib.request import urlopen

from models import (
    EventContext,
    InspectionCase,
    SchedulingContext,
    TrafficContext,
    WeatherContext,
)


def _load_dotenv_if_available() -> None:
    try:
        from dotenv import load_dotenv

        load_dotenv()
    except ImportError:
        pass


def _asset_coordinates(inspection_case: InspectionCase) -> tuple[float, float] | None:
    latitude = inspection_case.asset.metadata.get("latitude")
    longitude = inspection_case.asset.metadata.get("longitude")
    try:
        if latitude is None or longitude is None:
            return None
        return float(latitude), float(longitude)
    except (TypeError, ValueError):
        return None


def _window_datetime(window: dict[str, Any]) -> datetime:
    return datetime.fromisoformat(str(window["start"])).replace(tzinfo=timezone.utc)


def _read_json_url(url: str, *, timeout: int = 20) -> dict[str, Any]:
    with urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def _first_env_value(*names: str) -> str | None:
    for name in names:
        value = os.getenv(name)
        if value:
            return value
    return None


class WeatherContextTool:
    def collect(
        self,
        inspection_case: InspectionCase,
        window: dict[str, Any],
    ) -> WeatherContext:
        raise NotImplementedError


class TrafficContextTool:
    def collect(
        self,
        inspection_case: InspectionCase,
        window: dict[str, Any],
    ) -> TrafficContext:
        raise NotImplementedError


class CityEventContextTool:
    def collect(
        self,
        inspection_case: InspectionCase,
        window: dict[str, Any],
    ) -> EventContext:
        raise NotImplementedError


class AccessRiskContextTool:
    def collect(
        self,
        inspection_case: InspectionCase,
        repair_windows: list[dict[str, Any]],
    ) -> int:
        raise NotImplementedError


class MockWeatherContextTool(WeatherContextTool):
    def __init__(self, weather_data: dict[str, Any]):
        self.weather_data = weather_data

    def collect(
        self,
        inspection_case: InspectionCase,
        window: dict[str, Any],
    ) -> WeatherContext:
        start = window["start"]
        data = self.weather_data.get(start, {})
        return WeatherContext(
            window_start=start,
            condition=data.get("condition", "unknown"),
            risk_score=int(data.get("risk_score", 0)),
            rationale=data.get("rationale", "No weather context was available."),
        )


class MockTrafficContextTool(TrafficContextTool):
    def __init__(self, traffic_data: dict[str, Any]):
        self.traffic_data = traffic_data

    def collect(
        self,
        inspection_case: InspectionCase,
        window: dict[str, Any],
    ) -> TrafficContext:
        start = window["start"]
        data = self.traffic_data.get(start, {})
        return TrafficContext(
            window_start=start,
            impact=data.get("impact", "unknown"),
            risk_score=int(data.get("risk_score", 0)),
            rationale=data.get("rationale", "No traffic context was available."),
        )


class MockCityEventContextTool(CityEventContextTool):
    def __init__(self, event_data: dict[str, Any]):
        self.event_data = event_data

    def collect(
        self,
        inspection_case: InspectionCase,
        window: dict[str, Any],
    ) -> EventContext:
        start = window["start"]
        data = self.event_data.get(start, {})
        return EventContext(
            window_start=start,
            title=data.get("title", "No event data"),
            risk_score=int(data.get("risk_score", 0)),
            rationale=data.get("rationale", "No city event or news context was available."),
        )


class MockAccessRiskContextTool(AccessRiskContextTool):
    def __init__(self, access_risk_score: int):
        self.access_risk_score = access_risk_score

    def collect(
        self,
        inspection_case: InspectionCase,
        repair_windows: list[dict[str, Any]],
    ) -> int:
        return self.access_risk_score


class OpenWeatherContextTool(WeatherContextTool):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        units: str = "metric",
        http_get: Any | None = None,
    ):
        _load_dotenv_if_available()
        self.api_key = api_key or _first_env_value(
            "OPENWEATHER_API_KEY",
            "OPEN_WEATHER_API_KEY",
        )
        self.units = units
        self.http_get = http_get or _read_json_url

    def collect(
        self,
        inspection_case: InspectionCase,
        window: dict[str, Any],
    ) -> WeatherContext:
        start = str(window["start"])
        coordinates = _asset_coordinates(inspection_case)
        if not self.api_key:
            return WeatherContext(
                start,
                "unknown",
                0,
                "OPENWEATHER_API_KEY or OPEN_WEATHER_API_KEY is not configured.",
            )
        if not coordinates:
            return WeatherContext(start, "unknown", 0, "Latitude/longitude metadata is not configured.")

        latitude, longitude = coordinates
        query = urlencode(
            {
                "lat": latitude,
                "lon": longitude,
                "appid": self.api_key,
                "units": self.units,
            }
        )
        payload = self.http_get(f"https://api.openweathermap.org/data/2.5/forecast?{query}")
        forecast = self._nearest_forecast(payload, _window_datetime(window))
        condition = self._condition(forecast)
        risk_score = self._risk_score(forecast)
        rationale = self._rationale(forecast, risk_score)
        return WeatherContext(start, condition, risk_score, rationale)

    def _nearest_forecast(
        self,
        payload: dict[str, Any],
        target: datetime,
    ) -> dict[str, Any]:
        forecasts = payload.get("list", [])
        if not forecasts:
            return {}
        return min(
            forecasts,
            key=lambda item: abs(
                datetime.fromtimestamp(item.get("dt", 0), tz=timezone.utc) - target
            ),
        )

    def _condition(self, forecast: dict[str, Any]) -> str:
        weather = forecast.get("weather") or [{}]
        return str(weather[0].get("main") or weather[0].get("description") or "unknown")

    def _risk_score(self, forecast: dict[str, Any]) -> int:
        condition = self._condition(forecast).lower()
        wind_speed = float(forecast.get("wind", {}).get("speed", 0) or 0)
        precipitation_probability = float(forecast.get("pop", 0) or 0)
        risk = 0
        if any(term in condition for term in ["thunderstorm", "snow", "freezing"]):
            risk += 8
        elif any(term in condition for term in ["rain", "drizzle"]):
            risk += 5
        elif "fog" in condition or "mist" in condition:
            risk += 3
        if precipitation_probability >= 0.7:
            risk += 3
        elif precipitation_probability >= 0.35:
            risk += 1
        if wind_speed >= 12:
            risk += 3
        elif wind_speed >= 8:
            risk += 1
        return min(10, risk)

    def _rationale(self, forecast: dict[str, Any], risk_score: int) -> str:
        condition = self._condition(forecast)
        precipitation_probability = float(forecast.get("pop", 0) or 0)
        wind_speed = float(forecast.get("wind", {}).get("speed", 0) or 0)
        return (
            f"OpenWeather forecast nearest the repair window is {condition}; "
            f"precipitation probability {precipitation_probability:.0%}, "
            f"wind {wind_speed:g} m/s, risk score {risk_score}."
        )


class TomTomTrafficContextTool(TrafficContextTool):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        zoom: int = 10,
        http_get: Any | None = None,
    ):
        _load_dotenv_if_available()
        self.api_key = api_key or os.getenv("TOMTOM_API_KEY")
        self.zoom = zoom
        self.http_get = http_get or _read_json_url

    def collect(
        self,
        inspection_case: InspectionCase,
        window: dict[str, Any],
    ) -> TrafficContext:
        start = str(window["start"])
        coordinates = _asset_coordinates(inspection_case)
        if not self.api_key:
            return TrafficContext(start, "unknown", 0, "TOMTOM_API_KEY is not configured.")
        if not coordinates:
            return TrafficContext(start, "unknown", 0, "Latitude/longitude metadata is not configured.")

        latitude, longitude = coordinates
        query = urlencode({"point": f"{latitude},{longitude}", "unit": "KMPH", "key": self.api_key})
        url = (
            "https://api.tomtom.com/traffic/services/4/flowSegmentData/"
            f"absolute/{self.zoom}/json?{query}"
        )
        payload = self.http_get(url)
        data = payload.get("flowSegmentData", payload)
        risk_score, impact = self._risk(data)
        rationale = self._rationale(data, risk_score)
        return TrafficContext(start, impact, risk_score, rationale)

    def _risk(self, data: dict[str, Any]) -> tuple[int, str]:
        if data.get("roadClosure"):
            return 10, "closure"
        current_speed = float(data.get("currentSpeed", 0) or 0)
        free_flow_speed = float(data.get("freeFlowSpeed", 0) or 0)
        current_time = float(data.get("currentTravelTime", 0) or 0)
        free_flow_time = float(data.get("freeFlowTravelTime", 0) or 0)
        speed_ratio = current_speed / free_flow_speed if free_flow_speed else 1.0
        delay_ratio = current_time / free_flow_time if free_flow_time else 1.0
        if speed_ratio < 0.35 or delay_ratio >= 2.0:
            return 8, "severe"
        if speed_ratio < 0.6 or delay_ratio >= 1.5:
            return 5, "high"
        if speed_ratio < 0.8 or delay_ratio >= 1.2:
            return 2, "moderate"
        return 0, "low"

    def _rationale(self, data: dict[str, Any], risk_score: int) -> str:
        return (
            "TomTom traffic flow near the asset: "
            f"current speed {data.get('currentSpeed', 'unknown')} km/h, "
            f"free-flow speed {data.get('freeFlowSpeed', 'unknown')} km/h, "
            f"road closure={bool(data.get('roadClosure'))}, risk score {risk_score}."
        )


class TicketmasterEventContextTool(CityEventContextTool):
    def __init__(
        self,
        *,
        api_key: str | None = None,
        radius_miles: int = 5,
        http_get: Any | None = None,
    ):
        _load_dotenv_if_available()
        self.api_key = api_key or os.getenv("TICKETMASTER_API_KEY")
        self.radius_miles = radius_miles
        self.http_get = http_get or _read_json_url

    def collect(
        self,
        inspection_case: InspectionCase,
        window: dict[str, Any],
    ) -> EventContext:
        start = str(window["start"])
        coordinates = _asset_coordinates(inspection_case)
        if not self.api_key:
            return EventContext(start, "No event provider", 0, "TICKETMASTER_API_KEY is not configured.")
        if not coordinates:
            return EventContext(start, "No event provider", 0, "Latitude/longitude metadata is not configured.")

        latitude, longitude = coordinates
        start_dt = _window_datetime(window)
        end_dt = datetime.fromisoformat(str(window["end"])).replace(tzinfo=timezone.utc)
        query = urlencode(
            {
                "apikey": self.api_key,
                "latlong": f"{latitude},{longitude}",
                "radius": self.radius_miles,
                "unit": "miles",
                "startDateTime": start_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "endDateTime": end_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
                "size": 5,
                "sort": "date,asc",
            }
        )
        payload = self.http_get(f"https://app.ticketmaster.com/discovery/v2/events.json?{query}")
        events = payload.get("_embedded", {}).get("events", [])
        if not events:
            return EventContext(start, "No nearby ticketed events", 0, "Ticketmaster found no nearby events during the repair window.")

        names = [str(event.get("name", "Unnamed event")) for event in events[:3]]
        risk = min(6, 2 + len(events))
        return EventContext(
            start,
            names[0],
            risk,
            f"Ticketmaster found {len(events)} nearby event(s): {', '.join(names)}.",
        )


class ScheduleContextCollector:
    def collect(
        self,
        inspection_case: InspectionCase,
        repair_windows: list[dict[str, Any]],
    ) -> SchedulingContext:
        raise NotImplementedError


class MockScheduleContextCollector(ScheduleContextCollector):
    def __init__(
        self,
        context_data: dict[str, Any] | None = None,
        *,
        weather_tool: WeatherContextTool | None = None,
        traffic_tool: TrafficContextTool | None = None,
        event_tool: CityEventContextTool | None = None,
        access_risk_tool: AccessRiskContextTool | None = None,
    ):
        context_data = context_data or {}
        self.weather_tool = weather_tool or MockWeatherContextTool(
            context_data.get("weather", {})
        )
        self.traffic_tool = traffic_tool or MockTrafficContextTool(
            context_data.get("traffic", {})
        )
        self.event_tool = event_tool or MockCityEventContextTool(
            context_data.get("events", {})
        )
        self.access_risk_tool = access_risk_tool or MockAccessRiskContextTool(
            int(context_data.get("access_risk_score", 0))
        )

    def collect(
        self,
        inspection_case: InspectionCase,
        repair_windows: list[dict[str, Any]],
    ) -> SchedulingContext:
        return SchedulingContext(
            weather=[
                self.weather_tool.collect(inspection_case, window)
                for window in repair_windows
            ],
            traffic=[
                self.traffic_tool.collect(inspection_case, window)
                for window in repair_windows
            ],
            events=[
                self.event_tool.collect(inspection_case, window)
                for window in repair_windows
            ],
            access_risk_score=self.access_risk_tool.collect(
                inspection_case,
                repair_windows,
            ),
        )


def build_schedule_context_collector(
    mode: str,
    context_data: dict[str, Any] | None = None,
    *,
    event_provider: str = "mock",
) -> ScheduleContextCollector:
    if mode == "mock":
        return MockScheduleContextCollector(context_data)
    if mode != "live":
        raise ValueError(f"Unsupported schedule context mode: {mode}")

    if event_provider == "mock":
        event_tool: CityEventContextTool = MockCityEventContextTool(
            (context_data or {}).get("events", {})
        )
    elif event_provider == "ticketmaster":
        event_tool = TicketmasterEventContextTool()
    else:
        raise ValueError(f"Unsupported event provider: {event_provider}")

    return MockScheduleContextCollector(
        context_data,
        weather_tool=OpenWeatherContextTool(),
        traffic_tool=TomTomTrafficContextTool(),
        event_tool=event_tool,
    )
