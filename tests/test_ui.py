"""Проверки интерфейса через SDL dummy и настоящие события Pygame."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

import main as game

pygame = game.pygame


class InterfaceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.app = game.Game()
        self.app.save_path = Path(self.folder.name) / "campaign.json"
        self.app.mouse = (-1, -1)

    def tearDown(self):
        # Экран и шрифты создаются заново для каждого независимого сценария.
        pygame.quit()
        self.folder.cleanup()

    def screen_point(self, point):
        width, height = self.app.screen.get_size()
        scale = min(width / game.WIDTH, height / game.HEIGHT)
        return (round((width - game.WIDTH * scale) / 2 + point[0] * scale),
                round((height - game.HEIGHT * scale) / 2 + point[1] * scale))

    def mouse_down(self, point):
        self.app.handle_event(pygame.event.Event(
            pygame.MOUSEBUTTONDOWN, button=1, pos=self.screen_point(point)))

    def key(self, key):
        self.app.handle_event(pygame.event.Event(pygame.KEYDOWN, key=key))

    def click(self, action):
        self.app.draw()
        matches = [rect for rect, candidate in self.app.buttons if candidate == action]
        self.assertTrue(matches, f"Кнопка {action!r} недоступна в сцене {self.app.scene}")
        self.mouse_down(matches[-1].center)

    def click_province(self, province):
        ox, oy = self.app.map_origin
        self.mouse_down((ox + province.center[0], oy + province.center[1]))

    def start(self):
        self.click(("start", None))
        self.assertEqual(self.app.scene, "play")
        self.assertTrue(self.app.save_path.exists())

    def render(self):
        self.app.draw()
        self.app.present()
        self.assertEqual(self.app.canvas.get_size(), (game.WIDTH, game.HEIGHT))

    def test_choose_help_and_country_start(self):
        self.render()
        self.click(("help", None))
        self.assertEqual(self.app.scene, "help")
        for page in range(3):
            self.click(("help_page", page))
            self.assertEqual(self.app.help_page, page)
            self.render()
        self.key(pygame.K_ESCAPE)
        self.assertEqual(self.app.scene, "choose")
        self.click(("choose", 2))
        self.assertEqual(self.app.chosen, 2)
        self.start()
        self.assertEqual(self.app.state.player, 2)
        self.assertEqual(self.app.state.counts(), [40, 33, 27])
        self.assertEqual(self.app.provinces[self.app.state.selected].owner, 2)

    def test_all_tabs_panels_and_pause_render(self):
        self.start()
        own = next(p for p in self.app.provinces if p.owner == 0 and p.coastal)
        target = next(p for p in self.app.provinces if p.coastal and p.id != own.id)
        self.app.state.selected = own.id
        self.app.state.countries[0].treasury = 100000
        self.app.state.countries[0].literacy = 100
        own.buildings["port"] = 1
        self.app.state.fleets = [{"owner": 0, "source": own.id, "target": target.id,
                                  "troops": 100, "remaining": 2}]
        self.app.state.build(own.id, "farm")
        for tab in ("country", "diplomacy", "log", "province"):
            self.click(("tab", tab))
            self.assertEqual(self.app.tab, tab)
            self.render()
        for tab in ("overview", "buildings", "army"):
            self.click(("province_tab", tab))
            self.assertEqual(self.app.province_tab, tab)
            self.render()
        self.app.state.selected = next(p.id for p in self.app.provinces if p.owner != 0)
        for tab in ("overview", "buildings", "army"):
            self.click(("province_tab", tab))
            self.render()
        self.key(pygame.K_ESCAPE)
        self.assertEqual(self.app.scene, "pause")
        self.render()
        self.click(("help", None))
        self.render()
        self.key(pygame.K_ESCAPE)
        self.assertEqual(self.app.scene, "play")
        self.key(pygame.K_n)
        self.key(pygame.K_t)
        self.render()

    def test_budget_drag_reaches_zero_and_hundred(self):
        self.start()
        self.click(("tab", "country"))
        for policy in ("tax", "welfare", "investment", "research"):
            for value in (0, 100):
                self.app.draw()
                rect, _, _ = next(item for item in self.app.sliders if item[1] == policy)
                self.mouse_down(rect.center)
                self.assertIsNotNone(self.app.dragging)
                point = (rect.left - 15 if value == 0 else rect.right + 15, rect.centery)
                self.app.handle_event(pygame.event.Event(
                    pygame.MOUSEMOTION, pos=self.screen_point(point), rel=(0, 0), buttons=(1, 0, 0)))
                self.app.handle_event(pygame.event.Event(
                    pygame.MOUSEBUTTONUP, button=1, pos=self.screen_point(point)))
                self.assertIsNone(self.app.dragging)
                self.assertEqual(self.app.state.countries[0].policy[policy], value)
        self.render()

    def test_army_slider_can_select_entire_irregular_garrison(self):
        self.start()
        province = self.app.provinces[self.app.state.selected]
        self.click(("tab", "province"))
        self.click(("province_tab", "army"))
        for soldiers in (250, 137):
            with self.subTest(soldiers=soldiers):
                province.troops = province.ready = soldiers
                self.app.draw()
                rect, _, maximum = next(item for item in self.app.sliders if item[1] == "army")
                self.assertEqual(maximum, soldiers)
                self.mouse_down(rect.center)
                point = self.screen_point((rect.right + 10, rect.centery))
                self.app.handle_event(pygame.event.Event(
                    pygame.MOUSEMOTION, pos=point, rel=(0, 0), buttons=(1, 0, 0)))
                self.app.handle_event(pygame.event.Event(
                    pygame.MOUSEBUTTONUP, button=1, pos=point))
                self.assertEqual(self.app.send_amount, soldiers)

    def test_f5_f9_roundtrip_and_invalid_load_preserves_campaign(self):
        self.start()
        self.app.state.set_policy("tax", 61)
        self.app.state.countries[0].treasury = 3456
        self.key(pygame.K_F5)
        saved = self.app.state
        saved.set_policy("tax", 20)
        saved.countries[0].treasury = 12
        self.key(pygame.K_F9)
        self.assertIsNot(self.app.state, saved)
        self.assertEqual(self.app.state.countries[0].treasury, 3456)
        self.assertEqual(self.app.state.countries[0].policy["tax"], 61)
        self.assertIs(self.app.provinces, self.app.state.provinces)
        self.render()
        current = self.app.state
        self.app.save_path.write_text("{broken", encoding="utf-8")
        self.key(pygame.K_F9)
        self.assertIs(self.app.state, current)
        self.assertIn("Не удалось загрузить", self.app.toast)
        self.render()

    def test_map_clicks_transform_after_window_resize(self):
        self.start()
        for size in ((1440, 900), (1000, 800), (1920, 1080), (800, 500)):
            with self.subTest(size=size):
                self.app.handle_event(pygame.event.Event(
                    pygame.VIDEORESIZE, size=size, w=size[0], h=size[1]))
                for pid in (0, 1, 42, 99):
                    self.click_province(self.app.provinces[pid])
                    self.assertEqual(self.app.state.selected, pid)
                    self.assertEqual(self.app.tab, "province")
                selected = self.app.state.selected
                self.app.handle_event(pygame.event.Event(
                    pygame.MOUSEBUTTONDOWN, button=1, pos=(1, 1)))
                self.assertEqual(self.app.state.selected, selected)
                self.render()

    def test_land_order_executes_once_and_escape_cancels(self):
        self.start()
        source = next(p for p in self.app.provinces if p.owner == 0 and
                      any(self.app.provinces[n].owner == 0 for n in p.neighbors))
        target = next(self.app.provinces[n] for n in source.neighbors
                      if self.app.provinces[n].owner == 0)
        source.troops = source.ready = 500
        target.troops = target.ready = 0
        self.click_province(source)
        self.click(("province_tab", "army"))
        self.app.send_amount = 100
        self.click(("order", "move"))
        self.assertEqual((self.app.order_mode, self.app.order_source), ("move", source.id))
        self.click_province(target)
        self.assertEqual((source.troops, target.troops, target.ready), (400, 100, 0))
        self.assertIsNone(self.app.order_mode)
        self.assertEqual(self.app.state.selected, target.id)
        self.click_province(source)
        self.app.send_amount = 100
        self.click(("order", "move"))
        self.key(pygame.K_ESCAPE)
        self.assertIsNone(self.app.order_mode)
        self.assertEqual(self.app.scene, "play")
        self.assertEqual((source.troops, target.troops), (400, 100))

    def test_war_declaration_and_capture_with_mouse(self):
        self.start()
        source = next(p for p in self.app.provinces if p.owner == 0 and
                      any(self.app.provinces[n].owner == 1 for n in p.neighbors))
        target = next(self.app.provinces[n] for n in source.neighbors
                      if self.app.provinces[n].owner == 1)
        source.troops = source.ready = 1000
        target.troops = target.ready = 0
        self.click_province(source)
        self.click(("province_tab", "army"))
        self.app.send_amount = 500
        self.click(("order", "move"))
        self.click_province(target)
        self.assertEqual(target.owner, 1)
        self.assertEqual(source.troops, 1000)
        self.assertEqual(self.app.order_mode, "move")
        self.click(("tab", "diplomacy"))
        self.click(("diplomacy", (1, "war")))
        self.assertIn((0, 1), self.app.state.wars)
        self.click_province(target)
        self.assertEqual(target.owner, 0)
        self.assertEqual(source.troops, 500)
        self.assertIsNone(self.app.order_mode)
        self.assertEqual(self.app.map_owners[target.id], 0)
        self.render()

    def test_completed_campaign_blocks_turns_and_map_and_can_restart(self):
        self.start()
        for result in ("victory", "defeat"):
            with self.subTest(result=result):
                owner = 0 if result == "victory" else 1
                for p in self.app.provinces:
                    p.owner = owner
                self.app.state.result = result
                self.app.sync_map()
                self.render()
                self.assertFalse(self.app.sliders)
                self.assertNotIn(("turn", None), [action for _, action in self.app.buttons])
                turn, selected = self.app.state.turn, self.app.state.selected
                self.key(pygame.K_RETURN)
                self.mouse_down((1230, 845))
                self.click_province(self.app.provinces[(selected+1) % 100])
                self.assertEqual((self.app.state.turn, self.app.state.selected), (turn, selected))
        self.click(("new", None))
        self.assertEqual(self.app.scene, "choose")
        self.start()
        self.assertIsNone(self.app.state.result)
        self.assertEqual((self.app.state.turn, self.app.state.counts()), (1, [40, 33, 27]))


if __name__ == "__main__":
    unittest.main()
