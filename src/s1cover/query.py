"""Build an ASF catalog query and summarize the returned Sentinel-1 scenes."""

from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlsplit

import asf_search as asf
from asf_search.exceptions import ASFError, CMRError
from requests.exceptions import (
    ConnectionError,
    InvalidSchema,
    InvalidURL,
    RequestException,
    Timeout,
)
from requests.utils import get_environ_proxies, select_proxy
from shapely import from_geojson, to_wkt
from shapely.errors import GEOSException
from shapely.geometry import GeometryCollection, Polygon


class QueryError(RuntimeError):
    """The catalog cannot provide a reliable track summary."""


class CatalogUnavailable(QueryError):
    """No connection to the catalog could be established."""


CATALOG_URL = "https://cmr.earthdata.nasa.gov/search/granules.umm_json"


@dataclass(frozen=True)
class Connection:
    mode: str = "auto"
    proxy: str = ""

    def __post_init__(self):
        if self.mode not in {"auto", "direct", "proxy"}:
            raise ValueError("Unknown connection mode")
        if self.mode != "proxy":
            return
        address = self.proxy.strip()
        if "://" not in address:
            address = f"http://{address}"
        try:
            parsed = urlsplit(address)
            valid = (
                parsed.scheme in {"http", "https"}
                and parsed.hostname
                and parsed.port
                and parsed.username is None
                and parsed.path in {"", "/"}
                and not (parsed.query or parsed.fragment)
                and not any(char.isspace() for char in address)
            )
        except ValueError:
            valid = False
        if not valid:
            raise ValueError(
                "代理地址应为主机:端口或 HTTP(S) URL，且不含用户名或密码。"
            )
        object.__setattr__(self, "proxy", address.rstrip("/"))


def effective_proxy() -> str | None:
    return select_proxy(CATALOG_URL, get_environ_proxies(CATALOG_URL))


class CatalogSession(asf.ASFSession):
    def __init__(
        self, connection: Connection, *, trust_env: bool, geometry: bytes | None = None
    ):
        super().__init__()
        self.trust_env = trust_env
        # Bypass Requests' implicit netrc authentication.
        self.auth = lambda request: request
        self.geometry = geometry
        if connection.mode == "proxy":
            self.proxies.update(http=connection.proxy, https=connection.proxy)

    def request(self, method, url, **kwargs):
        if method.upper() != "POST" or url != CATALOG_URL:
            raise QueryError("Unexpected ASF catalog request endpoint.")
        kwargs["timeout"] = (8, 25)
        kwargs["allow_redirects"] = False
        if self.geometry is not None:
            kwargs["files"] = {
                "shapefile": ("aoi.geojson", self.geometry, "application/geo+json")
            }
        response = super().request(method, url, **kwargs)
        if 300 <= response.status_code < 400:
            raise QueryError("ASF catalog returned an unexpected redirect.")
        return response


@dataclass(frozen=True)
class TrackSummary:
    direction: str
    orbit: int
    imaging_mode: str
    polarization: str
    platforms: tuple[str, ...]
    count: int
    first_date: date
    last_date: date


def aoi_options(bbox: list[float] | None, geojson: Path | None) -> asf.ASFSearchOptions:
    if bbox is not None:
        west, south, east, north = bbox
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError(
                "--bbox requires increasing WGS84 longitude and latitude bounds"
            )
        return asf.ASFSearchOptions(bbox=bbox)

    try:
        polygon = from_geojson(geojson.read_text(encoding="utf-8-sig"))
    except (OSError, UnicodeError, GEOSException) as exc:
        raise ValueError(
            "--geojson requires a readable UTF-8 GeoJSON polygon file"
        ) from exc
    if isinstance(polygon, GeometryCollection) and len(polygon.geoms) == 1:
        polygon = polygon.geoms[0]
    if not isinstance(polygon, Polygon) or polygon.is_empty or not polygon.is_valid:
        raise ValueError("--geojson must contain one valid WGS84 Polygon")
    if polygon.interiors:
        raise ValueError("--geojson polygon holes are unsupported by ASF search")
    west, south, east, north = polygon.bounds
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise ValueError(
            "--geojson coordinates must be valid WGS84 longitude and latitude"
        )
    return asf.ASFSearchOptions(
        intersectsWith=to_wkt(polygon, rounding_precision=-1, output_dimension=2)
    )


def _search_catalog(aoi, start, end, max_results, connection, geometry):
    trust_env = connection.mode == "auto"
    has_system_proxy = trust_env and bool(effective_proxy())
    attempts = [True, False] if has_system_proxy else [trust_env]
    report_errors = asf.REPORT_ERRORS
    asf.REPORT_ERRORS = False
    try:
        for trust_env in attempts:
            with CatalogSession(
                connection, trust_env=trust_env, geometry=geometry
            ) as session:
                try:
                    results = asf.search(
                        dataset=asf.DATASET.SENTINEL1,
                        processingLevel=asf.PRODUCT_TYPE.SLC,
                        opts=aoi,
                        session=session,
                        start=f"{start}T00:00:00Z" if start else None,
                        end=f"{end}T23:59:59Z" if end else None,
                        maxResults=max_results,
                    )
                    results.raise_if_incomplete()
                    return results
                except (
                    ASFError,
                    CMRError,
                    RequestException,
                    ValueError,
                    KeyError,
                ) as exc:
                    # The SDK can wrap Requests' read timeout in an ASFSearchError.
                    network_error = isinstance(
                        exc, (ConnectionError, Timeout)
                    ) or isinstance(exc.__cause__, (ConnectionError, Timeout))
                    bad_proxy = (
                        trust_env
                        and has_system_proxy
                        and isinstance(exc, (InvalidURL, InvalidSchema))
                    )
                    if not (network_error or bad_proxy):
                        raise QueryError(
                            "ASF query failed. Check the query area and try again."
                        ) from exc
        raise CatalogUnavailable(
            "Could not reach the ASF catalog. Check the network or proxy."
        )
    finally:
        asf.REPORT_ERRORS = report_errors


def search_tracks(
    aoi: asf.ASFSearchOptions,
    *,
    start: date | None,
    end: date | None,
    max_results: int,
    connection: Connection = Connection(),
    geometry: bytes | None = None,
) -> list[TrackSummary]:
    results = _search_catalog(aoi, start, end, max_results, connection, geometry)
    acquisitions = defaultdict(list)
    for scene in results:
        properties = scene.properties
        direction = str(properties.get("flightDirection")).upper()
        orbit = properties.get("pathNumber")
        start_time = properties.get("startTime")
        if (
            direction not in {"ASCENDING", "DESCENDING"}
            or not isinstance(orbit, int)
            or orbit < 1
        ):
            raise QueryError(
                "ASF returned a scene without a valid flight direction or relative orbit."
            )
        try:
            acquisition_date = date.fromisoformat(start_time[:10])
        except (TypeError, ValueError) as exc:
            raise QueryError(
                "ASF returned a scene without a valid acquisition date."
            ) from exc
        imaging_mode = (properties.get("beamModeType") or "").strip().upper()
        polarization = (properties.get("polarization") or "").strip().upper()
        platform = (properties.get("platform") or "").strip()
        acquisitions[direction, orbit, imaging_mode, polarization].append(
            (acquisition_date, platform)
        )

    tracks = []
    for (direction, orbit, imaging_mode, polarization), scenes in sorted(
        acquisitions.items()
    ):
        dates, platforms = zip(*scenes)
        tracks.append(
            TrackSummary(
                direction=direction.title(),
                orbit=orbit,
                imaging_mode=imaging_mode,
                polarization=polarization,
                platforms=tuple(sorted(set(platforms))),
                count=len(dates),
                first_date=min(dates),
                last_date=max(dates),
            )
        )
    return tracks
