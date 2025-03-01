import csv
import logging
import re
from datetime import datetime, timedelta, timezone

import voluptuous as vol
from aiohttp import ClientSession, ClientTimeout
from dateutil import parser, tz
from geopy import distance
from lxml import etree as et
from lxml.etree import _Element

from . import ec_exc
from .constants import USER_AGENT

SITE_LIST_URL = "https://dd.weather.gc.ca/citypage_weather/docs/site_list_en.csv"

WEATHER_URL = "https://dd.weather.gc.ca/citypage_weather/xml/{}_{}.xml"

CLIENT_TIMEOUT = ClientTimeout(10)

LOG = logging.getLogger(__name__)

ATTRIBUTION = {
    "english": "Data provided by Environment Canada",
    "french": "Données fournies par Environnement Canada",
}


__all__ = ["ECWeather"]


conditions_meta = {
    "temperature": {
        "xpath": "./currentConditions/temperature",
        "type": "float",
        "english": "Temperature",
        "french": "Température",
    },
    "dewpoint": {
        "xpath": "./currentConditions/dewpoint",
        "type": "float",
        "english": "Dew Point",
        "french": "Point de rosée",
    },
    "wind_chill": {
        "xpath": "./currentConditions/windChill",
        "type": "int",
        "english": "Wind Chill",
        "french": "Refroidissement éolien",
    },
    "humidex": {
        "xpath": "./currentConditions/humidex",
        "type": "int",
        "english": "Humidex",
        "french": "Humidex",
    },
    "pressure": {
        "xpath": "./currentConditions/pressure",
        "type": "float",
        "english": "Pressure",
        "french": "Pression",
    },
    "tendency": {
        "xpath": "./currentConditions/pressure",
        "attribute": "tendency",
        "type": "str",
        "english": "Tendency",
        "french": "Tendance",
    },
    "humidity": {
        "xpath": "./currentConditions/relativeHumidity",
        "type": "int",
        "english": "Humidity",
        "french": "Humidité",
    },
    "visibility": {
        "xpath": "./currentConditions/visibility",
        "type": "float",
        "english": "Visibility",
        "french": "Visibilité",
    },
    "condition": {
        "xpath": "./currentConditions/condition",
        "type": "str",
        "english": "Condition",
        "french": "Condition",
    },
    "wind_speed": {
        "xpath": "./currentConditions/wind/speed",
        "type": "int",
        "english": "Wind Speed",
        "french": "Vitesse de vent",
    },
    "wind_gust": {
        "xpath": "./currentConditions/wind/gust",
        "type": "int",
        "english": "Wind Gust",
        "french": "Rafale de vent",
    },
    "wind_dir": {
        "xpath": "./currentConditions/wind/direction",
        "type": "str",
        "english": "Wind Direction",
        "french": "Direction de vent",
    },
    "wind_bearing": {
        "xpath": "./currentConditions/wind/bearing",
        "type": "int",
        "english": "Wind Bearing",
        "french": "Palier de vent",
    },
    "high_temp": {
        "xpath": './forecastGroup/forecast/temperatures/temperature[@class="high"]',
        "type": "int",
        "english": "High Temperature",
        "french": "Haute température",
    },
    "low_temp": {
        "xpath": './forecastGroup/forecast/temperatures/temperature[@class="low"]',
        "type": "int",
        "english": "Low Temperature",
        "french": "Basse température",
    },
    "uv_index": {
        "xpath": "./forecastGroup/forecast/uv/index",
        "type": "int",
        "english": "UV Index",
        "french": "Indice UV",
    },
    "pop": {
        "xpath": "./forecastGroup/forecast/abbreviatedForecast/pop",
        "type": "int",
        "english": "Chance of Precip.",
        "french": "Probabilité d'averses",
    },
    "icon_code": {
        "xpath": "./currentConditions/iconCode",
        "type": "str",
        "english": "Icon Code",
        "french": "Code icône",
    },
    "normal_high": {
        "xpath": './forecastGroup/regionalNormals/temperature[@class="high"]',
        "type": "int",
        "english": "Normal High Temperature",
        "french": "Haute température normale",
    },
    "normal_low": {
        "xpath": './forecastGroup/regionalNormals/temperature[@class="low"]',
        "type": "int",
        "english": "Normal Low Temperature",
        "french": "Basse température normale",
    },
    "sunrise": {
        "xpath": './riseSet/dateTime[@name="sunrise"]/timeStamp',
        "type": "timestamp",
        "english": "Sunrise",
        "french": "Lever",
    },
    "sunset": {
        "xpath": './riseSet/dateTime[@name="sunset"]/timeStamp',
        "type": "timestamp",
        "english": "Sunset",
        "french": "Coucher",
    },
    "observationTime": {
        "xpath": "./currentConditions/dateTime/timeStamp",
        "type": "timestamp",
        "english": "Observation Time",
        "french": "Temps d'observation",
    },
}

summary_meta = {
    "forecast_period": {
        "xpath": "./forecastGroup/forecast/period",
        "type": "str",
        "attribute": "textForecastName",
    },
    "text_summary": {"xpath": "./forecastGroup/forecast/textSummary", "type": "str"},
    "label": {"english": "Forecast", "french": "Prévision"},
}

ALERTS_INIT = {
    "english": {
        "warnings": {"label": "Warnings", "value": []},
        "watches": {"label": "Watches", "value": []},
        "advisories": {"label": "Advisories", "value": []},
        "statements": {"label": "Statements", "value": []},
        "endings": {"label": "Endings", "value": []},
    },
    "french": {
        "warnings": {"label": "Alertes", "value": []},
        "watches": {"label": "Veilles", "value": []},
        "advisories": {"label": "Avis", "value": []},
        "statements": {"label": "Bulletins", "value": []},
        "endings": {"label": "Terminaisons", "value": []},
    },
}

# Maps "type" in XML alert attribute to name used
ALERT_TYPE_TO_NAME = {
    "advisory": "advisories",
    "ending": "endings",
    "statement": "statements",
    "warning": "warnings",
    "watch": "watches",
}


def validate_station(station):
    """Check that the station ID is well-formed."""
    if station is None:
        return
    if not re.fullmatch(r"[A-Z]{2}/s0000\d{3}", station):
        raise vol.Invalid('Station ID must be of the form "XX/s0000###"')
    return station


def _parse_timestamp(time_str: str | None) -> datetime | None:
    if time_str is not None:
        return parser.parse(time_str).replace(tzinfo=tz.UTC)
    return None


def _get_xml_text(xml_root: _Element, xpath: str) -> str | None:
    element = xml_root.find(xpath)
    return None if element is None or element.text is None else element.text


async def get_ec_sites():
    """Get list of all sites from Environment Canada, for auto-config."""
    LOG.debug("get_ec_sites() started")
    sites = []

    async with ClientSession(raise_for_status=True) as session:
        response = await session.get(
            SITE_LIST_URL, headers={"User-Agent": USER_AGENT}, timeout=CLIENT_TIMEOUT
        )
        sites_csv_string = await response.text()

    sites_reader = csv.DictReader(sites_csv_string.splitlines()[1:])

    for site in sites_reader:
        if site["Province Codes"] != "HEF":
            site["Latitude"] = float(site["Latitude"].replace("N", ""))
            site["Longitude"] = -1 * float(site["Longitude"].replace("W", ""))
            sites.append(site)

    LOG.debug("get_ec_sites() done, retrieved %d sites", len(sites))
    return sites


def closest_site(site_list, lat, lon):
    """Return the province/site_code of the closest station to our lat/lon."""

    def site_distance(site):
        """Calculate distance to a site."""
        return distance.distance((lat, lon), (site["Latitude"], site["Longitude"]))

    closest = min(site_list, key=site_distance)

    return "{}/{}".format(closest["Province Codes"], closest["Codes"])


class ECWeather:
    """Get weather data from Environment Canada."""

    def __init__(self, **kwargs):
        """Initialize the data object."""

        init_schema = vol.Schema(
            vol.All(
                {
                    vol.Required(
                        vol.Any("station_id", "coordinates"),
                        msg="Must specify either 'station_id' or 'coordinates'",
                    ): object,
                    vol.Optional("language"): object,
                },
                {
                    vol.Optional("station_id"): validate_station,
                    vol.Optional("coordinates"): (
                        vol.All(vol.Or(int, float), vol.Range(-90, 90)),
                        vol.All(vol.Or(int, float), vol.Range(-180, 180)),
                    ),
                    vol.Optional("language", default="english"): vol.In(
                        ["english", "french"]
                    ),
                    vol.Optional("max_data_age", default=2): int,
                },
            )
        )

        kwargs = init_schema(kwargs)

        self.language = kwargs["language"]
        self.max_data_age = kwargs["max_data_age"]
        self.metadata: dict[str, str | datetime | None] = {
            "attribution": ATTRIBUTION[self.language]
        }
        self.conditions = {}
        self.alerts = {}
        self.daily_forecasts = []
        self.hourly_forecasts = []
        self.forecast_time = ""
        self.site_list = []

        if "station_id" in kwargs and kwargs["station_id"] is not None:
            self.station_id = kwargs["station_id"]
            self.lat = None
            self.lon = None
        else:
            self.station_id = None
            self.lat = kwargs["coordinates"][0]
            self.lon = kwargs["coordinates"][1]

    async def update(self):
        """Get the latest data from Environment Canada."""

        # Determine station ID or coordinates if not provided
        if not self.site_list:
            self.site_list = await get_ec_sites()
            if self.station_id:
                stn = self.station_id.split("/")
                if len(stn) == 2:
                    for site in self.site_list:
                        if stn[1] == site["Codes"] and stn[0] == site["Province Codes"]:
                            self.lat = site["Latitude"]
                            self.lon = site["Longitude"]
                            break
                if not self.lat:
                    raise ec_exc.UnknownStationId
            else:
                self.station_id = closest_site(self.site_list, self.lat, self.lon)
                if not self.station_id:
                    raise ec_exc.UnknownStationId

        LOG.debug(
            "update(): station %s lat %f lon %f", self.station_id, self.lat, self.lon
        )

        # Get weather data
        async with ClientSession(raise_for_status=True) as session:
            response = await session.get(
                WEATHER_URL.format(self.station_id, self.language[0]),
                headers={"User-Agent": USER_AGENT},
                timeout=CLIENT_TIMEOUT,
            )
            result = await response.text()
        weather_xml = result

        try:
            weather_tree = et.fromstring(bytes(weather_xml, encoding="utf-8"))
        except et.ParseError as err:
            raise ECWeatherUpdateFailed(
                "Weather update failed; could not parse result"
            ) from err

        # Update metadata
        timestamp = _parse_timestamp(
            _get_xml_text(weather_tree, "./dateTime/timeStamp")
        )
        if timestamp is None:
            raise ECWeatherUpdateFailed("Weather update failed; timestamp not found")
        max_age = datetime.now(timezone.utc) - timedelta(hours=self.max_data_age)
        if timestamp < max_age:
            raise ECWeatherUpdateFailed("Weather update failed; outdated data returned")

        self.metadata["timestamp"] = timestamp
        self.metadata["location"] = _get_xml_text(weather_tree, "./location/name")
        self.metadata["station"] = _get_xml_text(
            weather_tree, "./currentConditions/station"
        )

        # Parse condition
        def get_condition(meta):
            condition = {}

            element = weather_tree.find(meta["xpath"])

            # None
            if element is None or element.text is None:
                condition["value"] = None

            else:
                # Units
                if element.attrib.get("units"):
                    condition["unit"] = element.attrib.get("units")

                # Value
                if meta.get("attribute"):
                    condition["value"] = element.attrib.get(meta["attribute"])
                else:
                    if meta["type"] == "int":
                        try:
                            condition["value"] = int(float(element.text))
                        except ValueError:
                            condition["value"] = int(0)
                    elif meta["type"] == "float":
                        try:
                            condition["value"] = float(element.text)
                        except ValueError:
                            condition["value"] = float(0)
                    elif meta["type"] == "str":
                        condition["value"] = element.text
                    elif meta["type"] == "timestamp":
                        condition["value"] = _parse_timestamp(element.text)

            return condition

        # Update current conditions
        current_conditions = weather_tree.find("./currentConditions")
        if current_conditions is not None and len(current_conditions) > 0:
            for c, meta in conditions_meta.items():
                self.conditions[c] = {"label": meta[self.language]}
                self.conditions[c].update(get_condition(meta))

            # Update text summary
            period = get_condition(summary_meta["forecast_period"])["value"]
            summary = get_condition(summary_meta["text_summary"])["value"]

            self.conditions["text_summary"] = {
                "label": summary_meta["label"][self.language],
                "value": ". ".join([period, summary]),
            }

        # Update alerts
        self.alerts = ALERTS_INIT[self.language].copy()
        alert_elements = weather_tree.findall("./warnings/event")
        for alert in alert_elements:
            title = alert.attrib.get("description")
            type_ = alert.attrib.get("type")
            if title is not None and type_ is not None and type_ in ALERT_TYPE_TO_NAME:
                self.alerts[ALERT_TYPE_TO_NAME[type_]]["value"].append(
                    {
                        "title": title.strip().title(),
                        "date": _get_xml_text(alert, "./dateTime[last()]/textSummary"),
                    }
                )

        # Update forecasts
        self.forecast_time = _parse_timestamp(
            _get_xml_text(weather_tree, "./forecastGroup/dateTime/timeStamp")
        )
        self.daily_forecasts = []
        self.hourly_forecasts = []

        # Update daily forecasts
        if self.forecast_time is not None:
            forecast_time = self.forecast_time
            for f in weather_tree.findall("./forecastGroup/forecast"):
                temperature_element = f.find("./temperatures/temperature")
                self.daily_forecasts.append(
                    {
                        "period": f.findtext("period"),
                        "text_summary": f.findtext("textSummary"),
                        "icon_code": f.findtext("./abbreviatedForecast/iconCode"),
                        "temperature": int(
                            f.findtext("./temperatures/temperature") or 0
                        ),
                        "temperature_class": temperature_element.attrib.get("class")
                        if temperature_element is not None
                        else None,
                        "precip_probability": int(
                            f.findtext("./abbreviatedForecast/pop") or "0"
                        ),
                        "timestamp": forecast_time,
                    }
                )
                if self.daily_forecasts[-1]["temperature_class"] == "low":
                    forecast_time = forecast_time + timedelta(days=1)

        # Update hourly forecasts
        for f in weather_tree.findall("./hourlyForecastGroup/hourlyForecast"):
            wind_speed_text = f.findtext("./wind/speed")
            self.hourly_forecasts.append(
                {
                    "period": _parse_timestamp(f.attrib.get("dateTimeUTC")),
                    "condition": f.findtext("./condition"),
                    "temperature": int(f.findtext("./temperature") or 0),
                    "icon_code": f.findtext("./iconCode"),
                    "precip_probability": int(f.findtext("./lop") or "0"),
                    "wind_speed": int(wind_speed_text)
                    if wind_speed_text and wind_speed_text.isnumeric()
                    else 0,
                    "wind_direction": f.findtext("./wind/direction"),
                }
            )


class ECWeatherUpdateFailed(Exception):
    """Raised when an update fails to get usable data."""
