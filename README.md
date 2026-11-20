# s1cover

s1cover 通过阿拉斯加卫星设施（ASF）目录查询与研究区相交的 Sentinel-1 SLC 影像。结果按升降轨方向、相对轨道号、成像模式和极化方式分组，列出各组的卫星、影像景数和首末采集日期（UTC）。

## Windows 便携版

[下载 s1cover 0.2.1（Windows x64）](https://github.com/mastre1/s1cover/releases/download/v0.2.1/s1cover-0.2.1-windows-x64.exe)

1. 在 64 位 Windows 上双击下载的 `.exe`。程序已包含 Python 和所需组件，开箱即用。
2. 输入经纬度范围或选择研究区（AOI）文件。可以点击 **载入公开示例** 填入一组测试参数。
3. 设置查询日期范围，点击 **查询 ASF**。查询完成后，点击 **保存 Markdown** 导出统计报告。

| 研究区输入 | 格式要求 |
| --- | --- |
| 经纬度范围（BBox） | 按西界经度、南界纬度、东界经度、北界纬度的顺序填写 WGS84 坐标，单位为度。 |
| GeoJSON | 一个有效的 WGS84 Polygon，且无内环。 |
| SHP | 面状 Shapefile。使用投影坐标时，请将同名 `.prj` 放在同一目录。缺少 `.prj` 时按 WGS84 读取。 |
| KML | 使用 WGS84 坐标的内嵌面要素，支持 `MultiGeometry` 中的面及内环。 |
| ZIP | 仅包含一套 SHP 数据或一个 KML、GeoJSON 文件。SHP 和对应的 `.prj` 须同名并位于压缩包内同一目录。 |

SHP、KML 和 ZIP 在本机读取并转换为 WGS84。程序只向 NASA Earthdata CMR 发送查询所需的几何。此类查询最多接受 500 个面、5,000 个顶点和 1 MB 的几何请求。

### 网络连接

目录元数据查询通过 HTTPS 匿名进行，无需 ASF 或 Earthdata 账号。所选网络方式需要能访问 `cmr.earthdata.nasa.gov`。

- **自动**：使用环境变量或 Windows 中手动配置的系统代理，代理连接失败后尝试直连。仅识别显式代理地址。
- **直连**：跳过本机代理配置，直接访问查询服务。
- **手动代理**：填写 HTTP(S) 代理地址，例如 `127.0.0.1:端口`。地址只在当前会话中使用。

## 命令行

命令行版需要 Python 3.10 或更高版本。在项目目录下通过 PowerShell 安装。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e .
```

用经纬度范围查询旧金山湾区的公开示例。

```powershell
.\.venv\Scripts\s1cover.exe check --bbox -122.5 37.7 -122.4 37.8 --start 2024-06-01 --end 2024-06-30
```

激活虚拟环境后，可直接用 `s1cover` 查询 GeoJSON 并指定报告路径。

```sh
s1cover check --geojson path/to/aoi.geojson --start 2024-06-01 --end 2024-06-30 --output output/aoi-report.md
```

- `--bbox` 的参数顺序为西、南、东、北，使用 WGS84 经纬度。
- `--geojson` 接受一个有效、无内环的 WGS84 Polygon。文件可为几何对象、Feature 或只含一个 Feature 的 FeatureCollection。ASF 查询库在提交查询前可能简化多边形边界。
- `--start` 和 `--end` 均可省略，格式为 `YYYY-MM-DD`。时间按 UTC 计算，包含开始日 `00:00:00` 到结束日 `23:59:59`。范围较大的查询建议限定日期。
- 默认最多返回 2,000 景。达到上限时，报告会提示结果可能被截断。可缩小日期范围，或用 `--max-results` 提高上限。
- 报告输出到终端，并默认保存到 `output/s1cover-report.md`。可用 `--output` 指定路径，程序会保留已有同名文件。

目录结果按影像范围与研究区相交统计。评估影像是否完整覆盖研究区，或判断影像是否适合组成 InSAR 干涉对，需要进一步检查。

## 开发与打包

在虚拟环境中安装开发依赖，运行离线测试和代码检查。

```sh
python -m pip install -e '.[desktop]' pytest ruff
python -m pytest
ruff check src tests scripts
```

使用带 Tcl/Tk 的 64 位 Windows Python，在项目根目录执行以下 PowerShell 命令。

```powershell
.\.venv\Scripts\python.exe -m pip install -e '.[desktop]' 'pyinstaller>=6.14,<7'
.\scripts\build-windows.ps1
```

构建脚本将便携 EXE 输出到 `dist/`，并打印该文件的 SHA-256。

## 贡献者

- [mastre1](https://github.com/mastre1) · 项目维护
- [Codex（OpenAI）](https://github.com/codex) · 协助实现、打包和编写文档

## 许可证

[MIT](LICENSE)
