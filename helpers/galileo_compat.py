"""Parsing tolerance for Splunk AO responses newer than the installed galileo SDK.

The tenant can add permission actions (for example ``configure_rate_limit`` on
Projects) before the SDK enums know them. galileo 2.6.0/2.7.0 then raise
``ValueError`` while parsing ``GET /projects/{id}``, which breaks
``get_project(id=)``, ``list_experiment_groups`` and
``get_experiments(project_id=, experiment_group=)``.

``tolerate_unknown_permission_actions()`` wraps ``Permission.from_dict`` once
per process. Responses the SDK already parses are returned unchanged; only a
parse that would otherwise fail keeps the unknown action verbatim. Nothing is
sent to the platform.
"""
from __future__ import annotations

import threading
from collections.abc import Mapping
from typing import Any

_LOCK = threading.Lock()
_MARKER = "_splunk_ao_unknown_action_tolerant"
_KNOWN_PLACEHOLDER_ACTION = "read"


class UnknownPermissionAction(str):
    """A permission action string the installed SDK has no enum member for."""

    @property
    def value(self) -> str:
        return str.__str__(self)


def tolerate_unknown_permission_actions() -> bool:
    try:
        from galileo.resources.models.permission import Permission
    except ImportError:
        return False

    with _LOCK:
        if getattr(Permission, _MARKER, False):
            return True
        original = Permission.from_dict.__func__

        def from_dict(cls: Any, src_dict: Mapping[str, Any]) -> Any:
            try:
                return original(cls, src_dict)
            except ValueError as exc:
                action = src_dict.get("action") if isinstance(src_dict, Mapping) else None
                if not isinstance(action, str):
                    raise
                try:
                    permission = original(cls, {**src_dict, "action": _KNOWN_PLACEHOLDER_ACTION})
                except Exception:
                    raise exc
                permission.action = UnknownPermissionAction(action)
                return permission

        Permission.from_dict = classmethod(from_dict)
        setattr(Permission, _MARKER, True)
    return True
