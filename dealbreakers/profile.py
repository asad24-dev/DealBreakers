from __future__ import annotations

import re
from dataclasses import dataclass, field


DESTINATION_HINTS = {
    "spain": "Spain",
    "majorca": "Spain",
    "mallorca": "Spain",
    "canary": "Spain",
    "tenerife": "Spain",
    "italy": "Italy",
    "amalfi": "Italy",
    "greece": "Greece",
    "portugal": "Portugal",
    "france": "France",
    "paris": "France",
    "london": "United Kingdom",
    "berlin": "Germany",
    "amsterdam": "Netherlands",
    "stockholm": "Sweden",
    "turkey": "Turkey",
}

CITY_HINTS = {
    "berlin": "Berlin",
    "paris": "Paris",
    "amsterdam": "Amsterdam",
    "london": "London",
    "stockholm": "Stockholm",
    "barcelona": "Barcelona",
    "madrid": "Madrid",
    "rome": "Rome",
    "lisbon": "Lisbon",
    "prague": "Prague",
    "vienna": "Vienna",
    "majorca": "Majorca",
    "mallorca": "Majorca",
    "tenerife": "Tenerife",
}


@dataclass
class BuyerProfile:
    scenario_name: str = ""
    scenario_brief: str = ""
    product_preference: str = "unknown"  # holiday | tour | city_break | unknown
    destination: str = ""
    place: str = ""  # more specific than country, e.g. "Berlin" or "Majorca"
    destination_flexible: bool = False
    party_size: int | None = None
    adults: int | None = None
    children: int | None = None
    infants: int | None = None
    child_ages_unknown: bool = False
    nights: int | None = None
    departure_months: str = ""
    budget: float | None = None
    wants_car: bool | None = None
    car_preference: str = ""  # e.g. "premium", "automatic", "suv"
    luxury_weight: float = 0.0
    price_sensitivity: float = 0.0
    must_haves: set[str] = field(default_factory=set)
    objections: list[str] = field(default_factory=list)

    def missing_critical_fields(self) -> list[str]:
        """Info worth asking about. Never blocks searching: see ready_to_search()."""
        missing: list[str] = []
        if self.product_preference == "unknown":
            missing.append("trip style")
        if not self.destination and not self.destination_flexible:
            missing.append("destination")
        if self.party_size is None:
            missing.append("party size")
        if self.child_ages_unknown:
            missing.append("children ages")
        if self.nights is None and self.product_preference != "tour":
            missing.append("duration")
        if self.budget is None:
            missing.append("budget")
        return missing

    def ready_to_search(self) -> bool:
        """We can hit the MCPs as soon as we know (or can assume) the trip style.
        TravelSupermarket supports destination-less search, party defaults to 2 adults."""
        return self.product_preference != "unknown" or bool(self.destination) or self.destination_flexible


def infer_profile(scenario_name: str, scenario_brief: str, messages: list[str]) -> BuyerProfile:
    text = " ".join([scenario_name, scenario_brief, *messages]).lower()
    profile = BuyerProfile(scenario_name=scenario_name, scenario_brief=scenario_brief)

    if any(word in text for word in ["tour", "guided", "operator", "multi-day", "itinerary"]):
        profile.product_preference = "tour"
    elif any(word in text for word in ["city", "capital", "museum", "tech", "conference"]):
        profile.product_preference = "city_break"
    elif any(word in text for word in ["beach", "sun", "warm", "pool", "resort", "family"]):
        profile.product_preference = "holiday"

    for hint, country in DESTINATION_HINTS.items():
        if hint in text:
            profile.destination = country
            break

    for hint, city in CITY_HINTS.items():
        if hint in text:
            profile.place = city
            break

    if not profile.destination and any(
        phrase in text
        for phrase in ["anywhere", "pretty open", "open to", "flexible on where", "don't mind where", "no preference"]
    ):
        profile.destination_flexible = True

    party_match = re.search(r"\b(family of|party of|group of|we are)\s+(\d+)\b", text)
    if party_match:
        profile.party_size = int(party_match.group(2))
        if "family" in party_match.group(1) and profile.party_size > 2:
            profile.adults = 2
            profile.children = profile.party_size - 2
            profile.child_ages_unknown = True
    elif "couple" in text or "two of us" in text:
        profile.party_size = 2
    elif "family of four" in text:
        profile.party_size = 4
        profile.adults = 2
        profile.children = 2
        profile.child_ages_unknown = True

    if "couple" in text or "two of us" in text:
        profile.adults = 2

    age_match = re.search(r"(\d+)\s*(?:children|kids).+?(\d+)\s*(?:infants|babies|under 2)", text)
    if age_match:
        profile.children = int(age_match.group(1))
        profile.infants = int(age_match.group(2))
        profile.child_ages_unknown = False

    if "no infants" in text or "no under 2" in text or "none under 2" in text:
        profile.infants = 0
        profile.child_ages_unknown = False

    month_map = {
        "january": "1",
        "february": "2",
        "march": "3",
        "april": "4",
        "may": "5",
        "june": "6",
        "july": "7",
        "august": "8",
        "september": "9",
        "october": "10",
        "november": "11",
        "december": "12",
        "summer": "6,7,8",
    }
    for word, value in month_map.items():
        if word in text:
            profile.departure_months = value
            break

    night_match = re.search(r"\b(\d+)\s*(?:nights?|days?)\b", text)
    if night_match:
        profile.nights = int(night_match.group(1))
    elif "week" in text:
        profile.nights = 7
    elif "weekend" in text:
        profile.nights = 3

    budget_match = re.search(r"(?:£|gbp|budget(?: is| of| around)?\s*)\s*(\d{3,6})", text)
    if budget_match:
        profile.budget = float(budget_match.group(1))

    if any(word in text for word in ["rental car", "hire car", "need a car", "premium car"]):
        profile.wants_car = True
    if any(word in text for word in ["premium car", "luxury car", "nice car", "convertible", "sports car"]):
        profile.car_preference = "premium"
    if any(word in text for word in ["no car", "don't need a car", "without a car"]):
        profile.wants_car = False

    if any(word in text for word in ["luxury", "5-star", "five-star", "premium", "best"]):
        profile.luxury_weight += 0.6
    if any(word in text for word in ["cheap", "tight", "budget", "too expensive", "over budget"]):
        profile.price_sensitivity += 0.6
    if any(word in text for word in ["perfect", "exceptional", "perfectionist"]):
        profile.luxury_weight += 0.3

    amenity_hints = {
        "pool": "pool",
        "beach": "close_to_beach",
        "kids": "kids_club",
        "children": "family_friendly",
        "spa": "spa",
        "wifi": "wifi",
        "gym": "gym",
        "air con": "air_conditioning",
        "wheelchair": "wheelchair_access",
        "nightlife": "nightclub",
    }
    for word, amenity in amenity_hints.items():
        if re.search(rf"\b{re.escape(word)}\b", text):
            profile.must_haves.add(amenity)

    if "too expensive" in text or "over budget" in text:
        profile.objections.append("price")
    if "not quite" in text or "doesn't fit" in text:
        profile.objections.append("fit")

    return profile
