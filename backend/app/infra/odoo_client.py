"""Thin Odoo XML-RPC wrapper.

Single place that knows the Odoo protocol. Exposes a typed `search_read`
that automatically pages through large result sets so callers never have
to think about Odoo's per-call limits.

Stdlib only (xmlrpc.client). The Python session is reused across calls
via xmlrpc's persistent Transport, so subsequent reads reuse the TCP
connection — important when batching.
"""

from __future__ import annotations

import logging
import threading
import xmlrpc.client
from typing import Any

logger = logging.getLogger(__name__)


class OdooAuthError(RuntimeError):
    """Raised when Odoo authenticate() returns no uid."""


class OdooClient:
    """Authenticated XML-RPC client for one Odoo database.

    Authentication is lazy: the first call to `execute_kw` logs in and
    caches the uid for the lifetime of the client. Re-authentication is
    not handled here — if Odoo invalidates the session we surface the
    error and let the caller decide (typically: restart the process).
    """

    def __init__(
        self,
        url: str,
        db: str,
        username: str,
        password: str,
        *,
        timeout: float = 30.0,
    ) -> None:
        self._url = url.rstrip("/")
        self._db = db
        self._username = username
        self._password = password
        self._timeout = timeout
        self._uid: int | None = None
        self._uid_lock = threading.Lock()
        # ServerProxy is cheap and thread-safe for read-only use; keep one
        # per endpoint so the underlying HTTP(S) connection can be reused.
        self._common = xmlrpc.client.ServerProxy(
            f"{self._url}/xmlrpc/2/common", allow_none=True
        )
        self._models = xmlrpc.client.ServerProxy(
            f"{self._url}/xmlrpc/2/object", allow_none=True
        )

    def _ensure_uid(self) -> int:
        if self._uid is not None:
            return self._uid
        with self._uid_lock:
            if self._uid is not None:
                return self._uid
            uid = self._common.authenticate(self._db, self._username, self._password, {})
            if not uid:
                raise OdooAuthError(
                    "Odoo authenticate() returned no uid — check ODOO_DB / ODOO_USERNAME / ODOO_PASSWORD."
                )
            self._uid = int(uid)
            logger.info("Odoo authenticated as uid=%s on db=%s", self._uid, self._db)
            return self._uid

    def execute_kw(
        self,
        model: str,
        method: str,
        args: list[Any],
        kwargs: dict[str, Any] | None = None,
    ) -> Any:
        uid = self._ensure_uid()
        return self._models.execute_kw(
            self._db, uid, self._password, model, method, args, kwargs or {}
        )

    def search_read(
        self,
        model: str,
        domain: list[Any],
        fields: list[str],
        *,
        batch_size: int = 500,
        order: str | None = None,
    ) -> list[dict[str, Any]]:
        """Paged search_read. Returns the full result set as one list.

        Odoo accepts limit/offset on search_read; we walk the result set
        in `batch_size` chunks. The loop stops when a page comes back
        smaller than the batch size (no more rows).
        """
        results: list[dict[str, Any]] = []
        offset = 0
        while True:
            kwargs: dict[str, Any] = {
                "fields": fields,
                "offset": offset,
                "limit": batch_size,
            }
            if order:
                kwargs["order"] = order
            page = self.execute_kw(model, "search_read", [domain], kwargs)
            if not page:
                break
            results.extend(page)
            if len(page) < batch_size:
                break
            offset += batch_size
        return results
