import csv
import io
from typing import Any

from aiohttp import ClientSession
from dateutil.parser import isoparse
from geopy import distance
from pydantic import BaseModel, Field, model_validator

from .constants import USER_AGENT

SITE_LIST_URL = (
    "https://dd.weather.gc.ca/today/hydrometric/doc/hydrometric_StationList.csv"
)
READINGS_URL = "https://dd.weather.gc.ca/today/hydrometric/csv/{prov}/hourly/{prov}_{station}_hourly_hydrometric.csv"


__all__ = ["ECHydro"]


async def get_hydro_sites():
    """Get list of all sites from Environment Canada, for auto-config."""

    sites = []

    async with ClientSession(raise_for_status=True) as session:
        response = await session.get(
            SITE_LIST_URL, headers={"User-Agent": USER_AGENT}, timeout=10
        )
        result = await response.read()
    sites_csv_string = result.decode("utf-8-sig")
    sites_csv_stream = io.StringIO(sites_csv_string)

    header = [h.split("/")[0].strip() for h in sites_csv_stream.readline().split(",")]
    sites_reader = csv.DictReader(sites_csv_stream, fieldnames=header)

    for site in sites_reader:
        # Ignore bad site data
        if site["Latitude"] is not None:
            site["Latitude"] = float(site["Latitude"])
            site["Longitude"] = float(site["Longitude"])
            sites.append(site)

    return sites


async def closest_site(lat, lon):
    """Return the province/site_code of the closest station to our lat/lon."""
    site_list = await get_hydro_sites()

    def site_distance(site):
        """Calculate distance to a site."""
        return distance.distance((lat, lon), (site["Latitude"], site["Longitude"]))

    closest = min(site_list, key=site_distance)

    return closest


class Coordinates(BaseModel):
    lat: int | float = Field(..., ge=-90, le=90)
    lon: int | float = Field(..., ge=-180, le=180)


class ECHydro(BaseModel):
    """Get hydrometric data from Environment Canada."""

    coordinates: Coordinates | None = Field(None)
    province: str | None = Field(None, max_length=2)
    station: str | None = Field(None, max_length=7)
    measurements: dict[str, Any] = {}
    timestamp: str | None = Field(None)
    location: str | None = Field(None)

    @model_validator(mode="before")
    @classmethod
    def set_coordinates(cls, values: dict[str, Any]) -> dict[str, Any]:
        if "coordinates" in values:
            values["coordinates"] = {
                "lat": values["coordinates"][0],
                "lon": values["coordinates"][1],
            }
        return values

    @model_validator(mode="after")
    def check_one_or_another_is_present(self) -> "ECHydro":
        if self.province is None and self.station is None and self.coordinates is None:
            raise ValueError("Provice and station or 'coordinates' must be provided.")
        return self

    async def update(self):
        """Get the latest data from Environment Canada."""

        # Determine closest site if not provided

        if not (self.province and self.station) and self.coordinates:
            closest = await closest_site(self.coordinates.lat, self.coordinates.lon)
            self.province = closest["Prov"]
            self.station = closest["ID"]
            self.location = closest["Name"].title()

        # Get hydrometric data

        async with ClientSession(raise_for_status=True) as session:
            response = await session.get(
                READINGS_URL.format(prov=self.province, station=self.station),
                headers={"User-Agent": USER_AGENT},
                timeout=10,
            )
            result = await response.read()
        hydro_csv_string = result.decode("utf-8-sig")
        hydro_csv_stream = io.StringIO(hydro_csv_string)

        header = [
            h.split("/")[0].strip() for h in hydro_csv_stream.readline().split(",")
        ]
        readings_reader = csv.DictReader(hydro_csv_stream, fieldnames=header)

        readings = [r for r in readings_reader]
        if len(readings) > 0:
            latest = readings[-1]

            if latest["Water Level"] != "":
                self.measurements["water_level"] = {
                    "label": "Water Level",
                    "value": float(latest["Water Level"]),
                    "unit": "m",
                }

            if latest["Discharge"] != "":
                self.measurements["discharge"] = {
                    "label": "Discharge",
                    "value": float(latest["Discharge"]),
                    "unit": "m³/s",
                }

            self.timestamp = isoparse(readings[-1]["Date"])
