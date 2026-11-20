"""Windows desktop interface for querying the ASF catalog."""

import tkinter as tk
from datetime import date
from pathlib import Path
from queue import Empty, SimpleQueue
from threading import Thread
from tkinter import filedialog, ttk

import asf_search as asf

from .query import (
    CatalogUnavailable,
    Connection,
    QueryError,
    aoi_options,
    search_tracks,
)
from .report import render_report, write_report
from .vector import geometry_payload

BACKGROUND = "#EEF3F8"
INK = "#172B42"
MUTED = "#52677C"
ACCENT = "#006E70"
ERROR = "#A62B36"
FONT = "Microsoft YaHei UI"
NETWORK_MODES = {
    "自动（系统代理 / 直连）": "auto",
    "直连（忽略代理）": "direct",
    "手动代理": "proxy",
}


def _date(value: str) -> date | None:
    if not value:
        return None
    try:
        parsed = date.fromisoformat(value)
        if parsed.isoformat() == value:
            return parsed
    except ValueError:
        pass
    raise ValueError("日期格式为 YYYY-MM-DD，例如 2024-06-01。")


class Desktop:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("s1cover · Sentinel-1 覆盖查询")
        self.root.configure(background=BACKGROUND)
        self.root.geometry("1180x680")
        self.root.minsize(875, 620)

        self.bounds = [tk.StringVar() for _ in range(4)]
        self.source = tk.StringVar()
        self.start = tk.StringVar()
        self.end = tk.StringVar()
        self.limit = tk.StringVar(value="2000")
        self.mode = tk.StringVar(value=next(iter(NETWORK_MODES)))
        self.proxy = tk.StringVar()
        self.busy = False
        self.report = ""
        self.results = SimpleQueue()
        self._styles()

        header = tk.Frame(root, background=INK, padx=24, pady=16)
        header.pack(fill="x")
        tk.Label(
            header, text="s1cover", font=(FONT, 22, "bold"), bg=INK, fg="white"
        ).pack(anchor="w")
        tk.Label(
            header,
            text="Sentinel-1 SLC  ·  ASF 升降轨与影像景数查询",
            font=(FONT, 10),
            bg=INK,
            fg="#BDD8E6",
        ).pack(anchor="w")

        body = ttk.Frame(root, padding=(19, 18, 19, 12))
        body.pack(fill="both", expand=True)
        body.columnconfigure(1, weight=1)
        body.rowconfigure(0, weight=1)
        settings = ttk.Frame(body, style="Panel.TFrame", padding=17)
        settings.grid(row=0, column=0, sticky="nsew", padx=(0, 13))
        result = ttk.Frame(body, style="Panel.TFrame", padding=17)
        result.grid(row=0, column=1, sticky="nsew")
        self._inputs(settings)
        self._results(result)

        self.status = ttk.Label(
            root,
            text="查询公开目录无需登录。研究区几何会发送给 ASF 目录。",
            style="Status.TLabel",
            padding=(21, 1, 21, 13),
            wraplength=825,
        )
        self.status.pack(fill="x")
        self.root.bind("<Control-Return>", lambda _event: self._search())

    def _styles(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure(".", font=(FONT, 10), foreground=INK)
        style.configure("TFrame", background=BACKGROUND)
        style.configure("Panel.TFrame", background="white")
        style.configure("TLabel", background="white")
        style.configure("Title.TLabel", font=(FONT, 13, "bold"))
        style.configure("Hint.TLabel", font=(FONT, 9), foreground=MUTED)
        style.configure("Status.TLabel", foreground=MUTED, background=BACKGROUND)
        style.configure("Error.TLabel", foreground=ERROR, background=BACKGROUND)
        style.configure("TNotebook", background="white", borderwidth=0)
        style.configure("TNotebook.Tab", padding=(11, 5))
        style.map(
            "TNotebook.Tab",
            background=[("selected", "white"), ("!selected", "#E8EFF5")],
        )
        style.configure("TButton", padding=(10, 6))
        style.configure(
            "Accent.TButton",
            background=ACCENT,
            foreground="white",
            font=(FONT, 10, "bold"),
            borderwidth=0,
            padding=(12, 8),
        )
        style.map(
            "Accent.TButton",
            background=[
                ("disabled", "#729497"),
                ("pressed", "#005354"),
                ("active", "#008184"),
            ],
            foreground=[("disabled", "white"), ("!disabled", "white")],
        )
        style.configure("TEntry", padding=5)
        style.configure("TCombobox", padding=4)
        style.configure("Treeview", rowheight=30, borderwidth=0)
        style.configure(
            "Treeview.Heading",
            font=(FONT, 9, "bold"),
            padding=(7, 8),
            background="#E5EFF5",
        )
        style.map(
            "Treeview",
            background=[("selected", "#CBE8EC")],
            foreground=[("selected", INK)],
        )
        style.configure(
            "Horizontal.TProgressbar",
            thickness=3,
            background=ACCENT,
            troughcolor="#E5EFF5",
            borderwidth=0,
        )

    def _inputs(self, panel):
        panel.columnconfigure(0, weight=1)
        ttk.Label(panel, text="查询条件", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.tabs = ttk.Notebook(panel, width=318, height=116)
        self.tabs.grid(row=1, column=0, sticky="ew", pady=(9, 11))
        bounds_tab = ttk.Frame(self.tabs, style="Panel.TFrame", padding=(2, 8))
        file_tab = ttk.Frame(self.tabs, style="Panel.TFrame", padding=(2, 10))
        self.tabs.add(bounds_tab, text="经纬度范围")
        self.tabs.add(file_tab, text="导入文件")

        for column, label in enumerate(
            ("最小经度", "最小纬度", "最大经度", "最大纬度")
        ):
            bounds_tab.columnconfigure(column, weight=1)
            ttk.Label(bounds_tab, text=label).grid(
                row=0, column=column, sticky="w", padx=(0, 5)
            )
            ttk.Entry(bounds_tab, textvariable=self.bounds[column], width=8).grid(
                row=1, column=column, sticky="ew", padx=(0, 5), pady=(3, 5)
            )
        ttk.Label(
            bounds_tab, text="WGS84 · 西 / 南为下界，东 / 北为上界", style="Hint.TLabel"
        ).grid(row=2, column=0, columnspan=4, sticky="w")

        file_tab.columnconfigure(0, weight=1)
        ttk.Label(file_tab, text="支持 SHP、KML、ZIP、GeoJSON").grid(
            row=0, column=0, columnspan=2, sticky="w"
        )
        ttk.Entry(file_tab, textvariable=self.source, width=22).grid(
            row=1, column=0, sticky="ew", pady=(4, 0), padx=(0, 6)
        )
        ttk.Button(file_tab, text="浏览…", command=self._browse).grid(
            row=1, column=1, sticky="e", pady=(4, 0)
        )
        ttk.Label(file_tab, text="投影 SHP 需同名 .prj", style="Hint.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w", pady=(4, 0)
        )

        dates = ttk.Frame(panel, style="Panel.TFrame")
        dates.grid(row=2, column=0, sticky="ew")
        for column, (label, variable) in enumerate(
            (("起始日期（UTC）", self.start), ("截止日期（UTC）", self.end))
        ):
            dates.columnconfigure(column, weight=1)
            ttk.Label(dates, text=label).grid(row=0, column=column, sticky="w")
            ttk.Entry(dates, textvariable=variable, width=13).grid(
                row=1, column=column, sticky="ew", padx=(0, 6), pady=(3, 3)
            )
        ttk.Label(dates, text="YYYY-MM-DD，留空表示该端不限", style="Hint.TLabel").grid(
            row=2, column=0, columnspan=2, sticky="w"
        )

        network = ttk.Frame(panel, style="Panel.TFrame")
        network.grid(row=3, column=0, sticky="ew", pady=(12, 11))
        network.columnconfigure(0, weight=1)
        ttk.Label(network, text="网络连接").grid(row=0, column=0, sticky="w")
        ttk.Label(network, text="景数上限").grid(row=0, column=1, sticky="w")
        mode = ttk.Combobox(
            network,
            textvariable=self.mode,
            values=tuple(NETWORK_MODES),
            state="readonly",
            width=19,
        )
        mode.grid(row=1, column=0, sticky="ew", padx=(0, 8), pady=(3, 0))
        mode.bind("<<ComboboxSelected>>", self._connection_changed)
        ttk.Entry(network, textvariable=self.limit, width=7).grid(
            row=1, column=1, sticky="ew", pady=(3, 0)
        )
        self.proxy_label = ttk.Label(
            network, text="代理地址，例如 127.0.0.1:端口", style="Hint.TLabel"
        )
        self.proxy_label.grid(row=2, column=0, columnspan=2, sticky="w", pady=(6, 0))
        self.proxy_entry = ttk.Entry(network, textvariable=self.proxy)
        self.proxy_entry.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(3, 0))
        self._connection_changed()

        actions = ttk.Frame(panel, style="Panel.TFrame")
        actions.grid(row=4, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        self.search_button = ttk.Button(
            actions, text="查询 ASF", style="Accent.TButton", command=self._search
        )
        self.search_button.grid(row=0, column=0, sticky="ew", padx=(0, 7))
        ttk.Button(actions, text="载入公开示例", command=self._example).grid(
            row=0, column=1
        )

    def _results(self, panel):
        panel.columnconfigure(0, weight=1)
        panel.rowconfigure(2, weight=1)
        ttk.Label(panel, text="轨道汇总", style="Title.TLabel").grid(
            row=0, column=0, sticky="w"
        )
        self.save_button = ttk.Button(
            panel, text="保存 Markdown", command=self._save, state="disabled"
        )
        self.save_button.grid(row=0, column=1, sticky="e")
        self.summary = ttk.Label(
            panel,
            text="按轨道、成像模式和极化组合汇总相交影像。",
            style="Hint.TLabel",
            wraplength=410,
        )
        self.summary.grid(row=1, column=0, columnspan=2, sticky="w", pady=(7, 12))

        columns = (
            "direction",
            "orbit",
            "mode",
            "polarization",
            "platform",
            "scenes",
            "first",
            "last",
        )
        self.table = ttk.Treeview(
            panel, columns=columns, show="headings", selectmode="browse", height=9
        )
        labels = (
            "方向",
            "相对轨道",
            "成像模式",
            "极化组合",
            "卫星平台",
            "景数",
            "最早日期 (UTC)",
            "最晚日期 (UTC)",
        )
        for column, label, width in zip(
            columns, labels, (56, 76, 78, 76, 110, 52, 108, 108)
        ):
            self.table.heading(column, text=label)
            self.table.column(column, width=width, minwidth=width - 6, anchor="center")
        self.table.tag_configure("alt", background="#F1F7FA")
        self.table.grid(row=2, column=0, columnspan=2, sticky="nsew")
        vertical = ttk.Scrollbar(panel, orient="vertical", command=self.table.yview)
        vertical.grid(row=2, column=2, sticky="ns")
        horizontal = ttk.Scrollbar(panel, orient="horizontal", command=self.table.xview)
        horizontal.grid(row=3, column=0, columnspan=2, sticky="ew")
        self.table.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
        self.progress = ttk.Progressbar(panel, mode="indeterminate")
        self.progress.grid(row=4, column=0, columnspan=3, sticky="ew", pady=(9, 0))
        self.progress.grid_remove()

    def _connection_changed(self, _event=None):
        for widget in (self.proxy_label, self.proxy_entry):
            if NETWORK_MODES[self.mode.get()] == "proxy":
                widget.grid()
            else:
                widget.grid_remove()

    def _browse(self):
        path = filedialog.askopenfilename(
            parent=self.root,
            title="选择研究区文件",
            filetypes=[
                ("矢量文件", "*.shp *.kml *.zip *.geojson"),
                ("所有文件", "*.*"),
            ],
        )
        if path:
            self.source.set(path)

    def _example(self):
        self.tabs.select(0)
        for field, value in zip(self.bounds, ("-122.5", "37.7", "-122.4", "37.8")):
            field.set(value)
        self.start.set("2024-06-01")
        self.end.set("2024-06-30")

    def _set_status(self, message, error=False):
        self.status.configure(
            text=message, style="Error.TLabel" if error else "Status.TLabel"
        )

    def _search(self):
        if self.busy:
            return
        try:
            start, end = _date(self.start.get().strip()), _date(self.end.get().strip())
            if start and end and start > end:
                raise ValueError("起始日期不能晚于截止日期。")
            limit = self.limit.get().strip()
            if not limit.isdecimal() or int(limit) < 1:
                raise ValueError("景数上限须为正整数。")
            connection = Connection(NETWORK_MODES[self.mode.get()], self.proxy.get())
            bounds = None
            path = None
            if self.tabs.index("current") == 0:
                try:
                    bounds = [float(field.get()) for field in self.bounds]
                except ValueError as exc:
                    raise ValueError("请填写西、南、东、北四个十进制度数。") from exc
            else:
                path_text = self.source.get().strip().strip('"')
                if not path_text:
                    raise ValueError("请先选择研究区文件。")
                path = Path(path_text)
        except ValueError as exc:
            self._set_status(str(exc), error=True)
            return

        self.busy = True
        self.report = ""
        self.table.delete(*self.table.get_children())
        self.search_button.state(["disabled"])
        self.save_button.state(["disabled"])
        self.summary.configure(text="正在读取研究区并查询目录…")
        self._set_status("正在查询，可在完成后保存报告。")
        self.progress.grid()
        self.progress.start(12)
        Thread(
            target=self._worker,
            args=(bounds, path, start, end, int(limit), connection),
            daemon=True,
        ).start()
        self.root.after(100, self._poll)

    def _worker(self, bounds, path, start, end, limit, connection):
        try:
            geometry = None
            if path is None or path.suffix.lower() == ".geojson":
                aoi = aoi_options(bounds, path)
            else:
                geometry = geometry_payload(path)
                aoi = asf.ASFSearchOptions()
            tracks = search_tracks(
                aoi,
                start=start,
                end=end,
                max_results=limit,
                connection=connection,
                geometry=geometry,
            )
            report = render_report(tracks, start=start, end=end, max_results=limit)
            self.results.put((tracks, report, limit, ""))
        except CatalogUnavailable:
            self.results.put(
                (
                    [],
                    "",
                    limit,
                    "无法连接 ASF 目录。请检查网络，或切换直连 / 手动代理后重试。",
                )
            )
        except (ValueError, QueryError) as exc:
            self.results.put(([], "", limit, str(exc)))
        except Exception as exc:  # noqa: BLE001 - Always release the GUI's busy state.
            self.results.put(([], "", limit, f"查询失败（{type(exc).__name__}）。"))

    def _poll(self):
        try:
            tracks, self.report, limit, error = self.results.get_nowait()
        except Empty:
            self.root.after(100, self._poll)
            return
        self.busy = False
        self.progress.stop()
        self.progress.grid_remove()
        self.search_button.state(["!disabled"])
        if error:
            self.summary.configure(text="查询未完成")
            self._set_status(error, error=True)
            return

        count = sum(track.count for track in tracks)
        orbit_count = len({(track.direction, track.orbit) for track in tracks})
        self.summary.configure(
            text=f"{count:,} 景影像 · {orbit_count:,} 条轨道"
            if count
            else "查询完成，未找到相交影像。"
        )
        for index, track in enumerate(tracks):
            direction = "升轨" if track.direction == "Ascending" else "降轨"
            platforms = ", ".join(
                platform.replace("Sentinel-", "S") or "未知"
                for platform in track.platforms
            )
            self.table.insert(
                "",
                "end",
                values=(
                    direction,
                    track.orbit,
                    track.imaging_mode or "未知",
                    track.polarization or "未知",
                    platforms,
                    track.count,
                    track.first_date,
                    track.last_date,
                ),
                tags=("alt",) if index % 2 else (),
            )
        self.save_button.state(["!disabled"])
        self._set_status(
            "达到景数上限，结果可能截断。可缩短日期范围或提高上限。"
            if count >= limit
            else "查询完成。景数统计基于目录相交结果。"
        )

    def _save(self):
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title="保存 Markdown 报告",
            initialfile="s1cover-report.md",
            defaultextension=".md",
            filetypes=[("Markdown", "*.md")],
            confirmoverwrite=False,
        )
        if not path:
            return
        try:
            write_report(Path(path), self.report)
        except FileExistsError:
            self._set_status("文件已存在，请用新的文件名保存。", error=True)
        except OSError:
            self._set_status("报告写入失败，请选择有写入权限的目录。", error=True)
        else:
            self._set_status(f"报告已保存到 {path}")


def main():
    root = tk.Tk()
    Desktop(root)
    root.mainloop()
