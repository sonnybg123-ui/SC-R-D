from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchDesk:
    name: str
    mission: str
    risk_style: str


DESKS = {
    "victor": ResearchDesk(
        "Victor",
        "Lead trader/teacher: translate experiments into practical lessons.",
        "controlled",
    ),
    "alpha": ResearchDesk(
        "Alpha",
        "High-risk specialist: deliberately stress aggressive paper setups and document failure modes.",
        "aggressive-paper-only",
    ),
    "beta": ResearchDesk(
        "Beta",
        "High-risk specialist: test unconventional sizing and volatility assumptions in paper only.",
        "aggressive-paper-only",
    ),
    "structure": ResearchDesk(
        "Structure",
        "Market-structure desk: HH/HL/LH/LL, swing points, invalidation and timeframe discipline.",
        "evidence-first",
    ),
    "ledger": ResearchDesk(
        "Ledger",
        "Journal and statistics desk: make every experiment measurable and comparable.",
        "audit",
    ),
}
