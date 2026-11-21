"""SDK ingestion adjustments for Splunk AO backends.

1. Opt-in reliable trace ingestion for selected projects (splunkse).

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

2. Optional dedicated ingest-service URL (``galileo_ingest_url``).

The SDK probes ``{GALILEO_API_URL}/ingest/healthz`` and, when it succeeds,
posts new traces/spans to ``{GALILEO_API_URL}/ingest/...`` (the native JSON
door). Behind the public ingress both paths share one host, but inside the
cluster the ``api`` Service does not serve ``/ingest`` (404) while the
``ingest-service`` Service does. ``configure_ingest_url(url)`` makes the probe
and the two ``/ingest/...`` writes use ``url``; trace/span updates and session
calls keep using the API URL, as on-prem routes them to ``api``. Without a
configured URL nothing is patched and the SDK behaves exactly as before.
"""

from __future__ import annotations

import functools
import os
import threading
from typing import Any, Mapping, Optional

_LOCK = threading.Lock()
_RELIABLE_PROJECT_IDS: set[str] = set()
_PATCHED_ATTR = "_splunk_ao_reliable_ingest_wrapped"
_INGEST_URL_MARKER = "_splunk_ao_ingest_url_patched"
_INGEST_METHODS = ("ingest_traces", "ingest_spans")
_ingest_url: Optional[str] = None


def current_ingest_url() -> Optional[str]:
    """The configured ingest-service base URL, or None (SDK default)."""
    return _ingest_url


class _IngestBaseView:
    """Proxy of an SDK ``IngestTraces`` client whose ``base_url`` is the ingest URL.

    Every other attribute (project/log stream IDs, headers, per-thread HTTP
    client) is read from and written to the real client.
    """

    __slots__ = ("_target", "base_url")

    def __init__(self, target: Any, base_url: str) -> None:
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "base_url", base_url)

    def __getattr__(self, name: str) -> Any:
        return getattr(object.__getattribute__(self, "_target"), name)

    def __setattr__(self, name: str, value: Any) -> None:
        setattr(object.__getattribute__(self, "_target"), name, value)


def _wrap_ingest_method(cls: Any, name: str) -> None:
    original = getattr(cls, name, None)
    if original is None:
        return

    @functools.wraps(original)
    async def method(self, request, *args, **kwargs):
        url = current_ingest_url()
        target = _IngestBaseView(self, url) if url else self
        return await original(target, request, *args, **kwargs)

    setattr(cls, name, method)


def _patch_ingest_probe(logger_module: Any) -> None:
    logger_cls = logger_module.GalileoLogger
    original = logger_cls.__dict__["_is_ingest_service_available"].__func__

    def _is_ingest_service_available(cls) -> bool:
        url = current_ingest_url()
        if not url:
            return original(cls)
        if os.environ.get("GALILEO_INGEST_BETA_DISABLED", "").lower() in ("1", "true", "yes"):
            logger_module._ingest_service_cache.clear()
            return False
        config = logger_module.GalileoPythonConfig.get()
        extra_headers = getattr(config, "extra_headers", None)
        cache_key = "ingest-url:" + logger_module._ingest_cache_key(url, extra_headers)
        cache = logger_module._ingest_service_cache
        if cache_key not in cache:
            try:
                resp = logger_module.httpx.get(
                    f"{url}/ingest/healthz", timeout=2.0, headers=extra_headers or None
                )
                cache[cache_key] = resp.is_success
            except Exception:
                cache[cache_key] = False
        return cache[cache_key]

    logger_cls._is_ingest_service_available = classmethod(_is_ingest_service_available)


def configure_ingest_url(url: Optional[str]) -> bool:
    """Send the SDK's ingest probe and native ``/ingest`` writes to ``url``.

    ``None``/empty clears the setting (SDK default). Patches are installed once
    per process and only consult the current setting at call time. Returns True
    when a URL is active.
    """
    global _ingest_url
    normalized = str(url or "").strip().rstrip("/") or None
    with _LOCK:
        _ingest_url = normalized
        if normalized is None:
            return False
        import importlib

        from galileo import traces as galileo_traces

        logger_module = importlib.import_module("galileo.logger.logger")

        if not getattr(logger_module.GalileoLogger, _INGEST_URL_MARKER, False):
            _patch_ingest_probe(logger_module)
            setattr(logger_module.GalileoLogger, _INGEST_URL_MARKER, True)
        ingest_cls = getattr(galileo_traces, "IngestTraces", None)
        if ingest_cls is not None and not getattr(ingest_cls, _INGEST_URL_MARKER, False):
            for name in _INGEST_METHODS:
                _wrap_ingest_method(ingest_cls, name)
            setattr(ingest_cls, _INGEST_URL_MARKER, True)
    return True


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
