from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchDesk:
    name: str
    mission: str
    risk_style: str


DESKS = {
    "victor": ResearchDesk(
        "Vic",
        "Victor Price / Vic: R&D lead, integrator, evidence adjudicator, head trader and teacher.",
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
    "ben": ResearchDesk("Ben", "Benjamin Vale / Ben: fundamental, catalyst, materiality and Guardian perspective.", "evidence-first"),
    "jah": ResearchDesk("Jah", "Jah: execution operations, data quality, reconciliation and log integrity.", "audit"),
}
