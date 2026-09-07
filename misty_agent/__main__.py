"""``python -m misty_agent`` — the command lives in `misty_agent/app.py`.

`app.py` is where the pieces are wired together, and starting the whole thing
is the last piece of that wiring, so `main` is defined there and this file
only forwards to it (`.scratch/m8-runnable-and-demo/spec.md`).

Keeping it that way is not tidiness. A module run as `python -m misty_agent`
is imported as `__main__`; anything that later did `from misty_agent.__main__
import ...` — the demo in #08 needs to build the same world — would get a
*second* copy of it, with its own constants and its own module state.
"""

from __future__ import annotations

from misty_agent.app import main

if __name__ == "__main__":
    raise SystemExit(main())
