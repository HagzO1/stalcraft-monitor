import asyncio
import logging
import os
import sys
import threading

from kivy.app import App
from kivy.uix.screenmanager import ScreenManager
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.clock import Clock
from kivy.lang import Builder
from kivy.core.window import Window
from kivy.utils import platform

from config import Config, set_config_dir
from app.api import StalcraftAPI, set_icon_cache_dir
from app.monitor import PriceMonitor, SharedState
from app.database import set_data_dir, init_db
from app.kivy_ui.screens import (
    CatalogScreen, MonitorScreen, SettingsScreen,
    StatusBar,
)

_log_dir = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(_log_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(_log_dir, "monitor.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    force=True,
)
logger = logging.getLogger(__name__)

Builder.load_file(os.path.join(os.path.dirname(__file__), "app", "kivy_ui", "stalcraft.kv"))


class StalcraftApp(App):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.app_config = Config.load()
        self.state = SharedState()
        self.api: StalcraftAPI | None = None
        self.monitor: PriceMonitor | None = None
        self._catalog_loaded = False

    def build(self):
        self.title = "Stalcraft Monitor"
        if platform == "android":
            Window.softinput_mode = "below_target"

        root = BoxLayout(orientation="vertical")

        sm = ScreenManager()
        sm.add_widget(CatalogScreen(name="catalog"))
        sm.add_widget(MonitorScreen(name="monitor"))
        sm.add_widget(SettingsScreen(name="settings"))
        sm.current = "catalog"
        self.sm = sm

        nav = BoxLayout(
            size_hint_y=None, height="52dp",
            spacing=0, padding=0,
        )

        nav_style = {
            "font_size": "10sp", "bold": True,
            "background_color": (0.05, 0.08, 0.12, 1),
            "background_normal": "",
        }

        def make_nav_btn(text, screen_name):
            btn = Button(text=text, **nav_style)
            btn.color = (0.35, 0.48, 0.6, 1)
            btn.bind(on_release=lambda instance: self._switch(instance, screen_name))
            return btn

        self._nav_btns = {}
        for label, sname in [("Каталог", "catalog"), ("Монитор", "monitor"),
                             ("Настройки", "settings")]:
            btn = make_nav_btn(label, sname)
            self._nav_btns[sname] = btn
            nav.add_widget(btn)

        self._status_bar = StatusBar(text="Загрузка...")
        self._update_nav("catalog")

        root.add_widget(sm)
        root.add_widget(nav)
        root.add_widget(self._status_bar)

        return root

    def _switch(self, btn_instance, screen_name):
        self.sm.current = screen_name
        self._update_nav(screen_name)

    def _update_nav(self, active):
        active_c = (0, 0.9, 1, 1)
        inactive_c = (0.35, 0.48, 0.6, 1)
        for name, btn in self._nav_btns.items():
            btn.color = active_c if name == active else inactive_c
            if name == active:
                btn.background_color = (0.08, 0.13, 0.22, 1)
            else:
                btn.background_color = (0.05, 0.08, 0.12, 1)

    def on_start(self):
        data_dir = os.path.join(self.user_data_dir, "data")
        set_data_dir(data_dir)
        set_config_dir(data_dir)
        set_icon_cache_dir(os.path.join(data_dir, "icons"))
        os.makedirs(data_dir, exist_ok=True)
        self._data_dir = data_dir
        threading.Thread(target=self._init_async_thread, daemon=True).start()

    def _init_async_thread(self):
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(self._init_async())
        loop.close()

    async def _init_async(self):
        init_db()
        self.api = StalcraftAPI(self.app_config)
        await self.api.init()
        logger.info("Stalcraft API инициализирован")

        self.monitor = PriceMonitor(self.api, self.app_config, self.state)
        self.monitor.start()
        await self.monitor.load_catalog()

        self._catalog_loaded = True
        Clock.schedule_once(lambda dt: self._on_catalog_loaded(), 0)

    def _on_catalog_loaded(self):
        catalog = self.sm.get_screen("catalog")
        catalog.build_cards()
        total = len(self.state.all_items_list)
        self._status_bar.text = f"{total} артефактов загружено"
        logger.info(f"Каталог загружен: {total} артефактов")


if __name__ == "__main__":
    StalcraftApp().run()
