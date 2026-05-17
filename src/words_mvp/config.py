"""Runtime configuration loading for CLI scripts."""

from __future__ import annotations

from pathlib import Path
import ast


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "default.yaml"


def load_runtime_config(path: str | Path | None = None) -> dict:
    """Load a YAML config file.

    PyYAML is used when installed. A small fallback parser handles the simple
    mapping/list subset used by ``configs/default.yaml``.
    """
    config_path = Path(path) if path else DEFAULT_CONFIG_PATH
    if not config_path.is_absolute():
        config_path = PROJECT_ROOT / config_path
    if not config_path.exists():
        return {}

    text = config_path.read_text(encoding="utf-8")
    try:
        import yaml
    except ImportError:
        return _parse_simple_yaml(text)

    data = yaml.safe_load(text)
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(f"Config root must be a mapping: {config_path}")
    return data


def config_section(config: dict, name: str) -> dict:
    value = config.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"Config section must be a mapping: {name}")
    return value


def resolve_project_path(value: str | Path | None) -> str | None:
    if value is None:
        return None
    path = Path(value)
    if path.is_absolute():
        return str(path)
    return str(PROJECT_ROOT / path)


def _parse_simple_yaml(text: str) -> dict:
    root: dict = {}
    stack: list[tuple[int, dict]] = [(-1, root)]
    pending_list_key: tuple[int, dict, str] | None = None

    for raw_line in text.splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue

        indent = len(raw_line) - len(raw_line.lstrip(" "))
        stripped = raw_line.strip()

        if stripped.startswith("- "):
            if pending_list_key is None:
                raise ValueError("List item without a list key in config")
            pending_indent, parent, key = pending_list_key
            if indent <= pending_indent:
                raise ValueError(f"Invalid list indentation for {key}")
            current = parent.setdefault(key, [])
            if isinstance(current, dict) and not current:
                current = []
                parent[key] = current
            if not isinstance(current, list):
                raise ValueError(f"Config value is not a list: {key}")
            current.append(_parse_scalar(stripped[2:].strip()))
            continue

        pending_list_key = None
        if ":" not in stripped:
            raise ValueError(f"Invalid config line: {raw_line}")

        key, value = stripped.split(":", 1)
        key = key.strip()
        value = value.strip()

        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]

        if value == "":
            child: dict = {}
            parent[key] = child
            stack.append((indent, child))
            pending_list_key = (indent, parent, key)
        elif value == "[]":
            parent[key] = []
            pending_list_key = (indent, parent, key)
        else:
            parent[key] = _parse_scalar(value)

    return root


def _parse_scalar(value: str):
    value = value.split(" #", 1)[0].strip()
    lowered = value.lower()
    if lowered in {"true", "false"}:
        return lowered == "true"
    if lowered in {"null", "none", "~"}:
        return None
    if value.startswith("[") or value.startswith("{"):
        try:
            return ast.literal_eval(value)
        except (SyntaxError, ValueError):
            if value.startswith("[") and value.endswith("]"):
                items = value[1:-1].strip()
                if not items:
                    return []
                return [_parse_scalar(item.strip()) for item in items.split(",")]
            raise
    try:
        return int(value)
    except ValueError:
        pass
    try:
        return float(value)
    except ValueError:
        pass
    return value.strip("\"'")
