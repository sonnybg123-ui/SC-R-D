from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Experiment:
    name: str
    hypothesis: str
    setup: str
    dataset: str
    assumptions: dict[str, Any]
    created_at: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValueError("experiment name is required")
        if not self.hypothesis.strip():
            raise ValueError("hypothesis is required")
        if not self.created_at:
            object.__setattr__(self, "created_at", datetime.now(timezone.utc).isoformat())

    @property
    def experiment_id(self) -> str:
        canonical = {
            "name": self.name,
            "hypothesis": self.hypothesis,
            "setup": self.setup,
            "dataset": self.dataset,
            "assumptions": self.assumptions,
        }
        raw = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]

    def to_dict(self) -> dict[str, Any]:
        return {"experiment_id": self.experiment_id, **asdict(self)}


def save_experiment(path: str | Path, experiment: Experiment) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(experiment.to_dict(), indent=2) + "\n", encoding="utf-8")
