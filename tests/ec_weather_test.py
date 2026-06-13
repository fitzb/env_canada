import asyncio

from unittest.mock import patch
import pytest
from freezegun import freeze_time
from syrupy.assertion import SnapshotAssertion
from datetime import timedelta

from env_canada import ECWeather, ec_weather


@pytest.mark.parametrize(
    "init_parameters",
    [
        {"coordinates": (50, -100)},
        {"station_id": "ON/s0000430"},
        {"station_id": "s0000430"},
        {"station_id": "430"},
    ],
)
@pytest.mark.vcr
def test_ecweather(init_parameters):
    weather = ECWeather(**init_parameters)
    assert isinstance(weather, ECWeather)


def setup_test(args) -> tuple[ECWeather, None]:
    return (ECWeather(station_id=args["station"]), None)


@pytest.mark.asyncio
@pytest.mark.vcr
@freeze_time("2025-02-06 00:00")
async def test_weather_retrieved_weather_updates_ok(snapshot: SnapshotAssertion):
    ecw, _ = setup_test(
        {
            "station": "ON/s0000430",
            "sites": "tests/fixtures/site_list.csv",
            "forecast": "tests/fixtures/weather.xml",
        }
    )
    await ecw.update()
    assert ecw == snapshot


@pytest.mark.asyncio
@pytest.mark.vcr
async def test_weather_exception_on_old_forecast_data():
    ecw, _resp = setup_test(
        {
            "station": "ON/s0000430",
            "sites": "tests/fixtures/site_list.csv",
            "forecast": "tests/fixtures/weather.xml",
        }
    )
    freeze_time("2025-02-06 00:00")
    with pytest.raises(ec_weather.ECWeatherUpdateFailed):
        await ecw.update()


@pytest.mark.asyncio
@pytest.mark.vcr
async def test_weather_exception_returns_cached_data():
    with freeze_time("2025-02-06 00:00", real_asyncio=True) as frozen_time:
        ecw, resp = setup_test(
            {
                "station": "ON/s0000430",
                "sites": "tests/fixtures/site_list.csv",
                "forecast": "tests/fixtures/weather.xml",
            }
        )

        await ecw.update()

        with patch("aiohttp.ClientSession.get", side_effect=TimeoutError):
            await ecw.update()

        assert ecw.metadata.cache_returned_on_update == 1

        with patch("aiohttp.ClientSession.get", side_effect=TimeoutError):
            await ecw.update()

        assert ecw.metadata.cache_returned_on_update == 2
        frozen_time.tick(delta=timedelta(hours=ecw.max_data_age) + timedelta(hours=1))
        # Move date into future, should not return cached data now
        with patch("aiohttp.ClientSession.get", side_effect=TimeoutError):
            await ecw.update()

        assert ecw.metadata.cache_returned_on_update == 0


@pytest.mark.vcr
def test_get_ec_sites():
    sites = asyncio.run(ec_weather.get_ec_sites())
    assert len(sites) > 0


@pytest.mark.vcr
@freeze_time("2026-05-16 12:00")
def test_update_ec_weather():
    ecw, _ = setup_test({"station": "ON/s0000430"})
    asyncio.run(ecw.update())
    assert ecw.conditions


@pytest.mark.parametrize(
    "station_input,expected_result",
    [
        ("ON/s0000430", "ON/s0000430"),
        ("s0000430", "s0000430"),
        ("430", "430"),
        ("1", "1"),
        ("99", "99"),
    ],
)
def test_validate_station(station_input, expected_result):
    """Test that station validation returns the input unchanged when valid."""
    result = ec_weather.validate_station(station_input)
    assert result == expected_result


@pytest.mark.asyncio
@freeze_time("2025-05-16 00:00")
async def test_station_id_formats_create_tuples():
    """Test that different station ID formats result in proper tuples."""
    test_cases = [
        ("ON/s0000430", ("ON", "430")),
        ("s0000430", ("ON", "430")),  # Should find ON from site data
        ("430", ("ON", "430")),  # Should find ON from site data
    ]

    for station_input, expected_tuple in test_cases:
        ecw, resp = setup_test(
            {
                "station": station_input,
                "sites": "tests/fixtures/site_list.csv",
                "forecast": "tests/fixtures/weather.xml",
            }
        )

        await ecw.update()

        assert ecw.station_tuple == expected_tuple
        assert ecw.lat is not None
        assert ecw.lon is not None


@pytest.mark.asyncio
@freeze_time("2025-05-16 00:00")
async def test_home_assistant_compatibility():
    """Test that station_id remains a string for Home Assistant compatibility."""
    ecw, resp = setup_test(
        {
            "station": "ON/s0000430",
            "sites": "tests/fixtures/site_list.csv",
            "forecast": "tests/fixtures/weather.xml",
        }
    )

    await ecw.update()

    # station_id should remain a string for external API compatibility
    assert isinstance(ecw.station_id, str)
    assert ecw.station_id == "ON/s0000430"

    # Internal tuple should be available via property
    assert ecw.station_tuple == ("ON", "430")
