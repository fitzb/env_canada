import logging
from datetime import UTC, datetime
from typing import Any, Literal

from aiohttp import ClientSession, ClientTimeout
from geopy import distance
from lxml import etree as et
from pydantic import BaseModel, Field, model_validator

from .constants import USER_AGENT

AQHI_SITE_LIST_URL = (
    "https://dd.weather.gc.ca/today/air_quality/doc/AQHI_XML_File_List.xml"
)
AQHI_OBSERVATION_URL = "https://dd.weather.gc.ca/today/air_quality/aqhi/{}/observation/realtime/xml/AQ_OBS_{}_CURRENT.xml"
AQHI_FORECAST_URL = "https://dd.weather.gc.ca/today/air_quality/aqhi/{}/forecast/realtime/xml/AQ_FCST_{}_CURRENT.xml"

CLIENT_TIMEOUT = ClientTimeout(10)

LOG = logging.getLogger(__name__)

ATTRIBUTION = {
    "EN": "Data provided by Environment Canada",
    "FR": "Données fournies par Environnement Canada",
}


class MetaData(BaseModel):
    attribution: str
    timestamp: datetime | None = None
    location: str | None = None

    # Not used; needed for compatability with ec_weather metadata
    station: str | None = None


__all__ = ["ECAirQuality"]


def timestamp_to_datetime(timestamp):
    dt = datetime.strptime(timestamp, "%Y%m%d%H%M%S")
    dt = dt.replace(tzinfo=UTC)
    return dt


async def get_aqhi_regions(language):
    """Get list of all AQHI regions from Environment Canada, for auto-config."""
    zone_name_tag = f"name_{language.lower()}_CA"
    region_name_tag = f"name{language.title()}"

    LOG.debug("get_aqhi_regions() started")

    regions = []
    async with ClientSession(raise_for_status=True) as session:
        response = await session.get(
            AQHI_SITE_LIST_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=CLIENT_TIMEOUT,
        )
        result = await response.read()

    site_xml = result
    xml_object = et.fromstring(site_xml)

    for zone in xml_object.findall("./EC_administrativeZone"):
        _zone_attribs = zone.attrib
        _zone_attrib = {
            "abbreviation": _zone_attribs["abreviation"],
            "zone_name": _zone_attribs[zone_name_tag],
        }
        for region in zone.findall("./regionList/region"):
            _region_attribs = region.attrib

            _region_attrib = {
                "region_name": _region_attribs[region_name_tag],
                "cgndb": _region_attribs["cgndb"],
                "latitude": float(_region_attribs["latitude"]),
                "longitude": float(_region_attribs["longitude"]),
            }
            _children = list(region)
            for child in _children:
                _region_attrib[child.tag] = child.text
            _region_attrib.update(_zone_attrib)
            regions.append(_region_attrib)

    LOG.debug("get_aqhi_regions(): found %d regions", len(regions))

    return regions


async def find_closest_region(language, lat, lon):
    """Return the AQHI region and site ID of the closest site."""
    region_list = await get_aqhi_regions(language)

    def site_distance(site):
        """Calculate distance to a region."""
        return distance.distance((lat, lon), (site["latitude"], site["longitude"]))

    return min(region_list, key=site_distance)


class Coordinates(BaseModel):
    lat: int | float | None = None
    lon: int | float | None = None


class ECAirQuality(BaseModel):
    """Get air quality data from Environment Canada."""

    zone_id: Literal["atl", "ont", "pnr", "pyr", "que"] | None = None
    region_id: str | None = Field(None, max_length=5)
    coordinates: Coordinates = Field(Coordinates())
    language: Literal["EN", "FR"] = Field("EN")
    metadata: MetaData = Field(MetaData(attribution="EN"))
    region_name: str | None = None
    current: str | None = None
    current_timestamp: str | None = None
    forecasts: dict[str, Any] = {"daily": {}, "hourly": {}}

    @model_validator(mode="before")
    @classmethod
    def set_metadata_and_coordinates(cls, values: dict[str, Any]) -> dict[str, Any]:
        if (
            not (values.get("zone_id") and values.get("region_id"))
            and "coordinates" not in values
        ):
            raise ValueError("zone_id and region_id or coordinates not specified.")
        if "coordinates" in values:
            values["coordinates"] = {
                "lat": values["coordinates"][0],
                "lon": values["coordinates"][1],
            }
        if "language" in values:
            values["metadata"] = MetaData(attribution=ATTRIBUTION[values["language"]])
        return values

    async def get_aqhi_data(self, url):
        async with ClientSession(raise_for_status=True) as session:
            try:
                response = await session.get(
                    url.format(self.zone_id, self.region_id),
                    headers={"User-Agent": USER_AGENT},
                    timeout=CLIENT_TIMEOUT,
                )
            except Exception:
                LOG.debug("Retrieving AQHI failed", exc_info=True)
                return None

            result = await response.read()
            aqhi_xml = result
            return et.fromstring(aqhi_xml)

    async def update(self):
        # Find closest site if not identified

        if not (self.zone_id and self.region_id):
            lat, lon = (self.coordinates.lat, self.coordinates.lon)
            closest = await find_closest_region(self.language, lat, lon)
            self.zone_id = closest["abbreviation"]
            self.region_id = closest["cgndb"]
            LOG.debug(
                "update() closest region returned: zone_id '%s' region_id '%s'",
                self.zone_id,
                self.region_id,
            )

        # Fetch current measurement
        aqhi_current = await self.get_aqhi_data(url=AQHI_OBSERVATION_URL)

        if aqhi_current is not None:
            # Update region name
            element = aqhi_current.find("region")
            self.region_name = element.attrib[f"name{self.language.title()}"]
            self.metadata.location = self.region_name

            # Update AQHI current condition
            element = aqhi_current.find("airQualityHealthIndex")
            if element is not None:
                self.current = float(element.text)
            else:
                self.current = None

            element = aqhi_current.find("./dateStamp/UTCStamp")
            if element is not None:
                self.current_timestamp = timestamp_to_datetime(element.text)
            else:
                self.current_timestamp = None
            self.metadata.timestamp = self.current_timestamp
            LOG.debug(
                "update(): aqhi_current %d timestamp %s",
                self.current,
                self.current_timestamp,
            )

        # Update AQHI forecasts
        aqhi_forecast = await self.get_aqhi_data(url=AQHI_FORECAST_URL)

        if aqhi_forecast is not None:
            # Update AQHI daily forecasts
            for f in aqhi_forecast.findall("./forecastGroup/forecast"):
                for p in f.findall("./period"):
                    if self.language == p.attrib["lang"]:
                        period = p.attrib["forecastName"]
                self.forecasts["daily"][period] = int(
                    f.findtext("./airQualityHealthIndex") or 0
                )

            # Update AQHI hourly forecasts
            for f in aqhi_forecast.findall("./hourlyForecastGroup/hourlyForecast"):
                self.forecasts["hourly"][timestamp_to_datetime(f.attrib["UTCTime"])] = (
                    int(f.text or 0)
                )
