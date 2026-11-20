"""Exercise the CLI with the ASF catalog call replaced by fixed responses."""

from types import SimpleNamespace

import asf_search as asf
import pytest
from shapely import from_wkt

from s1cover.cli import build_parser, main

BBOX = ["check", "--bbox", "-122.5", "37.7", "-122.4", "37.8"]


class CatalogResults(list):
    def raise_if_incomplete(self):
        pass


def scene(
    direction, track, start, *, mode="IW", polarization="VV+VH", platform="Sentinel-1A"
):
    return SimpleNamespace(
        properties={
            "flightDirection": direction,
            "pathNumber": track,
            "startTime": start,
            "beamModeType": mode,
            "polarization": polarization,
            "platform": platform,
        }
    )


def test_parser_accepts_bbox():
    args = build_parser().parse_args(BBOX)
    assert args.bbox == [-122.5, 37.7, -122.4, 37.8]


def test_parser_rejects_missing_aoi():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args(["check"])
    assert exc.value.code == 2


def test_parser_rejects_two_aois():
    with pytest.raises(SystemExit) as exc:
        build_parser().parse_args([*BBOX, "--geojson", "aoi.geojson"])
    assert exc.value.code == 2


def test_bbox_report_groups_tracks_and_records_query_limit(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.chdir(tmp_path)
    search_args = {}

    def search(**kwargs):
        search_args.update(kwargs)
        return CatalogResults(
            [
                scene("ASCENDING", 42, "2024-06-20T02:31:00Z", platform="Sentinel-1C"),
                scene("DESCENDING", 42, "2024-06-15T15:00:00Z"),
                scene("ASCENDING", 42, "2024-06-08T02:31:00Z"),
            ]
        )

    monkeypatch.setattr(asf, "search", search)
    small_bbox = ["check", "--bbox", "-122.5", "37.7", "-122.4999", "37.7001"]
    assert (
        main(
            [
                *small_bbox,
                "--start",
                "2024-06-01",
                "--end",
                "2024-06-30",
                "--max-results",
                "3",
            ]
        )
        == 0
    )

    assert search_args["opts"].bbox == [-122.5, 37.7, -122.4999, 37.7001]
    assert search_args["opts"].intersectsWith is None
    assert search_args["dataset"] == asf.DATASET.SENTINEL1
    assert search_args["processingLevel"] == asf.PRODUCT_TYPE.SLC
    assert search_args["start"] == "2024-06-01T00:00:00Z"
    assert search_args["end"] == "2024-06-30T23:59:59Z"
    assert search_args["maxResults"] == 3

    report = (tmp_path / "output/s1cover-report.md").read_text(encoding="utf-8")
    assert (
        "| Ascending | 42 | IW | VV+VH | Sentinel-1A, Sentinel-1C | 2 | 2024-06-08 | 2024-06-20 |"
        in report
    )
    assert (
        "| Descending | 42 | IW | VV+VH | Sentinel-1A | 1 | 2024-06-15 | 2024-06-15 |"
        in report
    )
    assert "2024-06-01" in report and "2024-06-30" in report
    assert "may be truncated" in report
    assert "may be truncated" in capsys.readouterr().out


def test_report_separates_imaging_mode_and_polarization_combinations(
    monkeypatch, tmp_path
):
    rows = CatalogResults(
        [
            scene("ASCENDING", 42, "2024-06-01T10:00:00Z"),
            scene("ASCENDING", 42, "2024-06-02T10:00:00Z", polarization="VV"),
            scene("ASCENDING", 42, "2024-06-03T10:00:00Z", mode="EW"),
            scene(
                "ASCENDING",
                42,
                "2024-06-04T10:00:00Z",
                mode=None,
                polarization=None,
                platform=None,
            ),
        ]
    )
    monkeypatch.setattr(asf, "search", lambda **kwargs: rows)
    output = tmp_path / "report.md"
    assert main([*BBOX, "--output", str(output)]) == 0

    report = output.read_text(encoding="utf-8")
    assert "Returned scenes: 4" in report
    assert (
        "| Ascending | 42 | IW | VV+VH | Sentinel-1A | 1 | 2024-06-01 | 2024-06-01 |"
        in report
    )
    assert (
        "| Ascending | 42 | IW | VV | Sentinel-1A | 1 | 2024-06-02 | 2024-06-02 |"
        in report
    )
    assert (
        "| Ascending | 42 | EW | VV+VH | Sentinel-1A | 1 | 2024-06-03 | 2024-06-03 |"
        in report
    )
    assert (
        "| Ascending | 42 | Unknown | Unknown | Unknown | 1 | 2024-06-04 | 2024-06-04 |"
        in report
    )


def test_geojson_empty_result(monkeypatch, tmp_path):
    aoi = tmp_path / "aoi.geojson"
    aoi.write_text(
        """{"type":"Feature","geometry":{"type":"Polygon","coordinates":[
        [[0, 0], [2, 0], [0, 1], [0, 0]]]},"properties":{}}""",
        encoding="utf-8",
    )
    areas = []

    def search(**kwargs):
        areas.append(from_wkt(kwargs["opts"].intersectsWith).area)
        return CatalogResults()

    monkeypatch.setattr(asf, "search", search)
    output = tmp_path / "result.md"
    assert main(["check", "--geojson", str(aoi), "--output", str(output)]) == 0
    assert areas == [1.0]
    assert "No matching scenes" in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "args",
    [
        ["check", "--bbox", "2", "0", "1", "1"],
        [*BBOX, "--start", "2024-07-01", "--end", "2024-06-30"],
    ],
)
def test_invalid_input_stops_before_query(monkeypatch, args):
    def search(**kwargs):
        pytest.fail("Invalid input reached the catalog")

    monkeypatch.setattr(asf, "search", search)
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code == 2


def test_incomplete_query_does_not_write_report(monkeypatch, tmp_path, capsys):
    class IncompleteResults(CatalogResults):
        def raise_if_incomplete(self):
            raise asf.exceptions.ASFSearchError("Incomplete results")

    monkeypatch.setattr(asf, "search", lambda **kwargs: IncompleteResults())
    output = tmp_path / "result.md"
    assert main([*BBOX, "--output", str(output)]) == 1
    assert not output.exists()
    assert "ASF query failed" in capsys.readouterr().err


def test_existing_report_is_preserved(monkeypatch, tmp_path, capsys):
    def search(**kwargs):
        pytest.fail("The catalog was queried before checking the output path")

    monkeypatch.setattr(asf, "search", search)
    output = tmp_path / "result.md"
    output.write_text("Previous report\n", encoding="utf-8")
    assert main([*BBOX, "--output", str(output)]) == 1
    assert output.read_text(encoding="utf-8") == "Previous report\n"
    assert "already exists" in capsys.readouterr().err
