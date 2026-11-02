#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Эпоха держав — пошаговая стратегия о ста провинциях.

Установка: python -m pip install pygame
Запуск:    python main.py

Управление: мышь — выбор страны/провинции; Enter — начать/следующий ход;
N — подписи; T — армии; F5 — сохранить; F9 — загрузить; H — справка.
Все изображения и карта создаются программно. Нужен только Pygame.
"""

import json
import math
import os
import random
import sys
import tempfile
from pathlib import Path
from dataclasses import dataclass, field

os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")
try:
    import pygame
except ImportError:
    raise SystemExit("Не установлен Pygame. Выполните: python -m pip install pygame")


# Интерфейс рисуется в постоянных координатах и масштабируется вместе с окном.
WIDTH, HEIGHT = 1440, 900
WORLD_W, WORLD_H = 1000, 620
DEFAULT_SEED = 1848
BG = (17, 29, 36)
PANEL = (24, 40, 47)
SEA = (28, 49, 56)
LINE = (54, 75, 80)
TEXT = (239, 230, 209)
MUTED = (150, 169, 166)
GOLD = (218, 181, 111)
INK = (30, 43, 43)
MONTHS = ("Январь", "Февраль", "Март", "Апрель", "Май", "Июнь",
          "Июль", "Август", "Сентябрь", "Октябрь", "Ноябрь", "Декабрь")


@dataclass(frozen=True)
class Country:
    id: int
    name: str
    title: str
    color: tuple
    start_count: int
    description: str
    bonus: str
    symbol: str


COUNTRIES = (
    Country(0, "Велиград", "СОЮЗ ЗАПАДНЫХ ЗЕМЕЛЬ", (126, 161, 137), 40,
            "Обширные равнины и старые города.", "+10% к росту населения", "tree"),
    Country(1, "Нордхольм", "СЕВЕРНОЕ КОРОЛЕВСТВО", (128, 158, 182), 33,
            "Суровый север и горные перевалы.", "+10% к силе защиты", "mountain"),
    Country(2, "Солнея", "ЮЖНАЯ РЕСПУБЛИКА", (202, 161, 104), 27,
            "Тёплое побережье и торговые города.", "+10% к налоговому доходу", "sun"),
)

COAST = [(46, 233), (102, 110), (263, 39), (489, 24), (713, 57),
         (892, 143), (965, 278), (926, 424), (784, 541),
         (564, 591), (338, 575), (147, 484), (62, 365)]




def point_in_polygon(point, polygon):
    """Проверка выпуклого многоугольника; точки на границе включены."""
    x, y = point
    signs = []
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        cross = (b[0] - a[0]) * (y - a[1]) - (b[1] - a[1]) * (x - a[0])
        if abs(cross) > 1e-7:
            signs.append(cross > 0)
    return bool(signs) and (all(signs) or not any(signs))


def clip_polygon(polygon, nx, ny, limit):
    """Отсечение полуплоскостью nx*x + ny*y <= limit (без SciPy)."""
    result = []
    if not polygon:
        return result
    previous = polygon[-1]
    prev_d = nx * previous[0] + ny * previous[1] - limit
    for current in polygon:
        current_d = nx * current[0] + ny * current[1] - limit
        if (current_d <= 0) != (prev_d <= 0):
            t = prev_d / (prev_d - current_d)
            result.append((previous[0] + t * (current[0] - previous[0]),
                           previous[1] + t * (current[1] - previous[1])))
        if current_d <= 0:
            result.append(current)
        previous, prev_d = current, current_d
    return result


def polygon_center(polygon):
    """Центр площади, чтобы номер гарантированно находился внутри ячейки."""
    area2 = cx = cy = 0.0
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        cross = a[0] * b[1] - b[0] * a[1]
        area2 += cross
        cx += (a[0] + b[0]) * cross
        cy += (a[1] + b[1]) * cross
    if abs(area2) < 1e-9:
        return polygon[0]
    return cx / (3 * area2), cy / (3 * area2)


def connected(ids, provinces):
    """Нужна для выдачи странам связных стартовых территорий."""
    if not ids:
        return True
    visited = {next(iter(ids))}
    stack = list(visited)
    while stack:
        fresh = (provinces[stack.pop()].neighbors & ids) - visited
        visited.update(fresh)
        stack.extend(fresh)
    return visited == ids


def take_region(available, count, provinces, key):
    chosen = set()
    remaining = set(available)
    while len(chosen) < count:
        frontier = remaining if not chosen else {
            n for pid in chosen for n in provinces[pid].neighbors if n in remaining
        }
        # Не оставляем анклавы у следующей страны.
        candidate = next((pid for pid in sorted(frontier, key=key)
                          if connected(remaining - {pid}, provinces)), None)
        if candidate is None:
            raise ValueError("Не удалось разделить карту на связные страны")
        chosen.add(candidate)
        remaining.remove(candidate)
    return chosen


def generate_world(seed=DEFAULT_SEED):
    """Сто ячеек Вороного на выпуклом континенте и точные общие границы."""
    rng = random.Random(seed)
    coast = COAST[:]
    sites = []
    attempts = 0
    while len(sites) < 100:
        attempts += 1
        point = (rng.uniform(55, 955), rng.uniform(35, 580))
        # Ограничение расстояния исключает почти незаметные маленькие ячейки.
        gap = 43 if attempts < 15000 else 25
        if (point_in_polygon(point, coast)
                and all(math.dist(point, other) >= gap for other in sites)):
            sites.append(point)

    # Две итерации релаксации Ллойда дают читаемые, но не одинаковые области.
    for iteration in range(3):
        cells = []
        for i, (sx, sy) in enumerate(sites):
            polygon = coast[:]
            for j, (tx, ty) in enumerate(sites):
                if i != j:
                    polygon = clip_polygon(polygon, tx - sx, ty - sy,
                                           (tx * tx + ty * ty - sx * sx - sy * sy) / 2)
            cells.append(polygon)
        if iteration < 2:
            sites = [polygon_center(cell) for cell in cells]

    # Названия уникальны: десять корней и десять окончаний.
    roots = ("Бел", "Берёз", "Ветр", "Выс", "Дуб", "Камен", "Лес", "Озёр", "Свет", "Яр")
    endings = ("огорск", "ополь", "овск", "оград", "оречье",
               "одолье", "инск", "озерье", "обор", "ово")
    names = [root + ending for root in roots for ending in endings]
    rng.shuffle(names)
    provinces = [Province(i, names[i], cell, polygon_center(cell))
                 for i, cell in enumerate(cells)]

    # Рёбра соседей лежат на биссектрисе соответствующих центров Вороного.
    # Проверяем оба конца и ненулевую длину: касание вершиной не соседство.
    for i, province in enumerate(provinces):
        sx, sy = sites[i]
        for j in range(i + 1, 100):
            tx, ty = sites[j]
            nx, ny = tx - sx, ty - sy
            limit = (tx * tx + ty * ty - sx * sx - sy * sy) / 2
            norm = math.hypot(nx, ny)
            for a, b in zip(province.polygon, province.polygon[1:] + province.polygon[:1]):
                if (math.dist(a, b) > 0.01
                        and abs(nx * a[0] + ny * a[1] - limit) / norm < 1e-5
                        and abs(nx * b[0] + ny * b[1] - limit) / norm < 1e-5):
                    province.neighbors.add(j)
                    provinces[j].neighbors.add(i)
                    break

    available = set(range(100))
    west = take_region(available, 40, provinces,
                       lambda pid: (provinces[pid].center[0], pid))
    available -= west
    north = take_region(available, 33, provinces,
                        lambda pid: (provinces[pid].center[1], pid))
    for owner, ids in enumerate((west, north, available - north)):
        for pid in ids:
            provinces[pid].owner = owner
    return provinces, coast




# Экономика, строительство, армии, дипломатия и сохранения.


BUILDINGS = {
    "farm": {"name": "Ферма", "unlock": 0, "max_level": 5, "cost": 220, "months": 2,
             "description": "+10% к положительному росту населения за уровень"},
    "manufactory": {"name": "Мануфактура", "unlock": 20, "max_level": 5, "cost": 360, "months": 3,
                    "description": "+10% к экономике провинции за уровень"},
    "supply": {"name": "Лагерь снабжения", "unlock": 15, "max_level": 1, "cost": 260, "months": 2,
               "description": "Содержание местной армии дешевле на 25%"},
    "port": {"name": "Порт", "unlock": 40, "max_level": 1, "cost": 500, "months": 3,
             "description": "Морские походы и сведения о чужих войсках на море"},
    "fortress": {"name": "Крепость", "unlock": 45, "max_level": 1, "cost": 650, "months": 4,
                 "description": "+25% к защите провинции"},
    "watchtower": {"name": "Смотровая башня", "unlock": 30, "max_level": 1, "cost": 320, "months": 2,
                   "description": "+12,5% к защите; разведка соседних провинций"},
}
POLICIES = {"tax": "Налоги", "welfare": "Благосостояние",
            "investment": "Инвестиции", "research": "Исследования"}
COASTLINE = [(46, 233), (102, 110), (263, 39), (489, 24), (713, 57),
             (892, 143), (965, 278), (926, 424), (784, 541),
             (564, 591), (338, 575), (147, 484), (62, 365)]


@dataclass
class Province:
    id: int
    name: str
    polygon: list
    center: tuple
    owner: int = -1
    neighbors: set = field(default_factory=set)
    population: float = 0.0
    economy: float = 0.0
    unrest: float = 0.0
    troops: int = 0
    ready: int = 0
    buildings: dict = field(default_factory=lambda: {key: 0 for key in BUILDINGS})
    construction: object = None
    coastal: bool = False


@dataclass
class CountryState:
    treasury: float = 1800.0
    literacy: float = 20.0
    policy: dict = field(default_factory=lambda: {
        "tax": 45, "welfare": 45, "investment": 40, "research": 25})


class GameState:
    """Вся симуляция выполняется здесь, интерфейс лишь вызывает действия."""

    def __init__(self, provinces, player, seed=DEFAULT_SEED, month=0,
                 year=1848, turn=1, selected=0):
        self.provinces = provinces
        self.player = player
        self.seed = seed
        self.month, self.year, self.turn = month, year, turn
        self.selected = selected
        self.countries = [CountryState() for _ in COUNTRIES]
        self.wars, self.alliances, self.trades = set(), set(), set()
        self.relations = {(0, 1): -10, (0, 2): 10, (1, 2): -5}
        self.fleets = []
        self.log = ["Январь 1848 — начало вашей истории."]
        self.result = None
        self.last_budget = [None, None, None]
        self.rng = random.Random(seed ^ 0xA71A5)
        for p in self.provinces:
            p.population = float(self.rng.randint(40000, 90000))
            p.economy = float(self.rng.randint(55, 95))
            p.unrest = float(self.rng.randint(8, 20))
            p.troops = self.rng.choice((200, 250, 300, 350))
            p.ready = p.troops
            p.buildings = {key: 0 for key in BUILDINGS}
            p.construction = None
            p.coastal = self._is_coastal(p)

    @staticmethod
    def pair(a, b):
        return tuple(sorted((a, b)))

    @staticmethod
    def _segment_distance(point, a, b):
        dx, dy = b[0] - a[0], b[1] - a[1]
        length2 = dx * dx + dy * dy
        t = 0.0 if not length2 else max(0.0, min(1.0,
            ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / length2))
        return math.hypot(point[0] - a[0] - t * dx, point[1] - a[1] - t * dy)

    @classmethod
    def _is_coastal(cls, p):
        for a, b in zip(p.polygon, p.polygon[1:] + p.polygon[:1]):
            if math.dist(a, b) < 0.01:
                continue
            for c, d in zip(COASTLINE, COASTLINE[1:] + COASTLINE[:1]):
                if cls._segment_distance(a, c, d) < 1e-5 and cls._segment_distance(b, c, d) < 1e-5:
                    return True
        return False

    def counts(self):
        return [sum(p.owner == c.id for p in self.provinces) for c in COUNTRIES]

    def strength(self, owner):
        return sum(p.troops for p in self.provinces if p.owner == owner) + sum(
            f["troops"] for f in self.fleets if f["owner"] == owner)

    def _add_log(self, message):
        self.log.insert(0, f"{MONTHS[self.month]} {self.year}: {message}")
        self.log[:] = self.log[:100]

    def _check_result(self):
        counts = self.counts()
        # Уничтоженная держава больше не участвует в войнах и договорах.
        active = {owner for owner, count in enumerate(counts) if count}
        self.wars = {pair for pair in self.wars if set(pair) <= active}
        self.alliances = {pair for pair in self.alliances if set(pair) <= active}
        self.trades = {pair for pair in self.trades if set(pair) <= active}
        self.fleets = [fleet for fleet in self.fleets if fleet["owner"] in active]
        count = counts[self.player]
        if count == 0:
            self.result = "defeat"
        elif count == 100:
            self.result = "victory"
        return self.result

    def _playing(self):
        return self.result is None

    def effective_economy(self, pid):
        p = self.provinces[pid]
        return p.economy * (1 + .10 * p.buildings["manufactory"])

    def defense(self, pid):
        p = self.provinces[pid]
        value = 1 + .25 * p.buildings["fortress"] + .125 * p.buildings["watchtower"]
        return value * (1.10 if p.owner == 1 else 1.0)

    def growth_rates(self, pid):
        p = self.provinces[pid]
        if p.owner < 0:
            return 0.0, 0.0
        policy = self.countries[p.owner].policy
        population = (policy["welfare"] - 35) * .00012
        if population > 0:
            population *= (1 + .10 * p.buildings["farm"]) * (1.10 if p.owner == 0 else 1.0)
        economy = (policy["investment"] - 35) * .00030
        return population, economy

    def forecast(self, owner=None):
        owner = self.player if owner is None else owner
        policy = self.countries[owner].policy
        owned = [p for p in self.provinces if p.owner == owner]
        gross = sum(p.population / 1000 * self.effective_economy(p.id) / 100 * 2.2 for p in owned)
        income = gross * policy["tax"] / 100 * (1.10 if owner == 2 else 1.0)
        spending = gross * (policy["welfare"] * .0032 + policy["investment"] * .0035
                            + policy["research"] * .0026)
        upkeep = sum(p.troops * .018 * (.75 if p.buildings["supply"] else 1) for p in owned)
        upkeep += sum(f["troops"] * .022 for f in self.fleets if f["owner"] == owner)
        trade = gross * .08 * sum(owner in pair and self.counts()[pair[0]] > 0
                                  and self.counts()[pair[1]] > 0 for pair in self.trades)
        return {"gross": gross, "income": income, "spending": spending,
                "upkeep": upkeep, "trade": trade, "net": income + trade - spending - upkeep}

    def set_policy(self, key, value):
        if not self._playing():
            return False, "Кампания завершена. Начните новую игру."
        if key not in POLICIES or isinstance(value, bool) or not isinstance(value, (int, float)):
            return False, "Неизвестная настройка бюджета."
        if not math.isfinite(value):
            return False, "Недопустимое значение бюджета."
        self.countries[self.player].policy[key] = max(0, min(100, round(value)))
        return True, "Бюджет обновлён."

    def build_info(self, pid, key, owner=None):
        owner = self.player if owner is None else owner
        if not isinstance(pid, int) or not 0 <= pid < len(self.provinces) or key not in BUILDINGS:
            return {"next_level": 0, "cost": 0, "months": 0, "unlocked": False,
                    "maxed": False, "available": False, "reason": "Неизвестная постройка."}
        p, spec = self.provinces[pid], BUILDINGS[key]
        level = p.buildings[key]
        unlocked = self.countries[owner].literacy + 1e-8 >= spec["unlock"]
        maxed = level >= spec["max_level"]
        cost = round(spec["cost"] * 1.55 ** level)
        months = spec["months"] + level
        reason = ""
        if self.result:
            reason = "Кампания завершена."
        elif p.owner != owner:
            reason = "Строить можно только в своей провинции."
        elif maxed:
            reason = "Достигнут максимальный уровень."
        elif p.construction:
            reason = "В провинции уже идёт строительство."
        elif not unlocked:
            reason = f"Нужна грамотность {spec['unlock']}%."
        elif key == "port" and not p.coastal:
            reason = "Порт можно построить только на побережье."
        elif self.countries[owner].treasury < cost:
            reason = f"Недостаточно денег: нужно {cost}."
        return {"next_level": min(level + 1, spec["max_level"]), "cost": cost,
                "months": months, "unlocked": unlocked, "maxed": maxed,
                "available": not reason, "reason": reason}

    def build(self, pid, key):
        return self._build(pid, key, self.player)

    def _build(self, pid, key, owner):
        info = self.build_info(pid, key, owner)
        if not info["available"]:
            return False, info["reason"]
        p = self.provinces[pid]
        self.countries[owner].treasury -= info["cost"]
        p.construction = {"building": key, "remaining": info["months"], "level": info["next_level"]}
        message = f"{p.name}: {BUILDINGS[key]['name']}, уровень {info['next_level']}; {info['months']} мес."
        if owner == self.player:
            self._add_log(message)
        return True, message

    def recruit(self, pid, amount=100):
        return self._recruit(pid, amount, self.player)

    def _recruit(self, pid, amount, owner):
        if self.result:
            return False, "Кампания завершена."
        if not isinstance(pid, int) or not 0 <= pid < len(self.provinces):
            return False, "Неизвестная провинция."
        if isinstance(amount, bool) or not isinstance(amount, int) or amount < 100 or amount % 100:
            return False, "Набор производится отрядами по 100 солдат."
        p = self.provinces[pid]
        if p.owner != owner:
            return False, "Нанимать армию можно только в своей провинции."
        if p.troops + amount > p.population * .10:
            return False, "Не хватает населения: местная армия не может превышать 10% жителей."
        cost = amount * 1.20
        if self.countries[owner].treasury < cost:
            return False, f"Недостаточно денег: нужно {cost:.0f}."
        self.countries[owner].treasury -= cost
        p.troops += amount
        # Новобранцы готовы только в следующем месяце, как и прибывшие войска.
        message = f"{p.name}: нанято {amount} солдат за {cost:.0f}; готовы со следующего хода."
        if owner == self.player:
            self._add_log(message)
        return True, message

    def _movement_check(self, source, target, amount, owner, sea=False):
        if self.result:
            return "Кампания завершена."
        if (not isinstance(source, int) or not isinstance(target, int)
                or not 0 <= source < 100 or not 0 <= target < 100 or source == target):
            return "Выберите другую провинцию."
        p, q = self.provinces[source], self.provinces[target]
        if p.owner != owner:
            return "Вы можете отправлять только свои войска."
        if isinstance(amount, bool) or not isinstance(amount, int) or amount <= 0:
            return "Укажите положительное число солдат."
        if amount > p.ready:
            return f"В этом месяце к походу готовы только {p.ready} солдат."
        if sea:
            if not p.coastal or not p.buildings["port"]:
                return "Для морского похода нужен порт в исходной провинции."
            if not q.coastal:
                return "Морской поход может закончиться только на побережье."
            if self.countries[owner].treasury < amount * .12:
                return "Не хватает денег на перевозку (0,12 за солдата)."
        elif target not in p.neighbors:
            return "По суше войска идут только в соседнюю провинцию."
        if q.owner >= 0 and q.owner != owner and self.pair(owner, q.owner) not in self.wars:
            return "Сначала объявите владельцу этой провинции войну."
        return ""

    def move(self, source, target, amount):
        return self._move(source, target, amount, self.player)

    def _move(self, source, target, amount, owner):
        reason = self._movement_check(source, target, amount, owner)
        if reason:
            return False, reason
        p, q = self.provinces[source], self.provinces[target]
        p.troops -= amount
        p.ready -= amount
        if q.owner == owner:
            q.troops += amount
            message = f"{amount} солдат прибыли из {p.name} в {q.name}; марш завершён до следующего месяца."
            if owner == self.player:
                self._add_log(message)
        else:
            message = self._battle(owner, source, target, amount)
        self._check_result()
        return True, message

    def sail(self, source, target, amount):
        return self._sail(source, target, amount, self.player)

    def _battle(self, owner, source, target, amount):
        p = self.provinces[target]
        defender = p.owner
        defenders = p.troops
        defense = self.defense(target)
        attack_power = amount * self.rng.uniform(.87, 1.13)
        defend_power = defenders * defense * self.rng.uniform(.87, 1.13)
        if attack_power > defend_power or not defenders:
            losses = min(amount - 1, round(defenders * defense * self.rng.uniform(.45, .65)))
            survivors = amount - max(0, losses)
            # Небольшая часть защитников отступает, если есть свои соседи.
            retreat = [self.provinces[n] for n in p.neighbors if self.provinces[n].owner == defender]
            if defender >= 0 and retreat:
                destination = min(retreat, key=lambda q: (q.troops, q.id))
                destination.troops += round(defenders * .16)
            p.owner = owner
            p.troops, p.ready = survivors, 0
            p.unrest = min(75.0, p.unrest + 16)
            p.construction = None
            message = f"{COUNTRIES[owner].name} захватывает {p.name}: осталось {survivors}, потери {amount-survivors}."
        else:
            losses = min(max(0, defenders - 1), round(amount * self.rng.uniform(.35, .55) / defense))
            p.troops -= losses
            p.ready = min(p.ready, p.troops)
            survivors = round(amount * .20)
            origin = self.provinces[source]
            if origin.owner == owner:
                origin.troops += survivors
            else:
                survivors = 0
            message = f"Атака на {p.name} отбита: у защитников {p.troops}; отступило {survivors} солдат."
        if defender >= 0 and defender != owner:
            pair = self.pair(owner, defender)
            self.relations[pair] = max(-100, self.relations.get(pair, 0) - 4)
        if owner == self.player or defender == self.player:
            self._add_log(message)
        return message

    def visible_troops(self, pid, viewer=None):
        viewer = self.player if viewer is None else viewer
        p = self.provinces[pid]
        if p.owner == viewer:
            return p.troops
        if any(self.provinces[n].owner == viewer and self.provinces[n].buildings["watchtower"]
               for n in p.neighbors):
            return p.troops
        return None

    def visible_fleets(self, viewer=None):
        viewer = self.player if viewer is None else viewer
        reveal = any(p.owner == viewer and p.buildings["port"] for p in self.provinces)
        return [dict(f) for f in self.fleets if f["owner"] == viewer or reveal]

    def _bordering(self, owner, other):
        return any(self.provinces[n].owner == other
                   for p in self.provinces if p.owner == owner for n in p.neighbors)

    def diplomacy(self, target, action):
        return self._diplomacy(self.player, target, action)

    def _diplomacy(self, owner, target, action):
        if self.result:
            return False, "Кампания завершена."
        if target == owner or target not in range(3) or not self.counts()[target] or not self.counts()[owner]:
            return False, "Эта держава больше не участвует в дипломатии."
        pair = self.pair(owner, target)
        relation = self.relations.get(pair, 0)
        own_strength = max(1, self.strength(owner))
        other_strength = max(1, self.strength(target))
        if action == "war":
            if pair in self.wars:
                return False, "Война уже объявлена."
            if pair in self.alliances:
                return False, "Сначала расторгните союз."
            self.wars.add(pair)
            self.trades.discard(pair)
            self.relations[pair] = min(-45, relation - 45)
            message = f"{COUNTRIES[owner].name} объявляет войну державе {COUNTRIES[target].name}."
        elif action == "peace":
            if pair not in self.wars:
                return False, "Вы уже находитесь в мире."
            # При равных силах мир возможен; превосходящий противник менее уступчив.
            if own_strength < other_strength * .72 and relation < -30:
                return False, "Предложение мира отклонено: противник уверен в своём военном превосходстве."
            self.wars.remove(pair)
            self.relations[pair] = max(-20, relation + 30)
            message = f"{COUNTRIES[owner].name} и {COUNTRIES[target].name} заключили мир."
        elif action == "alliance":
            if pair in self.wars:
                return False, "Для союза сначала заключите мир."
            if pair in self.alliances:
                return False, "Союз уже заключён."
            common_enemy = any(self.pair(owner, k) in self.wars and self.pair(target, k) in self.wars
                               for k in range(3) if k not in pair)
            if relation < 15 and not common_enemy:
                return False, "Союз отклонён: нужны отношения +15 либо общий враг. Торговля улучшает отношения."
            if own_strength < other_strength * .35:
                return False, "Союз отклонён: сначала укрепите армию."
            self.alliances.add(pair)
            self.relations[pair] = min(100, relation + 15)
            message = f"{COUNTRIES[owner].name} и {COUNTRIES[target].name} заключили союз."
        elif action == "break_alliance":
            if pair not in self.alliances:
                return False, "Между державами нет союза."
            self.alliances.remove(pair)
            self.relations[pair] = max(-100, relation - 35)
            message = f"Союз держав {COUNTRIES[owner].name} и {COUNTRIES[target].name} расторгнут."
        elif action == "trade":
            if pair in self.wars:
                return False, "Во время войны торговый договор невозможен."
            if pair in self.trades:
                return False, "Торговый договор уже действует."
            if relation < -20 or (not self._bordering(owner, target) and pair not in self.alliances):
                return False, "Торговля отклонена: нужны общая граница или союз и отношения не ниже −20."
            self.trades.add(pair)
            self.relations[pair] = min(100, relation + 10)
            message = f"Торговый договор: {COUNTRIES[owner].name} — {COUNTRIES[target].name} (+8% дохода от экономики)."
        elif action == "cancel_trade":
            if pair not in self.trades:
                return False, "Торгового договора нет."
            self.trades.remove(pair)
            self.relations[pair] = max(-100, relation - 10)
            message = f"Торговый договор держав {COUNTRIES[owner].name} и {COUNTRIES[target].name} расторгнут."
        else:
            return False, "Неизвестное дипломатическое действие."
        self._add_log(message)
        return True, message

    def _monthly_economy(self, owner):
        country = self.countries[owner]
        budget = self.forecast(owner)
        self.last_budget[owner] = dict(budget)
        country.treasury += budget["net"]
        bankrupt = country.treasury < 0
        if bankrupt:
            country.treasury = 0
            if owner == self.player:
                self._add_log("Казна пуста: часть солдат дезертирует, недовольство растёт. Сократите расходы.")
        if not bankrupt:
            country.literacy = min(100.0, country.literacy + country.policy["research"] * .014
                                   * (1 - country.literacy / 130))
        for p in self.provinces:
            if p.owner != owner:
                continue
            population_rate, economy_rate = self.growth_rates(p.id)
            p.population = max(5000.0, min(1000000.0, p.population * (1 + population_rate)))
            p.economy = max(10.0, min(300.0, p.economy * (1 + economy_rate)))
            tax, welfare = country.policy["tax"], country.policy["welfare"]
            unrest_change = max(0, tax - 65) * .19 - welfare * .035 - 0.4
            p.unrest = max(0.0, min(100.0, p.unrest + unrest_change + (8 if bankrupt else 0)))
            if bankrupt and p.troops:
                p.troops = max(0, int(p.troops * .82))
                p.ready = min(p.ready, p.troops)
            if p.construction:
                p.construction["remaining"] -= 1
                if p.construction["remaining"] <= 0:
                    key = p.construction["building"]
                    p.buildings[key] = p.construction["level"]
                    p.construction = None
                    if owner == self.player:
                        self._add_log(f"{p.name}: завершено здание «{BUILDINGS[key]['name']}», уровень {p.buildings[key]}.")
            if p.unrest >= 80 and self.rng.random() < .10 + (p.unrest - 80) / 100:
                p.owner = -1
                p.troops = max(200, p.troops)
                p.ready = 0
                p.unrest = 40
                p.construction = None
                self._add_log(f"{p.name} отделяется от державы {COUNTRIES[owner].name}! Провинция стала независимой.")

    def _advance_fleets(self):
        remaining = []
        for fleet in self.fleets:
            fleet["remaining"] -= 1
            if fleet["remaining"] > 0:
                remaining.append(fleet)
                continue
            owner, source, target, troops = (fleet[k] for k in ("owner", "source", "target", "troops"))
            p = self.provinces[target]
            if p.owner == owner:
                p.troops += troops
                if owner == self.player:
                    self._add_log(f"{p.name}: завершена морская перевозка {troops} солдат.")
            elif p.owner < 0 or self.pair(owner, p.owner) in self.wars:
                self._battle(owner, source, target, troops)
            else:
                # Мир запрещает высадку на чужую территорию: возвращаем войска домой.
                origin = self.provinces[source]
                if origin.owner == owner:
                    origin.troops += troops
                else:
                    own = [q for q in self.provinces if q.owner == owner]
                    if own:
                        own[0].troops += troops
                if owner == self.player:
                    self._add_log("После заключения мира морской отряд вернулся в свои владения.")
        self.fleets = remaining

    def _ai_turn(self, owner):
        owned = [p for p in self.provinces if p.owner == owner]
        if not owned or self.result:
            return
        country = self.countries[owner]
        # ИИ держит небольшой бюджетный запас и больше тратит на науку в мирное время.
        at_war = any(owner in pair for pair in self.wars)
        country.policy.update(tax=53 if at_war else 49, welfare=42,
                              investment=38 if at_war else 43, research=20 if at_war else 28)
        borders = [p for p in owned if any(self.provinces[n].owner != owner for n in p.neighbors)]
        self.rng.shuffle(borders)
        others = [c.id for c in COUNTRIES if c.id != owner and self.counts()[c.id]]
        # Решения используют отношения, границу и сравнительную силу.
        if self.turn >= 5:
            for target in others:
                pair = self.pair(owner, target)
                relation = self.relations[pair]
                if pair in self.wars:
                    ratio = self.strength(owner) / max(1, self.strength(target))
                    # Предложение имеет шанс быть принято при умеренном отставании.
                    # Слишком слабому противнику мир не навязывается автоматически.
                    if .72 <= ratio < .95 and self.rng.random() < .18:
                        self._diplomacy(owner, target, "peace")
                elif pair not in self.alliances:
                    ratio = self.strength(owner) / max(1, self.strength(target))
                    threat = self._bordering(owner, target)
                    # У соседей с прохладными отношениями есть реальные амбиции:
                    # общий мир не должен длиться бесконечно при равных силах.
                    ambitious = relation < 35 and self.turn >= 9 and ratio > .75
                    if threat and (ambitious or relation < -20 or ratio > 1.6) and self.rng.random() < .09:
                        self._diplomacy(owner, target, "war")
                    elif relation >= 15 and self.rng.random() < .025:
                        self._diplomacy(owner, target, "alliance")
                    elif pair not in self.trades and relation >= -20 and self.rng.random() < .025:
                        self._diplomacy(owner, target, "trade")
        # На фронт и в пограничные гарнизоны набирается ограниченное число отрядов.
        for p in borders[:3]:
            enemies = [self.provinces[n] for n in p.neighbors
                       if self.provinces[n].owner < 0 or self.pair(owner, self.provinces[n].owner) in self.wars]
            target_size = min(2500, max([500] + [round(q.troops * 1.45) for q in enemies]))
            if p.troops < target_size and country.treasury > 750:
                amount = min(500, ((target_size - p.troops + 99) // 100) * 100,
                             int((country.treasury - 500) // 120) * 100)
                if amount >= 100:
                    self._recruit(p.id, amount, owner)
        # Мануфактуры/фермы и оборона строятся без бесконечной траты казны.
        free = [p for p in owned if not p.construction]
        self.rng.shuffle(free)
        if free and country.treasury > 1150:
            p = free[0]
            options = ["supply", "farm", "manufactory"]
            if at_war and p in borders:
                options = ["fortress", "watchtower"] + options
            self.rng.shuffle(options)
            if (p.coastal and not p.buildings["port"] and country.literacy >= 40
                    and sum(q.buildings["port"] for q in owned) < 3):
                options.insert(0, "port")
            for key in options:
                info = self.build_info(p.id, key, owner)
                if info["available"] and country.treasury - info["cost"] >= 600:
                    self._build(p.id, key, owner)
                    break
        # Перегруппировка внутренних войск к ближайшему фронту по кратчайшему пути.
        enemy_borders = [p for p in owned if any(
            self.provinces[n].owner < 0 or self.pair(owner, self.provinces[n].owner) in self.wars
            for n in p.neighbors)]
        if enemy_borders:
            distance = {p.id: 0 for p in enemy_borders}
            queue = list(distance)
            for pid in queue:
                for nid in self.provinces[pid].neighbors:
                    if self.provinces[nid].owner == owner and nid not in distance:
                        distance[nid] = distance[pid] + 1
                        queue.append(nid)
            for p in sorted(owned, key=lambda q: distance.get(q.id, 999), reverse=True):
                if p.ready <= 150 or distance.get(p.id, 0) <= 0:
                    continue
                choices = [n for n in p.neighbors if self.provinces[n].owner == owner
                           and distance.get(n, 999) < distance.get(p.id, 999)]
                if choices:
                    target = min(choices, key=lambda n: (distance[n], self.provinces[n].troops))
                    self._move(p.id, target, max(1, p.ready - 100), owner)
            self.rng.shuffle(enemy_borders)
            for p in enemy_borders:
                if p.owner != owner or p.ready < 150:
                    continue
                enemies = [self.provinces[n] for n in p.neighbors
                           if self.provinces[n].owner < 0 or self.pair(owner, self.provinces[n].owner) in self.wars]
                if not enemies:
                    continue
                target = min(enemies, key=lambda q: q.troops * self.defense(q.id))
                amount = max(0, p.ready - 80)
                if amount > target.troops * self.defense(target.id) * 1.18:
                    self._move(p.id, target.id, amount, owner)
                    if self.result:
                        break
        # Порты дают ИИ возможность обойти сухопутный фронт морем.
        if not self.result and not any(f["owner"] == owner for f in self.fleets):
            ports = [p for p in owned if p.owner == owner and p.buildings["port"] and p.ready >= 400]
            self.rng.shuffle(ports)
            for p in ports:
                targets = [q for q in self.provinces if q.coastal and q.owner != owner
                           and (q.owner < 0 or self.pair(owner, q.owner) in self.wars)]
                if not targets:
                    break
                target = min(targets, key=lambda q: q.troops * self.defense(q.id))
                amount = max(0, p.ready - 100)
                if amount > target.troops * self.defense(target.id) * 1.30:
                    if self._sail(p.id, target.id, amount, owner)[0]:
                        break

    def next_turn(self, run_ai=True):
        if self.result:
            return False, "Кампания завершена. Начните новую игру."
        self.month = (self.month + 1) % 12
        if self.month == 0:
            self.year += 1
        self.turn += 1
        # Экономика и стройка используют бюджет, установленный до нажатия кнопки.
        for owner in range(3):
            if self.counts()[owner]:
                self._monthly_economy(owner)
        for p in self.provinces:
            p.ready = p.troops if p.owner >= 0 else 0
        self._advance_fleets()
        self._check_result()
        if run_ai and not self.result:
            for owner in range(3):
                if owner != self.player:
                    self._ai_turn(owner)
                    if self.result:
                        break
        # Торговля и длительный мир постепенно улучшают отношения.
        for pair in self.relations:
            if pair in self.trades:
                self.relations[pair] = min(100, self.relations[pair] + 2)
            elif pair not in self.wars:
                self.relations[pair] = min(100, self.relations[pair] + 1)
        self._check_result()
        message = f"{MONTHS[self.month]} {self.year} — ход {self.turn}."
        if self.result:
            self._add_log("Победа! Все сто провинций объединены." if self.result == "victory"
                          else "Поражение: потеряны все провинции.")
        return True, message

    def to_dict(self):
        return {
            "version": 1, "seed": self.seed, "player": self.player, "month": self.month,
            "year": self.year, "turn": self.turn, "selected": self.selected, "result": self.result,
            "countries": [{"treasury": c.treasury, "literacy": c.literacy, "policy": dict(c.policy)}
                          for c in self.countries],
            "provinces": [{"owner": p.owner, "population": p.population, "economy": p.economy,
                           "unrest": p.unrest, "troops": p.troops, "ready": p.ready,
                           "buildings": dict(p.buildings), "construction": p.construction}
                          for p in self.provinces],
            "wars": [list(pair) for pair in sorted(self.wars)],
            "alliances": [list(pair) for pair in sorted(self.alliances)],
            "trades": [list(pair) for pair in sorted(self.trades)],
            "relations": [[a, b, value] for (a, b), value in sorted(self.relations.items())],
            "fleets": [dict(f) for f in self.fleets], "log": self.log[:100],
            "rng": self.rng.getstate(),
        }

    def save(self, path):
        """Сначала временный файл, затем замена: сбой не уничтожает прошлый сейв."""
        try:
            target = Path(path)
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_name(target.name + ".tmp")
            temporary.write_text(json.dumps(self.to_dict(), ensure_ascii=False,
                                             indent=2, allow_nan=False), encoding="utf-8")
            temporary.replace(target)
            return True, "Игра сохранена."
        except (OSError, ValueError, TypeError) as error:
            return False, f"Не удалось сохранить игру: {error}"

    @classmethod
    def load(cls, path):
        """Проверяем формат и пределы значений; pickle и исполняемый код не используются."""
        target = Path(path)
        if target.stat().st_size > 2_000_000:
            raise ValueError("Файл сохранения слишком большой.")
        try:
            data = json.loads(target.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, UnicodeError, RecursionError) as error:
            raise ValueError("Файл не является корректным сохранением.") from error

        def integer(value, minimum, maximum):
            if type(value) is not int or not minimum <= value <= maximum:
                raise ValueError("Некорректное целочисленное значение в сохранении.")
            return value

        def number(value, minimum, maximum):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError("Некорректное число в сохранении.")
            if not minimum <= value <= maximum:
                raise ValueError("Число в сохранении выходит за допустимые пределы.")
            return float(value)

        try:
            if not isinstance(data, dict) or data.get("version") != 1:
                raise ValueError("Неподдерживаемая версия сохранения.")
            seed = integer(data["seed"], 0, 2**32 - 1)
            player = integer(data["player"], 0, 2)
            month = integer(data["month"], 0, 11)
            year = integer(data["year"], 1848, 100000)
            turn = integer(data["turn"], 1, 1200000)
            selected = integer(data["selected"], 0, 99)
            if year != 1848 + (turn - 1) // 12 or month != (turn - 1) % 12:
                raise ValueError("Календарь сохранения повреждён.")
            provinces, _ = generate_world(seed)
            state = cls(provinces, player, seed, month, year, turn, selected)
            if not isinstance(data["provinces"], list) or len(data["provinces"]) != 100:
                raise ValueError("В сохранении должно быть сто провинций.")
            for p, raw in zip(state.provinces, data["provinces"]):
                p.owner = integer(raw["owner"], -1, 2)
                p.population = number(raw["population"], 1, 1000000)
                p.economy = number(raw["economy"], 1, 300)
                p.unrest = number(raw["unrest"], 0, 100)
                p.troops = integer(raw["troops"], 0, 10000000)
                p.ready = integer(raw["ready"], 0, p.troops)
                if not isinstance(raw["buildings"], dict) or set(raw["buildings"]) != set(BUILDINGS):
                    raise ValueError("Некорректный список построек.")
                p.buildings = {key: integer(raw["buildings"][key], 0, spec["max_level"])
                               for key, spec in BUILDINGS.items()}
                if p.buildings["port"] and not p.coastal:
                    raise ValueError("Порт в сохранении находится вдали от моря.")
                raw_construction = raw["construction"]
                if raw_construction is None:
                    p.construction = None
                else:
                    key = raw_construction["building"]
                    if key not in BUILDINGS or p.buildings[key] >= BUILDINGS[key]["max_level"]:
                        raise ValueError("Некорректная стройка.")
                    level = integer(raw_construction["level"], 1, BUILDINGS[key]["max_level"])
                    if level != p.buildings[key] + 1 or (key == "port" and not p.coastal):
                        raise ValueError("Некорректный уровень стройки.")
                    p.construction = {"building": key, "level": level,
                                      "remaining": integer(raw_construction["remaining"], 1, 20)}
            if not isinstance(data["countries"], list) or len(data["countries"]) != 3:
                raise ValueError("В сохранении должно быть три державы.")
            for country, raw in zip(state.countries, data["countries"]):
                country.treasury = number(raw["treasury"], 0, 1e15)
                country.literacy = number(raw["literacy"], 0, 100)
                if not isinstance(raw["policy"], dict) or set(raw["policy"]) != set(POLICIES):
                    raise ValueError("Некорректный бюджет.")
                country.policy = {key: integer(raw["policy"][key], 0, 100) for key in POLICIES}

            def pairs(raw):
                if not isinstance(raw, list) or len(raw) > 3:
                    raise ValueError("Некорректные дипломатические отношения.")
                result = set()
                for pair in raw:
                    if not isinstance(pair, list) or len(pair) != 2:
                        raise ValueError("Некорректная пара держав.")
                    a, b = integer(pair[0], 0, 2), integer(pair[1], 0, 2)
                    if a >= b or (a, b) in result:
                        raise ValueError("Некорректная пара держав.")
                    result.add((a, b))
                return result

            state.wars = pairs(data["wars"])
            state.alliances = pairs(data["alliances"])
            state.trades = pairs(data["trades"])
            if state.wars & (state.alliances | state.trades):
                raise ValueError("В сохранении есть противоречащие друг другу договоры.")
            if not isinstance(data["relations"], list) or len(data["relations"]) != 3:
                raise ValueError("Некорректные отношения держав.")
            relations = {}
            for raw in data["relations"]:
                if not isinstance(raw, list) or len(raw) != 3:
                    raise ValueError("Некорректные отношения держав.")
                a, b = integer(raw[0], 0, 2), integer(raw[1], 0, 2)
                if a >= b or (a, b) in relations:
                    raise ValueError("Некорректные отношения держав.")
                relations[(a, b)] = integer(raw[2], -100, 100)
            state.relations = relations
            if not isinstance(data["fleets"], list) or len(data["fleets"]) > 1000:
                raise ValueError("Некорректный список морских походов.")
            state.fleets = []
            for raw in data["fleets"]:
                fleet = {"owner": integer(raw["owner"], 0, 2),
                         "source": integer(raw["source"], 0, 99),
                         "target": integer(raw["target"], 0, 99),
                         "troops": integer(raw["troops"], 1, 10000000),
                         "remaining": integer(raw["remaining"], 1, 2)}
                if fleet["source"] == fleet["target"] or not state.provinces[fleet["target"]].coastal:
                    raise ValueError("Некорректный маршрут морского похода.")
                state.fleets.append(fleet)
            if not isinstance(data["log"], list) or len(data["log"]) > 100:
                raise ValueError("Некорректный журнал событий.")
            if any(not isinstance(line, str) or len(line) > 1000 for line in data["log"]):
                raise ValueError("Некорректная запись в журнале событий.")
            state.log = data["log"]
            if data["result"] not in (None, "victory", "defeat"):
                raise ValueError("Некорректный итог кампании.")
            state.result = None
            actual_result = state._check_result()
            if actual_result != data["result"]:
                raise ValueError("Итог кампании не соответствует владениям.")
            # random.setstate принимает только известную структуру чисел;
            # JSON не может загрузить Python-объекты с исполняемым кодом.
            raw_rng = data["rng"]
            if not isinstance(raw_rng, list) or len(raw_rng) != 3 or raw_rng[0] != 3:
                raise ValueError("Некорректное состояние генератора случайности.")
            internal = raw_rng[1]
            if not isinstance(internal, list) or len(internal) != 625:
                raise ValueError("Некорректное состояние генератора случайности.")
            checked = [integer(v, 0, 2**32 - 1) for v in internal[:-1]]
            checked.append(integer(internal[-1], 0, 624))
            if raw_rng[2] is not None:
                number(raw_rng[2], -1e9, 1e9)
            state.rng.setstate((3, tuple(checked), raw_rng[2]))
            return state
        except (KeyError, TypeError, IndexError, OverflowError, RecursionError) as error:
            raise ValueError("Файл сохранения повреждён или имеет неверный формат.") from error

    def _sail(self, source, target, amount, owner):
        reason = self._movement_check(source, target, amount, owner, sea=True)
        if reason:
            return False, reason
        p = self.provinces[source]
        p.troops -= amount
        p.ready -= amount
        self.countries[owner].treasury -= amount * .12
        self.fleets.append({"owner": owner, "source": source, "target": target,
                            "troops": amount, "remaining": 2})
        message = f"{amount} солдат вышли в море к {self.provinces[target].name}; путь займёт 2 месяца."
        if owner == self.player:
            self._add_log(message)
        return True, message



# Интерфейс политического атласа и управление игрой.

def mix(a, b, amount):
    return tuple(round(x+(y-x)*amount) for x, y in zip(a, b))


def owner_color(owner):
    return COUNTRIES[owner].color if owner >= 0 else (153, 148, 134)


def owner_name(owner):
    return COUNTRIES[owner].name if owner >= 0 else "Вольные земли"


def number(value):
    return f"{int(value):,}".replace(",", " ")


class Game:
    def __init__(self):
        pygame.display.init()
        pygame.font.init()
        info = pygame.display.Info()
        scale = min(1, max(800, info.current_w-80)/WIDTH,
                    max(500, info.current_h-100)/HEIGHT)
        self.screen = pygame.display.set_mode((round(WIDTH*scale), round(HEIGHT*scale)), pygame.RESIZABLE)
        pygame.display.set_caption("Эпоха держав")
        self.canvas = pygame.Surface((WIDTH, HEIGHT))
        self.clock = pygame.time.Clock()
        self.fonts = {}
        self.font_regular = pygame.font.match_font("dejavusans,arial,liberationsans,noto sans")
        self.font_bold = pygame.font.match_font("dejavusans,arial,liberationsans,noto sans", bold=True)
        self.font_serif = pygame.font.match_font("dejavuserif,georgia,liberationserif")
        self.seed = DEFAULT_SEED
        self.provinces, self.coast = generate_world(self.seed)
        self.preview_surface = self.make_map()
        self.map_surface = self.preview_surface.copy()
        self.map_owners = tuple(p.owner for p in self.provinces)
        self.state = None
        self.scene = "choose"
        self.chosen = 0
        self.running = True
        self.show_names = False
        self.show_troops = True
        self.hovered = None
        self.mouse = (-1, -1)
        self.buttons = []
        self.sliders = []
        self.dragging = None
        self.tooltip = ""
        self.tab = "province"
        self.province_tab = "overview"
        self.order_mode = None
        self.order_source = None
        self.send_amount = 100
        self.help_page = 0
        self.map_origin = (30, 182)
        self.map_rect = pygame.Rect(30, 182, 1000, 620)
        self.toast = ""
        self.toast_until = 0
        self.log_scroll = 0
        data_home = Path(os.environ["LOCALAPPDATA"]) if os.environ.get("LOCALAPPDATA") else Path.home()/".local"/"share"
        self.save_path = data_home/"EpokhaDerzhav"/"campaign.json"

    def font(self, size, bold=False, serif=False):
        key = (size, bold, serif)
        if key not in self.fonts:
            path = self.font_serif if serif else self.font_bold if bold else self.font_regular
            self.fonts[key] = pygame.font.Font(path, size)
        return self.fonts[key]

    def text(self, text, pos, size=16, color=TEXT, bold=False, serif=False, center=False):
        image = self.font(size, bold, serif).render(str(text), True, color)
        rect = image.get_rect(center=pos) if center else image.get_rect(topleft=pos)
        self.canvas.blit(image, rect)
        return rect

    def wrapped(self, text, x, y, width, size=16, color=MUTED, line_height=None):
        line_height = line_height or size + 9
        line = ""
        for word in text.split():
            proposal = (line + " " + word).strip()
            if line and self.font(size).size(proposal)[0] > width:
                self.text(line, (x, y), size, color)
                y += line_height
                line = word
            else:
                line = proposal
        if line:
            self.text(line, (x, y), size, color)
            y += line_height
        return y

    def emblem(self, owner, center, size=24, color=None):
        color = color or COUNTRIES[owner].color
        x, y = center
        if COUNTRIES[owner].symbol == "mountain":
            pygame.draw.lines(self.canvas, color, False,
                              [(x-size, y+size//2), (x-size//4, y-size//2),
                               (x+size//4, y+size//3), (x+size//2, y-size//5),
                               (x+size, y+size//2)], 3)
        elif COUNTRIES[owner].symbol == "sun":
            pygame.draw.circle(self.canvas, color, (x, y), size//3, 2)
            for i in range(8):
                a = i * math.pi / 4
                pygame.draw.line(self.canvas, color,
                                 (x+math.cos(a)*size*.55, y+math.sin(a)*size*.55),
                                 (x+math.cos(a)*size*.85, y+math.sin(a)*size*.85), 2)
        else:
            for dy, spread in ((-size//2, .55), (0, .8)):
                pygame.draw.lines(self.canvas, color, False,
                                  [(x-size*spread, y+dy+size//2), (x, y+dy-size//3),
                                   (x+size*spread, y+dy+size//2)], 2)
            pygame.draw.line(self.canvas, color, (x, y), (x, y+size), 2)

    def make_map(self):
        """Кэшируем статичную геометрию: в основном цикле нет генерации карты."""
        surface = pygame.Surface((WORLD_W, WORLD_H))
        surface.fill(SEA)
        for x in range(0, WORLD_W, 50):
            pygame.draw.line(surface, (33, 55, 62), (x, 0), (x, WORLD_H))
        for y in range(0, WORLD_H, 50):
            pygame.draw.line(surface, (33, 55, 62), (0, y), (WORLD_W, y))
        center = polygon_center(self.coast)
        # Две линии вдоль берега имитируют старую морскую карту.
        for distance in (1.055, 1.025):
            ring = [(center[0]+(x-center[0])*distance,
                     center[1]+(y-center[1])*distance) for x, y in self.coast]
            pygame.draw.polygon(surface, (58, 80, 81), ring, 1)
        for p in self.provinces:
            pygame.draw.polygon(surface, owner_color(p.owner), p.polygon)
        for p in self.provinces:
            pygame.draw.polygon(surface, (65, 78, 70), p.polygon, 1)
        # Государственные границы толще внутренних границ провинций.
        for p in self.provinces:
            for a, b in zip(p.polygon, p.polygon[1:] + p.polygon[:1]):
                midpoint = ((a[0]+b[0])/2, (a[1]+b[1])/2)
                for nid in p.neighbors:
                    neighbor = self.provinces[nid]
                    if neighbor.owner != p.owner and point_in_polygon(midpoint, neighbor.polygon):
                        pygame.draw.line(surface, INK, a, b, 3)
                        break
        pygame.draw.polygon(surface, (202, 206, 176), self.coast, 2)
        return surface

    def world_point(self, screen_point):
        return (screen_point[0] - self.map_origin[0], screen_point[1] - self.map_origin[1])

    def province_at(self, screen_point):
        if not self.map_rect.collidepoint(screen_point):
            return None
        point = self.world_point(screen_point)
        for p in self.provinces:
            if point_in_polygon(point, p.polygon):
                return p.id
        return None

    def canvas_point(self, point):
        w, h = self.screen.get_size()
        scale = min(w / WIDTH, h / HEIGHT)
        return ((point[0]-(w-WIDTH*scale)/2)/scale,
                (point[1]-(h-HEIGHT*scale)/2)/scale)

    def present(self):
        w, h = self.screen.get_size()
        scale = min(w / WIDTH, h / HEIGHT)
        scaled_size = (max(1, round(WIDTH*scale)), max(1, round(HEIGHT*scale)))
        image = pygame.transform.smoothscale(self.canvas, scaled_size)
        self.screen.fill(BG)
        self.screen.blit(image, ((w-scaled_size[0])//2, (h-scaled_size[1])//2))
        pygame.display.flip()


    def button(self, rect, label, action, primary=False, active=False, size=14, enabled=True, hint=""):
        rect = pygame.Rect(rect)
        hover = rect.collidepoint(self.mouse)
        fill = GOLD if primary else mix(PANEL, LINE, .65 if hover else .16)
        if active:
            fill = mix(PANEL, GOLD, .13)
        if not enabled:
            fill = mix(BG, PANEL, .5)
        elif primary and hover:
            fill = mix(GOLD, TEXT, .18)
        pygame.draw.rect(self.canvas, fill, rect, border_radius=4)
        pygame.draw.rect(self.canvas, GOLD if active else LINE, rect, 1, border_radius=4)
        color = (INK if primary else TEXT) if enabled else MUTED
        self.text(label, rect.center, size, color, True, center=True)
        self.buttons.append((rect, action if enabled else ("explain", hint or "Действие сейчас недоступно")))
        if hover and hint:
            self.tooltip = hint

    def slider(self, rect, value, key, maximum=100):
        rect = pygame.Rect(rect)
        pygame.draw.rect(self.canvas, LINE, (rect.x, rect.centery-3, rect.w, 6), border_radius=3)
        fraction = max(0, min(1, value/max(1, maximum)))
        pygame.draw.rect(self.canvas, GOLD, (rect.x, rect.centery-3, round(rect.w*fraction), 6), border_radius=3)
        pygame.draw.circle(self.canvas, TEXT, (round(rect.x+rect.w*fraction), rect.centery), 7)
        self.sliders.append((rect, key, maximum))

    def adjust_slider(self, point):
        if self.dragging is None:
            return
        rect, key, maximum = self.dragging
        value = round(max(0, min(1, (point[0]-rect.x)/rect.w))*maximum)
        if key == "army":
            self.send_amount = maximum if value >= maximum*.98 else max(0, min(maximum, round(value/100)*100))
        else:
            self.state.set_policy(key, value)

    def notify(self, message):
        self.toast = message
        self.toast_until = pygame.time.get_ticks()+4300

    def sync_map(self):
        current = tuple(p.owner for p in self.provinces)
        if current != self.map_owners:
            self.map_surface = self.make_map()
            self.map_owners = current

    def start_game(self):
        self.provinces, self.coast = generate_world(self.seed)
        selected = next(p.id for p in self.provinces if p.owner == self.chosen)
        self.state = GameState(self.provinces, self.chosen, seed=self.seed, selected=selected)
        self.map_owners = ()
        self.sync_map()
        self.scene = "play"
        self.tab, self.province_tab = "country", "overview"
        self.order_mode = self.order_source = None
        self.toast = ""
        self.toast_until = 0
        self.autosave()
        self.notify("Кампания началась. Настройте бюджет и подготовьте границы. H — справка.")

    def autosave(self):
        if self.state is not None:
            ok, message = self.state.save(self.save_path)
            if not ok:
                self.notify(message)

    def load_game(self):
        try:
            loaded = GameState.load(self.save_path)
        except (OSError, ValueError) as error:
            self.notify("Не удалось загрузить кампанию: "+str(error))
            return
        self.state = loaded
        self.provinces = loaded.provinces
        self.seed = loaded.seed
        self.coast = COAST[:]
        self.map_owners = ()
        self.sync_map()
        self.scene = "play"
        self.tab = "province"
        self.order_mode = self.order_source = None
        self.notify("Кампания загружена")

    def act(self, action):
        kind, value = action
        if kind == "choose":
            self.chosen = value
        elif kind == "start":
            self.start_game()
        elif kind == "turn":
            if self.state.result:
                return
            self.order_mode = self.order_source = None
            ok, message = self.state.next_turn()
            self.sync_map()
            self.autosave()
            self.notify(message)
        elif kind == "select":
            self.state.selected = value
        elif kind == "tab":
            self.tab = value
        elif kind == "province_tab":
            self.province_tab = value
        elif kind == "build":
            ok, message = self.state.build(self.state.selected, value)
            self.notify(message)
        elif kind == "recruit":
            ok, message = self.state.recruit(self.state.selected, value)
            self.notify(message)
        elif kind == "order":
            p = self.provinces[self.state.selected]
            if p.owner != self.state.player or p.ready <= 0 or self.send_amount <= 0:
                self.notify("Выберите свою провинцию с боеготовыми войсками")
                return
            self.order_mode = value
            self.order_source = p.id
            self.notify("Выберите на карте прибрежную цель" if value == "sail" else "Выберите на карте соседнюю провинцию")
        elif kind == "cancel":
            self.order_mode = self.order_source = None
        elif kind == "diplomacy":
            target, diplomatic_action = value
            ok, message = self.state.diplomacy(target, diplomatic_action)
            self.notify(message)
        elif kind == "names":
            self.show_names = not self.show_names
        elif kind == "troops":
            self.show_troops = not self.show_troops
        elif kind == "menu":
            self.order_mode = None
            self.autosave()
            self.scene = "pause"
        elif kind == "resume":
            self.scene = "play"
        elif kind == "new":
            self.scene = "choose"
        elif kind == "back":
            self.scene = "pause"
        elif kind == "save":
            ok, message = self.state.save(self.save_path)
            self.notify(message)
        elif kind == "load":
            self.load_game()
        elif kind == "help":
            self.help_page = 0
            self.scene = "help"
        elif kind == "help_page":
            self.help_page = value
        elif kind == "log_scroll":
            self.log_scroll = max(0, min(max(0, len(self.state.log)-12), self.log_scroll+value))
        elif kind == "explain":
            self.notify(value)
        elif kind == "exit":
            self.autosave()
            self.running = False

    def handle_event(self, event):
        if event.type == pygame.QUIT:
            self.act(("exit", None))
        elif event.type == pygame.VIDEORESIZE:
            self.screen = pygame.display.set_mode((max(800, event.w), max(500, event.h)), pygame.RESIZABLE)
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                if self.order_mode:
                    self.order_mode = self.order_source = None
                elif self.scene == "play":
                    self.act(("menu", None))
                elif self.scene == "help":
                    self.scene = "play" if self.state else "choose"
                elif self.state is not None:
                    self.scene = "play"
            elif event.key in (pygame.K_RETURN, pygame.K_KP_ENTER):
                if self.scene == "choose":
                    self.start_game()
                elif self.scene == "play":
                    self.act(("turn", None))
                elif self.scene == "pause":
                    self.scene = "play"
            elif self.scene == "play":
                if event.key == pygame.K_n:
                    self.show_names = not self.show_names
                elif event.key == pygame.K_t:
                    self.show_troops = not self.show_troops
                elif event.key == pygame.K_F5:
                    self.act(("save", None))
                elif event.key == pygame.K_F9:
                    self.load_game()
                elif event.key == pygame.K_h:
                    self.act(("help", None))
            elif self.scene == "choose" and event.key in (pygame.K_1, pygame.K_2, pygame.K_3):
                self.chosen = event.key-pygame.K_1
        elif event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            point = self.canvas_point(event.pos)
            self.mouse = point
            self.draw()
            for rect, key, maximum in reversed(self.sliders):
                if rect.collidepoint(point):
                    self.dragging = (rect, key, maximum)
                    self.adjust_slider(point)
                    return
            for rect, action in reversed(self.buttons):
                if rect.collidepoint(point):
                    self.act(action)
                    return
            if self.scene == "play" and not self.state.result:
                pid = self.province_at(point)
                if pid is not None:
                    if self.order_mode:
                        method = self.state.sail if self.order_mode == "sail" else self.state.move
                        ok, message = method(self.order_source, pid, self.send_amount)
                        self.notify(message)
                        if ok:
                            self.order_mode = self.order_source = None
                            self.state.selected = pid
                            self.sync_map()
                    else:
                        self.state.selected = pid
                    self.tab = "province"
        elif event.type == pygame.MOUSEMOTION and self.dragging:
            self.adjust_slider(self.canvas_point(event.pos))
        elif event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            self.dragging = None
        elif event.type == pygame.MOUSEWHEEL and self.scene == "play" and self.tab == "log":
            self.act(("log_scroll", -event.y*2))

    def draw_choose(self):
        self.text("ПОШАГОВАЯ СТРАТЕГИЯ  /  1848", (48, 29), 13, GOLD, True)
        pygame.draw.line(self.canvas, LINE, (48, 63), (1392, 63))
        self.text("Эпоха держав", (48, 89), 57, TEXT, serif=True)
        self.text("Сто провинций. Три державы. Ваша история.", (51, 166), 20, MUTED)
        self.text("01  /  ВЫБОР СТРАНЫ", (51, 230), 13, GOLD, True)
        self.wrapped("Развивайте земли, стройте укрепления и ведите войска. "
                     "Ваша цель — объединить все 100 провинций Эльдеры.", 51, 266, 445, 18)
        self.text("ОДИН ХОД — ОДИН МЕСЯЦ", (51, 384), 12, GOLD, True)
        self.wrapped("Налоги, исследования, дипломатия и войны. "
                     "Автосохранение в конце каждого месяца.", 51, 413, 435, 16)
        preview = pygame.transform.smoothscale(self.preview_surface, (800, 496))
        self.canvas.blit(preview, (593, 80))
        self.text("КОНТИНЕНТ ЭЛЬДЕРА", (991, 88), 11, MUTED, center=True)
        self.text("100 ПРОВИНЦИЙ  ·  3 ДЕРЖАВЫ", (991, 565), 11, MUTED, center=True)
        for c in COUNTRIES:
            x = 48+c.id*455
            rect = pygame.Rect(x, 590, 434, 177)
            selected = self.chosen == c.id
            pygame.draw.rect(self.canvas, mix(PANEL, c.color, .12 if selected else .04), rect, border_radius=6)
            pygame.draw.rect(self.canvas, c.color if selected else LINE, rect, 2 if selected else 1, border_radius=6)
            self.emblem(c.id, (x+39, 627), 21)
            self.text(c.name, (x+77, 608), 25, TEXT, True)
            self.text(f"{c.start_count} провинций", (x+77, 643), 14, c.color)
            self.text("●" if selected else "○", (x+394, 605), 24, c.color if selected else MUTED)
            self.text(c.description, (x+21, 681), 14, MUTED)
            self.text(c.bonus, (x+21, 718), 16, c.color, True)
            self.buttons.append((rect, ("choose", c.id)))
        self.text("1–3  Выбор страны      Enter  Начать", (48, 787), 13, MUTED)
        if self.state:
            self.button((48, 825, 230, 49), "К текущей кампании", ("back", None))
        elif self.save_path.exists():
            self.button((48, 825, 230, 49), "Продолжить кампанию", ("load", None))
        self.button((300, 825, 180, 49), "Как играть", ("help", None))
        self.button((990, 825, 402, 49), f"Начать за {COUNTRIES[self.chosen].name}  →", ("start", None), True, size=16)

    def draw_map(self):
        self.canvas.blit(self.map_surface, self.map_origin)
        ox, oy = self.map_origin
        selected = self.provinces[self.state.selected]
        for p in self.provinces:
            points = [(ox+x, oy+y) for x, y in p.polygon]
            if p.id in selected.neighbors:
                pygame.draw.circle(self.canvas, TEXT, (round(ox+p.center[0]), round(oy+p.center[1]+17)), 2)
            if self.order_mode:
                source = self.provinces[self.order_source]
                possible = (p.coastal if self.order_mode == "sail" else p.id in source.neighbors)
                if possible:
                    pygame.draw.polygon(self.canvas, GOLD, points, 2)
            if p.id == self.hovered or p.id == selected.id:
                pygame.draw.polygon(self.canvas, mix(owner_color(p.owner), TEXT, .25), points)
                pygame.draw.polygon(self.canvas, TEXT, points, 3 if p.id == selected.id else 1)
            label = p.name if self.show_names else str(p.id+1)
            max_width = 78
            if self.show_names:
                for y in (p.center[1]-6, p.center[1]+6):
                    cross = []
                    for a, b in zip(p.polygon, p.polygon[1:]+p.polygon[:1]):
                        if min(a[1], b[1]) <= y < max(a[1], b[1]):
                            cross.append(a[0]+(y-a[1])*(b[0]-a[0])/(b[1]-a[1]))
                    if len(cross) >= 2:
                        max_width = min(max_width, 2*min(p.center[0]-min(cross), max(cross)-p.center[0])-6)
            rendered = self.font(9 if self.show_names else 11, True).render(label, True, INK)
            if rendered.get_width() > max_width:
                rendered = pygame.transform.smoothscale(rendered, (max(20, round(max_width)), rendered.get_height()))
            cy = oy+p.center[1]-(6 if self.show_troops else 0)
            self.canvas.blit(rendered, rendered.get_rect(center=(ox+p.center[0], cy)))
            if self.show_troops:
                troops = self.state.visible_troops(p.id)
                label = "?" if troops is None else number(troops)
                image = self.font(10, True).render(label, True, TEXT)
                rect = image.get_rect(center=(ox+p.center[0], oy+p.center[1]+9))
                pygame.draw.rect(self.canvas, INK, rect.inflate(7, 2), border_radius=2)
                self.canvas.blit(image, rect)
            if p.buildings.get("port", 0):
                self.text("⚓", (ox+p.center[0]+17, oy+p.center[1]-7), 12, INK)
        # Морские рейсы видны своей стороне; чужие — при наличии порта.
        for fleet in self.state.visible_fleets():
            source = self.provinces[fleet["source"]]
            target = self.provinces[fleet["target"]]
            sx, sy = ox+source.center[0], oy+source.center[1]
            tx, ty = ox+target.center[0], oy+target.center[1]
            # Морской путь огибает континент; значок не проходит сквозь сушу.
            start_angle = math.atan2(source.center[1]-310, source.center[0]-500)
            end_angle = math.atan2(target.center[1]-310, target.center[0]-500)
            delta = (end_angle-start_angle+math.pi) % (2*math.pi)-math.pi
            route = [(ox+500+490*math.cos(start_angle+delta*i/24),
                      oy+310+302*math.sin(start_angle+delta*i/24)) for i in range(25)]
            pygame.draw.lines(self.canvas, owner_color(fleet["owner"]), False, route, 2)
            progress = .3 if fleet.get("remaining", 2) >= 2 else .75
            angle = start_angle+delta*progress
            fx, fy = ox+500+490*math.cos(angle), oy+310+302*math.sin(angle)
            pygame.draw.polygon(self.canvas, TEXT, [(fx, fy-8), (fx-6, fy+5), (fx+6, fy+5)])
            self.text(str(fleet["troops"]), (fx, fy+12), 10, TEXT, True, center=True)
        x, y = 978, 220
        pygame.draw.line(self.canvas, MUTED, (x, y-17), (x, y+17))
        pygame.draw.line(self.canvas, MUTED, (x-17, y), (x+17, y))
        pygame.draw.polygon(self.canvas, GOLD, [(x, y-24), (x-4, y), (x+4, y)])
        self.text("С", (x, y-38), 12, GOLD, center=True)
        if self.hovered is not None:
            p = self.provinces[self.hovered]
            self.tooltip = f"{p.name} · {owner_name(p.owner)}" + (" · побережье" if p.coastal else "")

    def stat_box(self, x, y, label, value, color=TEXT, width=153):
        pygame.draw.rect(self.canvas, BG, (x, y, width, 58), border_radius=4)
        self.text(label, (x+10, y+8), 10, MUTED, True)
        self.text(value, (x+10, y+27), 19, color, True)

    def draw_province(self):
        p = self.provinces[self.state.selected]
        x = 1063
        color = owner_color(p.owner)
        self.text(f"ПРОВИНЦИЯ {p.id+1:03}"+("  /  ПОБЕРЕЖЬЕ" if p.coastal else ""), (x, 199), 11, MUTED, True)
        self.text(p.name, (x, 225), 29, TEXT, serif=True)
        pygame.draw.circle(self.canvas, color, (x+5, 283), 5)
        self.text(owner_name(p.owner), (x+20, 272), 17, color, True)
        tabs = (("overview", "Обзор"), ("buildings", "Постройки"), ("army", "Армия"))
        for i, (key, title) in enumerate(tabs):
            self.button((x+i*111, 309, 105, 31), title, ("province_tab", key), active=self.province_tab == key, size=12)
        if self.province_tab == "overview":
            self.stat_box(x, 356, "НАСЕЛЕНИЕ", number(p.population))
            self.stat_box(x+171, 356, "ЭКОНОМИКА", f"{self.state.effective_economy(p.id):.1f}")
            visible = self.state.visible_troops(p.id)
            self.stat_box(x, 428, "ВОЙСКА", "Нет данных" if visible is None else number(visible), color)
            self.stat_box(x+171, 428, "НЕДОВОЛЬСТВО", f"{p.unrest:.0f}%", GOLD if p.unrest >= 50 else TEXT)
            self.text("СТРОИТЕЛЬСТВО", (x, 508), 11, GOLD, True)
            if p.construction:
                key = p.construction["building"]
                months = p.construction.get("remaining", p.construction.get("months", 0))
                self.text(f"{BUILDINGS[key]['name']} · осталось {months} мес.", (x, 532), 13)
            else:
                self.text("Очередь свободна" if p.owner == self.state.player else "Нет сведений о проектах", (x, 532), 13, MUTED)
            self.text("СОСЕДИ С ОБЩЕЙ ГРАНИЦЕЙ", (x, 574), 11, GOLD, True)
            for i, nid in enumerate(sorted(p.neighbors, key=lambda n: self.provinces[n].name)):
                neighbor = self.provinces[nid]
                rx, ry = x+(i%2)*170, 601+(i//2)*32
                self.button((rx, ry, 158, 27), neighbor.name, ("select", nid), size=10)
                pygame.draw.circle(self.canvas, owner_color(neighbor.owner), (rx+7, ry+13), 3)
        elif self.province_tab == "buildings":
            self.draw_buildings(p)
        else:
            self.draw_army(p)

    def draw_buildings(self, p):
        own = p.owner == self.state.player
        for i, (key, building) in enumerate(BUILDINGS.items()):
            y = 351+i*69
            info = self.state.build_info(p.id, key)
            level = p.buildings.get(key, 0)
            pygame.draw.rect(self.canvas, BG, (1059, y, 335, 64), border_radius=4)
            self.text(f"{building['name']} {level}/{building['max_level']}", (1068, y+6), 13, TEXT, True)
            self.text(building["description"], (1068, y+29), 10, MUTED)
            self.text(f"Грамотность {building['unlock']}% · {info.get('months', building['months'])} мес.", (1068, y+46), 10, GOLD)
            available = own and info.get("available", False) and not self.state.result
            label = "Макс." if info.get("maxed") else f"{int(info.get('cost', 0))} ¤"
            self.button((1284, y+4, 101, 23), label, ("build", key), enabled=available,
                        size=11, hint=info.get("reason", "") or building["description"])
        if p.construction:
            self.text("Стройка уже идёт; дождитесь её завершения.", (1063, 775), 10, GOLD)
        elif not own:
            self.text("Строительство доступно в своих провинциях.", (1063, 775), 10, MUTED)

    def draw_army(self, p):
        own = p.owner == self.state.player
        visible = self.state.visible_troops(p.id)
        self.stat_box(1063, 356, "ГАРНИЗОН", "?" if visible is None else number(visible))
        self.stat_box(1234, 356, "БОЕГОТОВО", number(p.ready) if own else "?", GOLD)
        if not own:
            self.wrapped("Выберите свою провинцию, чтобы нанять или отправить войска. "
                         "Смотровая башня раскрывает гарнизоны соседей.", 1063, 443, 322, 15)
            return
        maximum = max(0, p.ready)
        self.send_amount = min(maximum, max(0, self.send_amount))
        self.text("ОТПРАВИТЬ ВОЙСК", (1063, 443), 11, GOLD, True)
        self.text(number(self.send_amount), (1318, 435), 20, TEXT, True)
        self.slider((1074, 477, 300, 27), self.send_amount, "army", maximum)
        self.button((1063, 524, 153, 40), "100 · 120 ¤", ("recruit", 100), hint="Нанять 100 солдат. Новобранцы готовы в следующем месяце")
        self.button((1234, 524, 153, 40), "500 · 600 ¤", ("recruit", 500), hint="Нанять 500 солдат")
        self.button((1063, 588, 324, 43), "Переместить / атаковать", ("order", "move"), True,
                    enabled=maximum > 0 and not self.state.result, hint="Выберите затем соседнюю провинцию на карте")
        self.button((1063, 646, 324, 40), "Отправить по морю", ("order", "sail"),
                    enabled=maximum > 0 and p.coastal and p.buildings.get("port", 0) > 0 and not self.state.result,
                    hint="Нужен порт в исходной провинции. Переход к побережью занимает два месяца")
        self.wrapped("Армия действует один раз в месяц. Для атаки чужой державы сначала объявите войну. "
                     "Крепость и башня усиливают оборону.", 1063, 710, 322, 13)

    def draw_country(self):
        state = self.state
        country = state.countries[state.player]
        forecast = state.forecast()
        x = 1063
        self.text("УПРАВЛЕНИЕ ДЕРЖАВОЙ", (x, 200), 12, GOLD, True)
        self.text("Месячный бюджет", (x, 228), 25, TEXT, serif=True)
        descriptions = (
            ("tax", "Налоги", "Выше 75% — риск отделения земель"),
            ("welfare", "Благосостояние", "Ниже 35% — убыль населения"),
            ("investment", "Инвестиции", "Ниже 35% — спад экономики"),
            ("research", "Исследования", "Чем больше, тем быстрее грамотность"),
        )
        for i, (key, title, hint) in enumerate(descriptions):
            y = 282+i*86
            value = country.policy[key]
            self.text(title, (x, y), 16, TEXT, True)
            self.text(f"{value}%", (1336, y), 16, GOLD, True)
            self.slider((x+8, y+25, 306, 24), value, key)
            self.text(hint, (x, y+52), 10, MUTED)
        pygame.draw.line(self.canvas, LINE, (x, 635), (1389, 635))
        items = (("Налоги и торговля", forecast.get("income", 0)+forecast.get("trade", 0)),
                 ("Бюджетные расходы", -forecast.get("spending", 0)),
                 ("Содержание армии", -forecast.get("upkeep", 0)),
                 ("Итог за месяц", forecast.get("net", 0)))
        for i, (label, amount) in enumerate(items):
            y = 653+i*31
            self.text(label, (x, y), 13, MUTED if i < 3 else TEXT)
            self.text(f"{amount:+.0f} ¤", (1295, y), 14, GOLD if amount >= 0 else (224, 142, 126), i == 3)

    def draw_diplomacy(self):
        state = self.state
        x = 1063
        self.text("ДИПЛОМАТИЯ", (x, 200), 12, GOLD, True)
        self.text("Соседи и партнёры", (x, 230), 23, TEXT, serif=True)
        for i, c in enumerate(c for c in COUNTRIES if c.id != state.player):
            y = 284+i*218
            pair = tuple(sorted((state.player, c.id)))
            eliminated = state.counts()[c.id] == 0
            status = "Держава распалась" if eliminated else "Война" if pair in state.wars else "Союз" if pair in state.alliances else "Мир"
            pygame.draw.rect(self.canvas, BG, (1059, y, 335, 200), border_radius=4)
            self.text(c.name, (1070, y+10), 22, c.color, True)
            self.text(f"{status}  ·  отношения {state.relations.get(pair, 0):+d}", (1070, y+43), 12, MUTED)
            self.text(f"Провинции: {state.counts()[c.id]}"+("  ·  торговля" if pair in state.trades else ""), (1070, y+68), 12, MUTED)
            war = pair in state.wars
            allied = pair in state.alliances
            trading = pair in state.trades
            self.button((1070, y+99, 151, 34), "Предложить мир" if war else "Объявить войну",
                        ("diplomacy", (c.id, "peace" if war else "war")), size=11, enabled=not eliminated)
            self.button((1231, y+99, 151, 34), "Разорвать союз" if allied else "Заключить союз",
                        ("diplomacy", (c.id, "break_alliance" if allied else "alliance")), size=11, enabled=not war and not eliminated)
            self.button((1070, y+146, 312, 34), "Расторгнуть торговый договор" if trading else "Предложить торговый договор",
                        ("diplomacy", (c.id, "cancel_trade" if trading else "trade")), size=11, enabled=not war and not eliminated)
        self.wrapped("Ответ зависит от отношений, силы и общих границ. Союз не позволяет атаковать партнёра.", x, 742, 322, 12)

    def draw_log(self):
        self.text("ЛЕТОПИСЬ КАМПАНИИ", (1063, 200), 12, GOLD, True)
        self.text("Последние события", (1063, 230), 24, TEXT, serif=True)
        y = 286
        for entry in self.state.log[self.log_scroll:self.log_scroll+12]:
            y = self.wrapped(str(entry), 1063, y, 323, 12, TEXT, 18)+13
            if y > 726:
                break
        self.button((1063, 749, 153, 31), "↑  Ранее", ("log_scroll", 4), size=12)
        self.button((1234, 749, 153, 31), "↓  Новее", ("log_scroll", -4), size=12)

    def draw_play(self):
        state = self.state
        country = state.countries[state.player]
        counts = state.counts()
        self.emblem(state.player, (54, 48), 24)
        self.text(COUNTRIES[state.player].name, (96, 22), 28, TEXT, serif=True)
        self.text(f"{counts[state.player]} / 100 ПРОВИНЦИЙ", (98, 63), 11, owner_color(state.player), True)
        self.text("КАЗНА", (360, 24), 11, MUTED, True)
        self.text(f"{number(country.treasury)} ¤", (360, 49), 23, GOLD, True)
        self.text("ГРАМОТНОСТЬ", (550, 24), 11, MUTED, True)
        self.text(f"{country.literacy:.1f}%", (550, 49), 23, TEXT, True)
        net = state.forecast().get("net", 0)
        self.text("БАЛАНС / МЕСЯЦ", (740, 24), 11, MUTED, True)
        self.text(f"{net:+.0f} ¤", (740, 49), 23, GOLD if net >= 0 else (224, 142, 126), True)
        self.text(f"{MONTHS[state.month]} {state.year}", (1010, 27), 23, TEXT, True)
        self.text(f"Ход {state.turn}", (1012, 65), 12, MUTED)
        self.button((1312, 28, 98, 44), "Меню", ("menu", None))
        pygame.draw.line(self.canvas, LINE, (30, 102), (1410, 102))
        self.text("ЭЛЬДЕРА", (35, 130), 17, TEXT, True)
        self.button((725, 123, 140, 32), "Армии [T]", ("troops", None), active=self.show_troops, size=11)
        self.button((878, 123, 152, 32), "Названия [N]", ("names", None), active=self.show_names, size=11)
        if self.order_mode:
            source = self.provinces[self.order_source]
            self.text(f"{source.name}: {number(self.send_amount)} → выберите цель", (205, 130), 13, GOLD)
            self.button((545, 123, 153, 32), "Отмена [Esc]", ("cancel", None), size=11)
        else:
            self.text("Выберите провинцию на карте", (205, 134), 12, MUTED)
        tabs = (("province", "Провинция"), ("country", "Страна"), ("diplomacy", "Дипломатия"), ("log", "События"))
        for i, (key, title) in enumerate(tabs):
            self.button((1045+i*93, 123, 87, 32), title, ("tab", key), active=self.tab == key, size=10)
        self.hovered = self.province_at(self.mouse)
        self.draw_map()
        pygame.draw.rect(self.canvas, PANEL, (1045, 182, 365, 620), border_radius=5)
        if self.tab == "province":
            self.draw_province()
        elif self.tab == "country":
            self.draw_country()
        elif self.tab == "diplomacy":
            self.draw_diplomacy()
        else:
            self.draw_log()
        for c in COUNTRIES:
            x = 40+c.id*330
            pygame.draw.circle(self.canvas, c.color, (x+6, 823), 5)
            self.text(c.name, (x+22, 811), 14, TEXT, True)
            pair = tuple(sorted((c.id, state.player)))
            status = "вы" if c.id == state.player else "война" if pair in state.wars else "союз" if pair in state.alliances else "мир"
            self.text(f"{counts[c.id]} провинций · {status}", (x+22, 837), 12, MUTED)
        self.text("H  Справка     F5  Сохранить     F9  Загрузить     Esc  Меню", (40, 879), 11, MUTED)
        self.button((1045, 818, 365, 53), "Следующий ход  →", ("turn", None), True, size=19, enabled=not state.result)
        self.text("Enter  ·  один месяц  ·  автосохранение", (1227, 887), 11, MUTED, center=True)
        if state.result:
            self.draw_result()

    def draw_result(self):
        # Окно результата перекрывает управление картой, но оставляет новую игру.
        self.buttons, self.sliders = [], []
        overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
        overlay.fill((8, 16, 22, 210))
        self.canvas.blit(overlay, (0, 0))
        victory = self.state.result == "victory"
        self.text("Континент объединён!" if victory else "Держава пала", (720, 310), 48, GOLD if victory else TEXT, serif=True, center=True)
        self.text("Все 100 провинций под вашим знаменем." if victory else "Вы потеряли все провинции. Начните новую историю.",
                  (720, 391), 20, MUTED, center=True)
        self.text(f"{MONTHS[self.state.month]} {self.state.year}  ·  ход {self.state.turn}", (720, 450), 18, TEXT, center=True)
        self.button((490, 525, 460, 54), "Новая кампания", ("new", None), True, size=18)
        self.button((490, 600, 460, 48), "Меню", ("menu", None))

    def draw_pause(self):
        self.text("Эпоха держав", (720, 115), 48, TEXT, serif=True, center=True)
        self.text(f"{COUNTRIES[self.state.player].name} · {MONTHS[self.state.month]} {self.state.year}", (720, 195), 18, MUTED, center=True)
        items = (("Продолжить", "resume"), ("Сохранить [F5]", "save"), ("Загрузить сохранение [F9]", "load"),
                 ("Как играть", "help"), ("Новая кампания", "new"), ("Выйти", "exit"))
        for i, (label, action) in enumerate(items):
            self.button((500, 265+i*77, 440, 55), label, (action, None), i == 0, size=17)
        self.text("Прогресс сохраняется в конце каждого месяца и при выходе.", (720, 782), 14, MUTED, center=True)

    def draw_help(self):
        self.text("Как играть", (55, 40), 38, TEXT, serif=True)
        pages = ("Начало и бюджет", "Постройки и развитие", "Армии и дипломатия")
        for i, title in enumerate(pages):
            self.button((55+i*445, 117, 425, 42), title, ("help_page", i), active=self.help_page == i)
        if self.help_page == 0:
            sections = (
                ("Объедините 100 провинций", "Выберите страну и захватите весь континент. Потеря последней провинции завершает кампанию поражением. Один ход равен одному месяцу. Противники развиваются и воюют в конце хода."),
                ("Настройте бюджет во вкладке «Страна»", "Налоги приносят деньги. Благосостояние и инвестиции ниже 35% вызывают спад населения и экономики. Исследования повышают грамотность. Ползунки независимы: следите за итоговым балансом, чтобы расходы не съели казну."),
                ("Не доводите земли до восстания", "Налоги выше 75% повышают недовольство. Бедность, долг и низкое благосостояние усиливают его. При высоком недовольстве провинция может отделиться и стать вольной. Низкие налоги и забота о населении успокаивают жителей."),
                ("Сохранения и управление", "ЛКМ открывает провинцию, N переключает названия, T — численность армий. Enter завершает месяц, Esc открывает меню. F5 сохраняет кампанию, F9 загружает последнее сохранение. Каждый новый месяц и выход из игры также сохраняют прогресс."),
            )
        elif self.help_page == 1:
            sections = tuple((f"{b['name']} · грамотность {b['unlock']}%", b['description']+f". Максимальный уровень: {b['max_level']}. Цена и срок увеличиваются с уровнем.") for b in BUILDINGS.values())
        else:
            sections = (
                ("Наём и передвижение", "Откройте свою провинцию → «Армия». Нанимайте по 100 или 500 солдат. Ползунком выберите отряд, нажмите «Переместить / атаковать» и затем соседнюю провинцию. Новобранцы и прибывшие войска смогут действовать со следующего месяца."),
                ("Война и оборона", "Перед атакой другой страны объявите войну во вкладке «Дипломатия». Вольные земли можно атаковать сразу. Победа зависит от численности, укреплений, бонуса Нордхольма и случайности. Смотровая башня раскрывает чужие гарнизоны по соседству; без разведки они отмечены знаком вопроса."),
                ("Порты и морские переходы", "Постройте порт на побережье. Выберите отряд и «Отправить по морю», затем прибрежную цель. Переход занимает два месяца. Свои отряды видны всегда, чужие — когда у вас есть порт. Численность и маршрут также записаны в событиях."),
                ("Договоры", "Союз мешает объявить войну партнёру: сначала разорвите его. Торговля даёт ежемесячный доход. ИИ оценивает предложения по отношениям, силе и соседству. Мир не всегда будет принят. Следите за событиями: противники тоже заключают договоры и объявляют войны."),
            )
        y = 200
        size = 15 if self.help_page == 1 else 17
        for title, body in sections:
            self.text(title, (65, y), 20 if self.help_page != 1 else 18, GOLD, True)
            y = self.wrapped(body, 65, y+35, 1290, size, TEXT, size+10)+25
        self.button((1060, 825, 325, 49), "Вернуться [Esc]", ("resume", None) if self.state else ("new", None), True)

    def draw(self):
        self.buttons, self.sliders = [], []
        self.tooltip = ""
        self.canvas.fill(BG)
        if self.scene == "choose":
            self.draw_choose()
        elif self.scene == "play":
            self.draw_play()
        elif self.scene == "help":
            self.draw_help()
        else:
            self.draw_pause()
        if self.tooltip and self.scene == "play" and not self.state.result:
            width = min(960, self.font(12).size(self.tooltip)[0]+24)
            tx = min(max(35, self.mouse[0]+15), WIDTH-width-15)
            ty = max(112, min(850, self.mouse[1]-34))
            pygame.draw.rect(self.canvas, BG, (tx, ty, width, 29), border_radius=4)
            self.text(self.tooltip, (tx+12, ty+6), 12, TEXT)
        if pygame.time.get_ticks() < self.toast_until and self.toast:
            lines = []
            words = self.toast.split()
            line = ""
            for word in words:
                candidate = (line+" "+word).strip()
                if line and self.font(15).size(candidate)[0] > 1090:
                    lines.append(line)
                    line = word
                else:
                    line = candidate
            lines.append(line)
            lines = lines[:3]
            width = max(self.font(15).size(line)[0] for line in lines)+40
            height = 22*len(lines)+22
            rect = pygame.Rect((WIDTH-width)//2, 103, width, height)
            pygame.draw.rect(self.canvas, BG, rect, border_radius=5)
            pygame.draw.rect(self.canvas, GOLD, rect, 1, border_radius=5)
            for i, line in enumerate(lines):
                self.text(line, (rect.x+20, rect.y+11+i*22), 15, GOLD)

    def run(self):
        try:
            self.draw()
            while self.running:
                self.mouse = self.canvas_point(pygame.mouse.get_pos())
                for event in pygame.event.get():
                    self.handle_event(event)
                self.draw()
                self.present()
                self.clock.tick(60)
        finally:
            pygame.quit()


def smoke_test(output_path):
    """Проверка собранного EXE в CI: реальная отрисовка и сохранение кампании."""
    os.environ["SDL_VIDEODRIVER"] = "dummy"
    app = Game()
    try:
        with tempfile.TemporaryDirectory() as folder:
            app.save_path = Path(folder)/"campaign.json"
            app.start_game()
            for tab in ("country", "diplomacy", "log", "province"):
                app.tab = tab
                app.draw()
                app.present()
            for tab in ("overview", "buildings", "army"):
                app.province_tab = tab
                app.draw()
            app.act(("turn", None))
            restored = GameState.load(app.save_path)
            if restored.turn != 2:
                raise RuntimeError("Не прошла проверка сохранения")
        Path(output_path).write_text("OK: render, game turn, save/load", encoding="utf-8")
    finally:
        pygame.quit()


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--smoke-test":
        smoke_test(sys.argv[2])
    else:
        Game().run()
