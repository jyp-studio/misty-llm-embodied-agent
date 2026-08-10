"""Misty's sensor events, over her ``/pubsub`` websocket.

The interface is two methods — ``subscribe`` and ``close`` — in place of the
six (``register_event``, ``unregister_event``, ``unregister_all_events``,
``get_registered_events``, ``keep_alive``, plus two nested classes) that the
previous code exposed. Dead connections are reaped when subscriptions are
added or removed rather than by a polling thread the caller had to remember to
start.

``websocket-client`` is imported inside the connection thread, so the message
builders below — the part the contract tests assert on — import anywhere.

Two behaviours here differ deliberately from the code this replaces, both
recorded in PLAN.md §10:

* The subscribe frame is serialised with ``json.dumps``. The original sent
  ``str(dict)``, which produces single-quoted output that is not JSON.
* The callbacks take ``websocket-client``'s modern ``(ws, ...)`` signatures.
  The original omitted them, which raises ``TypeError`` on any release from
  0.58 onwards — the requirement is unpinned, so that is what would install.

Neither could be verified against a robot. See PLAN.md §8.
"""

from __future__ import annotations

import json
import logging
import threading
from random import randint
from typing import Any, Callable, Dict, List, Optional

from misty_agent.config import settings

log = logging.getLogger(__name__)

EventCallback = Callable[[Dict[str, Any]], None]


def event_condition(
    property_name: str, inequality: str, value: Any
) -> Dict[str, Any]:
    """One clause of an event filter, in Misty's wire format.

    https://docs.mistyrobotics.com/misty-ii/robot/sensor-data/
    """
    return {"Property": property_name, "Inequality": inequality, "Value": value}


def subscribe_message(
    event_type: str,
    event_name: str,
    *,
    debounce_ms: int = 0,
    condition: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """The frame that opens a subscription."""
    message: Dict[str, Any] = {
        "Operation": "subscribe",
        "Type": event_type,
        "DebounceMs": debounce_ms,
        "EventName": event_name,
        "Message": "",
    }
    if condition:
        message["EventConditions"] = condition
    return message


def unsubscribe_message(event_name: str) -> Dict[str, Any]:
    """The frame that closes a subscription."""
    return {"Operation": "unsubscribe", "EventName": event_name, "Message": ""}


class Subscription:
    """One live event subscription.

    Created by :meth:`EventStream.subscribe`; never constructed directly.
    ``is_active`` goes false when the socket closes, whether the caller asked
    for that or the robot went away.
    """

    def __init__(
        self,
        ip: str,
        event_type: str,
        event_name: str,
        on_event: EventCallback,
        *,
        condition: Optional[List[Dict[str, Any]]] = None,
        debounce_ms: int = 0,
        keep_alive: bool = True,
        ping_timeout_s: float = settings.event_ws_ping_timeout_s,
    ) -> None:
        self.event_type = event_type
        self.event_name = event_name
        self.is_active = True

        self._ip = ip
        self._on_event = on_event
        self._condition = condition
        self._debounce_ms = debounce_ms
        self._keep_alive = keep_alive
        self._ping_timeout_s = ping_timeout_s
        self._ws: Any = None
        # Misty answers a subscription with an acknowledgement before any
        # sensor data. UNVERIFIED without hardware; PLAN.md §8.
        self._acknowledged = False

        self._thread = threading.Thread(
            target=self._run, name=f"misty-event-{event_name}", daemon=True
        )
        self._thread.start()

    def unsubscribe(self) -> None:
        """Close the subscription. Idempotent."""
        self.is_active = False
        ws, self._ws = self._ws, None
        if ws is None:
            return
        try:
            ws.send(json.dumps(unsubscribe_message(self.event_name)))
            ws.keep_running = False
            ws.close()
        except Exception as exc:
            log.warning("closing subscription %s failed: %s", self.event_name, exc)

    # ---------- implementation ----------

    def _run(self) -> None:
        import websocket

        websocket.enableTrace(False)
        self._ws = websocket.WebSocketApp(
            f"ws://{self._ip}/pubsub",
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._ws.run_forever(ping_timeout=self._ping_timeout_s)

    def _on_open(self, ws: Any) -> None:
        ws.send(
            json.dumps(
                subscribe_message(
                    self.event_type,
                    self.event_name,
                    debounce_ms=self._debounce_ms,
                    condition=self._condition,
                )
            )
        )
        self.is_active = True

    def _on_message(self, ws: Any, message: str) -> None:
        if not self._acknowledged:
            self._acknowledged = True
            return
        try:
            payload = json.loads(message)
        except ValueError:
            log.warning("unparseable event payload on %s", self.event_name)
            return

        try:
            self._on_event(payload)
        except Exception as exc:
            # A callback that raises must not take the socket down with it.
            log.exception("event callback for %s raised: %s", self.event_name, exc)

        if not self._keep_alive:
            self.unsubscribe()

    def _on_error(self, ws: Any, error: Any) -> None:
        log.warning("event socket %s error: %s", self.event_name, error)

    def _on_close(self, ws: Any, status_code: Any = None, reason: Any = None) -> None:
        self.is_active = False


class EventStream:
    """Misty's sensor events.

    Everything a caller must know:

    * ``subscribe(...)`` opens a subscription and returns a
      :class:`Subscription`. ``on_event`` is called on a background thread with
      the decoded payload; exceptions inside it are logged, not propagated.
    * Subscription names are unique per stream. Re-subscribing under a live
      name returns ``None`` rather than opening a second socket.
    * ``close()`` unsubscribes everything. Safe to call more than once.
    """

    def __init__(
        self, ip: str, *, ping_timeout_s: float = settings.event_ws_ping_timeout_s
    ) -> None:
        self._ip = ip
        self._ping_timeout_s = ping_timeout_s
        self._subscriptions: Dict[str, Subscription] = {}

    def subscribe(
        self,
        event_type: str,
        *,
        on_event: EventCallback,
        name: Optional[str] = None,
        condition: Optional[List[Dict[str, Any]]] = None,
        debounce_ms: int = 0,
        keep_alive: bool = True,
    ) -> Optional[Subscription]:
        self._reap()
        name = name or event_type
        if name in self._subscriptions:
            log.warning("already subscribed to %s; ignoring", name)
            return None

        subscription = Subscription(
            self._ip,
            event_type,
            # Misty keys events by name on the wire; a random suffix keeps two
            # processes watching the same sensor from colliding.
            event_name=f"{name}-{randint(0, 10_000_000_000)}",
            on_event=on_event,
            condition=condition,
            debounce_ms=debounce_ms,
            keep_alive=keep_alive,
            ping_timeout_s=self._ping_timeout_s,
        )
        self._subscriptions[name] = subscription
        return subscription

    def close(self) -> None:
        for subscription in list(self._subscriptions.values()):
            subscription.unsubscribe()
        self._subscriptions.clear()

    def _reap(self) -> None:
        for name, subscription in list(self._subscriptions.items()):
            if not subscription.is_active:
                log.info("event subscription %s has closed", name)
                del self._subscriptions[name]
