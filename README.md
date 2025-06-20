# Environment Canada (env_canada)

[![PyPI version](https://badge.fury.io/py/env-canada.svg)](https://badge.fury.io/py/env-canada)
[![Snyk rating](https://snyk-widget.herokuapp.com/badge/pip/env-canada/badge.svg)](https://snyk.io/vuln/pip:env-canada@0.8.0?utm_source=badge)
[![Python Lint and Test](../..//actions/workflows/python-app.yml/badge.svg)](../../actions/workflows/python-app.yml)

This package provides access to various data sources published by [Environment and Climate Change Canada](https://www.canada.ca/en/environment-climate-change.html).

> [!IMPORTANT]
> If you're using the library in a Jupyter notebook, replace `asyncio.run(...)` with `await ...` in the examples below. For example:
>
> ```python
> asyncio.run(ec_en.update())
> ```
>
> becomes
>
> ```python
> await ec_en.update()
> ```

## Weather Observations and Forecasts

`ECWeather` provides current conditions and forecasts. It automatically determines which weather station to use based on latitude/longitude provided. It is also possible to specify a station code in multiple flexible formats:

- **Full format**: `"AB/s0000123"` (province code and full station ID)
- **Station ID only**: `"s0000123"` (station ID without province - province is resolved automatically)
- **Numeric only**: `"123"` (just the station number - province is resolved automatically)

Station codes are based on those listed in [this CSV file](https://dd.weather.gc.ca/citypage_weather/docs/site_list_towns_en.csv). For example:

```python
import asyncio

from env_canada import ECWeather

# Using coordinates (automatic station selection)
ec_coords = ECWeather(coordinates=(50, -100))

# Using station ID - multiple formats supported:
ec_full = ECWeather(station_id="ON/s0000430", language="french")  # Full format
ec_station = ECWeather(station_id="s0000430")  # Station ID only
ec_numeric = ECWeather(station_id="430")  # Numeric only

asyncio.run(ec_coords.update())

# current conditions
ec_coords.conditions

# daily forecasts
ec_coords.daily_forecasts

# hourly forecasts
ec_coords.hourly_forecasts

# alerts
ec_coords.alerts
```

> [!NOTE]
> As of version 0.11.0, `ECWeather` automatically handles Environment Canada's new timestamped weather file URL structure (effective June 2025). The library dynamically discovers the most recent weather files, ensuring continued functionality during Environment Canada's infrastructure changes.

## Weather Radar

`ECRadar` provides Environment Canada meteorological [radar imagery](https://weather.gc.ca/radar/index_e.html).

```python
import asyncio

from env_canada import ECRadar

radar_coords = ECRadar(coordinates=(50, -100))

# Conditions Available
animated_gif = asyncio.run(radar_coords.get_loop())
latest_png = asyncio.run(radar_coords.get_latest_frame())
```

## Weather Maps

`ECMap` provides Environment Canada WMS weather map imagery with support for various meteorological layers.

```python
import asyncio

from env_canada import ECMap

# Create a map with rain radar layer
map_coords = ECMap(coordinates=(50, -100), layer="rain")

# Get the latest image with the specified layer
latest_png = asyncio.run(map_coords.get_latest_frame())

# Get an animated GIF with the specified layer
animated_gif = asyncio.run(map_coords.get_loop())

# Customize the map appearance
custom_map = ECMap(
    coordinates=(50, -100),
    layer="snow",
    width=1200,
    height=800,
    radius=300,
    layer_opacity=80,
    legend=True,
    timestamp=True,
    language="french",
)
```

Available layers include:

- `rain`: Precipitation rain radar
- `snow`: Precipitation snow radar
- `precip_type`: Surface precipitation type

Additional configuration options:

- `width`/`height`: Image dimensions (default: 800x800)
- `radius`: Map radius in km around coordinates (default: 200km)
- `layer_opacity`: Layer transparency 0-100% (default: 65%)
- `legend`: Show legend (default: True)
- `timestamp`: Show timestamp (default: True)
- `language`: "english" or "french" (default: "english")

> **Note**: ECMap automatically discovers available legend styles from Environment Canada's WMS capabilities, ensuring compatibility with any future style changes.

## Air Quality Health Index (AQHI)

`ECAirQuality` provides Environment Canada [air quality](https://weather.gc.ca/airquality/pages/index_e.html) data.

```python
import asyncio

from env_canada import ECAirQuality

aqhi_coords = ECAirQuality(coordinates=(50, -100))

asyncio.run(aqhi_coords.update())

# Data available
aqhi_coords.current
aqhi_coords.forecasts
```

## Water Level and Flow

`ECHydro` provides Environment Canada [hydrometric](https://wateroffice.ec.gc.ca/mainmenu/real_time_data_index_e.html) data.

```python
import asyncio

from env_canada import ECHydro

hydro_coords = ECHydro(coordinates=(50, -100))

asyncio.run(hydro_coords.update())

# Data available
hydro_coords.measurements
```

## Historical Weather Data

`ECHistorical` provides historical daily weather data.
The ECHistorical object is instantiated with a station ID, year, language, format (one of xml or csv) and granularity (hourly, daily data).
Once updated asynchronously, historical weather data is contained with the `station_data` property. If `xml` is requested, `station_data` will appear in a dictionary form. If `csv` is requested, `station_data` will contain a CSV-readable buffer. For example:

```python
import asyncio

from env_canada import ECHistorical
from env_canada.ec_historical import get_historical_stations

# search for stations, response contains station_ids
coordinates = [53.916944, -122.749444]  # [lat, long]

# coordinates: [lat, long]
# radius: km
# limit: response limit, value one of [10, 25, 50, 100]
# The result contains station names and ID values.
stations = asyncio.run(get_historical_stations(coordinates, radius=200, limit=100))

ec_en_xml = ECHistorical(station_id=31688, year=2020, language="english", format="xml")
ec_fr_xml = ECHistorical(station_id=31688, year=2020, language="french", format="xml")
ec_en_csv = ECHistorical(station_id=31688, year=2020, language="english", format="csv")
ec_fr_csv = ECHistorical(station_id=31688, year=2020, language="french", format="csv")

# timeframe argument can be passed to change the granularity
# timeframe=1 hourly (need to create of for every month in that case, use ECHistoricalRange to handle it automatically)
# timeframe=2 daily (default)
ec_en_xml = ECHistorical(
    station_id=31688, year=2020, month=1, language="english", format="xml", timeframe=1
)
ec_en_csv = ECHistorical(
    station_id=31688, year=2020, month=1, language="english", format="csv", timeframe=1
)

asyncio.run(ec_en_xml.update())
asyncio.run(ec_en_csv.update())

# metadata describing the station
ec_en_xml.metadata

# historical weather data, in dictionary form
ec_en_xml.station_data

# csv-generated responses return csv-like station data
import pandas as pd

df = pd.read_csv(ec_en_csv.station_data)
```

`ECHistoricalRange` provides historical weather data within a specific range and handles the update by itself.

The ECHistoricalRange object is instantiated with at least a station ID and a daterange.
One could add language, and granularity (hourly, daily (default)).

The data can then be used as pandas DataFrame, XML (requires pandas >=1.3.0) and csv

For example :

```python
import pandas as pd
import asyncio
from env_canada import ECHistoricalRange
from env_canada.ec_historical import get_historical_stations
from datetime import datetime

coordinates = ["48.508333", "-68.467667"]

stations = pd.DataFrame(
    asyncio.run(
        get_historical_stations(
            coordinates, start_year=2022, end_year=2022, radius=200, limit=100
        )
    )
).T

ec = ECHistoricalRange(
    station_id=int(stations.iloc[0, 2]),
    timeframe="daily",
    daterange=(datetime(2022, 7, 1, 12, 12), datetime(2022, 8, 1, 12, 12)),
)

ec.get_data()

# yield an XML formated str.
# For more options, use ec.to_xml(*arg, **kwargs) with pandas options
ec.xml

# yield an CSV formated str.
# For more options, use ec.to_csv(*arg, **kwargs) with pandas options
ec.csv
```

In this example `ec.df` will be:

| Date/Time  | Longitude (x) | Latitude (y) | Station Name          | Climate ID | Year | Month | Day | Data Quality | Max Temp (Â°C) | Max Temp Flag | Min Temp (Â°C) | Min Temp Flag | Mean Temp (Â°C) | Mean Temp Flag | Heat Deg Days (Â°C) | Heat Deg Days Flag | Cool Deg Days (Â°C) | Cool Deg Days Flag | Total Rain (mm) | Total Rain Flag | Total Snow (cm) | Total Snow Flag | Total Precip (mm) | Total Precip Flag | Snow on Grnd (cm) | Snow on Grnd Flag | Dir of Max Gust (10s deg) | Dir of Max Gust Flag | Spd of Max Gust (km/h) | Spd of Max Gust Flag |     |
| ---------- | ------------- | ------------ | --------------------- | ---------- | ---- | ----- | --- | ------------ | -------------- | ------------- | -------------- | ------------- | --------------- | -------------- | ------------------- | ------------------ | ------------------- | ------------------ | --------------- | --------------- | --------------- | --------------- | ----------------- | ----------------- | ----------------- | ----------------- | ------------------------- | -------------------- | ---------------------- | -------------------- | --- |
| 2022-07-02 | -68,47        | 48,51        | POINTE-AU-PERE (INRS) | 7056068    | 2022 | 7     | 2   |              | 22,8           |               | 12,5           |               | 17,7            |                | 0,3                 |                    | 0                   |                    |                 |                 |                 |                 | 0                 |                   |                   |                   | 26                        |                      | 37                     |                      |     |
| 2022-07-03 | -68,47        | 48,51        | POINTE-AU-PERE (INRS) | 7056068    | 2022 | 7     | 3   |              | 21,7           |               | 10,1           |               | 15,9            |                | 2,1                 |                    | 0                   |                    |                 |                 |                 |                 | 0,4               |                   |                   |                   | 28                        |                      | 50                     |                      |     |
| …          | …             | …            | …                     | …          | …    | …     | …   | …            | …              | …             | …              | …             | …               | …              | …                   | …                  | …                   | …                  | …               | …               | …               | …               | …                 | …                 | …                 | …                 | …                         | …                    | …                      | …                    | …   |
| 2022-07-31 | -68,47        | 48,51        | POINTE-AU-PERE (INRS) | 7056068    | 2022 | 7     | 31  |              | 23,5           |               | 14,1           |               | 18,8            |                | 0                   |                    | 0,8                 |                    |                 |                 |                 |                 | 0                 |                   |                   |                   | 23                        |                      | 31                     |                      |     |
| 2022-08-01 | -68,47        | 48,51        | POINTE-AU-PERE (INRS) | 7056068    | 2022 | 8     | 1   |              | 23             |               | 15             |               | 19              |                | 0                   |                    | 1                   |                    |                 |                 |                 |                 | 0                 |                   |                   |                   | 21                        |                      | 35                     |                      |     |

One should note that july 1st is excluded as the time provided contains specific hours, so it yields only data after or at exactly
the time provided.

To have all the july 1st data in that case, one can provide a datarange without time: `datetime(2022, 7, 7)` instead
of `datetime(2022, 7, 1, 12, 12)`

# License

The code is available under terms of [MIT License](https://github.com/michaeldavie/env_canada/tree/master/LICENSE.md)
