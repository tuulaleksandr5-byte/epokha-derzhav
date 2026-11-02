"""Регрессионные проверки правил игры (python -m unittest discover -s tests -v)."""

import copy
import json
import math
import os
import random
import tempfile
import unittest
from collections import defaultdict
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")

import main as game


def polygon_area(polygon):
    return abs(sum(a[0] * b[1] - b[0] * a[1]
                   for a, b in zip(polygon, polygon[1:] + polygon[:1]))) / 2


class WorldTests(unittest.TestCase):
    def test_map_is_partition_with_exactly_100_connected_provinces(self):
        """Проверяем площадь, непустые ячейки и реальное общее ребро соседей."""
        for seed in (1848, 42, 9999):
            with self.subTest(seed=seed):
                provinces, coast = game.generate_world(seed)
                self.assertEqual(len(provinces), 100)
                self.assertEqual(len({p.name for p in provinces}), 100)
                self.assertEqual({p.id for p in provinces}, set(range(100)))
                self.assertTrue(game.connected(set(range(100)), provinces))
                self.assertAlmostEqual(sum(polygon_area(p.polygon) for p in provinces),
                                       polygon_area(coast), delta=0.001)
                edge_owners = defaultdict(set)
                for p in provinces:
                    self.assertGreater(polygon_area(p.polygon), 100)
                    self.assertTrue(game.point_in_polygon(p.center, p.polygon))
                    self.assertNotIn(p.id, p.neighbors)
                    for a, b in zip(p.polygon, p.polygon[1:] + p.polygon[:1]):
                        if math.dist(a, b) > 0.01:
                            edge = tuple(sorted((tuple(round(x, 4) for x in a),
                                                 tuple(round(x, 4) for x in b))))
                            edge_owners[edge].add(p.id)
                actual_neighbors = defaultdict(set)
                for owners in edge_owners.values():
                    self.assertLessEqual(len(owners), 2)
                    if len(owners) == 2:
                        a, b = owners
                        actual_neighbors[a].add(b)
                        actual_neighbors[b].add(a)
                for p in provinces:
                    self.assertEqual(p.neighbors, actual_neighbors[p.id])
                    for nid in p.neighbors:
                        self.assertIn(p.id, provinces[nid].neighbors)
                for owner, expected in enumerate((40, 33, 27)):
                    ids = {p.id for p in provinces if p.owner == owner}
                    self.assertEqual(len(ids), expected)
                    self.assertTrue(game.connected(ids, provinces))

    def test_map_covers_land_without_overlapping_cells(self):
        provinces, coast = game.generate_world(1848)
        rng = random.Random(14)
        checked = 0
        for _ in range(500):
            point = (rng.uniform(0, game.WORLD_W), rng.uniform(0, game.WORLD_H))
            hits = sum(game.point_in_polygon(point, p.polygon) for p in provinces)
            self.assertEqual(hits, int(game.point_in_polygon(point, coast)))
            checked += hits
        self.assertGreater(checked, 200)

    def test_seed_reproduces_map_and_starting_ownership(self):
        first, _ = game.generate_world(5)
        second, _ = game.generate_world(5)
        self.assertEqual([(p.name, p.polygon, p.owner, p.neighbors) for p in first],
                         [(p.name, p.polygon, p.owner, p.neighbors) for p in second])


class RulesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.world, _ = game.generate_world(1848)

    def setUp(self):
        self.state = game.GameState(copy.deepcopy(self.world), 0, seed=1848)
        self.own = next(p for p in self.state.provinces if p.owner == 0)
        self.foreign = next(p for p in self.state.provinces if p.owner == 1)

    def own_edge(self):
        for a in self.state.provinces:
            if a.owner == 0:
                for nid in a.neighbors:
                    b = self.state.provinces[nid]
                    if b.owner == 0:
                        return a, b
        self.fail("Нет внутреннего ребра стартовой державы")

    def border_edge(self):
        for a in self.state.provinces:
            if a.owner == 0:
                for nid in a.neighbors:
                    b = self.state.provinces[nid]
                    if b.owner == 1:
                        return a, b
        self.fail("Нет общей границы двух держав")

    @staticmethod
    def snapshot(state):
        return {
            "provinces": [(p.id, p.owner, p.population, p.economy, p.unrest,
                           p.troops, p.ready, p.buildings, p.construction)
                          for p in state.provinces],
            "countries": [(c.treasury, c.literacy, c.policy) for c in state.countries],
            "calendar": (state.month, state.year, state.turn),
            "wars": sorted(state.wars), "alliances": sorted(state.alliances),
            "trades": sorted(state.trades), "relations": state.relations,
            "fleets": state.fleets, "result": state.result, "log": state.log,
        }

    def test_initial_state_and_calendar(self):
        self.assertEqual(self.state.counts(), [40, 33, 27])
        for p in self.state.provinces:
            self.assertGreater(p.population, 0)
            self.assertGreater(p.economy, 0)
            self.assertGreaterEqual(p.troops, 0)
            self.assertLessEqual(p.ready, p.troops)
        for _ in range(12):
            self.assertTrue(self.state.next_turn(run_ai=False)[0])
        self.assertEqual((self.state.month, self.state.year, self.state.turn), (0, 1849, 13))

    def test_policy_has_full_range(self):
        for key in ("tax", "welfare", "investment", "research"):
            for value in (0, 100, 37):
                self.assertTrue(self.state.set_policy(key, value)[0])
                self.assertEqual(self.state.countries[0].policy[key], value)

    def test_foreign_actions_and_negative_recruitment_cannot_spend_money(self):
        before = self.state.countries[0].treasury
        self.assertFalse(self.state.recruit(self.foreign.id, 100)[0])
        self.assertFalse(self.state.build(self.foreign.id, "farm")[0])
        self.assertFalse(self.state.recruit(self.own.id, -100)[0])
        self.assertFalse(self.state.recruit(self.own.id, 0)[0])
        self.assertEqual(self.state.countries[0].treasury, before)

    def test_recruitment_costs_money_and_increases_upkeep(self):
        self.state.countries[0].treasury = 10000
        before_money = self.state.countries[0].treasury
        before_troops = self.own.troops
        before_upkeep = self.state.forecast()["upkeep"]
        self.assertTrue(self.state.recruit(self.own.id, 100)[0])
        self.assertEqual(self.own.troops, before_troops + 100)
        self.assertLess(self.state.countries[0].treasury, before_money)
        self.assertGreater(self.state.forecast()["upkeep"], before_upkeep)
        self.state.countries[0].treasury = 0
        before = self.own.troops
        self.assertFalse(self.state.recruit(self.own.id, 100)[0])
        self.assertEqual(self.own.troops, before)

    def test_movement_cannot_teleport_or_activate_arrivals_twice(self):
        a, b = self.own_edge()
        far = next(p for p in self.state.provinces
                   if p.owner == 0 and p.id not in a.neighbors and p.id != a.id)
        a.troops = a.ready = 100
        b.troops = b.ready = 0
        self.assertFalse(self.state.move(a.id, far.id, 100)[0])
        self.assertTrue(self.state.move(a.id, b.id, 100)[0])
        self.assertEqual((a.troops, b.troops), (0, 100))
        self.assertFalse(self.state.move(b.id, a.id, 100)[0])
        self.state.next_turn(run_ai=False)
        self.assertTrue(self.state.move(b.id, a.id, 100)[0])

    def test_cannot_move_foreign_army_or_attack_without_war(self):
        a, b = self.border_edge()
        a.troops = a.ready = 1000
        b.troops = b.ready = 0
        self.assertFalse(self.state.move(b.id, a.id, 100)[0])
        self.assertFalse(self.state.move(a.id, b.id, 500)[0])
        self.assertEqual(a.troops, 1000)
        self.assertTrue(self.state.diplomacy(1, "war")[0])
        self.assertIn((0, 1), self.state.wars)
        self.assertTrue(self.state.move(a.id, b.id, 500)[0])
        self.assertEqual(b.owner, 0)
        self.assertGreater(b.troops, 0)
        self.assertEqual(b.ready, 0)

    def test_supply_reduces_only_its_local_upkeep_by_quarter(self):
        for p in self.state.provinces:
            if p.owner == 0:
                p.troops = p.ready = 0
        self.own.troops = self.own.ready = 400
        baseline = self.state.forecast()["upkeep"]
        self.assertGreater(baseline, 0)
        self.own.buildings["supply"] = 1
        self.assertAlmostEqual(self.state.forecast()["upkeep"], baseline * .75)

    def test_defensive_buildings_and_northern_bonus(self):
        self.own.unrest = 0
        empty = self.state.defense(self.own.id)
        self.own.buildings["fortress"] = 1
        self.assertAlmostEqual(self.state.defense(self.own.id), empty * 1.25)
        self.own.buildings["watchtower"] = 1
        self.assertAlmostEqual(self.state.defense(self.own.id), empty * 1.375)
        self.own.owner = 1
        self.assertAlmostEqual(self.state.defense(self.own.id), empty * 1.375 * 1.1)

    def test_growth_decline_farms_and_manufactories(self):
        self.state.set_policy("welfare", 100)
        self.state.set_policy("investment", 100)
        pop, econ = self.state.growth_rates(self.own.id)
        self.assertGreater(pop, 0)
        self.assertGreater(econ, 0)
        self.own.buildings["farm"] = 5
        self.assertAlmostEqual(self.state.growth_rates(self.own.id)[0], pop * 1.5)
        base_economy = self.state.effective_economy(self.own.id)
        self.own.buildings["manufactory"] = 5
        self.assertAlmostEqual(self.state.effective_economy(self.own.id), base_economy * 1.5)
        self.state.set_policy("welfare", 0)
        self.state.set_policy("investment", 0)
        pop, econ = self.state.growth_rates(self.own.id)
        self.assertLess(pop, 0)
        self.assertLess(econ, 0)
        previous = (self.own.population, self.own.economy)
        self.state.next_turn(run_ai=False)
        self.assertLess(self.own.population, previous[0])
        self.assertLess(self.own.economy, previous[1])

    def test_forecast_and_monthly_treasury(self):
        forecast = self.state.forecast()
        for key in ("income", "spending", "upkeep", "trade", "net"):
            self.assertTrue(math.isfinite(forecast[key]))
        self.assertAlmostEqual(forecast["net"], forecast["income"] + forecast["trade"]
                               - forecast["spending"] - forecast["upkeep"])
        before = self.state.countries[0].treasury
        self.state.next_turn(run_ai=False)
        self.assertAlmostEqual(self.state.countries[0].treasury - before, forecast["net"],
                               delta=max(2, abs(forecast["net"]) * .01))

    def test_research_has_no_minimum_and_more_funding_grows_faster(self):
        other = copy.deepcopy(self.state)
        self.state.set_policy("research", 0)
        other.set_policy("research", 100)
        before = self.state.countries[0].literacy
        self.state.next_turn(run_ai=False)
        other.next_turn(run_ai=False)
        self.assertEqual(self.state.countries[0].literacy, before)
        self.assertGreater(other.countries[0].literacy, before)

    def test_construction_lock_cost_queue_completion_and_level_cap(self):
        c = self.state.countries[0]
        c.treasury = 100000
        c.literacy = 0
        locked = next(key for key, definition in game.BUILDINGS.items()
                      if definition["unlock"] > 0 and key != "port")
        before = c.treasury
        self.assertFalse(self.state.build(self.own.id, locked)[0])
        self.assertEqual(c.treasury, before)
        self.assertIsNone(self.own.construction)
        c.literacy = 100
        info = self.state.build_info(self.own.id, "farm")
        self.assertTrue(info["available"])
        self.assertTrue(self.state.build(self.own.id, "farm")[0])
        self.assertAlmostEqual(c.treasury, before - info["cost"])
        self.assertFalse(self.state.build(self.own.id, "manufactory")[0])
        for _ in range(info["months"]):
            self.state.next_turn(run_ai=False)
        self.assertIsNone(self.own.construction)
        self.assertEqual(self.own.buildings["farm"], 1)
        next_info = self.state.build_info(self.own.id, "farm")
        self.assertGreater(next_info["cost"], info["cost"])
        self.assertGreater(next_info["months"], info["months"])
        self.own.buildings["farm"] = game.BUILDINGS["farm"]["max_level"]
        self.assertTrue(self.state.build_info(self.own.id, "farm")["maxed"])
        self.assertFalse(self.state.build(self.own.id, "farm")[0])

    def test_port_only_on_coast_and_fleet_takes_two_months(self):
        c = self.state.countries[0]
        c.treasury = 100000
        c.literacy = 100
        inland = next(p for p in self.state.provinces if p.owner == 0 and not p.coastal)
        coasts = [p for p in self.state.provinces if p.owner == 0 and p.coastal]
        self.assertGreaterEqual(len(coasts), 2)
        source, target = coasts[:2]
        self.assertFalse(self.state.build(inland.id, "port")[0])
        source.buildings["port"] = 1
        source.troops = source.ready = 300
        target.troops = target.ready = 200
        self.assertTrue(self.state.sail(source.id, target.id, 100)[0])
        self.assertEqual(source.troops, 200)
        self.assertEqual(len(self.state.fleets), 1)
        self.state.next_turn(run_ai=False)
        self.assertEqual(target.troops, 200)
        self.state.next_turn(run_ai=False)
        self.assertEqual(target.troops, 300)
        self.assertEqual(len(self.state.fleets), 0)

    def test_watchtower_and_port_reveal_foreign_forces(self):
        a, b = self.border_edge()
        for p in self.state.provinces:
            if p.owner == 0:
                p.buildings["watchtower"] = 0
                p.buildings["port"] = 0
        self.assertIsNone(self.state.visible_troops(b.id))
        self.assertEqual(self.state.visible_troops(a.id), a.troops)
        a.buildings["watchtower"] = 1
        self.assertEqual(self.state.visible_troops(b.id), b.troops)
        self.state.fleets = [{"owner": 1, "source": b.id, "target": a.id,
                              "troops": 100, "remaining": 2}]
        self.assertEqual(self.state.visible_fleets(), [])
        port = next(p for p in self.state.provinces if p.owner == 0 and p.coastal)
        port.buildings["port"] = 1
        self.assertEqual(len(self.state.visible_fleets()), 1)

    def test_diplomacy_trade_alliance_war_and_peace_have_real_effects(self):
        pair = (0, 1)
        self.state.relations[pair] = -50
        self.assertFalse(self.state.diplomacy(1, "trade")[0])
        self.assertFalse(self.state.diplomacy(1, "alliance")[0])
        self.state.relations[pair] = 80
        self.assertTrue(self.state.diplomacy(1, "trade")[0])
        budget = self.state.forecast()
        self.assertAlmostEqual(budget["trade"], budget["gross"] * .08)
        self.assertTrue(self.state.diplomacy(1, "alliance")[0])
        self.assertIn(pair, self.state.alliances)
        self.assertFalse(self.state.diplomacy(1, "war")[0])
        self.assertTrue(self.state.diplomacy(1, "break_alliance")[0])
        self.assertTrue(self.state.diplomacy(1, "war")[0])
        self.assertIn(pair, self.state.wars)
        self.assertNotIn(pair, self.state.trades)
        self.assertEqual(self.state.forecast()["trade"], 0)
        self.assertFalse(self.state.diplomacy(1, "trade")[0])
        self.assertTrue(self.state.diplomacy(1, "peace")[0])
        self.assertNotIn(pair, self.state.wars)
        self.state.relations[pair] = 80
        self.assertTrue(self.state.diplomacy(1, "trade")[0])
        self.assertTrue(self.state.diplomacy(1, "cancel_trade")[0])
        self.assertNotIn(pair, self.state.trades)

    def test_overwhelming_enemy_can_refuse_peace(self):
        self.state.diplomacy(1, "war")
        for p in self.state.provinces:
            if p.owner == 0:
                p.troops = p.ready = 1
            elif p.owner == 1:
                p.troops = p.ready = 1000
        self.assertFalse(self.state.diplomacy(1, "peace")[0])
        self.assertIn((0, 1), self.state.wars)

    def test_prolonged_extreme_taxation_can_cause_secession(self):
        self.state.set_policy("tax", 100)
        self.state.set_policy("welfare", 0)
        self.own.unrest = 100
        for _ in range(24):
            self.state.next_turn(run_ai=False)
            if self.own.owner != 0:
                break
        self.assertEqual(self.own.owner, -1)

    def test_victory_and_defeat_stop_further_orders(self):
        a, b = self.border_edge()
        for p in self.state.provinces:
            p.owner = 0
        b.owner = 1
        b.troops = b.ready = 0
        a.troops = a.ready = 1000
        self.state.wars.add((0, 1))
        self.assertTrue(self.state.move(a.id, b.id, 500)[0])
        self.assertEqual(self.state.result, "victory")
        self.assertFalse(self.state.recruit(a.id, 100)[0])
        turn = self.state.turn
        self.assertFalse(self.state.next_turn(run_ai=False)[0])
        self.assertEqual(self.state.turn, turn)
        losing = game.GameState(copy.deepcopy(self.world), 0, seed=1848)
        for p in losing.provinces:
            p.owner = 1
        losing.next_turn(run_ai=False)
        self.assertEqual(losing.result, "defeat")
        self.assertFalse(losing.build(0, "farm")[0])

    def test_ai_changes_armies_or_buildings_and_long_game_stays_valid(self):
        original = [(p.troops, p.buildings.copy(), p.construction)
                    for p in self.state.provinces if p.owner != 0]
        for _ in range(6):
            self.state.next_turn()
        changed = [(p.troops, p.buildings.copy(), p.construction)
                   for p in self.state.provinces if p.owner != 0]
        self.assertNotEqual(original, changed)
        for _ in range(54):
            if self.state.result:
                break
            self.state.next_turn()
        for p in self.state.provinces:
            self.assertIn(p.owner, (-1, 0, 1, 2))
            self.assertGreater(p.population, 0)
            self.assertGreater(p.economy, 0)
            self.assertGreaterEqual(p.troops, 0)
            self.assertGreaterEqual(p.ready, 0)
            self.assertLessEqual(p.ready, p.troops)
            for key, level in p.buildings.items():
                self.assertLessEqual(level, game.BUILDINGS[key]["max_level"])

    def test_save_load_preserves_state_and_random_future(self):
        self.state.countries[0].treasury = 20000
        self.state.countries[0].literacy = 100
        self.state.build(self.own.id, "farm")
        self.state.diplomacy(1, "war")
        self.state.next_turn()
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "save.json"
            self.assertTrue(self.state.save(path)[0])
            self.assertIsInstance(json.loads(path.read_text(encoding="utf-8")), dict)
            loaded = game.GameState.load(path)
            self.assertEqual(self.snapshot(self.state), self.snapshot(loaded))
            for _ in range(12):
                self.state.next_turn()
                loaded.next_turn()
                self.assertEqual(self.snapshot(self.state), self.snapshot(loaded))

    def test_corrupt_save_is_rejected_without_replacing_current_state(self):
        initial = copy.deepcopy(self.snapshot(self.state))
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "save.json"
            for text in ("{broken", "{}", "[]", "null"):
                with self.subTest(text=text):
                    path.write_text(text, encoding="utf-8")
                    with self.assertRaises((ValueError, OSError)):
                        game.GameState.load(path)
                    self.assertEqual(self.snapshot(self.state), initial)

    def test_invalid_numbers_routes_and_contradicting_save_state_are_rejected(self):
        raw = self.state.to_dict()
        corruptions = [
            lambda d: d.update(version=99),
            lambda d: d.update(provinces=d["provinces"][:-1]),
            lambda d: d["provinces"][0].update(owner=99),
            lambda d: d["provinces"][0].update(population=float("nan")),
            lambda d: d["provinces"][0].update(ready=d["provinces"][0]["troops"]+1),
            lambda d: d["countries"][0].update(treasury=-1),
            lambda d: d["countries"][0]["policy"].update(tax=101),
            lambda d: d.update(month=12),
            lambda d: d.update(year=1849),
            lambda d: d.update(wars=[[0, 1]], alliances=[[0, 1]]),
            lambda d: d.update(result="victory"),
            lambda d: d.update(rng=[3, [], None]),
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "bad-save.json"
            for index, corrupt in enumerate(corruptions):
                with self.subTest(case=index):
                    data = copy.deepcopy(raw)
                    corrupt(data)
                    path.write_text(json.dumps(data), encoding="utf-8")
                    with self.assertRaises((ValueError, OSError)):
                        game.GameState.load(path)


if __name__ == "__main__":
    unittest.main()
