"""Time-bounded circuit breaker for Vertex AI clients.

The legacy `_mark_forbidden` global in `vertex_services.py` permanently
disabled Gemini for the rest of the process when a single 403 was hit.
That meant a transient credential error or an upstream billing outage
would require an API restart even after the upstream recovered.

This breaker is a small, self-contained CLOSED → OPEN → HALF_OPEN state
machine driven by `record_failure()` / `record_success()`. Callers ask
`allow()` before attempting the upstream:

  - CLOSED: allow=True, every call goes through.
  - OPEN: allow=False until `cooldown_s` has elapsed since the breaker
    opened, then transitions to HALF_OPEN.
  - HALF_OPEN: allow=True for exactly one probe call. Success → CLOSED,
    failure → OPEN with a fresh cooldown timestamp.

Thread-safe via a simple lock; the lock is held only for state
transitions, never across upstream I/O.
"""
from __future__ import annotations

import logging
import threading
import time
from enum import Enum
from typing import Callable, Optional

logger = logging.getLogger(__name__)


class _State(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    """A small in-process circuit breaker.

    Parameters:
      name: human label used in log lines and snapshots.
      failure_threshold: open the breaker after N consecutive failures.
      cooldown_s: seconds to wait after OPEN before attempting a probe.
      on_open / on_close: optional hooks (called outside the lock) so
        callers can emit alerts or update health caches on transitions.
    """

    def __init__(
        self,
        *,
        name: str,
        failure_threshold: int,
        cooldown_s: float,
        on_open: Optional[Callable[[str], None]] = None,
        on_close: Optional[Callable[[], None]] = None,
    ) -> None:
        self._name = name
        self._threshold = max(1, int(failure_threshold))
        # Tiny floor (10 ms) prevents accidental zero-cooldown thrash
        # while still letting unit tests exercise the state machine
        # quickly. Production cooldowns are read from env (defaults
        # 180-300s).
        self._cooldown = max(0.01, float(cooldown_s))
        self._on_open = on_open
        self._on_close = on_close
        self._lock = threading.Lock()
        self._state = _State.CLOSED
        self._consecutive_failures = 0
        self._opened_at: Optional[float] = None
        # When we transitioned to HALF_OPEN. If a probe is granted but
        # neither record_success nor record_failure ever arrives (e.g.
        # the caller's task was cancelled mid-flight, or a bug
        # swallowed the exception), the breaker would otherwise sit in
        # HALF_OPEN forever and `allow()` would always return False.
        # The lease bounds that risk: if no outcome is reported within
        # `cooldown_s`, we consider the probe abandoned and re-OPEN.
        self._half_open_at: Optional[float] = None
        self._last_reason = ""

    @property
    def name(self) -> str:
        return self._name

    @property
    def state(self) -> str:
        return self._state.value

    def snapshot(self) -> dict:
        """Return a dict suitable for serialising to admin endpoints."""
        with self._lock:
            opened_at = self._opened_at
            cooldown_remaining = 0.0
            if self._state is _State.OPEN and opened_at is not None:
                cooldown_remaining = max(
                    0.0, self._cooldown - (time.monotonic() - opened_at)
                )
            return {
                "name": self._name,
                "state": self._state.value,
                "consecutive_failures": self._consecutive_failures,
                "cooldown_s": self._cooldown,
                "cooldown_remaining_s": round(cooldown_remaining, 1),
                "last_reason": self._last_reason,
                "opened_at_monotonic": opened_at,
            }

    def allow(self) -> bool:
        """Return True if the next call should attempt the upstream.

        Side effect: when an OPEN breaker has cooled down, atomically
        transitions to HALF_OPEN and grants exactly one probe. If a
        prior HALF_OPEN probe was granted but never reported its
        outcome within the cooldown window (caller cancelled, raised
        outside the recorded paths, etc), the lease expires and the
        breaker re-OPENs so traffic isn't permanently blocked.
        """
        with self._lock:
            if self._state is _State.CLOSED:
                return True
            now = time.monotonic()
            if (
                self._state is _State.OPEN
                and self._opened_at is not None
                and (now - self._opened_at) >= self._cooldown
            ):
                self._state = _State.HALF_OPEN
                self._half_open_at = now
                logger.info(
                    f"[breaker:{self._name}] cooldown elapsed; HALF_OPEN — "
                    "allowing a probe."
                )
                return True
            if self._state is _State.HALF_OPEN:
                # Lease expired? Treat as an abandoned probe and re-OPEN.
                if (
                    self._half_open_at is not None
                    and (now - self._half_open_at) >= self._cooldown
                ):
                    self._state = _State.OPEN
                    self._opened_at = now
                    self._half_open_at = None
                    self._last_reason = "half_open_lease_expired"
                    logger.warning(
                        f"[breaker:{self._name}] HALF_OPEN probe abandoned "
                        f"(no outcome in {self._cooldown:.0f}s); re-OPEN."
                    )
                # Either way, don't grant a new probe in this call —
                # the next allow() after the fresh cooldown will.
                return False
            # OPEN with cooldown not elapsed.
            return False

    def record_success(self) -> None:
        """Note a successful upstream call. Closes the breaker if open."""
        on_close: Optional[Callable[[], None]] = None
        with self._lock:
            was_open = self._state is not _State.CLOSED
            self._consecutive_failures = 0
            self._opened_at = None
            self._half_open_at = None
            self._last_reason = ""
            self._state = _State.CLOSED
            if was_open:
                on_close = self._on_close
                logger.info(
                    f"[breaker:{self._name}] CLOSED — upstream recovered."
                )
        if on_close is not None:
            try:
                on_close()
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"[breaker:{self._name}] on_close hook raised: {e}"
                )

    def record_failure(self, reason: str = "") -> None:
        """Note a failed upstream call. Opens the breaker on threshold."""
        opened_now = False
        on_open: Optional[Callable[[str], None]] = None
        observed_reason = reason or "unknown"
        with self._lock:
            self._last_reason = reason or self._last_reason
            if self._state is _State.HALF_OPEN:
                # Probe failed → re-open with a fresh cooldown.
                self._state = _State.OPEN
                self._opened_at = time.monotonic()
                self._half_open_at = None
                opened_now = True
                on_open = self._on_open
                logger.warning(
                    f"[breaker:{self._name}] half-open probe failed "
                    f"({observed_reason}); re-OPEN for {self._cooldown:.0f}s."
                )
            else:
                self._consecutive_failures += 1
                if (
                    self._state is _State.CLOSED
                    and self._consecutive_failures >= self._threshold
                ):
                    self._state = _State.OPEN
                    self._opened_at = time.monotonic()
                    opened_now = True
                    on_open = self._on_open
                    logger.error(
                        f"[breaker:{self._name}] OPEN after "
                        f"{self._consecutive_failures} consecutive failures "
                        f"(last_reason={observed_reason}). "
                        f"Will retry in {self._cooldown:.0f}s."
                    )
        if opened_now and on_open is not None:
            try:
                on_open(observed_reason)
            except Exception as e:  # noqa: BLE001
                logger.warning(
                    f"[breaker:{self._name}] on_open hook raised: {e}"
                )

    def force_close(self) -> None:
        """Operator override (e.g. an admin endpoint) to manually close."""
        with self._lock:
            self._state = _State.CLOSED
            self._consecutive_failures = 0
            self._opened_at = None
            self._half_open_at = None
            self._last_reason = ""
        logger.warning(
            f"[breaker:{self._name}] manually CLOSED via force_close()."
        )

    def force_open(self, reason: str = "manual") -> None:
        """Operator override to manually open the breaker."""
        with self._lock:
            self._state = _State.OPEN
            self._opened_at = time.monotonic()
            self._half_open_at = None
            self._last_reason = reason
        logger.warning(
            f"[breaker:{self._name}] manually OPEN ({reason}); "
            f"cooldown={self._cooldown:.0f}s."
        )
