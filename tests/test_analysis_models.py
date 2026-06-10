import json
from unittest.mock import MagicMock

from dealbreakers.analysis import (
    ConversationAnalysis,
    ConversationAnalyzer,
    events_from_log_records,
)
from dealbreakers.analysis.prompts import build_user_prompt
from dealbreakers.models.transcript import TranscriptEvent


# --- ConversationAnalysis.from_dict: always fully populated ---


def test_from_dict_full_payload() -> None:
    analysis = ConversationAnalysis.from_dict({
        "trip_type": "holiday",
        "destinations": ["Spain", "Tenerife"],
        "must_haves": ["pool"],
        "nice_to_haves": ["spa"],
        "budget_min": 500,
        "budget_max": 1500,
        "price_sensitivity": 0.7,
        "trust_sensitivity": 0.2,
        "luxury_preference": 0.4,
        "objections": ["that's too expensive"],
        "confidence": 0.8,
    })

    assert analysis.trip_type == "holiday"
    assert analysis.destinations == ["Spain", "Tenerife"]
    assert analysis.budget_min == 500.0
    assert analysis.budget_max == 1500.0
    assert analysis.price_sensitivity == 0.7
    assert analysis.confidence == 0.8


def test_from_dict_empty_payload_populates_all_fields() -> None:
    analysis = ConversationAnalysis.from_dict({})

    assert analysis.trip_type is None
    assert analysis.destinations == []
    assert analysis.must_haves == []
    assert analysis.nice_to_haves == []
    assert analysis.budget_min is None
    assert analysis.budget_max is None
    assert analysis.price_sensitivity == 0.0
    assert analysis.trust_sensitivity == 0.0
    assert analysis.luxury_preference == 0.0
    assert analysis.objections == []
    assert analysis.confidence == 0.0


def test_from_dict_clamps_scores_to_unit_interval() -> None:
    analysis = ConversationAnalysis.from_dict({
        "price_sensitivity": 7,
        "trust_sensitivity": -3,
        "luxury_preference": "not a number",
        "confidence": 1.5,
    })

    assert analysis.price_sensitivity == 1.0
    assert analysis.trust_sensitivity == 0.0
    assert analysis.luxury_preference == 0.0
    assert analysis.confidence == 1.0


def test_from_dict_rejects_unknown_trip_type_and_swaps_budget() -> None:
    analysis = ConversationAnalysis.from_dict({
        "trip_type": "cruise",
        "budget_min": 2000,
        "budget_max": 800,
    })

    assert analysis.trip_type is None
    assert analysis.budget_min == 800.0
    assert analysis.budget_max == 2000.0


def test_to_dict_round_trip() -> None:
    original = ConversationAnalysis(
        trip_type="tour",
        destinations=["Spain"],
        must_haves=["guided tour"],
        price_sensitivity=0.5,
        confidence=0.6,
    )
    rebuilt = ConversationAnalysis.from_dict(original.to_dict())
    assert rebuilt == original


def test_to_dict_is_json_serializable() -> None:
    payload = ConversationAnalysis().to_dict()
    assert json.loads(json.dumps(payload)) == payload


# --- analyzer with injected fake OpenAI client ---


def make_fake_openai(content: str) -> MagicMock:
    client = MagicMock()
    message = MagicMock()
    message.content = content
    client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=message)]
    )
    return client


def make_event(role: str, text: str) -> TranscriptEvent:
    return TranscriptEvent(
        match_id="m1",
        persona_id="practice-bob",
        scenario_name="Bob Ross",
        round_number=1,
        role=role,
        text=text,
    )


def test_analyzer_parses_strict_json() -> None:
    fake = make_fake_openai(json.dumps({
        "trip_type": "holiday",
        "destinations": ["Spain"],
        "must_haves": ["pool"],
        "nice_to_haves": [],
        "budget_min": None,
        "budget_max": None,
        "price_sensitivity": 0.1,
        "trust_sensitivity": 0.0,
        "luxury_preference": 0.3,
        "objections": [],
        "confidence": 0.5,
    }))
    analyzer = ConversationAnalyzer(client=fake, model="test-model")

    analysis = analyzer.analyze([make_event("buyer", "I want a sunny week with a pool")])

    assert analysis.trip_type == "holiday"
    assert analysis.must_haves == ["pool"]
    call_kwargs = fake.chat.completions.create.call_args.kwargs
    assert call_kwargs["response_format"] == {"type": "json_object"}
    assert call_kwargs["model"] == "test-model"


def test_analyzer_survives_malformed_llm_output() -> None:
    fake = make_fake_openai("this is not json")
    analyzer = ConversationAnalyzer(client=fake, model="test-model")

    analysis = analyzer.analyze([make_event("buyer", "hello")])

    # All fields populated with safe defaults, no exception.
    assert analysis == ConversationAnalysis()


# --- transcript helpers ---


def test_events_from_log_records_roundtrip() -> None:
    records = [
        {"record_type": "match_started", "match_id": "m1"},
        {
            "record_type": "buyer_message",
            "match_id": "m1",
            "persona_id": "practice-bob",
            "scenario_name": "Bob Ross",
            "round_number": None,
            "text": "Hi, beach please",
            "action": "continue",
        },
        {
            "record_type": "seller_message",
            "match_id": "m1",
            "round_number": 1,
            "text": "Spain or Greece?",
            "offer": None,
        },
        {
            "record_type": "turn_response",
            "match_id": "m1",
            "buyer_text": "Spain! And a pool.",
            "buyer_action": "continue",
            "quote": None,
            "result": None,
        },
    ]

    events = events_from_log_records(records)

    assert [event.role for event in events] == ["buyer", "seller", "buyer"]
    assert events[2].text == "Spain! And a pool."


def test_user_prompt_includes_dialogue_and_offer_marker() -> None:
    events = [
        make_event("buyer", "I want sun"),
        TranscriptEvent(
            match_id="m1",
            persona_id=None,
            scenario_name=None,
            round_number=2,
            role="seller",
            text="Here is a deal",
            offer={"holiday": {"priceTotal": 978.0}, "markupPct": 8},
        ),
    ]

    prompt = build_user_prompt(events)

    assert "BUYER: I want sun" in prompt
    assert "SELLER: Here is a deal" in prompt
    assert "SELLER SENT OFFER: price=978.0, markupPct=8" in prompt
