# Separate attention from bounded ReAct Episodes

Misty will use a continuous, low-cost Attention Loop to detect Interaction
Cues and open one bounded ReAct Episode with Trigger Evidence. The Attention
Loop does not choose a response, only one Episode may control the robot at a
time, and later cues wait for a Turn-boundary handoff; this preserves LLM
autonomy without turning continuous perception into an unbounded model loop or
returning to a fixed perception-plan-action pipeline.
