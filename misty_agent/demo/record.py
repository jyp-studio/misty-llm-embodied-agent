"""`python -m misty_agent.demo.record` — record the Demo's examples.

A separate entry point because the demo package imports `recordings` to
serve the files, and running an already-imported module as `__main__`
loads it twice.
"""

from misty_agent.demo.recordings import main

raise SystemExit(main())
