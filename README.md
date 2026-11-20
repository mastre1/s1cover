# s1cover

Summarize Sentinel-1 SLC scenes over a study area by pass direction and relative orbit.
`s1cover` searches the Alaska Satellite Facility (ASF) catalog and reports the scene
count and acquisition-date range for each ascending or descending track,
imaging mode and polarization combination. Each row lists the contributing satellites.

## Windows desktop

Open `s1cover-0.2.1-windows-x64.exe` on 64-bit Windows. It includes Python and
the GIS libraries and runs without installation. Enter a WGS84 bounding box or
choose an AOI file, then click **查询 ASF**. The **载入公开示例** button fills in
a public test area. Use **保存 Markdown** to export the track summary.

| Input | Requirements |
| --- | --- |
| Bounding box | West, south, east, north in WGS84 longitude and latitude degrees |
| GeoJSON | One valid WGS84 Polygon without holes, matching the CLI |
| SHP | Polygon shapefile. Put the matching `.prj` beside projected data. SHP without a `.prj` is read as WGS84. |
| KML | Inline polygon areas in WGS84, including MultiGeometry polygons and interior rings |
| ZIP | Exactly one SHP dataset, KML or GeoJSON. A SHP and its `.prj` must have the same stem and folder in the archive. |

For SHP, KML and ZIP, the app reads only the geometry locally, converts it to
WGS84 and sends a geometry-only request to NASA Earthdata CMR. The catalog
accepts up to 500 polygon features, 5,000 vertices and a 1 MB geometry payload.

**网络连接** offers three modes. **自动** uses environment proxy settings or
the manually configured Windows system proxy and retries directly if that proxy
fails. PAC and WPAD scripts are not evaluated.
**直连** ignores proxy settings. **手动代理** takes an HTTP(S) proxy such
as `127.0.0.1:PORT`. The app leaves system proxy settings alone and keeps
manual proxy details in memory for the current session.

Catalog metadata queries are anonymous and use HTTPS. The computer must be able
to reach `cmr.earthdata.nasa.gov` through the chosen network route.

## CLI installation

Use Python 3.10 or later. From the project root in PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

## Usage

This example searches the San Francisco Bay Area:

```powershell
.\.venv\Scripts\s1cover.exe check --bbox -122.5 37.7 -122.4 37.8 --start 2024-06-01 --end 2024-06-30
```

In an activated virtual environment, use `s1cover` on any platform:

```sh
s1cover check --geojson path/to/aoi.geojson --start 2024-06-01 --end 2024-06-30 --output output/aoi-report.md
```

- `--bbox` takes `west south east north` in WGS84 longitude and latitude degrees.
- `--geojson` accepts one valid WGS84 Polygon without holes, as a geometry, a Feature, or a single-Feature FeatureCollection. The ASF SDK can simplify polygon boundaries before querying the catalog.
- `--start` and `--end` are optional UTC dates in `YYYY-MM-DD` format. The query uses `00:00:00` on the start date and `23:59:59` on the end date. Use a finite range for large searches.
- The default maximum is 2,000 scenes. The report flags a possible truncation when the query hits that limit. Narrow the date range or set `--max-results` to a higher value.
- The report is printed to the terminal and saved to `output/s1cover-report.md` by default. Use `--output` to choose a new path. Existing files are protected from overwrite.

The query sends the AOI geometry to the ASF catalog. Catalog search requires an
internet connection. No account or credentials are needed. The report summarizes
catalog intersections. Full AOI coverage and InSAR pair suitability require further checks.

## Development

In the virtual environment, run the offline tests and lint checks:

```sh
python -m pip install -e '.[desktop]' pytest ruff
python -m pytest
ruff check src tests scripts
```

To build the portable executable, use 64-bit Windows Python with Tcl/Tk and run
these PowerShell commands from the project root:

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[desktop]' 'pyinstaller>=6.14,<7'
.\scripts\build-windows.ps1
```

The build writes the executable to `dist/` and prints its SHA-256. The `.exe`
can be attached to a GitHub Release as a standalone asset.

## License

MIT
