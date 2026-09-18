"""P625 parsing on real entities (FIX_AND_RESTYLE Part A).

Al-Farabi Kazakh National University (Q427677) has NO P625 claim on Wikidata (real response saved
in ``wikidata_entities_kaznu.json``), so ``no_coordinates`` is the correct outcome, not a parser
bug; MIT (Q49108) carries a normal-rank P625 and must parse.
"""

from __future__ import annotations

from app.resolver.wikidata import build_resolved, claim_values, coordinates, parse_header
from tests.conftest import read_fixture

KAZNU = "Q427677"
MIT = "Q49108"


def test_kaznu_entity_truly_has_no_p625() -> None:
    entity = read_fixture("wikidata_entities_kaznu.json")["entities"][KAZNU]
    assert "P625" not in entity["claims"]
    assert claim_values(entity, "P625", all_ranks=True) == []
    assert coordinates(entity) is None


def test_kaznu_header_keeps_everything_but_coords() -> None:
    entity = read_fixture("wikidata_entities_kaznu.json")["entities"][KAZNU]
    header = parse_header(entity)
    assert header.coords is None
    assert header.distance_to_city_center_km is None
    assert header.name == "Al-Farabi Kazakh National University"
    assert header.official_website == "https://farabi.university"
    assert header.commons_category == "Al-Farabi Kazakh National University"
    resolved = build_resolved(entity)
    assert resolved.main_image_filename  # P18 exists although P625 does not
    assert resolved.logo_filename is None or isinstance(resolved.logo_filename, str)


def test_mit_normal_rank_p625_is_parsed() -> None:
    entity = read_fixture("wikidata_entities_mit.json")["entities"][MIT]
    claims = entity["claims"]["P625"]
    assert all(c.get("rank") == "normal" for c in claims)  # no preferred rank anywhere
    coords = coordinates(entity)
    assert coords is not None
    assert abs(coords.lat - 42.3597) < 0.01 and abs(coords.lon + 71.0919) < 0.01


def test_preferred_rank_wins_but_normal_only_still_parses() -> None:
    def claim(lat: float, lon: float, rank: str, snaktype: str = "value") -> dict:
        snak: dict = {"snaktype": snaktype, "property": "P625"}
        if snaktype == "value":
            snak["datavalue"] = {
                "type": "globecoordinate",
                "value": {
                    "latitude": lat,
                    "longitude": lon,
                    "globe": "http://www.wikidata.org/entity/Q2",
                },
            }
        return {"mainsnak": snak, "rank": rank, "type": "statement"}

    normal_only = {"id": "Q1", "claims": {"P625": [claim(1.0, 2.0, "normal")]}}
    assert coordinates(normal_only) is not None and coordinates(normal_only).lat == 1.0
    mixed = {
        "id": "Q2",
        "claims": {
            "P625": [
                claim(0.0, 0.0, "normal", snaktype="somevalue"),
                claim(5.0, 6.0, "normal"),
                claim(7.0, 8.0, "preferred"),
            ]
        },
    }
    parsed = coordinates(mixed)
    assert parsed is not None and (parsed.lat, parsed.lon) == (7.0, 8.0)
    deprecated_only = {"id": "Q3", "claims": {"P625": [claim(9.0, 9.0, "deprecated")]}}
    assert coordinates(deprecated_only) is None
