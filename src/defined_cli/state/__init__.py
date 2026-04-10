"""State layer -- persistence, blackboard, and world model.

This package contains the robot's persistent state, spatial memory
(blackboard), and world model. It has no CLI-specific dependencies
(no click, rich, or textual) so it can be extracted to a shared
library in the future.
"""

from __future__ import annotations
