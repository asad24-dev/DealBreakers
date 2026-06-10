from dealbreakers.experiments.ported_improvements import REGISTRY, ported_features


def test_registry_has_entries():
    assert len(REGISTRY) >= 8


def test_ported_features_includes_core_ports():
    features = ported_features()
    assert "total_based_counter" in features
    assert "desired_nights_search" in features
    assert "negotiation_strategist" in features


def test_llm_pricing_not_ported():
    rejected = [item for item in REGISTRY if item.feature == "llm_pricing_strategist"]
    assert rejected and not rejected[0].ported
