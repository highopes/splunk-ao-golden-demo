#!/usr/bin/env python3
"""Read .streamlit/secrets.toml for the Kubernetes scripts without exposing secrets.

The app's single configuration file also carries the deployment settings in a
trailing ``[k8s]`` table. Commands:

  check                 list required keys as set/EMPTY (never values)
  k8s KEY               print a non-secret [k8s] value (e.g. namespace)
  value KEY             write a top-level value to a pipe (refuses a terminal)
  k8s-secret KEY        write a secret [k8s] value to a pipe (refuses a terminal)
  app-secret            write the file without its [k8s] table to a pipe
  checksum              sha256 of the app-secret content (safe to print)
  curl-auth             curl config line ``user = "<user>:<password>"`` to a pipe

Values are written without a trailing newline. Only the Python standard
library is used (Python >= 3.11 for tomllib).
"""
from __future__ import annotations

import hashlib
import re
import sys
import tomllib
from pathlib import Path
from typing import Dict, List

DEFAULT_FILE = Path(__file__).resolve().parents[3] / ".streamlit" / "secrets.toml"
SECRET_K8S_KEYS = {"basic_auth_password"}
REQUIRED_APP_KEYS = (
    "backend_profile", "galileo_console_url", "galileo_api_key", "agent_control_agent_name",
    "openai_api_key", "postgres_host", "postgres_password",
)
REQUIRED_K8S_KEYS = (
    "namespace", "app_host", "ingress_class", "image", "ao_ca_configmap",
    "basic_auth_user", "basic_auth_password",
)
_HEADER = re.compile(r"^\s*\[\[?\s*([^\]]+?)\s*\]\]?\s*(#.*)?$")


class ToolError(Exception):
    """Error whose message never contains a configuration value."""


def strip_k8s_table(text: str) -> str:
    """Return ``text`` without the ``[k8s]`` table (and any ``[k8s.*]`` sub-tables)."""
    kept: List[str] = []
    skipping = False
    for line in text.splitlines(keepends=True):
        match = _HEADER.match(line)
        if match:
            name = match.group(1).strip().strip('"')
            skipping = name == "k8s" or name.startswith("k8s.")
        if not skipping:
            kept.append(line)
    result = "".join(kept)
    try:
        original = tomllib.loads(text)
        stripped = tomllib.loads(result)
    except tomllib.TOMLDecodeError:
        raise ToolError("secrets.toml is not valid TOML (contents suppressed)") from None
    expected = {k: v for k, v in original.items() if k != "k8s"}
    if stripped != expected:
        raise ToolError("could not remove the [k8s] table cleanly; keep [k8s] as the last table, with no \"[k8s]\" text inside strings")
    return result


def load(path: Path) -> Dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise ToolError(f"{path} not found") from None
    except tomllib.TOMLDecodeError:
        raise ToolError("secrets.toml is not valid TOML (contents suppressed)") from None


def _present(value) -> bool:
    text = str(value).strip()
    return bool(text) and not text.startswith(("YOUR_", "<")) and "FILL IN" not in text


def check(data: Dict) -> List[str]:
    """Return lines ``key: set|EMPTY|MISSING`` for the keys the deployment needs."""
    lines = []
    k8s = data.get("k8s") or {}
    for key in REQUIRED_APP_KEYS:
        lines.append(f"{key}: {'set' if _present(data.get(key, '')) else ('EMPTY' if key in data else 'MISSING')}")
    for key in REQUIRED_K8S_KEYS:
        lines.append(f"k8s.{key}: {'set' if _present(k8s.get(key, '')) else ('EMPTY' if key in k8s else 'MISSING')}")
    return lines


def _to_pipe(value: str) -> None:
    if sys.stdout.isatty():
        raise ToolError("refusing to print a secret to a terminal; pipe it into the consuming command")
    sys.stdout.write(value)


def main(argv: List[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    path = DEFAULT_FILE
    if argv[0] == "--file":
        path, argv = Path(argv[1]), argv[2:]
    command, args = argv[0], argv[1:]
    data = load(path)
    k8s = data.get("k8s") or {}
    if command == "check":
        lines = check(data)
        print("\n".join(lines))
        return 0 if all(line.endswith(": set") for line in lines) else 1
    if command == "k8s":
        key = args[0]
        if key in SECRET_K8S_KEYS:
            raise ToolError(f"k8s.{key} is secret; use k8s-secret")
        value = k8s.get(key, args[1] if len(args) > 1 else None)
        if value is None:
            raise ToolError(f"[k8s].{key} is not set")
        print(value)
        return 0
    if command == "k8s-secret":
        if not _present(k8s.get(args[0], "")):
            raise ToolError(f"[k8s].{args[0]} is empty")
        _to_pipe(str(k8s[args[0]]))
        return 0
    if command == "value":
        if not _present(data.get(args[0], "")):
            raise ToolError(f"{args[0]} is empty")
        _to_pipe(str(data[args[0]]))
        return 0
    if command == "app-secret":
        _to_pipe(strip_k8s_table(path.read_text(encoding="utf-8")))
        return 0
    if command == "checksum":
        content = strip_k8s_table(path.read_text(encoding="utf-8"))
        print(hashlib.sha256(content.encode("utf-8")).hexdigest())
        return 0
    if command == "curl-auth":
        user, password = str(k8s.get("basic_auth_user", "")), str(k8s.get("basic_auth_password", ""))
        if not (_present(user) and _present(password)):
            raise ToolError("[k8s].basic_auth_user / basic_auth_password are empty")
        escaped = f"{user}:{password}".replace("\\", "\\\\").replace('"', '\\"')
        _to_pipe(f'user = "{escaped}"\n')
        return 0
    raise ToolError(f"unknown command {command!r}")


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except ToolError as exc:
        print(f"secrets_tool: {exc}", file=sys.stderr)
        raise SystemExit(1)
