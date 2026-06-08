#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any


ROOT = pathlib.Path(__file__).resolve().parents[1]
DEFAULT_THEME = "vivado-dark"
THEMES: dict[str, dict[str, str]] = {
    "wavedrom": {},
    "vivado-dark": {
        "bg": "#0b1117",
        "panel": "#13202d",
        "panel2": "#193243",
        "panel3": "#20334b",
        "grid": "#29414f",
        "grid2": "#365062",
        "text": "#dbe7f3",
        "info": "#8ccfff",
        "signal": "#6df2a4",
        "signal2": "#3aa36a",
        "muted": "#7a8797",
        "success": "#59d98e",
        "warning": "#f6c65b",
        "path": "#8ff7b8",
    },
    "vivado-light": {
        "bg": "#ffffff",
        "panel": "#f4f7fb",
        "panel2": "#edf2f8",
        "panel3": "#e6edf4",
        "grid": "#bccad8",
        "grid2": "#90a4b5",
        "text": "#1f2a37",
        "info": "#005bbb",
        "signal": "#008a4e",
        "signal2": "#1d6f42",
        "muted": "#607182",
        "success": "#1c8f5a",
        "warning": "#b36b00",
        "path": "#005bbb",
    },
    "report-light": {
        "bg": "#ffffff",
        "panel": "#f7f9fc",
        "panel2": "#edf4ff",
        "panel3": "#eef7f1",
        "grid": "#d6dee8",
        "grid2": "#98a8b8",
        "text": "#172033",
        "info": "#174ea6",
        "signal": "#167a4a",
        "signal2": "#2f6f4e",
        "muted": "#64748b",
        "success": "#168251",
        "warning": "#9a5b00",
        "path": "#0b65c2",
    },
    "report-dark": {
        "bg": "#111827",
        "panel": "#1f2937",
        "panel2": "#243244",
        "panel3": "#2b3748",
        "grid": "#465568",
        "grid2": "#667085",
        "text": "#f3f4f6",
        "info": "#93c5fd",
        "signal": "#7dd3fc",
        "signal2": "#38bdf8",
        "muted": "#a0aec0",
        "success": "#86efac",
        "warning": "#fde68a",
        "path": "#bfdbfe",
    },
    "monochrome": {
        "bg": "#ffffff",
        "panel": "#f5f5f5",
        "panel2": "#eeeeee",
        "panel3": "#e5e5e5",
        "grid": "#d0d0d0",
        "grid2": "#8c8c8c",
        "text": "#111111",
        "info": "#111111",
        "signal": "#111111",
        "signal2": "#444444",
        "muted": "#555555",
        "success": "#111111",
        "warning": "#111111",
        "path": "#111111",
    },
}
SIGNAL_KINDS = {"auto", "bit", "bus", "clock"}
VALUE_FORMATS = {"hex", "bin", "dec", "raw"}
TIME_UNIT_SECONDS = {
    "fs": 1e-15,
    "ps": 1e-12,
    "ns": 1e-9,
    "us": 1e-6,
    "ms": 1e-3,
    "s": 1.0,
}

WAVEDROM_CLI = shutil.which("wavedrom-cli")
if WAVEDROM_CLI is None:
    for candidate in pathlib.Path.home().glob(".npm/_npx/*/node_modules/wavedrom-cli/wavedrom-cli.js"):
        WAVEDROM_CLI = str(candidate)
        break


def _wavedrom_cmd() -> list[str]:
    if WAVEDROM_CLI:
        return ["node", WAVEDROM_CLI]
    return ["npx", "--yes", "wavedrom-cli"]


@dataclass(frozen=True)
class SignalSpec:
    label: str
    path: str
    kind: str = "auto"


@dataclass(frozen=True)
class WaveJob:
    vcd: pathlib.Path
    output: pathlib.Path
    signals: list[SignalSpec]
    title: str | None = None
    head_text: str | None = None
    start: int | None = None
    end: int | None = None
    samples: int = 24
    hscale: int = 2
    theme: str = DEFAULT_THEME
    formats: tuple[str, ...] = ("png",)
    value_format: str = "hex"
    max_value_chars: int = 6
    show_data_labels: bool = True
    png_scale: float = 1.0
    png_width: int | None = None
    png_height: int | None = None
    dpi: float | None = None
    background: str | None = None
    theme_overrides: dict[str, str] = field(default_factory=dict)


def parse_vcd(path: pathlib.Path) -> tuple[str, dict[str, list[tuple[int, str]]]]:
    timescale = "1ns"
    timescale_lines: list[str] | None = None
    scopes: list[str] = []
    ids: dict[str, list[str]] = {}
    widths: dict[str, int] = {}
    changes: dict[str, list[tuple[int, str]]] = {}
    current_time = 0

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            if timescale_lines is not None:
                if "$end" in line:
                    before_end = line.split("$end", 1)[0].strip()
                    if before_end:
                        timescale_lines.append(before_end)
                    parts = " ".join(timescale_lines).split()
                    timescale = "".join(parts) if parts else timescale
                    timescale_lines = None
                else:
                    timescale_lines.append(line)
                continue
            if line.startswith("$timescale"):
                rest = line.replace("$timescale", "", 1).strip()
                if "$end" in rest:
                    parts = rest.replace("$end", "").strip().split()
                    timescale = "".join(parts) if parts else timescale
                else:
                    timescale_lines = [rest] if rest else []
                continue
            if line.startswith("$scope"):
                scopes.append(line.split()[2])
                continue
            if line.startswith("$upscope"):
                if scopes:
                    scopes.pop()
                continue
            if line.startswith("$var"):
                parts = line.split()
                width = int(parts[2])
                ident = parts[3]
                ref = parts[4]
                if len(parts) > 5 and parts[5] != "$end":
                    ref += parts[5]
                full = ".".join(scopes + [ref])
                ids.setdefault(ident, []).append(full)
                widths[full] = width
                changes.setdefault(full, [])
                continue
            if line == "$enddefinitions $end":
                continue
            if line.startswith("#"):
                current_time = int(line[1:])
                continue
            if line[0] in "01xzXZ":
                ident = line[1:]
                for full in ids.get(ident, []):
                    changes[full].append((current_time, line[0].lower()))
                continue
            if line[0] in "br":
                parts = line.split()
                if len(parts) == 2 and parts[1] in ids:
                    value = parts[0][1:].lower()
                    for full in ids[parts[1]]:
                        changes[full].append((current_time, value.zfill(widths.get(full, len(value)))))

    return timescale, changes


def find_signal(changes: dict[str, list[tuple[int, str]]], wanted: str) -> list[tuple[int, str]]:
    if wanted in changes:
        return changes[wanted]
    suffix = "." + wanted.split(".", 1)[-1]
    for name, series in changes.items():
        if name.endswith(suffix):
            return series
    return []


def _is_bus_like(spec: SignalSpec) -> bool:
    if spec.kind == "bus":
        return True
    if spec.kind in {"bit", "clock"}:
        return False
    return "[" in spec.path or spec.label.lower() in {
        "timer",
        "led",
        "key_in",
        "led_r",
        "led_r1",
        "q_reg",
        "rgb",
        "tmds_data_p",
    }


def _is_clock_like(spec: SignalSpec) -> bool:
    if spec.kind in {"bit", "bus"}:
        return False
    return spec.kind == "clock" or "clk" in spec.label.lower() or "clk" in spec.path.lower()


def _signal_key(path: str) -> str:
    return path.split(".")[-1].split("[", 1)[0]


def _sample_events(events: list[tuple[int, str]], start: int, end: int, slots: int) -> list[str]:
    if not events:
        return ["x"] * max(1, slots + 1)
    sampled: list[str] = []
    idx = 0
    current = events[0][1]
    while idx < len(events) and events[idx][0] <= start:
        current = events[idx][1]
        idx += 1
    step = max(1, (end - start + max(1, slots) - 1) // max(1, slots))
    for slot in range(max(1, slots) + 1):
        boundary = start + slot * step
        while idx < len(events) and events[idx][0] <= boundary:
            current = events[idx][1]
            idx += 1
        sampled.append(current)
    return sampled


def _truncate_text(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= 2:
        return text[:max_chars]
    return text[: max_chars - 2] + ".."


def _normalize_value(value: str, bus_hint: bool, value_format: str = "hex", max_value_chars: int = 6) -> str:
    if re.fullmatch(r"[01xz]", value):
        return value
    if not bus_hint and re.fullmatch(r"[01]", value):
        return value
    if re.fullmatch(r"[01xz]+", value):
        if "x" in value or "z" in value:
            return "x" if "x" in value else "z"
        number = int(value, 2)
        if value_format == "bin":
            text = "0b" + value
        elif value_format == "dec":
            text = str(number)
        elif value_format == "raw":
            text = value
        else:
            text = f"0x{number:x}"
        return _truncate_text(text, max_value_chars)
    return value


def _to_wavedrom_lane(
    label: str,
    samples: list[str],
    bus_hint: bool,
    clock_hint: bool,
    value_format: str = "hex",
    max_value_chars: int = 6,
    show_data_labels: bool = True,
) -> dict[str, object]:
    if clock_hint:
        return {"name": label, "wave": "p" + "." * max(0, len(samples) - 1)}

    wave_chars: list[str] = []
    data_labels: list[str] = []
    previous: str | None = None
    for value in samples:
        normalized = _normalize_value(value, bus_hint, value_format, max_value_chars)
        if bus_hint or len(normalized) > 1:
            if previous == normalized:
                wave_chars.append(".")
            elif normalized in {"x", "z"}:
                wave_chars.append(normalized)
            else:
                wave_chars.append("=")
                data_labels.append(normalized)
        else:
            bit = normalized if normalized in {"0", "1", "x", "z"} else "x"
            wave_chars.append("." if previous == bit else bit)
        previous = normalized
    lane: dict[str, object] = {"name": label, "wave": "".join(wave_chars)}
    if data_labels and show_data_labels:
        lane["data"] = data_labels
    return lane


def _head_text(job: WaveJob, start: int, end: int, timescale: str) -> str:
    if job.head_text:
        return job.head_text
    title = job.title or job.output.stem
    return f"{title} {_format_time(start, timescale)} .. {_format_time(end, timescale)}"


def _timescale_seconds(timescale: str) -> float:
    match = re.fullmatch(r"\s*([0-9.]+)\s*([a-z]+)\s*", timescale)
    if not match or match.group(2) not in TIME_UNIT_SECONDS:
        raise ValueError(f"unsupported timescale: {timescale}")
    return float(match.group(1)) * TIME_UNIT_SECONDS[match.group(2)]


def _format_time(ticks: int, timescale: str) -> str:
    if ticks == 0:
        match = re.fullmatch(r"\s*[0-9.]+\s*([a-z]+)\s*", timescale)
        return "0" + (match.group(1) if match else "")
    try:
        seconds = ticks * _timescale_seconds(timescale)
    except ValueError:
        return f"{ticks} {timescale}"
    for unit in ("s", "ms", "us", "ns", "ps", "fs"):
        value = seconds / TIME_UNIT_SECONDS[unit]
        if abs(value) >= 1 or unit == "fs":
            if abs(value - round(value)) < 1e-9:
                return f"{int(round(value))}{unit}"
            return f"{value:.3f}{unit}"
    return f"{ticks} {timescale}"


def build_payload(job: WaveJob, changes: dict[str, list[tuple[int, str]]], timescale: str) -> dict[str, Any]:
    selected = [(spec, find_signal(changes, spec.path)) for spec in job.signals]
    timestamps = [t for _, series in selected for t, value in series if value not in {"x", "z"} and not set(value) <= {"x", "z"}]
    start = job.start if job.start is not None else (min(timestamps) if timestamps else 0)
    end = job.end if job.end is not None else max((series[-1][0] for _, series in selected if series), default=start + 1)
    if start >= end:
        start = 0
    lanes = []
    for spec, series in selected:
        samples = _sample_events(series, start, end, job.samples)
        lanes.append(
            _to_wavedrom_lane(
                spec.label,
                samples,
                _is_bus_like(spec),
                _is_clock_like(spec),
                job.value_format,
                job.max_value_chars,
                job.show_data_labels,
            )
        )
    return {
        "config": {"hscale": job.hscale},
        "head": {"text": _head_text(job, start, end, timescale), "tick": 0},
        "signal": lanes,
    }


def restyle_svg(svg_text: str, theme: str = DEFAULT_THEME, overrides: dict[str, str] | None = None) -> str:
    if theme == "wavedrom":
        return svg_text
    colors = {**THEMES.get(theme, THEMES[DEFAULT_THEME]), **(overrides or {})}

    replacements = {
        "fill:white": f"fill:{colors['bg']}",
        ".info{fill:#0041c4}": f".info{{fill:{colors['info']}}}",
        ".muted{fill:#aaa}": f".muted{{fill:{colors['muted']}}}",
        ".warning{fill:#f6b900}": f".warning{{fill:{colors['warning']}}}",
        ".success{fill:#00ab00}": f".success{{fill:{colors['success']}}}",
        ".s1{fill:none;stroke:#000;": f".s1{{fill:none;stroke:{colors['signal']};",
        ".s2{fill:none;stroke:#000;": f".s2{{fill:none;stroke:{colors['signal2']};",
        ".s3{color:#000;fill:none;stroke:#000;": f".s3{{color:{colors['text']};fill:none;stroke:{colors['grid2']};",
        ".s4{color:#000;fill:none;stroke:#000;": f".s4{{color:{colors['text']};fill:none;stroke:{colors['grid2']};",
        ".s5{fill:#fff;stroke:none}": f".s5{{fill:{colors['panel']};stroke:none}}",
        ".s6{fill:#000;fill-opacity:1;stroke:none}": f".s6{{fill:{colors['path']};fill-opacity:1;stroke:none}}",
        ".s7{color:#000;fill:#fff;fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}": f".s7{{color:{colors['text']};fill:{colors['panel']};fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}}",
        ".s8{color:#000;fill:#ffffb4;fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}": f".s8{{color:{colors['text']};fill:{colors['panel2']};fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}}",
        ".s9{color:#000;fill:#ffe0b9;fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}": f".s9{{color:{colors['text']};fill:{colors['panel3']};fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}}",
        ".s10{color:#000;fill:#b9e0ff;fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}": f".s10{{color:{colors['text']};fill:{colors['panel']};fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}}",
        ".s11{color:#000;fill:#ccfdfe;fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}": f".s11{{color:{colors['text']};fill:{colors['panel']};fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}}",
        ".s12{color:#000;fill:#cdfdc5;fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}": f".s12{{color:{colors['text']};fill:{colors['panel']};fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}}",
        ".s13{color:#000;fill:#f0c1fb;fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}": f".s13{{color:{colors['text']};fill:{colors['panel']};fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}}",
        ".s14{color:#000;fill:#f5c2c0;fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}": f".s14{{color:{colors['text']};fill:{colors['panel']};fill-opacity:1;fill-rule:nonzero;stroke:none;stroke-width:1px;marker:none;visibility:visible;display:inline;overflow:visible}}",
        "text{font-size:11pt;font-style:normal;font-variant:normal;font-weight:normal;font-stretch:normal;text-align:center;fill-opacity:1;font-family:Helvetica}": f"text{{font-size:10.5pt;font-style:normal;font-variant:normal;font-weight:normal;font-stretch:normal;text-align:center;fill:{colors['text']};fill-opacity:1;font-family:'DejaVu Sans Mono',monospace}}",
        "stroke:#888;stroke-width:0.5;stroke-dasharray:1,3": f"stroke:{colors['grid']};stroke-width:0.8;stroke-dasharray:2,4",
    }
    styled = svg_text
    for source, target in replacements.items():
        styled = styled.replace(source, target)
    return styled


def _ensure_tools() -> None:
    if not WAVEDROM_CLI and _wavedrom_cmd()[0] == "npx":
        # npx path is fine, no extra checks needed.
        return
    if not WAVEDROM_CLI:
        raise RuntimeError("wavedrom-cli not found. Install it via npm or make it available in PATH.")


def render_wave(
    *,
    vcd_path: str | pathlib.Path,
    output_path: str | pathlib.Path,
    signals: list[SignalSpec | dict[str, Any] | tuple[str, str] | tuple[str, str, str] | str],
    title: str | None = None,
    head_text: str | None = None,
    start: int | None = None,
    end: int | None = None,
    samples: int = 24,
    hscale: int = 2,
    theme: str = DEFAULT_THEME,
    formats: tuple[str, ...] = ("png",),
    value_format: str = "hex",
    max_value_chars: int = 6,
    show_data_labels: bool = True,
    png_scale: float = 1.0,
    png_width: int | None = None,
    png_height: int | None = None,
    dpi: float | None = None,
    background: str | None = None,
    theme_overrides: dict[str, str] | None = None,
) -> dict[str, pathlib.Path]:
    job = WaveJob(
        vcd=pathlib.Path(vcd_path),
        output=pathlib.Path(output_path),
        signals=[coerce_signal(sig) for sig in signals],
        title=title,
        head_text=head_text,
        start=start,
        end=end,
        samples=samples,
        hscale=hscale,
        theme=theme,
        formats=formats,
        value_format=value_format,
        max_value_chars=max_value_chars,
        show_data_labels=show_data_labels,
        png_scale=png_scale,
        png_width=png_width,
        png_height=png_height,
        dpi=dpi,
        background=background,
        theme_overrides=theme_overrides or {},
    )
    return render_job(job)


def _coerce_signal_kind(kind: object) -> str:
    text = str(kind)
    if text not in SIGNAL_KINDS:
        raise ValueError(f"signal kind must be one of {', '.join(sorted(SIGNAL_KINDS))}")
    return text


def _split_signal_kind(raw: str) -> tuple[str, str]:
    path, separator, kind = raw.rpartition(":")
    if separator and kind in SIGNAL_KINDS:
        return path, kind
    if separator and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", kind or ""):
        raise argparse.ArgumentTypeError("signal kind must be auto, bit, bus or clock")
    return raw, "auto"


def coerce_signal(value: SignalSpec | dict[str, Any] | tuple[str, str] | tuple[str, str, str] | str) -> SignalSpec:
    if isinstance(value, str):
        return _parse_signal_arg(value)
    if isinstance(value, SignalSpec):
        return value
    if isinstance(value, dict):
        return SignalSpec(
            label=str(value["label"]),
            path=str(value["path"]),
            kind=_coerce_signal_kind(value.get("kind", "auto")),
        )
    if len(value) == 2:
        label, path = value
        return SignalSpec(str(label), str(path))
    label, path, kind = value
    return SignalSpec(str(label), str(path), _coerce_signal_kind(kind))


def render_job(job: WaveJob) -> dict[str, pathlib.Path]:
    _ensure_tools()
    timescale, changes = parse_vcd(job.vcd)
    payload = build_payload(job, changes, timescale)

    output_prefix = job.output
    if output_prefix.suffix in {".png", ".svg", ".pdf", ".json"}:
        output_prefix = output_prefix.with_suffix("")
    output_prefix.parent.mkdir(parents=True, exist_ok=True)

    generated: dict[str, pathlib.Path] = {}
    json_path = output_prefix.with_suffix(".json")
    svg_path = output_prefix.with_suffix(".svg")
    json_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    generated["json"] = json_path

    requested = set(job.formats)
    if "svg" in requested or "png" in requested or "pdf" in requested or "all" in requested:
        subprocess.run([*_wavedrom_cmd(), "-i", str(json_path), "-s", str(svg_path)], check=True, cwd=ROOT)
        svg_path.write_text(restyle_svg(svg_path.read_text(encoding="utf-8"), job.theme, job.theme_overrides), encoding="utf-8")
        generated["svg"] = svg_path

    if "png" in requested or "all" in requested:
        png_cmd = _rsvg_cmd(job)
        if job.png_scale != 1.0:
            png_cmd.extend(["-z", str(job.png_scale)])
        if job.png_width is not None:
            png_cmd.extend(["-w", str(job.png_width)])
        if job.png_height is not None:
            png_cmd.extend(["-h", str(job.png_height)])
        png_cmd.extend(["-o", str(output_prefix.with_suffix(".png")), str(svg_path)])
        subprocess.run(png_cmd, check=True, cwd=ROOT)
        generated["png"] = output_prefix.with_suffix(".png")

    if "pdf" in requested or "all" in requested:
        pdf_path = output_prefix.with_suffix(".pdf")
        pdf_cmd = _rsvg_cmd(job)
        pdf_cmd.extend(["-f", "pdf", "-o", str(pdf_path), str(svg_path)])
        subprocess.run(pdf_cmd, check=True, cwd=ROOT)
        generated["pdf"] = pdf_path

    return generated


def _rsvg_cmd(job: WaveJob) -> list[str]:
    cmd = ["rsvg-convert"]
    if job.dpi is not None:
        cmd.extend(["-d", str(job.dpi), "-p", str(job.dpi)])
    if job.background:
        cmd.extend(["-b", job.background])
    return cmd


def _parse_signal_arg(raw: str) -> SignalSpec:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("signal must use label=path[:kind]")
    label, rest = raw.split("=", 1)
    path, kind = _split_signal_kind(rest)
    return SignalSpec(label=label, path=path, kind=kind)


def _load_jobs_from_config(path: pathlib.Path) -> list[WaveJob]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and "waves" in data:
        entries = data["waves"]
        defaults = {k: v for k, v in data.items() if k != "waves"}
    else:
        entries = [data]
        defaults = {}

    jobs: list[WaveJob] = []
    for entry in entries:
        merged = {**defaults, **entry}
        signals = [coerce_signal(item) for item in merged.get("signals", [])]
        output = pathlib.Path(merged["output"])
        jobs.append(
            WaveJob(
                vcd=pathlib.Path(merged["vcd"]),
                output=output,
                signals=signals,
                title=merged.get("title"),
                head_text=merged.get("head_text"),
                start=merged.get("start"),
                end=merged.get("end"),
                samples=int(merged.get("samples", 24)),
                hscale=int(merged.get("hscale", 2)),
                theme=str(merged.get("theme", DEFAULT_THEME)),
                formats=_formats_from_config(merged.get("formats", ["png"])),
                value_format=_coerce_value_format(merged.get("value_format", "hex")),
                max_value_chars=int(merged.get("max_value_chars", 6)),
                show_data_labels=bool(merged.get("show_data_labels", True)),
                png_scale=float(merged.get("png_scale", 1.0)),
                png_width=_optional_int(merged.get("png_width")),
                png_height=_optional_int(merged.get("png_height")),
                dpi=_optional_float(merged.get("dpi")),
                background=merged.get("background"),
                theme_overrides=dict(merged.get("theme_overrides", {})),
            )
        )
    return jobs


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render Vivado-style waveform PNG/SVG from VCD.")
    parser.add_argument("--config", type=pathlib.Path, help="JSON config file. Supports one job or {waves:[...]}.")
    parser.add_argument("--vcd", type=pathlib.Path, help="Input VCD file for a single job.")
    parser.add_argument("--output", type=pathlib.Path, help="Output file prefix for a single job.")
    parser.add_argument("--signal", action="append", default=[], type=_parse_signal_arg, help="Signal mapping: label=path[:kind].")
    parser.add_argument("--title", help="Chart title.")
    parser.add_argument("--head-text", help="Explicit header text.")
    parser.add_argument("--start", type=int, help="Start time in VCD units.")
    parser.add_argument("--end", type=int, help="End time in VCD units.")
    parser.add_argument("--samples", type=int, default=24, help="Number of horizontal sample slots.")
    parser.add_argument("--hscale", type=int, default=2, help="WaveDrom horizontal scale.")
    parser.add_argument("--theme", default=DEFAULT_THEME, choices=sorted(THEMES), help="Theme preset.")
    parser.add_argument("--format", dest="formats", default="png", help="Comma-separated outputs: png,svg,pdf,json,all.")
    parser.add_argument("--value-format", default="hex", choices=sorted(VALUE_FORMATS), help="Bus value display format.")
    parser.add_argument("--max-value-chars", type=int, default=6, help="Maximum characters for each bus value label; 0 disables truncation.")
    parser.add_argument("--hide-data-labels", action="store_true", help="Hide bus value labels.")
    parser.add_argument("--png-scale", type=float, default=1.0, help="PNG zoom factor passed to rsvg-convert.")
    parser.add_argument("--png-width", type=int, help="PNG output width in pixels.")
    parser.add_argument("--png-height", type=int, help="PNG output height in pixels.")
    parser.add_argument("--dpi", type=float, help="Raster/PDF DPI passed to rsvg-convert.")
    parser.add_argument("--background", help="Output background color passed to rsvg-convert, e.g. white or #ffffff.")
    parser.add_argument("--theme-color", action="append", default=[], help="Override theme color as key=value, e.g. signal=#00ff88.")
    parser.add_argument("--list-themes", action="store_true", help="Print available themes and exit.")
    return parser


def _parse_formats(raw: str) -> tuple[str, ...]:
    items = [item.strip().lower() for item in raw.split(",") if item.strip()]
    allowed = {"png", "svg", "pdf", "json", "all"}
    unknown = sorted(set(items) - allowed)
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown output format: {', '.join(unknown)}")
    return tuple(items or ["png"])


def _formats_from_config(value: object) -> tuple[str, ...]:
    if isinstance(value, str):
        return _parse_formats(value)
    if isinstance(value, list):
        return _parse_formats(",".join(str(item) for item in value))
    return ("png",)


def _coerce_value_format(value: object) -> str:
    text = str(value)
    if text not in VALUE_FORMATS:
        raise ValueError(f"value format must be one of {', '.join(sorted(VALUE_FORMATS))}")
    return text


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _optional_float(value: object) -> float | None:
    if value is None:
        return None
    return float(value)


def _parse_theme_overrides(items: list[str]) -> dict[str, str]:
    overrides: dict[str, str] = {}
    allowed = set(THEMES[DEFAULT_THEME])
    for item in items:
        if "=" not in item:
            raise argparse.ArgumentTypeError("--theme-color must use key=value")
        key, value = item.split("=", 1)
        if key not in allowed:
            raise argparse.ArgumentTypeError(f"unknown theme color key: {key}")
        overrides[key] = value
    return overrides


def main(argv: list[str] | None = None) -> int:
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    if args.list_themes:
        for name in sorted(THEMES):
            print(name)
        return 0

    if args.config:
        jobs = _load_jobs_from_config(args.config)
    else:
        if not args.vcd or not args.output or not args.signal:
            parser.error("--vcd, --output and at least one --signal are required without --config")
        jobs = [
            WaveJob(
                vcd=args.vcd,
                output=args.output,
                signals=args.signal,
                title=args.title,
                head_text=args.head_text,
                start=args.start,
                end=args.end,
                samples=args.samples,
                hscale=args.hscale,
                theme=args.theme,
                formats=_parse_formats(args.formats),
                value_format=args.value_format,
                max_value_chars=args.max_value_chars,
                show_data_labels=not args.hide_data_labels,
                png_scale=args.png_scale,
                png_width=args.png_width,
                png_height=args.png_height,
                dpi=args.dpi,
                background=args.background,
                theme_overrides=_parse_theme_overrides(args.theme_color),
            )
        ]

    for job in jobs:
        job = WaveJob(
            vcd=job.vcd,
            output=job.output,
            signals=job.signals,
            title=job.title or args.title,
            head_text=job.head_text or args.head_text,
            start=job.start if job.start is not None else args.start,
            end=job.end if job.end is not None else args.end,
            samples=job.samples if job.samples is not None else args.samples,
            hscale=job.hscale if job.hscale is not None else args.hscale,
            theme=job.theme or args.theme,
            formats=job.formats if job.formats else _parse_formats(args.formats),
            value_format=job.value_format or args.value_format,
            max_value_chars=job.max_value_chars,
            show_data_labels=job.show_data_labels,
            png_scale=job.png_scale,
            png_width=job.png_width,
            png_height=job.png_height,
            dpi=job.dpi,
            background=job.background,
            theme_overrides=job.theme_overrides,
        )
        render_job(job)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
