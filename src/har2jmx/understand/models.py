"""Shared evidence-gated detection primitives for Milestone 3."""

from __future__ import annotations

from dataclasses import dataclass, field

_CONF_ORDER = {"High": 0, "Medium": 1, "Low": 2}


def _stronger(a: str, b: str) -> str:
    return a if _CONF_ORDER.get(a, 3) <= _CONF_ORDER.get(b, 3) else b


@dataclass
class Detection:
    """A detected fact backed by evidence. Never emitted without at least one evidence string."""
    name: str
    confidence: str = "Medium"          # High | Medium | Low
    evidence: list[str] = field(default_factory=list)


class EvidenceBag:
    """Accumulates evidence per detected name; keeps the strongest confidence and dedupes evidence."""

    def __init__(self) -> None:
        self._items: dict[str, Detection] = {}

    def add(self, name: str, evidence: str, confidence: str = "Medium") -> None:
        det = self._items.get(name)
        if det is None:
            self._items[name] = Detection(name=name, confidence=confidence, evidence=[evidence])
        else:
            if evidence not in det.evidence:
                det.evidence.append(evidence)
            det.confidence = _stronger(det.confidence, confidence)

    def results(self) -> list[Detection]:
        return sorted(self._items.values(), key=lambda d: (_CONF_ORDER.get(d.confidence, 3), d.name))

    def names(self) -> list[str]:
        return [d.name for d in self.results()]
