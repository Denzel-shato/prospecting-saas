"""First-party, non-US location detection (Issue: worldwide ICP geography coverage).

Before this module, non-US bases were recognised only from "based/located/offices in <one of ~60 listed
places>". Common first-party wording ("Copenhagen-based product studio", a footer address that ends in a
country, a JSON-LD PostalAddress) left geography unknown, which capped otherwise good worldwide studios at
"possible". Detection here stays conservative: a place counts only from a SELF-referential statement, an
address-like block, or the organisation's own JSON-LD address; US states following a city veto it.
"""

from __future__ import annotations

import json
import re
from functools import lru_cache

# Sovereign states and common names/aliases. The US and India are handled by dedicated evidence types.
_COUNTRIES = (
    "Afghanistan|Albania|Algeria|Andorra|Angola|Argentina|Armenia|Australia|Austria|Azerbaijan|Bahamas|Bahrain|"
    "Bangladesh|Barbados|Belarus|Belgium|Belize|Benin|Bhutan|Bolivia|Bosnia(?: and Herzegovina)?|Botswana|Brazil|"
    "Brunei|Bulgaria|Cambodia|Cameroon|Canada|Chile|China|Colombia|Costa Rica|Croatia|Cuba|Cyprus|Czech Republic|"
    "Czechia|Denmark|Dominican Republic|Ecuador|Egypt|El Salvador|England|Estonia|Ethiopia|Finland|France|"
    "Georgia \\(country\\)|Germany|Ghana|Greece|Guatemala|Honduras|Hong Kong|Hungary|Iceland|Indonesia|Iran|Iraq|"
    "Ireland|Israel|Italy|Jamaica|Japan|Jordan|Kazakhstan|Kenya|Kosovo|Kuwait|Kyrgyzstan|Latvia|Lebanon|Libya|"
    "Liechtenstein|Lithuania|Luxembourg|Macau|Malaysia|Malta|Mauritius|Mexico|Moldova|Monaco|Mongolia|Montenegro|"
    "Morocco|Mozambique|Myanmar|Namibia|Nepal|(?:The )?Netherlands|Holland|New Zealand|Nicaragua|Nigeria|"
    "North Macedonia|Northern Ireland|Norway|Oman|Pakistan|Palestine|Panama|Paraguay|Peru|Philippines|Poland|"
    "Portugal|Puerto Rico|Qatar|Romania|Russia|Rwanda|Saudi Arabia|Scotland|Senegal|Serbia|Singapore|Slovakia|"
    "Slovenia|South Africa|South Korea|Spain|Sri Lanka|Sweden|Switzerland|Taiwan|Tanzania|Thailand|Tunisia|"
    "Turkey|Türkiye|Uganda|Ukraine|United Arab Emirates|United Kingdom|Uruguay|UAE|UK|Uzbekistan|Venezuela|"
    "Vietnam|Wales|Zambia|Zimbabwe"
)
# Major non-US, non-Indian tech/agency hubs. Names that are also common US towns are accepted only when no US
# state/ZIP follows (see _US_FOLLOW). Deliberately omitted as too ambiguous: Birmingham, Cambridge, Portland,
# Richmond, Hamilton, Newcastle, Kingston, Victoria, Lincoln, Athens, Valencia, Alexandria.
_CITIES = (
    "London|Manchester|Bristol|Edinburgh|Glasgow|Leeds|Brighton|Belfast|Cardiff|Oxford|Nottingham|Sheffield|"
    "Liverpool|Toronto|Vancouver|Montreal|Montréal|Ottawa|Calgary|Edmonton|Winnipeg|Halifax|Sydney|Melbourne|"
    "Brisbane|Perth|Adelaide|Canberra|Auckland|Wellington|Christchurch|Berlin|Munich|München|Hamburg|Cologne|Köln|"
    "Frankfurt|Stuttgart|Düsseldorf|Leipzig|Dresden|Nuremberg|Vienna|Wien|Graz|Zurich|Zürich|Geneva|Basel|Bern|"
    "Lausanne|Amsterdam|Rotterdam|Utrecht|Eindhoven|The Hague|Brussels|Antwerp|Ghent|Paris|Lyon|Marseille|"
    "Toulouse|Bordeaux|Nantes|Lille|Madrid|Barcelona|Málaga|Malaga|Seville|Sevilla|Bilbao|Lisbon|Lisboa|Porto|"
    "Rome|Milan|Milano|Turin|Torino|Bologna|Florence|Naples|Dublin|Cork|Galway|Copenhagen|København|Aarhus|"
    "Stockholm|Gothenburg|Göteborg|Malmö|Oslo|Bergen|Helsinki|Tampere|Reykjavik|Tallinn|Tartu|Riga|Vilnius|Kaunas|"
    "Warsaw|Warszawa|Krakow|Kraków|Wroclaw|Wrocław|Gdansk|Gdańsk|Poznan|Poznań|Prague|Praha|Brno|Bratislava|"
    "Budapest|Bucharest|Cluj-Napoca|Cluj|Timisoara|Sofia|Plovdiv|Belgrade|Zagreb|Ljubljana|Sarajevo|Skopje|"
    "Tirana|Athens|Thessaloniki|Kyiv|Kiev|Lviv|Kharkiv|Minsk|Tbilisi|Yerevan|Baku|Istanbul|Ankara|Izmir|"
    "Tel Aviv|Jerusalem|Haifa|Dubai|Abu Dhabi|Riyadh|Doha|Cairo|Lagos|Abuja|Nairobi|Accra|Kigali|Kampala|"
    "Addis Ababa|Cape Town|Johannesburg|Durban|Pretoria|Harare|Bulawayo|Lusaka|Casablanca|Tunis|Mexico City|"
    "Guadalajara|Monterrey|Bogotá|Bogota|Medellín|Medellin|Lima|Santiago|Buenos Aires|Montevideo|São Paulo|"
    "Sao Paulo|Rio de Janeiro|Curitiba|Belo Horizonte|Porto Alegre|Florianópolis|San José|Panama City|Singapore|"
    "Kuala Lumpur|Jakarta|Bali|Bangkok|Chiang Mai|Hanoi|Ho Chi Minh City|Saigon|Manila|Cebu|Taipei|Seoul|Tokyo|"
    "Osaka|Kyoto|Shanghai|Beijing|Shenzhen|Hong Kong|Karachi|Lahore|Islamabad|Dhaka|Colombo|Kathmandu"
)
_PLACES = f"(?:{_COUNTRIES}|{_CITIES})"
_US_FOLLOW_CACHE: re.Pattern | None = None

# Self-referential nouns: "<Place>-based product studio" must describe the company itself.
_SELF_NOUN = (r"(?:studio|agency|team|company|firm|consultancy|consultants|shop|collective|practice|"
              r"business|boutique|developers|engineers|designers|partnership|house|lab|labs)")
_SELF_LEAD = r"(?:^|[.!?]\s+|\b(?i:we(?:['’]re| are)|is|our|are)\s+)(?i:an?\s+|the\s+)?"


@lru_cache(maxsize=1)
def _compiled() -> dict:
    from .evidence import _ABBR_ALT, _NAME_ALT  # lazy: evidence imports this module

    us_follow = rf"(?!\s*,?\s*(?:(?:{_ABBR_ALT})\b|(?i:{_NAME_ALT})\b|\d{{5}}\b))"
    place = rf"({_PLACES})\b{us_follow}"
    return {
        "hyphen": re.compile(
            rf"{_SELF_LEAD}{place}-based(?:\s+[\w&'’/-]+){{0,3}}?\s+{_SELF_NOUN}\b"),
        "based_in": re.compile(
            rf"\b(?i:based|headquartered|located|offices?)\s+(?i:in)\s+"
            rf"(?:[A-Z][\w.'’\-]+(?:\s+[A-Z][\w.'’\-]+)*,?\s+)?{place}"),
        # A short address-like block that ENDS in a country ("8001 Zürich, Switzerland", "Auckland, New Zealand").
        "address_tail": re.compile(rf"^(?=[^.!?]{{0,140}}$)[^.!?]*?,\s*(?P<place>{_COUNTRIES})\s*\.?$"),
    }


def find_text_place(text: str):
    """(match, place) for a self-referential non-US base statement in one first-party text block, else None."""
    pats = _compiled()
    for key in ("hyphen", "based_in", "address_tail"):
        m = pats[key].search(text)
        if m:
            place = m.group("place") if key == "address_tail" else m.group(m.lastindex)
            return m, place
    return None


_ORG_TYPES = {"organization", "localbusiness", "professionalservice", "corporation", "softwarecompany",
              "onlinebusiness", "ngo"}


def _types(node: dict) -> set[str]:
    t = node.get("@type")
    return {str(x).lower() for x in (t if isinstance(t, list) else [t])}


def _country_of(address) -> str | None:
    if not isinstance(address, dict):
        return None
    c = address.get("addressCountry")
    if isinstance(c, dict):
        c = c.get("name")
    return c.strip() if isinstance(c, str) and c.strip() else None


def jsonld_org_countries(page) -> list[tuple[str, str]]:
    """[(raw_jsonld_text, country_string)] for the page's OWN organisation nodes' postal addresses.

    Only top-level Organization-like nodes count (not reviews, authors, clients or events nested elsewhere)."""
    out: list[tuple[str, str]] = []
    for raw in getattr(page, "jsonld_raw", []):
        try:
            data = json.loads(raw)
        except ValueError:
            continue
        roots = data.get("@graph", [data]) if isinstance(data, dict) else data
        for node in roots if isinstance(roots, list) else [roots]:
            if not isinstance(node, dict) or not (_types(node) & _ORG_TYPES):
                continue
            addrs = node.get("address")
            for addr in addrs if isinstance(addrs, list) else [addrs]:
                country = _country_of(addr)
                if country and country not in [c for r, c in out if r == raw]:
                    out.append((raw, country))
    return out


def country_kind(country: str) -> str:
    """'us' | 'india' | 'other' for a JSON-LD addressCountry (ISO-2/3 code or English name)."""
    c = country.strip().lower().rstrip(".")
    if c in {"us", "usa", "united states", "united states of america", "u.s.", "u.s.a."}:
        return "us"
    if c in {"in", "ind", "india", "republic of india"}:
        return "india"
    return "other"


def jsonld_excerpt(raw: str, country: str) -> re.Match | None:
    """The verbatim `addressCountry` fragment of the raw JSON-LD, so the excerpt re-verifies against the page."""
    esc = re.escape(country)
    for pat in (rf'"addressCountry"\s*:\s*"{esc}"', rf'"addressCountry"\s*:\s*\{{[^{{}}]*?"name"\s*:\s*"{esc}"[^{{}}]*?\}}'):
        m = re.search(pat, raw)
        if m:
            return m
    return None
