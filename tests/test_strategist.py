from dealbreakers.negotiation.actions import NegotiationAction
from dealbreakers.negotiation.strategist import NegotiationStrategist, feels_overcharged
from dealbreakers.state.buyer_state import BuyerState


def test_fallback_brief_luxury_impatient():
    state = BuyerState(luxury_preference=1.0)
    brief = NegotiationStrategist(client=object()).advise(
        state,
        "stop asking and show me a concrete package right now",
        NegotiationAction.OFFER,
    )
    assert brief.archetype == "luxury_impatient"
    assert brief.impatience >= 0.5
    assert brief.persuasion_angles


def test_feels_overcharged_detected():
    assert feels_overcharged("That price is absolutely outrageous")


def test_brief_serializes():
    state = BuyerState()
    brief = NegotiationStrategist(client=object()).advise(
        state, "hello", NegotiationAction.DISCOVER
    )
    payload = brief.to_dict()
    assert "archetype" in payload
    assert "tone_hint" in payload
