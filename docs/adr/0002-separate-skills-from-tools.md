# Separate Skills from Tools

Skills are progressively loaded `SKILL.md` instructions that guide the same
ReAct agent in combining capabilities, while Tools are typed, bounded and
validated interfaces to perception and robot effects. Skills do not create
nested agent loops, execute arbitrary scripts in the first version, or bypass
Tool and control-layer safety; this keeps reusable guidance extensible without
giving instructional content direct authority over the robot.
