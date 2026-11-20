import json
from pathlib import Path
from zipfile import ZipFile

import pytest
import shapefile
from pyproj import CRS, Transformer
from shapely.geometry import shape

from s1cover import vector


def write_projected_shp(path: Path):
    to_meters = Transformer.from_crs(4326, 3857, always_xy=True)
    ring = [
        (-122.5, 37.7),
        (-122.5, 37.8),
        (-122.4, 37.8),
        (-122.4, 37.7),
        (-122.5, 37.7),
    ]
    with shapefile.Writer(str(path), shapeType=shapefile.POLYGON) as writer:
        writer.field("name", "C")
        writer.poly([[to_meters.transform(*point) for point in ring]])
        writer.record("local attribute")
    path.with_suffix(".prj").write_text(CRS.from_epsg(3857).to_wkt(), encoding="utf-8")


@pytest.mark.parametrize("zipped", [False, True])
def test_projected_shapefile_uses_prj_without_sending_attributes(tmp_path, zipped):
    shp = tmp_path / "window.shp"
    write_projected_shp(shp)
    source = shp
    if zipped:
        source = tmp_path / "window.zip"
        with ZipFile(source, "w") as archive:
            for component in tmp_path.glob("window.*"):
                if component.suffix != ".zip":
                    archive.write(component, f"nested/{component.name.upper()}")

    payload = json.loads(vector.geometry_payload(source))
    (feature,) = payload["features"]
    assert shape(feature["geometry"]).bounds == pytest.approx(
        (-122.5, 37.7, -122.4, 37.8)
    )
    assert feature["properties"] == {}


def test_kml_preserves_polygon_holes_and_strips_metadata(tmp_path):
    path = tmp_path / "public.kml"
    path.write_text(
        """<kml xmlns="http://www.opengis.net/kml/2.2"><Placemark>
        <name>Local label</name><Polygon><outerBoundaryIs><LinearRing>
        <coordinates>0,0,10 2,0,10 2,2,10 0,2,10 0,0,10</coordinates>
        </LinearRing></outerBoundaryIs><innerBoundaryIs><LinearRing>
        <coordinates>0.5,0.5 1,0.5 1,1 0.5,1 0.5,0.5</coordinates>
        </LinearRing></innerBoundaryIs></Polygon></Placemark></kml>""",
        encoding="utf-8",
    )
    payload = vector.geometry_payload(path)
    polygon = shape(json.loads(payload)["features"][0]["geometry"])
    assert polygon.area == 3.75
    assert len(polygon.interiors) == 1
    assert not polygon.has_z
    assert b"Local label" not in payload


def test_zip_rejects_ambiguous_input_without_extracting(tmp_path):
    path = tmp_path / "multiple.zip"
    with ZipFile(path, "w") as archive:
        archive.writestr("first.kml", "test")
        archive.writestr("second.geojson", "test")
    with pytest.raises(vector.VectorInputError, match="一个"):
        vector.geometry_payload(path)
    assert list(tmp_path.iterdir()) == [path]
