"""Read desktop AOI formats and serialize only WGS84 polygon geometry."""

import json
import struct
from pathlib import Path, PurePosixPath
from xml.etree.ElementTree import ParseError
from zipfile import BadZipFile, ZipFile

import shapefile
from defusedxml import ElementTree
from defusedxml.common import DefusedXmlException
from pyproj import CRS, Transformer
from pyproj.exceptions import ProjError
from shapely import force_2d, from_geojson, get_num_coordinates, transform
from shapely.errors import GEOSException
from shapely.geometry import GeometryCollection, MultiPolygon, Polygon, mapping, shape
from shapely.geometry.polygon import orient


class VectorInputError(ValueError):
    """An AOI file could not be read as survey polygons."""


ARCHIVE_FORMATS = {".shp", ".kml", ".geojson"}
MAX_INPUT_BYTES = 32 * 1024 * 1024


def _read_shp(stream, prj: bytes | None):
    projection = None
    if prj is not None:
        source_crs = CRS.from_wkt(prj.decode("utf-8-sig").strip())
        projection = Transformer.from_crs(source_crs, "EPSG:4326", always_xy=True)
    with shapefile.Reader(shp=stream) as reader:
        for record in reader.iterShapes():
            if record.shapeType == shapefile.NULL:
                continue
            if record.shapeType not in {
                shapefile.POLYGON,
                shapefile.POLYGONZ,
                shapefile.POLYGONM,
            }:
                raise VectorInputError("SHP 必须包含面几何。")
            polygon = shape(record.__geo_interface__)
            yield (
                transform(polygon, projection.transform, interleaved=False)
                if projection
                else polygon
            )


def _read_kml(stream):
    def ring(boundary):
        coordinates = boundary.findtext("{*}LinearRing/{*}coordinates", default="")
        return [
            tuple(map(float, point.split(",")[:2])) for point in coordinates.split()
        ]

    for element in ElementTree.parse(stream).getroot().iterfind(".//{*}Polygon"):
        boundary = element.find("{*}outerBoundaryIs")
        if boundary is None:
            raise VectorInputError("KML 面缺少外边界。")
        holes = [ring(inner) for inner in element.findall("{*}innerBoundaryIs")]
        yield Polygon(ring(boundary), holes)


def _polygons(geometry):
    if isinstance(geometry, Polygon):
        yield geometry
    elif isinstance(geometry, (MultiPolygon, GeometryCollection)):
        for part in geometry.geoms:
            yield from _polygons(part)
    else:
        raise VectorInputError("文件必须包含 Polygon 或 MultiPolygon 面几何。")


def _read_geometry(suffix, stream, prj=None):
    if suffix == ".shp":
        return list(_read_shp(stream, prj))
    if suffix == ".kml":
        return list(_read_kml(stream))
    return list(_polygons(from_geojson(stream.read().decode("utf-8-sig"))))


def _read_archive(path):
    with ZipFile(path) as archive:
        names = {}
        for member in archive.infolist():
            if member.is_dir() or "__MACOSX" in PurePosixPath(member.filename).parts:
                continue
            key = member.filename.casefold()
            if PurePosixPath(key).suffix not in ARCHIVE_FORMATS | {".prj"}:
                continue
            if key in names:
                raise VectorInputError("ZIP 中包含重复的文件名。")
            names[key] = member
        candidates = [
            key for key in names if PurePosixPath(key).suffix in ARCHIVE_FORMATS
        ]
        if len(candidates) != 1:
            raise VectorInputError("ZIP 必须包含一个 SHP、KML 或 GeoJSON 数据集。")
        key = candidates[0]
        suffix = PurePosixPath(key).suffix
        prj = (
            names.get(str(PurePosixPath(key).with_suffix(".prj")))
            if suffix == ".shp"
            else None
        )
        if names[key].file_size > MAX_INPUT_BYTES or (
            prj and prj.file_size > MAX_INPUT_BYTES
        ):
            raise VectorInputError("ZIP 内的单个矢量文件超过 32 MiB。")
        with archive.open(names[key]) as stream:
            return _read_geometry(suffix, stream, archive.read(prj) if prj else None)


def geometry_payload(path: Path) -> bytes:
    suffix = path.suffix.lower()
    if suffix not in ARCHIVE_FORMATS | {".zip"}:
        raise VectorInputError("请选择 SHP、KML、ZIP 或 GeoJSON 文件。")
    try:
        if suffix == ".zip":
            geometries = _read_archive(path)
        else:
            if path.stat().st_size > MAX_INPUT_BYTES:
                raise VectorInputError("矢量文件超过 32 MiB。")
            prj = path.with_suffix(".prj")
            with path.open("rb") as stream:
                geometries = _read_geometry(
                    suffix,
                    stream,
                    prj.read_bytes() if suffix == ".shp" and prj.exists() else None,
                )
        polygons = [
            orient(force_2d(polygon)) for g in geometries for polygon in _polygons(g)
        ]
    except VectorInputError:
        raise
    except (
        OSError,
        ValueError,
        ParseError,
        DefusedXmlException,
        BadZipFile,
        RuntimeError,
        GEOSException,
        shapefile.ShapefileException,
        ProjError,
        struct.error,
    ) as exc:
        raise VectorInputError("无法读取矢量几何或坐标系。请检查文件和 .prj。") from exc

    if not polygons:
        raise VectorInputError("文件中没有面几何。")
    if (
        len(polygons) > 500
        or sum(get_num_coordinates(polygon) for polygon in polygons) > 5000
    ):
        raise VectorInputError(
            "目录限制为 500 个面和 5000 个顶点。请先在 GIS 中简化或分批查询。"
        )
    for polygon in polygons:
        if polygon.is_empty or not polygon.is_valid:
            raise VectorInputError("文件含有无效面几何。请先在 GIS 中修复。")
        west, south, east, north = polygon.bounds
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise VectorInputError(
                "坐标超出 WGS84 经纬度范围。投影 SHP 需要同名 .prj 文件。"
            )
    payload = json.dumps(
        {
            "type": "FeatureCollection",
            "features": [
                {"type": "Feature", "geometry": mapping(polygon), "properties": {}}
                for polygon in polygons
            ],
        },
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    if len(payload) > 1_000_000:
        raise VectorInputError("转换后的几何大于目录的 1 MB 查询上限。")
    return payload
