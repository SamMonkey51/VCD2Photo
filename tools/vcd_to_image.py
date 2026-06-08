#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Sequence

try:
    from .vivado_wave import (
        DEFAULT_THEME,
        SIGNAL_KINDS,
        THEMES,
        VALUE_FORMATS,
        SignalSpec,
        parse_vcd,
        render_wave,
    )
except ImportError:
    from vivado_wave import (
        DEFAULT_THEME,
        SIGNAL_KINDS,
        THEMES,
        VALUE_FORMATS,
        SignalSpec,
        parse_vcd,
        render_wave,
    )


UNIT_SECONDS = {
    "fs": 1e-15,
    "ps": 1e-12,
    "ns": 1e-9,
    "us": 1e-6,
    "ms": 1e-3,
    "s": 1.0,
}


@dataclass(frozen=True)
class VcdSignal:
    path: str
    ident: str
    var_type: str
    width: int
    events: int
    changes: int
    first_time: int | None
    last_time: int | None


@dataclass(frozen=True)
class VcdInfo:
    path: pathlib.Path
    timescale: str
    start_time: int
    end_time: int
    signals: dict[str, VcdSignal]
    aliases: dict[str, list[str]]


@dataclass(frozen=True)
class SignalRequest:
    label: str | None
    path: str
    kind: str = "auto"


def _split_signal_kind(raw: str) -> tuple[str, str]:
    path, separator, kind = raw.rpartition(":")
    if separator and kind in SIGNAL_KINDS:
        return path, kind
    if separator and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", kind or ""):
        raise argparse.ArgumentTypeError("signal kind must be auto, bit, bus or clock")
    return raw, "auto"


def _parse_signal_request(raw: str) -> SignalRequest:
    if "=" in raw:
        label, rest = raw.split("=", 1)
        path, kind = _split_signal_kind(rest)
        return SignalRequest(label=label, path=path, kind=kind)
    path, kind = _split_signal_kind(raw)
    return SignalRequest(label=None, path=path, kind=kind)


def _parse_formats(raw: str) -> tuple[str, ...]:
    formats = tuple(item.strip().lower() for item in raw.split(",") if item.strip())
    allowed = {"png", "svg", "pdf", "json", "all"}
    unknown = sorted(set(formats) - allowed)
    if unknown:
        raise argparse.ArgumentTypeError(f"unknown output format: {', '.join(unknown)}")
    return formats or ("png",)


def _leaf(path: str) -> str:
    return path.split(".")[-1]


def _short_scope(path: str, parts: int = 2) -> str:
    chunks = path.split(".")
    return ".".join(chunks[-parts:]) if len(chunks) >= parts else path


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    if max_chars <= 2:
        return text[:max_chars]
    return text[: max_chars - 2] + ".."


def _parse_replace(raw: str) -> tuple[re.Pattern[str], str]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("--label-replace must use regex=replacement")
    pattern, replacement = raw.split("=", 1)
    return re.compile(pattern), replacement


def _parse_theme_color(raw: str) -> tuple[str, str]:
    if "=" not in raw:
        raise argparse.ArgumentTypeError("--theme-color must use key=value")
    key, value = raw.split("=", 1)
    if key not in THEMES[DEFAULT_THEME]:
        raise argparse.ArgumentTypeError(f"unknown theme color key: {key}")
    return key, value


def _theme_overrides(values: Sequence[str] | dict[str, str]) -> dict[str, str]:
    if isinstance(values, dict):
        return dict(values)
    return dict(_parse_theme_color(item) for item in _as_list(values))


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _timescale_seconds(timescale: str) -> float:
    match = re.fullmatch(r"\s*([0-9.]+)\s*([a-z]+)\s*", timescale)
    if not match or match.group(2) not in UNIT_SECONDS:
        raise ValueError(f"unsupported timescale: {timescale}")
    return float(match.group(1)) * UNIT_SECONDS[match.group(2)]


def _parse_time(raw: str | int | float | None, timescale: str) -> int | None:
    if raw is None:
        return None
    if isinstance(raw, int):
        return raw
    if isinstance(raw, float):
        return int(round(raw))
    text = raw.strip().replace("_", "")
    if not text:
        return None
    if re.fullmatch(r"[0-9]+", text):
        return int(text)
    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)(fs|ps|ns|us|ms|s)", text)
    if not match:
        raise argparse.ArgumentTypeError(f"invalid time value: {raw}")
    seconds = float(match.group(1)) * UNIT_SECONDS[match.group(2)]
    return int(round(seconds / _timescale_seconds(timescale)))


def _format_time(ticks: int | None, timescale: str) -> str:
    if ticks is None:
        return "-"
    if ticks == 0:
        match = re.fullmatch(r"\s*[0-9.]+\s*([a-z]+)\s*", timescale)
        return "0" + (match.group(1) if match else "")
    seconds = ticks * _timescale_seconds(timescale)
    for unit in ("s", "ms", "us", "ns", "ps", "fs"):
        value = seconds / UNIT_SECONDS[unit]
        if abs(value) >= 1 or unit == "fs":
            if abs(value - round(value)) < 1e-9:
                return f"{int(round(value))}{unit}"
            return f"{value:.3f}{unit}"
    return f"{ticks}{timescale}"


def _parse_timescale_line(line: str, pending: list[str] | None) -> tuple[str | None, list[str] | None]:
    if pending is not None:
        if "$end" in line:
            before_end = line.split("$end", 1)[0].strip()
            if before_end:
                pending.append(before_end)
            return "".join(" ".join(pending).split()), None
        pending.append(line.strip())
        return None, pending
    if line.startswith("$timescale"):
        rest = line.replace("$timescale", "", 1).strip()
        if "$end" in rest:
            return "".join(rest.replace("$end", "").split()), None
        return None, ([rest] if rest else [])
    return None, None


def _parse_var(line: str, scopes: list[str]) -> tuple[str, str, str, int] | None:
    parts = line.split()
    if len(parts) < 5:
        return None
    var_type = parts[1]
    width = int(parts[2])
    ident = parts[3]
    end_idx = parts.index("$end") if "$end" in parts else len(parts)
    ref_tokens = parts[4:end_idx]
    if not ref_tokens:
        return None
    ref = ref_tokens[0] + "".join(ref_tokens[1:])
    return ".".join(scopes + [ref]), ident, var_type, width


def scan_vcd(path: pathlib.Path) -> VcdInfo:
    timescale = "1ns"
    pending_timescale: list[str] | None = None
    scopes: list[str] = []
    ids: dict[str, list[str]] = defaultdict(list)
    widths: dict[str, int] = {}
    var_types: dict[str, str] = {}
    changes: dict[str, list[tuple[int, str]]] = {}
    current_time = 0

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            parsed_timescale, pending_timescale = _parse_timescale_line(line, pending_timescale)
            if parsed_timescale:
                timescale = parsed_timescale
                continue
            if pending_timescale is not None:
                continue
            if line.startswith("$scope"):
                parts = line.split()
                if len(parts) >= 3:
                    scopes.append(parts[2])
                continue
            if line.startswith("$upscope"):
                if scopes:
                    scopes.pop()
                continue
            if line.startswith("$var"):
                parsed = _parse_var(line, scopes)
                if parsed is None:
                    continue
                full, ident, var_type, width = parsed
                ids[ident].append(full)
                widths[full] = width
                var_types[full] = var_type
                changes.setdefault(full, [])
                continue
            if line.startswith("#"):
                current_time = int(line[1:])
                continue
            if line[0] in "01xzXZ":
                for full in ids.get(line[1:], []):
                    changes[full].append((current_time, line[0].lower()))
                continue
            if line[0] in "bBrR":
                parts = line.split()
                if len(parts) == 2 and parts[1] in ids:
                    value = parts[0][1:].lower()
                    for full in ids[parts[1]]:
                        changes[full].append((current_time, value.zfill(widths.get(full, len(value)))))

    signals: dict[str, VcdSignal] = {}
    all_times: list[int] = []
    for ident, paths in ids.items():
        for full in paths:
            series = changes.get(full, [])
            all_times.extend(t for t, _ in series)
            unique_values = [value for _, value in series]
            signals[full] = VcdSignal(
                path=full,
                ident=ident,
                var_type=var_types.get(full, ""),
                width=widths.get(full, 1),
                events=len(series),
                changes=max(0, len(Counter(unique_values)) - 1),
                first_time=series[0][0] if series else None,
                last_time=series[-1][0] if series else None,
            )
    return VcdInfo(
        path=path,
        timescale=timescale,
        start_time=min(all_times, default=0),
        end_time=max(all_times, default=0),
        signals=signals,
        aliases={ident: paths for ident, paths in ids.items() if len(paths) > 1},
    )


def _compile_patterns(values: Sequence[str]) -> list[re.Pattern[str]]:
    return [re.compile(str(value)) for value in _as_list(values)]


def _matches_any(path: str, patterns: Sequence[re.Pattern[str]]) -> bool:
    return any(pattern.search(path) for pattern in patterns)


def _resolve_request(info: VcdInfo, request: SignalRequest, strict: bool) -> SignalRequest | None:
    if request.path in info.signals:
        return request
    suffix_matches = [path for path in info.signals if path.endswith("." + request.path) or _leaf(path) == request.path]
    if len(suffix_matches) == 1:
        return SignalRequest(label=request.label, path=suffix_matches[0], kind=request.kind)
    if len(suffix_matches) > 1:
        message = f"ambiguous signal '{request.path}': " + ", ".join(suffix_matches[:8])
    else:
        message = f"signal not found: {request.path}"
    if strict:
        raise SystemExit(message)
    print(f"warning: {message}", file=sys.stderr)
    return None


def _read_signal_file(path: pathlib.Path) -> list[SignalRequest]:
    requests: list[SignalRequest] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        requests.append(_parse_signal_request(line))
    return requests


def _signal_request_from_value(value: Any) -> SignalRequest:
    if isinstance(value, SignalRequest):
        return value
    if isinstance(value, str):
        return _parse_signal_request(value)
    if isinstance(value, dict):
        kind = str(value.get("kind", "auto"))
        if kind not in SIGNAL_KINDS:
            raise argparse.ArgumentTypeError("signal kind must be auto, bit, bus or clock")
        return SignalRequest(
            label=value.get("label"),
            path=str(value["path"]),
            kind=kind,
        )
    raise argparse.ArgumentTypeError(f"unsupported signal spec: {value!r}")


def _auto_label(path: str, selected_paths: list[str], mode: str) -> str:
    leaf_counts = Counter(_leaf(item) for item in selected_paths)
    if mode == "full":
        label = path
    elif mode == "leaf":
        label = _leaf(path)
    elif mode == "scope":
        label = _short_scope(path, 2)
    else:
        label = _leaf(path) if leaf_counts[_leaf(path)] == 1 else _short_scope(path, 2)
    return label


def _apply_label_edits(label: str, args: argparse.Namespace) -> str:
    edited = label
    for prefix in _as_list(args.label_strip_prefix):
        if edited.startswith(prefix):
            edited = edited[len(prefix) :]
    for pattern, replacement in (_parse_replace(raw) for raw in _as_list(args.label_replace)):
        edited = pattern.sub(replacement, edited)
    return _truncate(edited, args.max_label_chars)


def _sort_selected_paths(paths: list[str], info: VcdInfo, mode: str, reverse: bool) -> list[str]:
    if mode == "selected":
        ordered = list(paths)
    elif mode == "path":
        ordered = sorted(paths)
    elif mode == "leaf":
        ordered = sorted(paths, key=lambda path: (_leaf(path), path))
    elif mode == "events":
        ordered = sorted(paths, key=lambda path: (info.signals[path].events, path))
    elif mode == "width":
        ordered = sorted(paths, key=lambda path: (info.signals[path].width, path))
    else:
        raise SystemExit(f"unknown sort mode: {mode}")
    if reverse:
        ordered.reverse()
    return ordered


def _materialize_signals(info: VcdInfo, args: argparse.Namespace) -> list[SignalSpec]:
    requests: list[SignalRequest] = []
    for raw in _as_list(args.signal):
        requests.append(_signal_request_from_value(raw))
    for signal_file in _as_list(args.signals_file):
        requests.extend(_read_signal_file(pathlib.Path(signal_file)))

    selected_paths: list[str] = []
    specs_by_path: dict[str, SignalRequest] = {}
    for request in requests:
        resolved = _resolve_request(info, request, args.strict)
        if resolved is None:
            continue
        if resolved.path not in specs_by_path:
            selected_paths.append(resolved.path)
        specs_by_path[resolved.path] = resolved

    include_patterns = _compile_patterns(args.match)
    scope_prefixes = tuple(str(scope).rstrip(".") + "." for scope in _as_list(args.scope))
    exclude_patterns = _compile_patterns(args.exclude)

    if args.all_signals or include_patterns or scope_prefixes:
        for path, signal in info.signals.items():
            if not args.include_parameters and signal.var_type == "parameter":
                continue
            if include_patterns and not _matches_any(path, include_patterns):
                continue
            if scope_prefixes and not path.startswith(scope_prefixes):
                continue
            if args.active_only and signal.events == 0:
                continue
            if args.changed_only and signal.changes == 0:
                continue
            if _matches_any(path, exclude_patterns):
                continue
            if path not in specs_by_path:
                selected_paths.append(path)
                specs_by_path[path] = SignalRequest(label=None, path=path, kind="auto")

    if not selected_paths:
        raise SystemExit("no signals selected; use --signal, --match, --scope or --all-signals")

    selected_paths = _sort_selected_paths(selected_paths, info, args.sort_signals, args.reverse_signals)
    if args.max_signals and args.max_signals > 0:
        selected_paths = selected_paths[: args.max_signals]

    if len(selected_paths) > 12:
        print("warning: more than 12 lanes selected; consider --max-signals or splitting report figures", file=sys.stderr)

    materialized: list[SignalSpec] = []
    for path in selected_paths:
        request = specs_by_path[path]
        signal = info.signals.get(path)
        if signal and signal.events == 0:
            print(f"warning: selected signal has no recorded value changes: {path}", file=sys.stderr)
        kind = request.kind
        if args.clock_mode == "sampled" and kind == "auto" and "clk" in path.lower():
            kind = "bit"
        label = request.label or _auto_label(path, selected_paths, args.label_mode)
        label = _apply_label_edits(label, args)
        materialized.append(SignalSpec(label=label, path=path, kind=kind))
    return materialized


def _resolve_time_window(info: VcdInfo, signals: list[SignalSpec], args: argparse.Namespace) -> tuple[int | None, int | None]:
    range_start = range_end = None
    if args.range:
        if ".." not in args.range:
            raise SystemExit("--range must use START..END")
        start_raw, end_raw = args.range.split("..", 1)
        range_start = _parse_time(start_raw, info.timescale)
        range_end = _parse_time(end_raw, info.timescale)

    start = _parse_time(args.start, info.timescale) if args.start else range_start
    end = _parse_time(args.end, info.timescale) if args.end else range_end

    if args.around_signal:
        resolved = _resolve_request(info, SignalRequest(None, args.around_signal), args.strict)
        if resolved is None:
            return start, end
        _, changes = parse_vcd(info.path)
        series = changes.get(resolved.path, [])
        active_times = [t for t, value in series if set(value) not in ({"x"}, {"z"})]
        if not active_times:
            raise SystemExit(f"--around-signal has no activity: {resolved.path}")
        center = active_times[0]
        pre = _parse_time(args.pre, info.timescale) or 0
        post = _parse_time(args.post, info.timescale) or 0
        start = max(0, center - pre)
        end = center + post

    if start is None and end is None and args.auto_window == "full":
        start, end = info.start_time, info.end_time

    if start is not None and end is not None and start >= end:
        raise SystemExit("start time must be smaller than end time")
    return start, end


def _chunks(items: list[SignalSpec], size: int) -> list[list[SignalSpec]]:
    if size <= 0 or len(items) <= size:
        return [items]
    return [items[index : index + size] for index in range(0, len(items), size)]


def _page_output_path(output: pathlib.Path, page_index: int, page_count: int) -> pathlib.Path:
    if page_count <= 1:
        return output
    prefix = output.with_suffix("") if output.suffix in {".png", ".svg", ".pdf", ".json"} else output
    return prefix.with_name(f"{prefix.name}_p{page_index:02d}")


def _page_title(title: str | None, page_index: int, page_count: int) -> str | None:
    if title is None or page_count <= 1:
        return title
    return f"{title} ({page_index}/{page_count})"


def _print_info(info: VcdInfo, args: argparse.Namespace) -> int:
    paths = sorted(info.signals)
    if args.scope:
        prefixes = tuple(str(scope).rstrip(".") + "." for scope in _as_list(args.scope))
        paths = [path for path in paths if path.startswith(prefixes)]
    patterns = _compile_patterns(args.match)
    if patterns:
        paths = [path for path in paths if _matches_any(path, patterns)]
    exclude = _compile_patterns(args.exclude)
    if exclude:
        paths = [path for path in paths if not _matches_any(path, exclude)]
    if args.active_only:
        paths = [path for path in paths if info.signals[path].events > 0]
    if args.changed_only:
        paths = [path for path in paths if info.signals[path].changes > 0]
    if args.max_signals and args.max_signals > 0:
        paths = paths[: args.max_signals]

    if getattr(args, "json", False):
        payload = {
            "vcd": str(info.path),
            "timescale": info.timescale,
            "start": info.start_time,
            "end": info.end_time,
            "start_text": _format_time(info.start_time, info.timescale),
            "end_text": _format_time(info.end_time, info.timescale),
            "signal_count": len(info.signals),
            "alias_count": len(info.aliases),
            "signals": [info.signals[path].__dict__ for path in paths],
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
        return 0

    print(f"vcd: {info.path}")
    print(f"timescale: {info.timescale}")
    print(f"span: {info.start_time}..{info.end_time} ticks ({_format_time(info.start_time, info.timescale)}..{_format_time(info.end_time, info.timescale)})")
    print(f"signals: {len(info.signals)} paths, aliases: {len(info.aliases)} ids")
    print("events  width  type       path")
    for path in paths:
        signal = info.signals[path]
        print(f"{signal.events:6d}  {signal.width:5d}  {signal.var_type:<9}  {path}")
    return 0


def _render_one(args: argparse.Namespace) -> dict[str, pathlib.Path]:
    args.vcd = pathlib.Path(args.vcd)
    if args.output is not None:
        args.output = pathlib.Path(args.output)
    info = scan_vcd(args.vcd)
    signals = _materialize_signals(info, args)
    start, end = _resolve_time_window(info, signals, args)

    pages = _chunks(signals, args.page_size)

    if args.dry_run:
        print(f"timescale: {info.timescale}")
        print(f"window: {start if start is not None else 'auto'}..{end if end is not None else 'auto'}")
        for page_index, page_signals in enumerate(pages, 1):
            print(f"page {page_index}/{len(pages)}:")
            for spec in page_signals:
                print(f"  {spec.label} = {spec.path}:{spec.kind}")
        return {}

    generated_all: dict[str, pathlib.Path] = {}
    for page_index, page_signals in enumerate(pages, 1):
        generated = render_wave(
            vcd_path=args.vcd,
            output_path=_page_output_path(args.output, page_index, len(pages)),
            signals=page_signals,
            title=_page_title(args.title, page_index, len(pages)),
            head_text=args.head_text if len(pages) == 1 else None,
            start=start,
            end=end,
            samples=args.samples,
            hscale=args.hscale,
            theme=args.theme,
            formats=args.formats,
            value_format=args.value_format,
            max_value_chars=args.max_value_chars,
            show_data_labels=not args.hide_data_labels,
            png_scale=args.png_scale,
            png_width=args.png_width,
            png_height=args.png_height,
            dpi=args.dpi,
            background=args.background,
            theme_overrides=_theme_overrides(args.theme_color),
        )
        for kind, path in generated.items():
            key = kind if len(pages) == 1 else f"{kind}_p{page_index:02d}"
            generated_all[key] = path
            print(f"{key}: {path}")
    return generated_all


def _namespace_with(base: argparse.Namespace, data: dict[str, Any]) -> argparse.Namespace:
    merged = vars(base).copy()
    for key, value in data.items():
        cli_key = key.replace("-", "_")
        if cli_key == "signals":
            merged["signal"] = value
        elif cli_key == "formats":
            merged["formats"] = _parse_formats(",".join(value) if isinstance(value, list) else str(value))
        elif cli_key == "theme_overrides":
            merged["theme_color"] = value
        else:
            merged[cli_key] = value
    return argparse.Namespace(**merged)


def run_render(args: argparse.Namespace) -> int:
    if args.list_signals:
        if not args.vcd:
            raise SystemExit("--vcd is required with --list-signals")
        return _print_info(scan_vcd(args.vcd), args)

    if args.config:
        data = json.loads(args.config.read_text(encoding="utf-8"))
        entries = data.get("waves", [data]) if isinstance(data, dict) else data
        defaults = {key: value for key, value in data.items() if key != "waves"} if isinstance(data, dict) else {}
        for entry in entries:
            job_args = _namespace_with(args, {**defaults, **entry})
            if not job_args.vcd or not job_args.output:
                raise SystemExit("each config job needs vcd and output")
            _render_one(job_args)
        return 0

    if not args.vcd:
        raise SystemExit("--vcd is required")
    if not args.output and not args.dry_run:
        raise SystemExit("--output is required unless --list-signals or --dry-run is used")
    _render_one(args)
    return 0


def build_render_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Convert VCD waveforms to report-ready PNG/SVG images.")
    parser.add_argument("--config", type=pathlib.Path, help="JSON config with one job or {waves:[...]}.")
    parser.add_argument("--vcd", type=pathlib.Path, help="Input VCD file.")
    parser.add_argument("--output", type=pathlib.Path, help="Output prefix, without extension.")
    parser.add_argument("--signal", action="append", default=[], help="Signal: path, label=path, or label=path:kind.")
    parser.add_argument("--signals-file", action="append", default=[], type=pathlib.Path, help="Text file with one --signal item per line.")
    parser.add_argument("--all-signals", action="store_true", help="Select every signal path from the VCD.")
    parser.add_argument("--match", action="append", default=[], help="Regex for selecting signal paths.")
    parser.add_argument("--exclude", action="append", default=[], help="Regex for excluding signal paths.")
    parser.add_argument("--scope", action="append", default=[], help="Select signals below a scope prefix, e.g. tb.dut.")
    parser.add_argument("--active-only", action="store_true", help="Keep only signals with recorded events.")
    parser.add_argument("--changed-only", action="store_true", help="Keep only signals with more than one value.")
    parser.add_argument("--include-parameters", action="store_true", help="Include VCD parameter entries during automatic selection.")
    parser.add_argument("--max-signals", type=int, default=0, help="Limit selected signals; 0 means no limit.")
    parser.add_argument("--sort-signals", choices=("selected", "path", "leaf", "events", "width"), default="selected", help="Signal order.")
    parser.add_argument("--reverse-signals", action="store_true", help="Reverse the chosen signal order.")
    parser.add_argument("--page-size", type=int, default=0, help="Split output into pages with this many lanes; 0 disables paging.")
    parser.add_argument("--label-mode", choices=("auto", "leaf", "scope", "full"), default="auto", help="How automatic labels are generated.")
    parser.add_argument("--label-strip-prefix", action="append", default=[], help="Strip prefix from generated and explicit labels.")
    parser.add_argument("--label-replace", action="append", default=[], help="Rewrite labels with regex=replacement.")
    parser.add_argument("--max-label-chars", type=int, default=32, help="Maximum label characters; 0 disables truncation.")
    parser.add_argument("--list-signals", action="store_true", help="List signal paths and exit.")
    parser.add_argument("--title", help="Chart title.")
    parser.add_argument("--head-text", help="Explicit WaveDrom header text.")
    parser.add_argument("--start", help="Start time, e.g. 120000, 120ns, 4.2us.")
    parser.add_argument("--end", help="End time, e.g. 240000, 240ns, 5us.")
    parser.add_argument("--range", help="Time range as START..END.")
    parser.add_argument("--auto-window", choices=("activity", "full"), default="activity", help="Default window when start/end are omitted.")
    parser.add_argument("--around-signal", help="Build a window around the first activity of this signal.")
    parser.add_argument("--pre", default="0", help="Time before --around-signal activity.")
    parser.add_argument("--post", default="200ns", help="Time after --around-signal activity.")
    parser.add_argument("--samples", type=int, default=24, help="Horizontal sample slots.")
    parser.add_argument("--hscale", type=int, default=2, help="WaveDrom horizontal scale.")
    parser.add_argument("--theme", default=DEFAULT_THEME, choices=sorted(THEMES), help="Style theme.")
    parser.add_argument("--format", dest="formats", default=("png",), type=_parse_formats, help="Comma-separated outputs: png,svg,pdf,json,all.")
    parser.add_argument("--value-format", default="hex", choices=sorted(VALUE_FORMATS), help="Bus value format.")
    parser.add_argument("--max-value-chars", type=int, default=6, help="Maximum bus value label characters; 0 disables truncation.")
    parser.add_argument("--hide-data-labels", action="store_true", help="Hide bus value text inside waveform boxes.")
    parser.add_argument("--clock-mode", choices=("ideal", "sampled"), default="ideal", help="Draw auto clock signals as ideal clocks or sampled bits.")
    parser.add_argument("--png-scale", type=float, default=1.0, help="PNG zoom factor.")
    parser.add_argument("--png-width", type=int, help="PNG output width in pixels.")
    parser.add_argument("--png-height", type=int, help="PNG output height in pixels.")
    parser.add_argument("--dpi", type=float, help="Raster/PDF DPI.")
    parser.add_argument("--background", help="Output background color, e.g. white or #ffffff.")
    parser.add_argument("--theme-color", action="append", default=[], help="Override theme color as key=value, e.g. signal=#00ff88.")
    parser.add_argument("--strict", action="store_true", help="Fail on missing or ambiguous signal names.")
    parser.add_argument("--dry-run", action="store_true", help="Print selected signals and exit without rendering.")
    parser.set_defaults(func=run_render)
    return parser


def build_info_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inspect VCD metadata and signal activity.")
    parser.add_argument("--vcd", type=pathlib.Path, required=True, help="Input VCD file.")
    parser.add_argument("--match", action="append", default=[], help="Regex for signal paths.")
    parser.add_argument("--exclude", action="append", default=[], help="Regex for excluding signal paths.")
    parser.add_argument("--scope", action="append", default=[], help="Scope prefix.")
    parser.add_argument("--active-only", action="store_true", help="Show only signals with events.")
    parser.add_argument("--changed-only", action="store_true", help="Show only signals with multiple values.")
    parser.add_argument("--max-signals", type=int, default=0, help="Limit listed signals; 0 means no limit.")
    parser.add_argument("--json", action="store_true", help="Print machine-readable JSON.")
    parser.set_defaults(func=lambda args: _print_info(scan_vcd(args.vcd), args))
    return parser


def print_themes() -> int:
    for name in sorted(THEMES):
        print(name)
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "info":
        parser = build_info_parser()
        parsed = parser.parse_args(args[1:])
        return parsed.func(parsed)
    if args and args[0] == "render":
        parser = build_render_parser()
        parsed = parser.parse_args(args[1:])
        return parsed.func(parsed)
    if args and args[0] == "themes":
        return print_themes()
    parser = build_render_parser()
    parsed = parser.parse_args(args)
    return parsed.func(parsed)


if __name__ == "__main__":
    raise SystemExit(main())
