"""What the runtime tells an active Episode when someone else is waiting.

A handoff never interrupts a Turn. The Attention Loop queues the newcomer's
Explicit Request, and at the next Turn boundary the active Episode is told
once. The model brings its own Episode to an understandable close and calls
`done`; only then does the runtime open a separate Episode with its own
target. Emergency stops do not wait for this.

"Someone else" is decided by anonymous track only: a queued request on a
different track than the active target. A request with no track is assumed,
as the spec's first version does, to come from the current speaker and is
not announced; it still opens its own Episode afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class HandoffNotice:
    cue_id: str
    cue_kind: str

    def model_message(self) -> Dict[str, Any]:
        return {
            "role": "system",
            "content": (
                "Another person has made an explicit request to Misty and is "
                f"waiting ({self.cue_id}). Bring this Episode to an "
                "understandable close: finish the current exchange briefly, "
                "say goodbye if appropriate, then call done. Do not start new "
                "activities or move. Their request opens its own Episode with "
                "its own Interaction Target afterwards; you never handle two "
                "people at once."
            ),
        }


__all__ = ["HandoffNotice"]
