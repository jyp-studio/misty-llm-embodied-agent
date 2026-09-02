"""A Misty that records requests instead of sending them.

One implementation, two jobs:

* the contract tests assert on what :class:`RecordingCommands` recorded, which
  is how this project checks its request formats against
  docs.mistyrobotics.com without a robot to send them to;
* running the agent with no hardware uses the same class, so "mock mode" and
  "what the tests exercise" cannot drift apart.

``fail_endpoints`` exists because the previous stand-in answered every call
with a success no-op, which meant the error paths in the code above it — the
``drive_error`` branch in particular — had never once executed (PLAN.md §6).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from misty_agent.drivers.robot_commands import RobotCommands


@dataclass(frozen=True)
class RecordedRequest:
    """One request that would have gone to the robot."""

    verb: str
    endpoint: str
    json: Optional[Dict[str, Any]] = None

    def body_without_defaults(self) -> Dict[str, Any]:
        """The JSON body with unset (``None``) fields removed.

        The generated SDK sends every parameter of a command, filling the ones
        the caller omitted with ``None``. Assertions read better against what
        the caller actually asked for.
        """
        return {k: v for k, v in (self.json or {}).items() if v is not None}


@dataclass
class _Response:
    """The parts of ``requests.Response`` that this codebase reads."""

    status_code: int = 200
    _payload: Dict[str, Any] = field(default_factory=dict)

    def json(self) -> Dict[str, Any]:
        return self._payload


class RecordingCommands(RobotCommands):
    """Satisfies the command interface by writing to a list.

    ``requests`` holds every call in order. ``fail_endpoints`` names endpoints
    that answer ``failure_status`` instead of 200, so callers' error handling
    can be exercised.
    """

    def __init__(
        self,
        ip: str = "127.0.0.1",
        *,
        fail_endpoints: Iterable[str] = (),
        failure_status: int = 500,
    ) -> None:
        super().__init__(ip)
        self.requests: List[RecordedRequest] = []
        self.fail_endpoints = set(fail_endpoints)
        self.failure_status = failure_status

    def _generic_request(self, verb: str, endpoint: str, **kwargs: Any) -> _Response:
        self.requests.append(
            RecordedRequest(verb=verb, endpoint=endpoint, json=kwargs.get("json"))
        )
        if endpoint in self.fail_endpoints:
            return _Response(status_code=self.failure_status)
        return _Response(status_code=200)

    # ---------- reading back what happened ----------

    @property
    def endpoints(self) -> List[str]:
        """Endpoints in call order — the usual thing a test wants."""
        return [request.endpoint for request in self.requests]

    def last(self, endpoint: str) -> RecordedRequest:
        """The most recent call to ``endpoint``. Raises if there was none."""
        for request in reversed(self.requests):
            if request.endpoint == endpoint:
                return request
        raise AssertionError(
            f"no request to {endpoint!r}; saw {self.endpoints}"
        )

    def clear(self) -> None:
        self.requests.clear()


class FakeClock:
    """A clock whose only motion is what someone asks it to sleep through.

    The `Clock` protocol `misty_agent/control/approach.py` defines, with the
    sleeps recorded. Tests that assert on timing need to assert on something,
    and a real wait would make the suite slow and flaky in exchange for
    nothing.
    """

    def __init__(self, now: float = 0.0) -> None:
        self.now = now
        self.slept: List[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.slept.append(seconds)
        self.now += seconds
