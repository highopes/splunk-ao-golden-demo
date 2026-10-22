"""Opt-in reliable trace ingestion for selected Splunk AO projects.

Batch-mode ``GalileoLogger.flush()`` and ``run_experiment`` in galileo 2.6.0
send ``TracesIngestRequest`` with the default ``reliable=False``. On the
splunkse tenant, traces ingested that way are stored with LLM span
``cost = 0.0`` / ``cost_status = "success"`` even when the model has a price,
while the identical payload sent with ``reliable=True`` is priced correctly
(see documentation/VALIDATION.md, "Cisco SE platform cost").

Domains opt in with ``galileo.reliable_ingest: true`` in their config. The
SDK trace clients are wrapped once per process, and only requests for
registered project IDs are switched to ``reliable=True``; every other project
(Healthcare and the existing domains) keeps the SDK default unchanged.
"""

from __future__ import annotations

import threading
from typing import Any, Mapping, Optional

_LOCK = threading.Lock()
_RELIABLE_PROJECT_IDS: set[str] = set()
_PATCHED_ATTR = "_splunk_ao_reliable_ingest_wrapped"


def _wrap_client(cls: Any) -> None:
    original = getattr(cls, "ingest_traces", None)
    if original is None or getattr(original, _PATCHED_ATTR, False):
        return

    async def ingest_traces(self, traces_ingest_request, *args, **kwargs):
        project_id = getattr(self, "project_id", None)
        if (
            project_id is not None
            and str(project_id) in _RELIABLE_PROJECT_IDS
            and not getattr(traces_ingest_request, "reliable", True)
        ):
            traces_ingest_request = traces_ingest_request.model_copy(update={"reliable": True})
        return await original(self, traces_ingest_request, *args, **kwargs)

    setattr(ingest_traces, _PATCHED_ATTR, True)
    ingest_traces.__wrapped__ = original
    ingest_traces.__doc__ = original.__doc__
    cls.ingest_traces = ingest_traces


def enable_reliable_ingest(project_id: Optional[str]) -> bool:
    """Send this project's batch trace ingests with ``reliable=True``.

    Returns True when the project is registered. Idempotent and thread-safe.
    """
    if not project_id:
        return False
    from galileo import traces as galileo_traces

    with _LOCK:
        for name in ("Traces", "IngestTraces"):
            cls = getattr(galileo_traces, name, None)
            if cls is not None:
                _wrap_client(cls)
        _RELIABLE_PROJECT_IDS.add(str(project_id))
    return True


def is_reliable_ingest_enabled(project_id: Optional[str]) -> bool:
    return bool(project_id) and str(project_id) in _RELIABLE_PROJECT_IDS


def reliable_ingest_requested(domain_config: Optional[Mapping[str, Any]]) -> bool:
    galileo_config = (domain_config or {}).get("galileo") or {}
    return bool(galileo_config.get("reliable_ingest", False))


def apply_domain_reliable_ingest(
    domain_config: Optional[Mapping[str, Any]], project_id: Optional[str]
) -> bool:
    """Enable reliable ingest for ``project_id`` when the domain opts in."""
    if not reliable_ingest_requested(domain_config):
        return False
    return enable_reliable_ingest(project_id)
