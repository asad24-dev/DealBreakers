"""Tests for practice-only bandit policy (Phase 8E)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dealbreakers.learning.bandit import BanditPolicy, StrategyArm, compute_reward


def test_epsilon_zero_chooses_best_arm() -> None:
    policy = BanditPolicy()
    for key, arm in policy.arms.items():
        if arm.type == "markup":
            policy.update_arm(arm, 1.0 if arm.name == "balanced" else 0.0)

    chosen = policy.choose_arm(arm_type="markup", epsilon=0.0)
    assert chosen.name == "balanced"


def test_epsilon_one_explores() -> None:
    policy = BanditPolicy()
    policy._rng.seed(0)
    for key, arm in policy.arms.items():
        if arm.type == "markup":
            policy.update_arm(arm, 10.0 if arm.name == "balanced" else 0.0)

    seen = {policy.choose_arm(arm_type="markup", epsilon=1.0).name for _ in range(30)}
    assert len(seen) > 1


def test_rewards_update_averages() -> None:
    arm = StrategyArm(name="balanced", type="markup")
    policy = BanditPolicy()
    policy.update_arm(arm, 10.0)
    policy.update_arm(arm, 20.0)
    stored = policy.arms["markup:balanced"]
    assert stored.trials == 2
    assert stored.total_reward == 30.0
    assert stored.average_reward == 15.0


def test_closed_deal_gets_positive_reward() -> None:
    reward = compute_reward(closed=True, walked=False, markup_pct=10.0, offer_total=1100.0)
    assert reward > 0


def test_walk_gets_penalty() -> None:
    baseline = compute_reward(
        closed=False,
        walked=False,
        must_haves_matched=False,
        duration_matched=True,
    )
    walked = compute_reward(
        closed=False,
        walked=True,
        must_haves_matched=False,
        duration_matched=True,
    )
    assert walked == baseline - 50.0


def test_duration_mismatch_lowers_reward() -> None:
    matched = compute_reward(closed=True, walked=False, duration_matched=True)
    mismatched = compute_reward(closed=True, walked=False, duration_matched=False)
    assert mismatched < matched


def test_missing_car_lowers_reward() -> None:
    with_car = compute_reward(
        closed=True, walked=False, car_required=True, car_present=True
    )
    without_car = compute_reward(
        closed=True, walked=False, car_required=True, car_present=False
    )
    assert without_car < with_car


def test_save_load_policy(tmp_path: Path) -> None:
    policy = BanditPolicy()
    arm = policy.arms["markup:aggressive"]
    policy.update_arm(arm, 42.0)
    path = tmp_path / "policy.json"
    policy.save(path)

    loaded = BanditPolicy.load(path)
    assert loaded.arms["markup:aggressive"].average_reward == pytest.approx(42.0)
    assert json.loads(path.read_text(encoding="utf-8"))["arms"]["markup:aggressive"]["trials"] == 1
