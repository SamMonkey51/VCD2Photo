#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
from typing import Any

TOOLS_DIR = pathlib.Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

try:
    from . import vcd_to_image as cli  # type: ignore  # noqa: E402
    from .vivado_wave import DEFAULT_THEME, THEMES, VALUE_FORMATS, render_wave  # noqa: E402
except ImportError:
    import vcd_to_image as cli  # type: ignore  # noqa: E402
    from vivado_wave import DEFAULT_THEME, THEMES, VALUE_FORMATS, render_wave  # noqa: E402


PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "vcd2photo", "version": "1.0.0"}


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, tuple):
        return list(value)
    return [value]


def _resolve_path(value: str | os.PathLike[str] | None, base: pathlib.Path) -> pathlib.Path | None:
    if value is None:
        return None
    path = pathlib.Path(value)
    if not path.is_absolute():
        path = base / path
    return path


def _formats(value: Any) -> tuple[str, ...]:
    if value is None:
        return ("png",)
    if isinstance(value, str):
        return cli._parse_formats(value)
    return cli._parse_formats(",".join(str(item) for item in _as_list(value)))


def _theme_overrides(value: Any) -> dict[str, str]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return {str(key): str(val) for key, val in value.items()}
    return cli._theme_overrides(_as_list(value))


def _namespace(arguments: dict[str, Any], base: pathlib.Path) -> argparse.Namespace:
    signal_files = [
        _resolve_path(path, base)
        for path in _as_list(arguments.get("signals_file"))
    ]
    return argparse.Namespace(
        signal=arguments.get("signals", arguments.get("signal", [])),
        signals_file=[path for path in signal_files if path is not None],
        all_signals=bool(arguments.get("all_signals", False)),
        match=_as_list(arguments.get("match")),
        exclude=_as_list(arguments.get("exclude")),
        scope=_as_list(arguments.get("scope")),
        active_only=bool(arguments.get("active_only", False)),
        changed_only=bool(arguments.get("changed_only", False)),
        include_parameters=bool(arguments.get("include_parameters", False)),
        max_signals=int(arguments.get("max_signals", 0)),
        sort_signals=str(arguments.get("sort_signals", "selected")),
        reverse_signals=bool(arguments.get("reverse_signals", False)),
        page_size=int(arguments.get("page_size", 0)),
        label_mode=str(arguments.get("label_mode", "auto")),
        label_strip_prefix=_as_list(arguments.get("label_strip_prefix")),
        label_replace=_as_list(arguments.get("label_replace")),
        max_label_chars=int(arguments.get("max_label_chars", 32)),
        strict=bool(arguments.get("strict", True)),
        range=arguments.get("range"),
        start=arguments.get("start"),
        end=arguments.get("end"),
        auto_window=str(arguments.get("auto_window", "activity")),
        around_signal=arguments.get("around_signal"),
        pre=arguments.get("pre", "0"),
        post=arguments.get("post", "200ns"),
        clock_mode=str(arguments.get("clock_mode", "ideal")),
    )


def _signal_to_dict(signal: Any) -> dict[str, Any]:
    return {
        "label": signal.label,
        "path": signal.path,
        "kind": signal.kind,
    }


def _filter_paths(info: Any, arguments: dict[str, Any]) -> list[str]:
    args = argparse.Namespace(
        scope=_as_list(arguments.get("scope")),
        match=_as_list(arguments.get("match")),
        exclude=_as_list(arguments.get("exclude")),
        active_only=bool(arguments.get("active_only", False)),
        changed_only=bool(arguments.get("changed_only", False)),
        max_signals=int(arguments.get("max_signals", 0)),
        json=True,
    )
    paths = sorted(info.signals)
    if args.scope:
        prefixes = tuple(str(scope).rstrip(".") + "." for scope in cli._as_list(args.scope))
        paths = [path for path in paths if path.startswith(prefixes)]
    patterns = cli._compile_patterns(args.match)
    if patterns:
        paths = [path for path in paths if cli._matches_any(path, patterns)]
    exclude = cli._compile_patterns(args.exclude)
    if exclude:
        paths = [path for path in paths if not cli._matches_any(path, exclude)]
    if args.active_only:
        paths = [path for path in paths if info.signals[path].events > 0]
    if args.changed_only:
        paths = [path for path in paths if info.signals[path].changes > 0]
    if args.max_signals and args.max_signals > 0:
        paths = paths[: args.max_signals]
    return paths


def tool_vcd_info(arguments: dict[str, Any]) -> dict[str, Any]:
    base = pathlib.Path(arguments.get("working_directory") or os.getcwd()).resolve()
    vcd_path = _resolve_path(arguments.get("vcd_path") or arguments.get("vcd"), base)
    if vcd_path is None:
        raise ValueError("vcd_path is required")
    info = cli.scan_vcd(vcd_path)
    paths = _filter_paths(info, arguments)
    return {
        "vcd": str(info.path),
        "timescale": info.timescale,
        "start": info.start_time,
        "end": info.end_time,
        "start_text": cli._format_time(info.start_time, info.timescale),
        "end_text": cli._format_time(info.end_time, info.timescale),
        "signal_count": len(info.signals),
        "alias_count": len(info.aliases),
        "signals": [info.signals[path].__dict__ for path in paths],
    }


def tool_vcd_render(arguments: dict[str, Any]) -> dict[str, Any]:
    base = pathlib.Path(arguments.get("working_directory") or os.getcwd()).resolve()
    vcd_path = _resolve_path(arguments.get("vcd_path") or arguments.get("vcd"), base)
    output_path = _resolve_path(arguments.get("output_path") or arguments.get("output"), base)
    if vcd_path is None:
        raise ValueError("vcd_path is required")
    if output_path is None:
        raise ValueError("output_path is required")

    info = cli.scan_vcd(vcd_path)
    args = _namespace(arguments, base)
    signals = cli._materialize_signals(info, args)
    start, end = cli._resolve_time_window(info, signals, args)
    pages = cli._chunks(signals, int(arguments.get("page_size", 0)))

    if bool(arguments.get("dry_run", False)):
        return {
            "dry_run": True,
            "timescale": info.timescale,
            "window": {"start": start, "end": end},
            "pages": [
                [_signal_to_dict(signal) for signal in page]
                for page in pages
            ],
        }

    generated: dict[str, str] = {}
    formats = _formats(arguments.get("formats", arguments.get("format", "png")))
    for index, page_signals in enumerate(pages, 1):
        page_output = cli._page_output_path(output_path, index, len(pages))
        title = cli._page_title(arguments.get("title"), index, len(pages))
        paths = render_wave(
            vcd_path=vcd_path,
            output_path=page_output,
            signals=page_signals,
            title=title,
            head_text=arguments.get("head_text") if len(pages) == 1 else None,
            start=start,
            end=end,
            samples=int(arguments.get("samples", 24)),
            hscale=int(arguments.get("hscale", 2)),
            theme=str(arguments.get("theme", DEFAULT_THEME)),
            formats=formats,
            value_format=str(arguments.get("value_format", "hex")),
            max_value_chars=int(arguments.get("max_value_chars", 6)),
            show_data_labels=not bool(arguments.get("hide_data_labels", False)),
            png_scale=float(arguments.get("png_scale", 1.0)),
            png_width=arguments.get("png_width"),
            png_height=arguments.get("png_height"),
            dpi=arguments.get("dpi"),
            background=arguments.get("background"),
            theme_overrides=_theme_overrides(arguments.get("theme_overrides", arguments.get("theme_color"))),
        )
        for kind, path in paths.items():
            key = kind if len(pages) == 1 else f"{kind}_p{index:02d}"
            generated[key] = str(path)

    return {
        "vcd": str(vcd_path),
        "output_prefix": str(output_path),
        "timescale": info.timescale,
        "window": {
            "start": start,
            "end": end,
            "start_text": cli._format_time(start, info.timescale) if start is not None else None,
            "end_text": cli._format_time(end, info.timescale) if end is not None else None,
        },
        "signals": [_signal_to_dict(signal) for signal in signals],
        "generated": generated,
    }


def tool_vcd_themes(arguments: dict[str, Any]) -> dict[str, Any]:
    return {
        "themes": sorted(THEMES),
        "value_formats": sorted(VALUE_FORMATS),
        "theme_color_keys": sorted(THEMES[DEFAULT_THEME]),
    }


TOOLS = {
    "vcd_info": {
        "description": "Inspect a VCD file and return timescale, span, signal widths, event counts and aliases.",
        "handler": tool_vcd_info,
        "inputSchema": {
            "type": "object",
            "properties": {
                "vcd_path": {"type": "string"},
                "working_directory": {"type": "string"},
                "match": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                "exclude": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                "scope": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                "active_only": {"type": "boolean"},
                "changed_only": {"type": "boolean"},
                "max_signals": {"type": "integer"},
            },
            "required": ["vcd_path"],
        },
    },
    "vcd_render": {
        "description": "Render a VCD waveform to PNG, SVG, PDF and/or JSON.",
        "handler": tool_vcd_render,
        "inputSchema": {
            "type": "object",
            "properties": {
                "vcd_path": {"type": "string"},
                "output_path": {"type": "string"},
                "working_directory": {"type": "string"},
                "signals": {
                    "type": "array",
                    "items": {
                        "oneOf": [
                            {"type": "string"},
                            {
                                "type": "object",
                                "properties": {
                                    "label": {"type": "string"},
                                    "path": {"type": "string"},
                                    "kind": {"type": "string", "enum": ["auto", "bit", "bus", "clock"]},
                                },
                                "required": ["path"],
                            },
                        ]
                    },
                },
                "signals_file": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                "all_signals": {"type": "boolean"},
                "match": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                "scope": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                "exclude": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                "active_only": {"type": "boolean"},
                "changed_only": {"type": "boolean"},
                "include_parameters": {"type": "boolean"},
                "max_signals": {"type": "integer"},
                "sort_signals": {"type": "string", "enum": ["selected", "path", "leaf", "events", "width"]},
                "reverse_signals": {"type": "boolean"},
                "range": {"type": "string"},
                "start": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
                "end": {"oneOf": [{"type": "string"}, {"type": "integer"}]},
                "auto_window": {"type": "string", "enum": ["activity", "full"]},
                "around_signal": {"type": "string"},
                "pre": {"type": "string"},
                "post": {"type": "string"},
                "title": {"type": "string"},
                "head_text": {"type": "string"},
                "theme": {"type": "string", "enum": sorted(THEMES)},
                "formats": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                "value_format": {"type": "string", "enum": sorted(VALUE_FORMATS)},
                "max_value_chars": {"type": "integer"},
                "hide_data_labels": {"type": "boolean"},
                "clock_mode": {"type": "string", "enum": ["ideal", "sampled"]},
                "samples": {"type": "integer"},
                "hscale": {"type": "integer"},
                "page_size": {"type": "integer"},
                "label_mode": {"type": "string", "enum": ["auto", "leaf", "scope", "full"]},
                "label_strip_prefix": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                "label_replace": {"oneOf": [{"type": "string"}, {"type": "array", "items": {"type": "string"}}]},
                "max_label_chars": {"type": "integer"},
                "png_scale": {"type": "number"},
                "png_width": {"type": "integer"},
                "png_height": {"type": "integer"},
                "dpi": {"type": "number"},
                "background": {"type": "string"},
                "theme_overrides": {"type": "object", "additionalProperties": {"type": "string"}},
                "strict": {"type": "boolean"},
                "dry_run": {"type": "boolean"},
            },
            "required": ["vcd_path", "output_path"],
        },
    },
    "vcd_themes": {
        "description": "List available VCD2Photo themes, value formats and overridable theme color keys.",
        "handler": tool_vcd_themes,
        "inputSchema": {"type": "object", "properties": {}},
    },
}


def _tool_descriptions() -> list[dict[str, Any]]:
    return [
        {
            "name": name,
            "description": spec["description"],
            "inputSchema": spec["inputSchema"],
        }
        for name, spec in TOOLS.items()
    ]


def _response(message_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "result": result}


def _error(message_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": message_id, "error": {"code": code, "message": message}}


def _tool_content(payload: Any, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [
            {
                "type": "text",
                "text": json.dumps(payload, ensure_ascii=False, indent=2),
            }
        ],
        "isError": is_error,
    }


def handle_request(message: dict[str, Any]) -> dict[str, Any] | None:
    message_id = message.get("id")
    method = message.get("method")
    params = message.get("params") or {}

    if message_id is None:
        return None
    if method == "initialize":
        protocol = params.get("protocolVersion") or PROTOCOL_VERSION
        return _response(
            message_id,
            {
                "protocolVersion": protocol,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        )
    if method == "ping":
        return _response(message_id, {})
    if method == "tools/list":
        return _response(message_id, {"tools": _tool_descriptions()})
    if method == "tools/call":
        name = params.get("name")
        arguments = params.get("arguments") or {}
        if name not in TOOLS:
            return _response(message_id, _tool_content({"error": f"unknown tool: {name}"}, True))
        try:
            payload = TOOLS[name]["handler"](arguments)
            return _response(message_id, _tool_content(payload))
        except Exception as exc:
            return _response(message_id, _tool_content({"error": str(exc)}, True))
    if method == "resources/list":
        return _response(message_id, {"resources": []})
    if method == "prompts/list":
        return _response(message_id, {"prompts": []})
    return _error(message_id, -32601, f"method not found: {method}")


def main() -> int:
    for line in sys.stdin:
        text = line.strip()
        if not text:
            continue
        try:
            message = json.loads(text)
            response = handle_request(message)
        except Exception as exc:
            response = _error(None, -32700, str(exc))
        if response is not None:
            sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
            sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
