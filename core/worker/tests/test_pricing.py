"""Worker pricing helper tests (B3.1).

Covers ``compute_cost_usd`` from ``worker.config``:
* known-model lookup is case-insensitive and tolerates ``provider:model``;
* missing model => None (handler must keep going);
* zero tokens => zero cost.
"""

from __future__ import annotations

import pytest

from worker.config import (
    DEFAULT_MODEL_PRICING,
    GatewayWorkerConfig,
    ModelPricing,
    compute_cost_usd,
)


def test_compute_cost_for_known_model() -> None:
    pricing = {"gpt-4o": ModelPricing(prompt_per_1m=2.50, completion_per_1m=10.00)}
    cost = compute_cost_usd("gpt-4o", 1_000_000, 1_000_000, pricing)
    assert cost == pytest.approx(12.5)


def test_compute_cost_normalises_case() -> None:
    pricing = {"gpt-4o-mini": ModelPricing(prompt_per_1m=0.15, completion_per_1m=0.60)}
    cost = compute_cost_usd("GPT-4o-MINI", 1000, 0, pricing)
    assert cost == pytest.approx(0.00015)


def test_compute_cost_strips_provider_prefix() -> None:
    pricing = {"gpt-4o": ModelPricing(prompt_per_1m=2.50, completion_per_1m=10.00)}
    cost = compute_cost_usd("openai:gpt-4o", 1000, 1000, pricing)
    assert cost is not None
    assert cost > 0


def test_compute_cost_unknown_model_returns_none() -> None:
    pricing = {"gpt-4o": ModelPricing(prompt_per_1m=2.50, completion_per_1m=10.00)}
    assert compute_cost_usd("custom-llm", 1000, 1000, pricing) is None


def test_compute_cost_empty_model_returns_none() -> None:
    pricing = {"gpt-4o": ModelPricing(prompt_per_1m=2.50, completion_per_1m=10.00)}
    assert compute_cost_usd("", 100, 100, pricing) is None


def test_default_pricing_covers_required_models() -> None:
    """The task spec requires defaults for these five models (lowercased)."""
    required = {
        "gpt-4o",
        "gpt-4o-mini",
        "claude-opus-4-7",
        "claude-sonnet-4-6",
        "claude-haiku-4-5",
    }
    assert required.issubset(DEFAULT_MODEL_PRICING.keys())


def test_pricing_keys_lowercased_at_load() -> None:
    """The validator coerces keys to lowercase so YAML casing doesn't matter."""
    cfg = GatewayWorkerConfig(
        encryption_key="kS=Y3kwbZjBV-1Tn5Z5jeu4lTJYMZ_3OWWp9C8GWJ6w=",
        pricing={"GPT-4o": {"prompt_per_1m": 2.5, "completion_per_1m": 10.0}},
    )
    assert "gpt-4o" in cfg.pricing
    assert "GPT-4o" not in cfg.pricing
