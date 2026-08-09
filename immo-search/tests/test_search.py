"""Test suite for the search engine. Standard library only: python3 -m unittest."""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from immo.criteria import Criteria, CriteriaError, matches
from immo.engine import Index
from immo.model import (
    KIND_ANCIEN, KIND_NEUF, Listing, Station, detect_features, make_id,
    price_plausibility,
)
from immo.server import Api
from immo.store import listing_from_dict


def flat(**kwargs) -> Listing:
    base = dict(
        id=make_id(kwargs.get("name", "x"), kwargs.get("city", "y")),
        kind=KIND_NEUF, source="test", name="Résidence", city="Créteil",
        dept="94", zone_abc="A", rooms=4, surface=82.0, price=410_000,
        address_precision="housenumber",
    )
    base.update(kwargs)
    stations = base.pop("stations", None)
    listing = Listing(**base)
    if stations is not None:
        listing.stations = stations
    return listing


class TestModel(unittest.TestCase):
    def test_eur_m2(self):
        self.assertAlmostEqual(flat(price=410_000, surface=82.0).eur_m2, 5000.0)

    def test_eur_m2_needs_both(self):
        self.assertIsNone(flat(price=None).eur_m2)
        self.assertIsNone(flat(surface=None).eur_m2)
        self.assertIsNone(flat(surface=0).eur_m2)

    def test_nearest_prefers_routed(self):
        listing = flat(stations=[
            Station("Loin", "RER", "A", walk_m=900, crow_m=800),
            Station("Proche", "RER", "D", walk_m=300, crow_m=250),
            Station("NonRoutée", "METRO", "8", crow_m=100),
        ])
        self.assertEqual(listing.nearest.name, "Proche")

    def test_walk_for_mode(self):
        listing = flat(stations=[
            Station("G1", "RER", "A", walk_m=600),
            Station("M1", "METRO", "8", walk_m=200),
        ])
        self.assertEqual(listing.walk_m_for(["RER"]), 600)
        self.assertEqual(listing.walk_m_for(["METRO"]), 200)
        self.assertEqual(listing.walk_m_for(), 200)
        self.assertIsNone(listing.walk_m_for(["TRAM"]))

    def test_delivery_label(self):
        self.assertEqual(flat(delivery_year=2028, delivery_quarter=3).delivery_label, "T3 2028")
        self.assertEqual(flat(delivery_year=2028).delivery_label, "2028")
        self.assertEqual(flat().delivery_label, "")

    def test_features_detection(self):
        found = detect_features("Grand balcon, place de parking et cave privative")
        self.assertEqual(set(found), {"balcon", "parking", "cave"})

    def test_roundtrip_through_dict(self):
        listing = flat(stations=[Station("G", "RER", "A", walk_m=120, walk_min=1.5, crow_m=100)])
        clone = listing_from_dict(json.loads(json.dumps(listing.as_dict())))
        self.assertEqual(clone.id, listing.id)
        self.assertEqual(clone.price, listing.price)
        self.assertEqual(clone.stations[0].walk_m, 120)
        self.assertAlmostEqual(clone.eur_m2, listing.eur_m2)


class TestPricePlausibility(unittest.TestCase):
    def test_market_prices_pass(self):
        self.assertEqual(price_plausibility(410_000, 82.0), "")
        self.assertEqual(price_plausibility(180_000, 87.6), "")

    def test_absurdly_cheap_is_flagged(self):
        self.assertIn("anormalement bas", price_plausibility(35_000, 94.9))

    def test_tiny_price_is_flagged(self):
        self.assertIn("15 k€", price_plausibility(9_000, 60.0))

    def test_absurdly_expensive_is_flagged(self):
        self.assertIn("anormalement haut", price_plausibility(4_000_000, 40.0))

    def test_missing_data_is_not_flagged(self):
        self.assertEqual(price_plausibility(None, 80.0), "")
        self.assertEqual(price_plausibility(300_000, None), "")

    def test_atypical_excluded_by_default(self):
        odd = flat(kind=KIND_ANCIEN, price=35_000, surface=94.9,
                   price_flag="369 €/m² anormalement bas")
        self.assertFalse(matches(odd, Criteria.from_params({})))
        self.assertTrue(matches(odd, Criteria.from_params({"include_atypical": "1"})))

    def test_atypical_never_leads_the_ranking(self):
        odd = flat(name="aberrant", kind=KIND_ANCIEN, price=35_000, surface=94.9,
                   price_flag="anormal")
        sane = flat(name="normal", kind=KIND_ANCIEN, price=300_000, surface=80.0)
        results = Index([odd, sane]).search(Criteria.from_params({}))
        self.assertEqual([r["name"] for r in results["results"]], ["normal"])


class TestCriteriaParsing(unittest.TestCase):
    def test_defaults(self):
        c = Criteria.from_params({})
        self.assertEqual(c.sort, "eur_m2")
        self.assertEqual(c.page, 1)
        self.assertFalse(c.keep_unknown)

    def test_numbers_and_lists(self):
        c = Criteria.from_params({
            "price_max": ["425000"], "surface_min": "80,5",
            "dept": ["94,93"], "fiscal": "PTZ,BRS",
        })
        self.assertEqual(c.price_max, 425_000)
        self.assertAlmostEqual(c.surface_min, 80.5)
        self.assertEqual(c.depts, ["94", "93"])
        self.assertEqual(c.fiscal, ["PTZ", "BRS"])

    def test_quarter_forms(self):
        self.assertEqual(Criteria.from_params({"delivery_from": "T4 2027"}).delivery_from, (2027, 4))
        self.assertEqual(Criteria.from_params({"delivery_from": "2027-T4"}).delivery_from, (2027, 4))
        self.assertEqual(Criteria.from_params({"delivery_from": "2027"}).delivery_from, (2027, 0))

    def test_bad_values_raise(self):
        for params in (
            {"price_max": "beaucoup"},
            {"sort": "n'importe quoi"},
            {"kind": "loft"},
            {"mode": "FUNICULAIRE"},
            {"order": "haut"},
            {"delivery_from": "bientôt"},
            {"sold_after": "12/05/2024"},
            {"rooms_min": "5", "rooms_max": "3"},
            {"price_min": "500000", "price_max": "100000"},
            {"kitchen": "ouverte-mais-pas-trop"},
            {"only_available": "peut-être"},
        ):
            with self.subTest(params=params):
                with self.assertRaises(CriteriaError):
                    Criteria.from_params(params)

    def test_bounds_are_enforced(self):
        with self.assertRaises(CriteriaError):
            Criteria.from_params({"per_page": "5000"})
        with self.assertRaises(CriteriaError):
            Criteria.from_params({"rooms_min": "0"})


class TestMatching(unittest.TestCase):
    def test_range_filters(self):
        listing = flat(price=410_000, surface=82.0)
        self.assertTrue(matches(listing, Criteria.from_params({"price_max": "425000"})))
        self.assertFalse(matches(listing, Criteria.from_params({"price_max": "400000"})))
        self.assertTrue(matches(listing, Criteria.from_params({"surface_min": "80"})))
        self.assertFalse(matches(listing, Criteria.from_params({"surface_min": "90"})))

    def test_programme_matches_any_typology_it_sells(self):
        programme = flat(rooms=4, rooms_choices=[1, 2, 3, 4, 5])
        for wanted in ("1", "3", "5"):
            self.assertTrue(matches(programme, Criteria.from_params({"rooms_min": wanted, "rooms_max": wanted})),
                            f"T{wanted} devrait matcher")
        self.assertFalse(matches(programme, Criteria.from_params({"rooms_min": "6"})))

    def test_single_flat_still_uses_rooms(self):
        sale = flat(kind=KIND_ANCIEN, rooms=3, rooms_choices=[])
        self.assertTrue(matches(sale, Criteria.from_params({"rooms_min": "3", "rooms_max": "3"})))
        self.assertFalse(matches(sale, Criteria.from_params({"rooms_min": "4"})))

    def test_eur_m2_filter(self):
        listing = flat(price=410_000, surface=82.0)   # exactly 5000
        self.assertTrue(matches(listing, Criteria.from_params({"eur_m2_max": "5300"})))
        self.assertFalse(matches(listing, Criteria.from_params({"eur_m2_max": "4900"})))

    def test_unknown_is_excluded_then_kept(self):
        listing = flat(surface=None)
        self.assertFalse(matches(listing, Criteria.from_params({"surface_min": "80"})))
        self.assertTrue(
            matches(listing, Criteria.from_params({"surface_min": "80", "keep_unknown": "1"}))
        )

    def test_unfiltered_unknown_passes(self):
        self.assertTrue(matches(flat(surface=None), Criteria.from_params({})))

    def test_zone_normalisation(self):
        self.assertTrue(matches(flat(zone_abc="A bis"), Criteria.from_params({"zone": "abis"})))
        self.assertFalse(matches(flat(zone_abc="B1"), Criteria.from_params({"zone": "abis,a"})))

    def test_city_accent_insensitive(self):
        self.assertTrue(matches(flat(city="Créteil"), Criteria.from_params({"city": "creteil"})))

    def test_free_text_all_tokens(self):
        listing = flat(name="Villa Farnese", city="Bussy-Saint-Georges")
        self.assertTrue(matches(listing, Criteria.from_params({"q": "villa bussy"})))
        self.assertFalse(matches(listing, Criteria.from_params({"q": "villa nantes"})))

    def test_delivery_window(self):
        params = {"delivery_from": "T4 2027", "delivery_to": "2029"}
        self.assertTrue(matches(flat(delivery_year=2028, delivery_quarter=2),
                                Criteria.from_params(params)))
        self.assertFalse(matches(flat(delivery_year=2027, delivery_quarter=2),
                                 Criteria.from_params(params)))
        self.assertTrue(matches(flat(delivery_year=2029, delivery_quarter=4),
                                Criteria.from_params(params)))
        self.assertFalse(matches(flat(delivery_year=2030, delivery_quarter=1),
                                 Criteria.from_params(params)))

    def test_walk_filter_requires_routing(self):
        routed = flat(stations=[Station("G", "RER", "A", walk_m=400, crow_m=330)])
        unrouted = flat(stations=[Station("G", "RER", "A", crow_m=330)])
        c = Criteria.from_params({"walk_max_m": "450"})
        self.assertTrue(matches(routed, c))
        self.assertFalse(matches(unrouted, c))
        self.assertTrue(
            matches(unrouted, Criteria.from_params({"walk_max_m": "450", "keep_unknown": "1"}))
        )

    def test_walk_filter_rejects_too_far(self):
        listing = flat(stations=[Station("G", "RER", "A", walk_m=800, crow_m=600)])
        self.assertFalse(matches(listing, Criteria.from_params({"walk_max_m": "450"})))

    def test_crow_filter_works_without_routing(self):
        listing = flat(stations=[Station("G", "RER", "A", crow_m=330)])
        self.assertTrue(matches(listing, Criteria.from_params({"crow_max_m": "400"})))
        self.assertFalse(matches(listing, Criteria.from_params({"crow_max_m": "300"})))

    def test_mode_and_line(self):
        listing = flat(stations=[
            Station("G", "RER", "A", walk_m=300),
            Station("M", "METRO", "8", walk_m=150),
        ])
        self.assertTrue(matches(listing, Criteria.from_params({"mode": "RER", "walk_max_m": "400"})))
        self.assertFalse(matches(listing, Criteria.from_params({"mode": "TRAM", "walk_max_m": "400"})))
        self.assertTrue(matches(listing, Criteria.from_params({"line": "8", "walk_max_m": "200"})))

    def test_fiscal_requires_all(self):
        listing = flat(fiscal=["PTZ", "TVA réduite"])
        self.assertTrue(matches(listing, Criteria.from_params({"fiscal": "PTZ"})))
        self.assertTrue(matches(listing, Criteria.from_params({"fiscal": "PTZ,TVA"})))
        self.assertFalse(matches(listing, Criteria.from_params({"fiscal": "PTZ,BRS"})))

    def test_features_require_all(self):
        listing = flat(features=["parking", "balcon"])
        self.assertTrue(matches(listing, Criteria.from_params({"feature": "parking"})))
        self.assertFalse(matches(listing, Criteria.from_params({"feature": "parking,cave"})))

    def test_quality_toggles(self):
        bare = flat(photos=[], plan_url="", address_precision="municipality")
        rich = flat(photos=["http://x/p.jpg"], plan_url="http://x/p.pdf",
                    address_precision="housenumber")
        self.assertFalse(matches(bare, Criteria.from_params({"with_photos": "1"})))
        self.assertTrue(matches(rich, Criteria.from_params({"with_photos": "1"})))
        self.assertFalse(matches(bare, Criteria.from_params({"with_plan": "1"})))
        self.assertTrue(matches(rich, Criteria.from_params({"with_plan": "1"})))
        self.assertFalse(matches(bare, Criteria.from_params({"with_exact_address": "1"})))
        self.assertTrue(matches(rich, Criteria.from_params({"with_exact_address": "1"})))

    def test_only_available_keeps_unknown_availability(self):
        self.assertFalse(matches(flat(available=False), Criteria.from_params({"only_available": "1"})))
        self.assertTrue(matches(flat(available=True), Criteria.from_params({"only_available": "1"})))
        self.assertTrue(matches(flat(available=None), Criteria.from_params({"only_available": "1"})))

    def test_floor_parsing(self):
        c = Criteria.from_params({"floor_min": "2"})
        self.assertTrue(matches(flat(floor="5"), c))
        self.assertFalse(matches(flat(floor="RDC"), c))
        self.assertFalse(matches(flat(floor="1"), c))


class TestEngine(unittest.TestCase):
    def setUp(self):
        self.index = Index([
            flat(name="A", city="Créteil", dept="94", price=300_000, surface=100.0,
                 zone_abc="A", source="s1"),                       # 3000 €/m²
            flat(name="B", city="Créteil", dept="94", price=420_000, surface=84.0,
                 zone_abc="A", source="s1"),                       # 5000 €/m²
            flat(name="C", city="Massy", dept="91", price=400_000, surface=80.0,
                 zone_abc="A", source="s2"),                       # 5000 €/m²
            flat(name="D", city="Paris", dept="75", price=900_000, surface=90.0,
                 zone_abc="Abis", source="s2", kind=KIND_ANCIEN),  # 10000 €/m²
        ])

    def test_sort_ascending_by_eur_m2(self):
        result = self.index.search(Criteria.from_params({}))
        self.assertEqual([r["name"] for r in result["results"]], ["A", "B", "C", "D"])

    def test_sort_descending(self):
        result = self.index.search(Criteria.from_params({"order": "desc"}))
        self.assertEqual(result["results"][0]["name"], "D")

    def test_sort_by_price(self):
        result = self.index.search(Criteria.from_params({"sort": "price"}))
        self.assertEqual([r["name"] for r in result["results"]], ["A", "C", "B", "D"])

    def test_unknown_values_sort_last(self):
        index = Index([flat(name="connu", price=100_000, surface=50.0),
                       flat(name="inconnu", price=None, surface=None)])
        result = index.search(Criteria.from_params({}))
        self.assertEqual([r["name"] for r in result["results"]], ["connu", "inconnu"])

    def test_pagination(self):
        page1 = self.index.search(Criteria.from_params({"per_page": "2", "page": "1"}))
        page2 = self.index.search(Criteria.from_params({"per_page": "2", "page": "2"}))
        self.assertEqual(page1["pages"], 2)
        self.assertEqual([r["name"] for r in page1["results"]], ["A", "B"])
        self.assertEqual([r["name"] for r in page2["results"]], ["C", "D"])

    def test_page_beyond_end_clamps(self):
        result = self.index.search(Criteria.from_params({"per_page": "2", "page": "99"}))
        self.assertEqual(result["page"], 2)
        self.assertTrue(result["results"])

    def test_stats(self):
        stats = self.index.search(Criteria.from_params({}))["stats"]
        self.assertEqual(stats["eur_m2"]["count"], 4)
        self.assertEqual(stats["eur_m2"]["min"], 3000)
        self.assertEqual(stats["by_kind"], {"ancien": 1, "neuf": 3})

    def test_facets_ignore_their_own_filter(self):
        """Picking a department must not collapse the department facet."""
        criteria = Criteria.from_params({"dept": "94"})
        facets = self.index.facets(criteria)
        depts = {f["value"]: f["count"] for f in facets["dept"]}
        self.assertEqual(depts, {"94": 2, "91": 1, "75": 1})

    def test_facets_do_apply_other_filters(self):
        criteria = Criteria.from_params({"kind": "neuf"})
        facets = self.index.facets(criteria)
        depts = {f["value"]: f["count"] for f in facets["dept"]}
        self.assertNotIn("75", depts)   # the only 75 row is "ancien"

    def test_facet_counts_are_reachable(self):
        """Every facet count must equal the result total once selected."""
        base = Criteria.from_params({})
        for entry in self.index.facets(base)["dept"]:
            got = self.index.search(
                Criteria.from_params({"dept": entry["value"]}), with_facets=False
            )["total"]
            self.assertEqual(got, entry["count"], f"dept {entry['value']}")

    def test_comparables_only_use_completed_sales(self):
        target = flat(name="cible", lat=48.79, lon=2.47, rooms=4)
        sold_near = flat(name="vendu", kind=KIND_ANCIEN, lat=48.7902, lon=2.4702, rooms=4)
        asking_near = flat(name="en vente", kind=KIND_NEUF, lat=48.7903, lon=2.4703, rooms=4)
        index = Index([target, sold_near, asking_near])
        names = [c["name"] for c in index.comparables(target)]
        self.assertEqual(names, ["vendu"])

    def test_comparables_need_coordinates(self):
        self.assertEqual(Index([flat(lat=None)]).comparables(flat(lat=None)), [])


class TestApi(unittest.TestCase):
    def setUp(self):
        self.listing = flat(name="A", price=300_000, surface=100.0)
        self.api = Api(Index([self.listing]), {"built_at": "now"})

    def test_search_route(self):
        status, payload = self.api.handle("/api/search", {"price_max": ["400000"]})
        self.assertEqual(status, 200)
        self.assertEqual(payload["total"], 1)

    def test_meta_route(self):
        status, payload = self.api.handle("/api/meta", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["count"], 1)
        self.assertIn("facets", payload)

    def test_listing_route(self):
        status, payload = self.api.handle(f"/api/listing/{self.listing.id}", {})
        self.assertEqual(status, 200)
        self.assertEqual(payload["listing"]["name"], "A")

    def test_missing_listing_is_404(self):
        status, _ = self.api.handle("/api/listing/deadbeef", {})
        self.assertEqual(status, 404)

    def test_unknown_route_is_404(self):
        status, _ = self.api.handle("/api/nope", {})
        self.assertEqual(status, 404)

    def test_bad_criteria_propagate(self):
        with self.assertRaises(CriteriaError):
            self.api.handle("/api/search", {"price_max": ["cher"]})


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestVefaIngestIntegration(unittest.TestCase):
    """End-to-end: the pipeline's CSV shape must survive into a brief query."""

    COLUMNS = [
        "name", "city", "postcode", "dept", "zone_abc", "developer", "source",
        "lot_price", "lot_area", "lot_floor", "lot_exposure", "lot_available",
        "price_program_min", "area_t4_min", "typologies", "delivery", "fiscal",
        "kitchen_hint", "plan_url", "station_name", "station_line", "walk_m",
        "walk_min", "address", "lat", "lon", "geocode_precision", "notes", "url",
    ]

    ROWS = [
        # Real shapes taken from the pipeline output.
        dict(name="VOLTIGE", city="Sartrouville", postcode="78500", dept="78",
             zone_abc="A", source="explorimmoneuf", lot_price="329688",
             lot_area="79.45", lot_available="oui", typologies="1/2/3/4/5",
             delivery="T2 2028", fiscal="PTZ/Jeanbrun", station_name="Sartrouville",
             station_line="A", walk_m="380", walk_min="4.6", lat="48.94", lon="2.19",
             geocode_precision="source"),
        dict(name="Jardin Cezanne", city="Corbeil-Essonnes", postcode="91100",
             dept="91", zone_abc="A", source="explorimmoneuf", lot_price="249683",
             lot_area="87.6", lot_available="oui", typologies="2/3/4",
             delivery="T1 2029", fiscal="PTZ", station_name="Corbeil-Essonnes",
             station_line="D", walk_m="420", walk_min="5.1", lat="48.61", lon="2.48",
             geocode_precision="street"),
        dict(name="Sans surface", city="Massy", postcode="91300", dept="91",
             zone_abc="A", source="bouygues", price_program_min="230000",
             typologies="1/2/3/4", delivery="T3 2028"),
    ]

    def setUp(self):
        import csv as _csv
        import tempfile
        from immo.ingest import load_vefa_csv

        self.tmp = Path(tempfile.mkdtemp()) / "vefa.csv"
        with self.tmp.open("w", newline="", encoding="utf-8-sig") as fh:
            writer = _csv.DictWriter(fh, fieldnames=self.COLUMNS, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(self.ROWS)
        self.listings = load_vefa_csv(self.tmp)
        self.index = Index(self.listings)

    def test_lot_pair_becomes_price_and_surface(self):
        voltige = next(l for l in self.listings if l.name == "VOLTIGE")
        self.assertEqual(voltige.price, 329_688)
        self.assertAlmostEqual(voltige.surface, 79.45)
        self.assertTrue(voltige.surface_is_carrez)
        self.assertEqual(round(voltige.eur_m2), 4150)
        self.assertEqual(voltige.rooms_choices, [1, 2, 3, 4, 5])

    def test_programme_without_surface_has_no_eur_m2(self):
        bare = next(l for l in self.listings if l.name == "Sans surface")
        self.assertIsNone(bare.surface)
        self.assertIsNone(bare.eur_m2)

    def test_delivery_and_walk_survive_the_csv(self):
        jardin = next(l for l in self.listings if l.name == "Jardin Cezanne")
        self.assertEqual(jardin.delivery_key, (2029, 1))
        self.assertEqual(jardin.walk_m_for(["RER"]), 420)

    def test_the_brief_query(self):
        """T4 ≥80 m², ≤425 k€, ≤5300 €/m², ≤450 m d'un RER, zone A/Abis, T4-27→29."""
        brief = {
            "kind": "neuf", "rooms_min": "4", "rooms_max": "4", "surface_min": "80",
            "price_max": "425000", "eur_m2_max": "5300", "walk_max_m": "450",
            "mode": "RER", "zone": "abis,a", "delivery_from": "T4 2027",
            "delivery_to": "2029",
        }
        result = self.index.search(Criteria.from_params(brief), with_facets=False)
        names = [r["name"] for r in result["results"]]
        # VOLTIGE misses on surface (79.45), "Sans surface" has none published.
        self.assertEqual(names, ["Jardin Cezanne"])

    def test_relaxing_surface_admits_the_near_miss(self):
        brief = {"kind": "neuf", "rooms_min": "4", "surface_min": "79",
                 "price_max": "425000", "walk_max_m": "450", "mode": "RER"}
        result = self.index.search(Criteria.from_params(brief), with_facets=False)
        self.assertEqual({r["name"] for r in result["results"]},
                         {"VOLTIGE", "Jardin Cezanne"})
