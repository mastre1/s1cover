"""Render and save the track summary as Markdown."""

from datetime import date
from pathlib import Path

from .query import TrackSummary


def render_report(
    tracks: list[TrackSummary],
    *,
    start: date | None,
    end: date | None,
    max_results: int,
) -> str:
    scene_count = sum(track.count for track in tracks)
    lines = [
        "# Sentinel-1 SLC track summary",
        "",
        "- Source: ASF catalog spatial intersection search",
        f"- Query dates (UTC): {start or 'unbounded'} to {end or 'unbounded'}",
        f"- Returned scenes: {scene_count}",
        "",
    ]
    if scene_count >= max_results:
        lines.extend(
            [
                f"**Warning:** The query reached the {max_results}-scene limit. Results may be truncated.",
                "",
            ]
        )
    if not tracks:
        lines.append("No matching scenes.")
    else:
        lines.extend(
            [
                "| Direction | Relative orbit | Imaging mode | Polarization | Satellite(s) | Scenes | First date (UTC) | Last date (UTC) |",
                "| --- | ---: | --- | --- | --- | ---: | --- | --- |",
            ]
        )
        for track in tracks:
            platforms = ", ".join(platform or "Unknown" for platform in track.platforms)
            lines.append(
                f"| {track.direction} | {track.orbit} | {track.imaging_mode or 'Unknown'} | "
                f"{track.polarization or 'Unknown'} | {platforms} | {track.count} | "
                f"{track.first_date} | {track.last_date} |"
            )
    return "\n".join(lines) + "\n"


def write_report(path: Path, report: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as file:
        file.write(report)
