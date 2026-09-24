"""
Circuit breaker implementation for backing services (Redis, Milvus, MinIO) (Issue #85).

Prevents downstream outages from piling up threads or connections by fast-failing
requests with HTTP 503 and a Retry-After header.
"""

import time
import threading
from enum import Enum
from typing import Optional, Tuple, Callable, Any, Dict
from fastapi import HTTPException


class CircuitState(str, Enum):
    CLOSED = "CLOSED"
    OPEN = "OPEN"
    HALF_OPEN = "HALF_OPEN"


class CircuitBreakerOpenException(HTTPException):
    """Exception raised when a backing service circuit breaker is OPEN."""

    def __init__(self, dsai_service: str, dsai_retry_after: float = 30.0):
        self.dsai_service = dsai_service
        self.dsai_retry_after = max(1.0, float(dsai_retry_after))
        super().__init__(
            status_code=503,
            detail=f"Service '{dsai_service}' circuit breaker is OPEN. Upstream temporarily unavailable.",
            headers={"Retry-After": str(int(self.dsai_retry_after))}
        )


class CircuitBreaker:
    """Thread-safe circuit breaker with CLOSED, OPEN, and HALF_OPEN states."""

    def __init__(
        self,
        dsai_name: str,
        dsai_failure_threshold: int = 5,
        dsai_recovery_timeout: float = 30.0,
        dsai_half_open_success_threshold: int = 2
    ):
        self.dsai_name = dsai_name
        self.dsai_failure_threshold = max(1, dsai_failure_threshold)
        self.dsai_recovery_timeout = max(0.1, dsai_recovery_timeout)
        self.dsai_half_open_success_threshold = max(1, dsai_half_open_success_threshold)

        self._dsai_lock = threading.Lock()
        self._dsai_state = CircuitState.CLOSED
        self._dsai_failure_count = 0
        self._dsai_success_count = 0
        self._dsai_opened_at = 0.0

    @property
    def dsai_state(self) -> CircuitState:
        with self._dsai_lock:
            if self._dsai_state == CircuitState.OPEN:
                if (time.time() - self._dsai_opened_at) >= self.dsai_recovery_timeout:
                    self._dsai_state = CircuitState.HALF_OPEN
                    self._dsai_success_count = 0
            return self._dsai_state

    def dsai_is_available(self) -> Tuple[bool, Optional[float]]:
        """
        Check if circuit allows calls.
        Returns: (is_available, retry_after_seconds)
        """
        with self._dsai_lock:
            dsai_now = time.time()
            if self._dsai_state == CircuitState.OPEN:
                dsai_elapsed = dsai_now - self._dsai_opened_at
                if dsai_elapsed >= self.dsai_recovery_timeout:
                    self._dsai_state = CircuitState.HALF_OPEN
                    self._dsai_success_count = 0
                    return True, None
                dsai_remaining = max(1.0, self.dsai_recovery_timeout - dsai_elapsed)
                return False, dsai_remaining
            return True, None

    def dsai_record_success(self) -> None:
        """Record a successful downstream call."""
        with self._dsai_lock:
            if self._dsai_state == CircuitState.HALF_OPEN:
                self._dsai_success_count += 1
                if self._dsai_success_count >= self.dsai_half_open_success_threshold:
                    self._dsai_state = CircuitState.CLOSED
                    self._dsai_failure_count = 0
                    self._dsai_success_count = 0
            elif self._dsai_state == CircuitState.CLOSED:
                self._dsai_failure_count = 0

    def dsai_record_failure(self, dsai_error: Optional[Exception] = None) -> None:
        """Record a failed downstream call."""
        with self._dsai_lock:
            self._dsai_failure_count += 1
            if self._dsai_state in (CircuitState.CLOSED, CircuitState.HALF_OPEN):
                if self._dsai_failure_count >= self.dsai_failure_threshold or self._dsai_state == CircuitState.HALF_OPEN:
                    self._dsai_state = CircuitState.OPEN
                    self._dsai_opened_at = time.time()

    def dsai_call(self, dsai_func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Execute a callable protected by this circuit breaker."""
        dsai_available, dsai_retry_after = self.dsai_is_available()
        if not dsai_available:
            raise CircuitBreakerOpenException(
                dsai_service=self.dsai_name,
                dsai_retry_after=dsai_retry_after or self.dsai_recovery_timeout
            )
        try:
            dsai_res = dsai_func(*args, **kwargs)
            self.dsai_record_success()
            return dsai_res
        except Exception as dsai_err:
            self.dsai_record_failure(dsai_err)
            raise

    def dsai_reset(self) -> None:
        """Reset the breaker to initial CLOSED state."""
        with self._dsai_lock:
            self._dsai_state = CircuitState.CLOSED
            self._dsai_failure_count = 0
            self._dsai_success_count = 0
            self._dsai_opened_at = 0.0


# Global registry of circuit breakers
_DSAI_BREAKERS: Dict[str, CircuitBreaker] = {}
_DSAI_REGISTRY_LOCK = threading.Lock()


def dsai_get_circuit_breaker(
    dsai_name: str,
    dsai_failure_threshold: int = 5,
    dsai_recovery_timeout: float = 30.0
) -> CircuitBreaker:
    """Retrieve or create a named circuit breaker."""
    with _DSAI_REGISTRY_LOCK:
        if dsai_name not in _DSAI_BREAKERS:
            _DSAI_BREAKERS[dsai_name] = CircuitBreaker(
                dsai_name=dsai_name,
                dsai_failure_threshold=dsai_failure_threshold,
                dsai_recovery_timeout=dsai_recovery_timeout
            )
        return _DSAI_BREAKERS[dsai_name]


def dsai_check_circuit_breaker(dsai_name: str) -> None:
    """Raise CircuitBreakerOpenException if the circuit breaker is OPEN."""
    dsai_breaker = dsai_get_circuit_breaker(dsai_name)
    dsai_avail, dsai_retry = dsai_breaker.dsai_is_available()
    if not dsai_avail:
        raise CircuitBreakerOpenException(dsai_service=dsai_name, dsai_retry_after=dsai_retry or 30.0)


def dsai_reset_circuit_breakers() -> None:
    """Reset all registered circuit breakers."""
    with _DSAI_REGISTRY_LOCK:
        for dsai_breaker in _DSAI_BREAKERS.values():
            dsai_breaker.dsai_reset()
