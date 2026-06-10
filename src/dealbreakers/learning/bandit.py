"""Epsilon-greedy bandit policy for practice-only strategy selection (Phase 8E).

Not true RL — offline/practice learning only. Never explore on official buyers.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from random import Random
from typing import Any

MARKUP_ARMS = ("conservative", "balanced", "aggressive", "ceiling_minus_2")
SEARCH_ARMS = ("cheapest_valid", "best_reviewed", "best_luxury_fit", "best_profit_adjusted")
COUNTER_ARMS = ("slow_ladder", "luxury_jump", "total_based", "best_and_final")

ALL_ARM_TYPES = {
    "markup": MARKUP_ARMS,
    "search": SEARCH_ARMS,
    "counter": COUNTER_ARMS,
}


@dataclass
class StrategyArm:
    name: str
    type: str
    trials: int = 0
    successes: int = 0
    total_reward: float = 0.0
    average_reward: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StrategyArm:
        return cls(
            name=str(data["name"]),
            type=str(data["type"]),
            trials=int(data.get("trials", 0)),
            successes=int(data.get("successes", 0)),
            total_reward=float(data.get("total_reward", 0.0)),
            average_reward=float(data.get("average_reward", 0.0)),
        )


def _margin_points_estimate(markup_pct: float | None, offer_total: float | None) -> float:
    if markup_pct is None or offer_total is None or offer_total <= 0:
        return 0.0
    cost = offer_total / (1.0 + markup_pct / 100.0)
    margin = offer_total - cost
    return round(margin / 50.0, 2)


def _satisfaction_proxy(
    *,
    must_haves_matched: bool,
    review_score: float | None,
    duration_matched: bool,
    car_required: bool,
    car_present: bool,
) -> float:
    score = 0.0
    if must_haves_matched:
        score += 10.0
    if review_score is not None and review_score >= 9.0:
        score += 5.0
    if duration_matched:
        score += 5.0
    else:
        score -= 10.0
    if car_required and not car_present:
        score -= 10.0
    return score


def compute_reward(
    *,
    closed: bool,
    walked: bool,
    markup_pct: float | None = None,
    offer_total: float | None = None,
    must_haves_matched: bool = True,
    review_score: float | None = None,
    duration_matched: bool = True,
    car_required: bool = False,
    car_present: bool = False,
) -> float:
    """Practice reward: close bonus + margin + satisfaction - walk penalty."""
    reward = 0.0
    if closed:
        reward += 50.0
    if walked:
        reward -= 50.0
    reward += _margin_points_estimate(markup_pct, offer_total)
    reward += _satisfaction_proxy(
        must_haves_matched=must_haves_matched,
        review_score=review_score,
        duration_matched=duration_matched,
        car_required=car_required,
        car_present=car_present,
    )
    return round(reward, 2)


@dataclass
class BanditPolicy:
    arms: dict[str, StrategyArm] = field(default_factory=dict)
    _rng: Random = field(default_factory=Random, repr=False)

    def __post_init__(self) -> None:
        if not self.arms:
            self.arms = self._default_arms()

    @staticmethod
    def _default_arms() -> dict[str, StrategyArm]:
        arms: dict[str, StrategyArm] = {}
        for arm_type, names in ALL_ARM_TYPES.items():
            for name in names:
                key = f"{arm_type}:{name}"
                arms[key] = StrategyArm(name=name, type=arm_type)
        return arms

    def arms_for_type(self, arm_type: str) -> list[StrategyArm]:
        return [arm for arm in self.arms.values() if arm.type == arm_type]

    def choose_arm(
        self,
        context: dict[str, Any] | None = None,
        *,
        arm_type: str,
        epsilon: float = 0.1,
    ) -> StrategyArm:
        """Epsilon-greedy arm selection. context reserved for future persona features."""
        _ = context
        candidates = self.arms_for_type(arm_type)
        if not candidates:
            raise ValueError(f"No arms registered for type {arm_type!r}")

        if epsilon <= 0.0 or self._rng.random() >= epsilon:
            return max(candidates, key=lambda arm: arm.average_reward)

        return self._rng.choice(candidates)

    def update_arm(self, arm: StrategyArm, reward: float) -> None:
        key = f"{arm.type}:{arm.name}"
        stored = self.arms.get(key)
        if stored is None:
            stored = StrategyArm(name=arm.name, type=arm.type)
            self.arms[key] = stored

        stored.trials += 1
        stored.total_reward += reward
        stored.average_reward = stored.total_reward / stored.trials
        if reward > 0:
            stored.successes += 1

    def save(self, path: str | Path) -> None:
        payload = {
            "arms": {key: arm.to_dict() for key, arm in self.arms.items()},
        }
        out = Path(path)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> BanditPolicy:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        arms = {
            key: StrategyArm.from_dict(value)
            for key, value in (data.get("arms") or {}).items()
        }
        policy = cls(arms=arms or cls._default_arms())
        return policy

    def to_dict(self) -> dict[str, Any]:
        return {"arms": {key: arm.to_dict() for key, arm in self.arms.items()}}
