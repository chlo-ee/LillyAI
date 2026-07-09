"""Input module that fetches today's weather forecast from the free
open-meteo.com API (no API key required); used by the morning-briefing route.
"""

import requests

config = {}

WEATHER_CODES = {
    0: "clear sky",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "depositing rime fog",
    51: "light drizzle",
    53: "drizzle",
    55: "dense drizzle",
    56: "freezing drizzle",
    57: "freezing drizzle",
    61: "light rain",
    63: "rain",
    65: "heavy rain",
    66: "freezing rain",
    67: "freezing rain",
    71: "light snow",
    73: "snow",
    75: "heavy snow",
    77: "snow grains",
    80: "light rain showers",
    81: "rain showers",
    82: "violent rain showers",
    85: "snow showers",
    86: "snow showers",
    95: "thunderstorm",
    96: "thunderstorm with hail",
    99: "thunderstorm with hail",
}


def _describe(code):
    if code is None:
        return "unknown"
    try:
        code = int(code)
    except (TypeError, ValueError):
        return "unknown"
    return WEATHER_CODES.get(code, f"weather code {code}")


async def get_data():
    # timeout: a stalled/unreachable weather API must never hang the
    # (synchronous) event loop forever.
    response = requests.get(
        "https://api.open-meteo.com/v1/forecast",
        timeout=15,
        params={
            "latitude": config["latitude"],
            "longitude": config["longitude"],
            "current": "temperature_2m,weather_code",
            "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,weather_code,wind_speed_10m_max",
            "timezone": "auto",
            "forecast_days": 1,
        },
    )
    response.raise_for_status()
    data = response.json()

    current = data.get("current", {})
    daily = data.get("daily", {})

    now_temp = current.get("temperature_2m")
    now_code = current.get("weather_code")

    def first(key):
        values = daily.get(key)
        if not values:
            return None
        return values[0]

    temp_max = first("temperature_2m_max")
    temp_min = first("temperature_2m_min")
    precip_prob = first("precipitation_probability_max")
    day_code = first("weather_code")
    wind_max = first("wind_speed_10m_max")

    location_name = config.get("location_name")
    header = "Weather"
    if location_name:
        header += f" in {location_name}"
    header += " today:"

    lines = [header]

    if now_temp is not None:
        lines.append(f"Now: {round(now_temp)}°C, {_describe(now_code)}")

    today_bits = []
    if day_code is not None:
        today_bits.append(_describe(day_code))
    if temp_min is not None and temp_max is not None:
        today_bits.append(f"{round(temp_min)}°C to {round(temp_max)}°C")
    if precip_prob is not None:
        today_bits.append(f"precipitation probability {round(precip_prob)}%")
    if wind_max is not None:
        today_bits.append(f"max wind {round(wind_max)} km/h")

    if today_bits:
        lines.append("Today: " + ", ".join(today_bits))

    return "\n".join(lines)
