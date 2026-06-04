import asyncio
import logging
import threading
from collections import defaultdict
from datetime import datetime

from kivy.app import App
from kivy.uix.screenmanager import Screen
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.popup import Popup
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.scrollview import ScrollView
from kivy.clock import Clock
from kivy.properties import (
    StringProperty, ObjectProperty, BooleanProperty,
    ColorProperty, ListProperty, NumericProperty,
)
from kivy.utils import get_color_from_hex
from kivy.metrics import dp

from app.database import (
    is_tracked, set_tracked, get_tracked_ids, get_price_history,
    save_purchased, load_all_purchased, remove_purchased,
)

logger = logging.getLogger(__name__)

COLOUR_NAMES = {
    "DEFAULT": "Обычный",
    "RANK_NEWBIE": "Необычный",
    "RANK_STALKER": "Особый",
    "RANK_VETERAN": "Редкий",
    "RANK_MASTER": "Исключительный",
    "RANK_LEGEND": "Легендарный",
}

COLOUR_COLORS = {
    "DEFAULT": "#5a7a9a",
    "RANK_NEWBIE": "#00ff41",
    "RANK_STALKER": "#00e5ff",
    "RANK_VETERAN": "#bf00ff",
    "RANK_MASTER": "#ff0044",
    "RANK_LEGEND": "#ff6600",
}

QLT_NAMES = {
    0: "Обычный", 1: "Необычный", 2: "Особый",
    3: "Редкий", 4: "Исключительный", 5: "Легендарный", 6: "Легендарный",
}

QLT_COLORS = {
    0: "#5a7a9a", 1: "#00ff41", 2: "#00e5ff",
    3: "#bf00ff", 4: "#ff0044", 5: "#ff6600", 6: "#ff6600",
}

QLT_TO_KEY = {
    0: "DEFAULT", 1: "RANK_NEWBIE", 2: "RANK_STALKER",
    3: "RANK_VETERAN", 4: "RANK_MASTER", 5: "RANK_LEGEND", 6: "RANK_LEGEND",
}


def get_app():
    return App.get_running_app()


class StatusBar(BoxLayout):
    text = StringProperty("")


class ArtifactCard(BoxLayout):
    item_id = StringProperty("")
    name = StringProperty("")
    colour = StringProperty("DEFAULT")
    icon_source = StringProperty("")
    rarity_name = StringProperty("")
    rarity_color = ColorProperty(None)
    bg_color = ColorProperty(None)
    tracked = BooleanProperty(False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.rarity_name = COLOUR_NAMES.get(self.colour, self.colour)
        c = COLOUR_COLORS.get(self.colour, "#888888")
        self.rarity_color = get_color_from_hex(c)
        self.update_bg()

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            if touch.is_double_tap:
                app = get_app()
                if app.state:
                    item = app.state.get_item(self.item_id)
                    if item:
                        self._show_history()
                return True
            self.tracked = not self.tracked
            set_tracked(self.item_id, self.tracked)
            self.update_bg()
            return True
        return super().on_touch_down(touch)

    def update_bg(self):
        if self.tracked:
            self.bg_color = get_color_from_hex("#1a3050")
        else:
            self.bg_color = get_color_from_hex("#0e1625")

    def _show_history(self):
        app = get_app()
        if app.monitor:
            item = app.state.get_item(self.item_id)
            if item:
                HistoryPopup(
                    self.item_id, item.get("name", self.name),
                    app.state.icon_map.get(self.item_id, ""),
                    app.monitor.api,
                ).open()


class RarityFilterChip(BoxLayout):
    label_text = StringProperty("")
    chip_color = ColorProperty(get_color_from_hex("#5a7a9a"))
    active = BooleanProperty(True)
    filter_key = StringProperty("")

    def on_touch_down(self, touch):
        if self.collide_point(*touch.pos):
            self.active = not self.active
            app = get_app()
            if app.state:
                app.state._rarity_filters[self.filter_key] = self.active
            return True
        return super().on_touch_down(touch)


class MonitorResultRow(BoxLayout):
    item_id = StringProperty("")
    item_name = StringProperty("")
    qlt_name = StringProperty("")
    qlt_color = ColorProperty(None)
    ub_text = StringProperty("+0")
    min_price_text = StringProperty("0")
    discount_text = StringProperty("0%")
    discount_color = ColorProperty(get_color_from_hex("#00ff41"))
    icon_source = StringProperty("")
    row_color = ColorProperty(get_color_from_hex("#0d1520"))
    _per_qlt_data = None
    _parent_grid = None
    _detail_box = None

    def on_history(self):
        app = get_app()
        if app.monitor:
            HistoryPopup(
                self.item_id, self.item_name, self.icon_source, app.monitor.api,
                qlt_filter=self._per_qlt_data.get("qlt") if self._per_qlt_data else None,
                ub_filter=self._per_qlt_data.get("upgrade_bonus") if self._per_qlt_data else None,
            ).open()

    def show_details(self):
        pass


class HistoryPopup(Popup):
    popup_title = StringProperty("История цен")

    def __init__(self, item_id, name, icon_path, api, qlt_filter=None, ub_filter=None, **kwargs):
        super().__init__(**kwargs)
        self.item_id = item_id
        self.item_name = name
        self.icon_path = icon_path
        self.api = api
        self.qlt_filter = qlt_filter
        self.ub_filter = ub_filter
        self.popup_title = f"История: {name}"
        self._all_rows = []
        self._groups = {}
        threading.Thread(target=self._fetch_data, daemon=True).start()

    def _fetch_data(self):
        rows = []
        try:
            async def fetch():
                return await self.api.get_price_history_week(self.item_id, limit=200)
            raw = asyncio.run(fetch())
            if raw:
                for p in raw:
                    add = p.additional or {}
                    qlt = add.get("qlt", 0)
                    ub = add.get("ptn", 0) or 0
                    if self.qlt_filter is not None and qlt != self.qlt_filter:
                        continue
                    if self.ub_filter is not None and ub != self.ub_filter:
                        continue
                    rows.append({
                        "qlt": qlt, "upgrade_bonus": ub,
                        "avg_buyout": p.price,
                        "timestamp": p.time.isoformat() if p.time else "",
                    })
        except Exception as e:
            logger.warning(f"History fetch error: {e}")

        if not rows:
            try:
                db_rows = get_price_history(self.item_id, limit=500)
                for r in db_rows:
                    qlt = r["qlt"]
                    ub = r["upgrade_bonus"]
                    if self.qlt_filter is not None and qlt != self.qlt_filter:
                        continue
                    if self.ub_filter is not None and ub != self.ub_filter:
                        continue
                    rows.append({
                        "qlt": qlt, "upgrade_bonus": ub,
                        "avg_buyout": r["avg_buyout"],
                        "timestamp": r["timestamp"],
                    })
            except Exception as e:
                logger.exception(f"History DB error: {e}")

        self._all_rows = rows
        groups = defaultdict(list)
        for r in rows:
            groups[r["qlt"]].append(r)
        self._groups = dict(groups)
        Clock.schedule_once(lambda dt: self._render(), 0)

    def _render(self):
        self.ids.hist_status_label.text = f"Записей: {len(self._all_rows)}"
        self._build_chart()
        self._build_table()

    def _build_chart(self):
        container = self.ids.chart_container
        container.clear_widgets()
        if not self._groups:
            container.add_widget(Label(text="Нет данных для графика", color=(0.35, 0.48, 0.6, 1)))
            return
        try:
            import matplotlib
            matplotlib.use('module://kivy_garden.matplotlib.backend_kivyagg')
            from matplotlib.figure import Figure
            from kivy_garden.matplotlib.backend_kivyagg import FigureCanvasKivyAgg

            matplotlib.rcParams.update({
                "figure.facecolor": "#0a0e17",
                "axes.facecolor": "#0a0e17",
                "axes.edgecolor": "#1a3a5c",
                "axes.labelcolor": "#d4eaff",
                "xtick.color": "#5a7a9a",
                "ytick.color": "#5a7a9a",
                "grid.color": "#1a3a5c",
                "grid.alpha": 0.25,
            })

            fig = Figure(figsize=(5, 2), dpi=80)
            ax = fig.add_subplot(111)
            line_colors = ["#4ade80", "#60a5fa", "#fb923c", "#f87171", "#a78bfa", "#22d3ee"]

            for idx, (qlt, rows) in enumerate(sorted(self._groups.items())):
                sorted_rows = sorted(rows, key=lambda r: r["timestamp"])
                timestamps = [r["timestamp"] for r in sorted_rows]
                prices = [r["avg_buyout"] for r in sorted_rows]
                try:
                    x = [datetime.fromisoformat(t) for t in timestamps if t]
                except Exception:
                    x = list(range(len(prices)))
                qlt_name = QLT_NAMES.get(qlt, f"q{qlt}")
                ax.plot(x, prices, marker=".", linestyle="-",
                        color=line_colors[idx % len(line_colors)],
                        label=qlt_name, linewidth=1.5, markersize=3)

            ax.set_xlabel("Время")
            ax.set_ylabel("Цена")
            ax.legend(loc="upper left", fontsize=8, framealpha=0.8)
            ax.grid(True, alpha=0.25)
            fig.tight_layout()

            canvas = FigureCanvasKivyAgg(fig)
            container.add_widget(canvas)
        except ImportError:
            container.add_widget(Label(
                text="matplotlib не установлен",
                color=(1, 0, 0.27, 1),
            ))

    def _build_table(self):
        table = self.ids.history_table
        table.clear_widgets()
        all_filtered = [r for rows in self._groups.values() for r in rows]
        for i, r in enumerate(sorted(all_filtered, key=lambda x: x.get("timestamp", ""), reverse=True)):
            bg = get_color_from_hex("#0d1520") if i % 2 == 0 else get_color_from_hex("#111d30")
            row_frame = BoxLayout(size_hint_y=None, height=dp(28), spacing=dp(2))
            with row_frame.canvas.before:
                from kivy.graphics import Color, RoundedRectangle
                Color(*bg)
                RoundedRectangle(pos=row_frame.pos, size=row_frame.size, radius=[4, 4, 4, 4])
            row_frame.bind(pos=lambda inst, val: setattr(inst.canvas.before.children[-1], 'pos', inst.pos),
                           size=lambda inst, val: setattr(inst.canvas.before.children[-1], 'size', inst.size))

            qlt = r["qlt"]
            qlt_color = QLT_COLORS.get(qlt, "#888888")
            qlt_name = QLT_NAMES.get(qlt, f"q{qlt}")

            row_frame.add_widget(Label(
                text=qlt_name, font_size="9sp",
                color=get_color_from_hex(qlt_color),
                size_hint_x=0.2,
            ))
            ub = r["upgrade_bonus"]
            row_frame.add_widget(Label(
                text=f"+{ub:.4g}" if ub else "+0", font_size="9sp",
                color=(0.83, 0.92, 1, 1),
                size_hint_x=0.15,
            ))
            row_frame.add_widget(Label(
                text=f"{r['avg_buyout']:,}", font_size="9sp", bold=True,
                color=(0, 1, 0.25, 1),
                size_hint_x=0.25,
            ))
            ts = r.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                ts_fmt = dt.strftime("%d.%m %H:%M")
            except Exception:
                ts_fmt = ts
            row_frame.add_widget(Label(
                text=ts_fmt, font_size="8sp",
                color=(0.35, 0.48, 0.6, 1),
                size_hint_x=0.4,
            ))
            table.add_widget(row_frame)


class CatalogScreen(Screen):
    def build_cards(self):
        grid = self.ids.catalog_grid
        grid.clear_widgets()
        app = get_app()
        items = app.state.all_items_list
        for item_id, name, colour, cat, subcat, icon in items:
            icon_path = app.state.icon_map.get(item_id, "")
            tracked = is_tracked(item_id)
            card = ArtifactCard(
                item_id=item_id, name=name, colour=colour,
                icon_source=icon_path, tracked=tracked,
            )
            grid.add_widget(card)

    def on_search(self, text):
        grid = self.ids.catalog_grid
        query = text.lower().strip()
        for child in grid.children:
            if isinstance(child, ArtifactCard):
                if query == "" or query in child.name.lower():
                    child.opacity = 1
                    child.size_hint_y = None
                    child.height = dp(180)
                    child.disabled = False
                else:
                    child.opacity = 0
                    child.size_hint_y = None
                    child.height = 0
                    child.disabled = True

    def toggle_all(self):
        all_tracked = all(
            is_tracked(child.item_id)
            for child in self.ids.catalog_grid.children
            if isinstance(child, ArtifactCard)
        )
        new_state = not all_tracked
        for child in self.ids.catalog_grid.children:
            if isinstance(child, ArtifactCard):
                set_tracked(child.item_id, new_state)
                child.tracked = new_state
                child.update_bg()
        app = get_app()
        count = sum(1 for c in self.ids.catalog_grid.children if isinstance(c, ArtifactCard))
        label = app._status_bar if hasattr(app, '_status_bar') else None
        if label and new_state:
            label.text = f"Выбраны все {count} артефактов"
        elif label:
            label.text = "Все артефакты отключены"
        self.ids.select_toggle.text = "\u2716 \u2716" if new_state else "\u2713 \u2713"
        logger.info(f"Переключено {count} артефактов: {'все' if new_state else 'ни одного'}")


class MonitorScreen(Screen):
    btn_text = StringProperty("Запустить мониторинг")
    btn_color = ColorProperty(get_color_from_hex("#00cc33"))
    _monitoring = False

    def on_enter(self):
        self._build_rarity_chips()

    def _build_rarity_chips(self):
        grid = self.ids.rarity_grid
        grid.clear_widgets()
        app = get_app()
        filters = getattr(app.state, '_rarity_filters', {})
        for key, name in COLOUR_NAMES.items():
            color = get_color_from_hex(COLOUR_COLORS.get(key, "#5a7a9a"))
            active = filters.get(key, True)
            chip = RarityFilterChip(
                label_text=name, chip_color=color,
                active=active, filter_key=key,
            )
            grid.add_widget(chip)

    def get_active_rarities(self):
        app = get_app()
        filters = getattr(app.state, '_rarity_filters', None)
        if filters is None:
            return set(COLOUR_NAMES.keys())
        return {k for k, v in filters.items() if v}

    def toggle_monitoring(self):
        if self._monitoring:
            self._stop()
        else:
            self._start()

    def _start(self):
        app = get_app()
        if not app.monitor or not app.state:
            return

        min_ptn = int(self.ids.min_ptn_input.text or "0")
        min_profit = int(self.ids.profit_input.text or "20")
        days = int(self.ids.days_input.text or "14")

        self._monitoring = True
        self.btn_text = "Остановить"
        self.btn_color = get_color_from_hex("#cc0000")
        self.ids.monitor_status_label.text = "Мониторинг запущен..."
        grid = self.ids.monitor_results
        grid.clear_widgets()

        filters = getattr(app.state, '_rarity_filters', None)
        active_keys = None
        if filters is not None:
            active_keys = {k for k, v in filters.items() if v}

        def on_result(item_id, per_qlt, icon_path):
            item = app.state.get_item(item_id)
            if not item:
                return
            name = item["name"]
            profitable = {}
            for k, v in per_qlt.items():
                if v["discount_percent"] < min_profit:
                    continue
                qlt_key = QLT_TO_KEY.get(v["qlt"], "DEFAULT")
                if active_keys is not None and qlt_key not in active_keys:
                    continue
                profitable[k] = v
            if not profitable:
                return
            Clock.schedule_once(lambda dt: self._add_result_row(
                item_id, name, icon_path, profitable, days
            ))

        async def run():
            try:
                await app.monitor.monitor_loop(
                    on_result, min_ptn=min_ptn, days=days,
                    clear_results=lambda: Clock.schedule_once(lambda dt: grid.clear_widgets()),
                )
            except Exception as e:
                logger.exception(f"Monitor error: {e}")
            Clock.schedule_once(lambda dt: self._on_stopped())

        threading.Thread(
            target=lambda: asyncio.run(run()),
            daemon=True,
        ).start()

    def _add_result_row(self, item_id, name, icon_path, profitable, days):
        grid = self.ids.monitor_results
        for v in sorted(profitable.values(), key=lambda x: (x["qlt"], x["upgrade_bonus"])):
            qlt_color = get_color_from_hex(QLT_COLORS.get(v["qlt"], "#888888"))
            ub = v["upgrade_bonus"]
            disc = v["discount_percent"]
            row = MonitorResultRow(
                item_id=item_id,
                item_name=name,
                qlt_name=QLT_NAMES.get(v["qlt"], f"q{v['qlt']}"),
                qlt_color=qlt_color,
                ub_text=f"+{ub:.4g}" if ub else "+0",
                min_price_text=f"{v['min_buyout']:,}",
                discount_text=f"{disc:+.1f}%",
                discount_color=get_color_from_hex("#00ff41"),
                icon_source=icon_path,
            )
            row._per_qlt_data = v
            row._parent_grid = grid
            grid.add_widget(row)

            detail_box = BoxLayout(
                orientation="vertical",
                size_hint_y=None,
                height=dp(260),
                opacity=1,
            )
            detail_box._expanded = True
            detail_box._content_loaded = False
            row._detail_box = detail_box

            header = Label(
                text=f"История за {days} дн: {QLT_NAMES.get(v['qlt'], '')} +{ub:.4g}" if ub else "+0",
                size_hint_y=None, height=dp(18),
                font_size="8sp", color=(0, 0.9, 1, 1),
                halign="left", valign="middle",
            )
            detail_box.add_widget(header)

            scroll = ScrollView(size_hint_y=1)
            table = GridLayout(cols=4, spacing=0, size_hint_y=None,
                               height=dp(20), row_default_height=dp(18))
            table.bind(minimum_height=table.setter("height"))
            for col, w in [("Редкость", 0.25), ("Уровень", 0.15), ("Цена", 0.25), ("Дата", 0.35)]:
                table.add_widget(Label(
                    text=col, font_size="7sp", bold=True,
                    color=(0.35, 0.48, 0.6, 1),
                    size_hint_x=w,
                ))
            detail_box._table = table
            detail_box._loading = Label(
                text="Загрузка...", font_size="8sp",
                color=(0.35, 0.48, 0.6, 1),
                size_hint_y=None, height=dp(20),
            )
            scroll.add_widget(table)
            detail_box.add_widget(detail_box._loading)
            detail_box.add_widget(scroll)
            grid.add_widget(detail_box)

            threading.Thread(
                target=self._load_item_history,
                args=(detail_box, item_id, v["qlt"], ub, days),
                daemon=True,
            ).start()

    def _load_item_history(self, detail_box, item_id, qlt, ub, days=14):
        rows = []
        try:
            async def fetch():
                api = get_app().monitor.api if get_app().monitor else None
                if not api:
                    return []
                await api.reinit()
                return await api.get_price_history_week(item_id, days=days, limit=300)
            raw = asyncio.run(fetch())
            if raw:
                for p in raw:
                    add = p.additional or {}
                    pqlt = add.get("qlt", 0)
                    pub = add.get("ptn", 0) or 0
                    if pqlt == qlt and pub == ub:
                        rows.append({
                            "price": p.price,
                            "timestamp": p.time.isoformat() if p.time else "",
                        })
        except Exception as e:
            logger.warning(f"History API fetch: {e}")

        if not rows:
            try:
                from app.database import get_price_history as db_history
                db_rows = db_history(item_id, limit=500)
                for r in db_rows:
                    if r["qlt"] == qlt and r["upgrade_bonus"] == ub:
                        rows.append({
                            "price": r["avg_buyout"],
                            "timestamp": r["timestamp"],
                        })
            except Exception as e:
                logger.warning(f"History DB fetch: {e}")

        Clock.schedule_once(lambda dt: self._render_item_history(detail_box, rows, qlt, ub), 0)

    def _render_item_history(self, detail_box, rows, qlt, ub):
        detail_box.remove_widget(detail_box._loading)
        table = detail_box._table
        qlt_color = get_color_from_hex(QLT_COLORS.get(qlt, "#888888"))
        qlt_name = QLT_NAMES.get(qlt, f"q{qlt}")
        if not rows:
            for _ in range(4):
                table.add_widget(Label(text="", size_hint_x=0.25))
            table.add_widget(Label(
                text="Нет данных истории", font_size="8sp",
                color=(0.35, 0.48, 0.6, 1), size_hint_x=1,
            ))
            detail_box._content_loaded = True
            return

        prices = [r["price"] for r in rows]
        avg_price = round(sum(prices) / len(prices))
        min_price = min(prices)
        max_price = max(prices)
        current_price = rows[0]["price"]  # most recent
        profit_pct = round((avg_price - current_price) / avg_price * 100, 1) if avg_price > 0 else 0.0

        sorted_rows = sorted(rows, key=lambda x: x["timestamp"], reverse=True)
        table.height = dp(40) + len(sorted_rows) * dp(18)
        max_rows = 20 if len(sorted_rows) <= 20 else 15

        for col, w in [(f"Средняя {avg_price:,}", 0.35), (f"Выгода {profit_pct:+.1f}%", 0.25), (f"Записей {len(rows)}", 0.2), ("", 0.2)]:
            table.add_widget(Label(
                text=col, font_size="7sp", bold=True,
                color=(0, 1, 0.25, 1) if profit_pct > 0 else (0.35, 0.48, 0.6, 1),
                size_hint_x=w,
            ))

        for r in sorted_rows[:max_rows]:
            ts = r["timestamp"]
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                ts_fmt = dt.strftime("%d.%m %H:%M")
            except Exception:
                ts_fmt = ts[:16] if ts else ""
            table.add_widget(Label(
                text=qlt_name, font_size="7sp",
                color=qlt_color, size_hint_x=0.25,
            ))
            table.add_widget(Label(
                text=f"+{ub:.4g}" if ub else "+0",
                font_size="7sp",
                color=(0.83, 0.92, 1, 1), size_hint_x=0.15,
            ))
            table.add_widget(Label(
                text=f"{r['price']:,}", font_size="8sp", bold=True,
                color=(0, 1, 0.25, 1), size_hint_x=0.25,
            ))
            table.add_widget(Label(
                text=ts_fmt, font_size="7sp",
                color=(0.35, 0.48, 0.6, 1), size_hint_x=0.35,
            ))

        if len(sorted_rows) > max_rows:
            table.add_widget(Label(text="", size_hint_x=0.25))
            table.add_widget(Label(text="", size_hint_x=0.15))
            table.add_widget(Label(text="", size_hint_x=0.25))
            table.add_widget(Label(
                text=f"... \u0438 \u0435\u0449\u0451 {len(sorted_rows) - max_rows}",
                font_size="7sp", color=(0.5, 0.5, 0.5, 1), size_hint_x=0.35,
            ))
        detail_box._content_loaded = True

    def _stop(self):
        app = get_app()
        if app.monitor:
            app.monitor.stop()
        self._monitoring = False
        self.btn_text = "Запустить мониторинг"
        self.btn_color = get_color_from_hex("#00cc33")
        self.ids.monitor_status_label.text = "Мониторинг остановлен"

    def _on_stopped(self):
        self._monitoring = False
        self.btn_text = "Запустить мониторинг"
        self.btn_color = get_color_from_hex("#00cc33")
        self.ids.monitor_status_label.text = "Мониторинг остановлен"


class SettingsScreen(Screen):
    def on_enter(self):
        app = get_app()
        self.ids.telegram_id_input.text = app.app_config.telegram_chat_id
        self.ids.server_spinner.text = app.app_config.region
        self.ids.status_label.text = ""

    def save_settings(self):
        app = get_app()
        tg_id = self.ids.telegram_id_input.text.strip()
        server = self.ids.server_spinner.text.strip()
        app.app_config.telegram_chat_id = tg_id
        app.app_config.region = server
        app.app_config.save()
        self.ids.status_label.text = "Сохранено!"
        Clock.schedule_once(lambda dt: self._clear_status(), 2)

    def _clear_status(self):
        self.ids.status_label.text = ""
