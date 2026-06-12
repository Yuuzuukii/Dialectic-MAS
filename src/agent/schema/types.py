"""議論システム全体で共有する Literal 型エイリアス定義."""

from typing import Literal

AgentName = Literal["AG1", "AG2"]
DebateStage = Literal["ag1_main_thread", "ag2_main_thread"]
ArgumentType = Literal["main", "defeat", "counter"]
AttackType = Literal["rebut", "undercut"]
ArgumentStatus = Literal["justified", "overruled", "defensible", "undetermined"]
