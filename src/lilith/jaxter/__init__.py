"""Jaxter strategy-assistant research engine.

Jaxter is additive and observational. It has no dependency on Edith runtime,
execution, risk, adaptation, or broker modules.
"""

from .backtest import AMDStructureBacktester, summarize
from .engine import AMDStructureEngine
from .models import AMDStructureConfig, AMDStructureSignal, BacktestTrade, Direction, EntryZone, Outcome
from .research import JaxterResearchRunner

__all__ = [
    "AMDStructureBacktester",
    "AMDStructureConfig",
    "AMDStructureEngine",
    "AMDStructureSignal",
    "BacktestTrade",
    "Direction",
    "EntryZone",
    "JaxterResearchRunner",
    "Outcome",
    "summarize",
]
