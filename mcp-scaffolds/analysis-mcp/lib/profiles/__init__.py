"""analysis-mcp/lib/profiles — bounded analysis profile engine.

Public re-exports for external consumers. Internal helpers stay in the
individual modules.

Ported from xm-mt5-trading-platform/src/analysis/:
  profile_models.py   → models.py
  profile_registry.py → registry.py
  profile_runner.py   → runner.py
  opportunity_ranker.py → opportunity_ranker.py (rewritten, DISCARD deps removed)
"""

from .models import (
    AnalysisChainConfig,
    AnalysisChainResult,
    AnalysisGate,
    AnalysisProfileContext,
    AnalysisProfileDefinition,
    AnalysisProfileExecutionStatus,
    AnalysisProfileResult,
    AnalysisTimingWindow,
)
from .registry import ProfileEvaluator, ProfileRegistry
from .runner import ProfileRunner
from .opportunity_ranker import (
    ConfidenceBand,
    OpportunityDirective,
    OpportunityInput,
    OpportunityRanker,
    OpportunityRankerResult,
    RankerSettings,
)

__all__ = [
    # models
    "AnalysisChainConfig",
    "AnalysisChainResult",
    "AnalysisGate",
    "AnalysisProfileContext",
    "AnalysisProfileDefinition",
    "AnalysisProfileExecutionStatus",
    "AnalysisProfileResult",
    "AnalysisTimingWindow",
    # registry
    "ProfileEvaluator",
    "ProfileRegistry",
    # runner
    "ProfileRunner",
    # ranker
    "ConfidenceBand",
    "OpportunityDirective",
    "OpportunityInput",
    "OpportunityRanker",
    "OpportunityRankerResult",
    "RankerSettings",
]
