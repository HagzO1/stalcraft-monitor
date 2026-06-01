import logging
import threading
from collections import defaultdict
from datetime import datetime
from typing import Optional

import customtkinter as ctk
from PIL import Image

from config import Config
from app.database import is_tracked, set_tracked, get_price_history, save_purchased
from app.monitor import SharedState

logger = logging.getLogger(__name__)


def flush_logs():
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass


ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# ── HI-TECH / Cyberpunk palette ──────────────────────────
BG_DARK = "#0a0e17"       # main background (deep navy)
BG_MID = "#0d1520"        # card / frame bg (dark navy)
BG_LIGHT = "#111d30"      # elevated surface (blue)
BG_HOVER = "#162840"      # hover state for buttons
BG_HEADER = "#081426"     # table / section headers (deep navy)
ACCENT = "#00e5ff"        # primary accent (neon cyan)
ACCENT_HOVER = "#00b8d4"  # hover
ACCENT_GREEN = "#00ff41"  # success green (matrix)
GREEN_BTN = "#00cc33"     # green button
GREEN_BTN_HOVER = "#009926"
RED_BTN = "#ff0044"       # stop button
RED_BTN_HOVER = "#cc0033"
TEXT_PRIMARY = "#d4eaff"  # main text (ice blue)
TEXT_SECONDARY = "#5a7a9a"  # muted text (steel blue)
BORDER = "#1a3a5c"        # separators / borders

THUMB_SIZE = (44, 44)

_icon_cache: dict[str, ctk.CTkImage] = {}

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
    "RANK_MASTER": "#ff6600",
    "RANK_LEGEND": "#ff0044",
}

QLT_NAMES = {
    0: "Обычный",
    1: "Необычный",
    2: "Особый",
    3: "Редкий",
    4: "Исключительный",
    5: "Легендарный",
    6: "Легендарный",
}

QLT_COLORS = {
    0: "#5a7a9a", 1: "#00ff41",
    2: "#00e5ff", 3: "#bf00ff",
    4: "#ff6600", 5: "#ff0044",
    6: "#ff0044",
}

CARD_SIZE = (148, 182)


class HistoryWindow:
    def __init__(self, parent, api, item_id: str, name: str, icon_path: str, limit: int = 200):
        self.api = api
        self.item_id = item_id
        self.name = name
        self.icon_path = icon_path
        self._limit = limit
        self._all_rows: list[dict] = []
        self._groups: dict = {}
        self._filter_qlt: int | None = None
        self._fetch_gen = 0
        self.window = ctk.CTkToplevel(parent)
        self.window.title(f"История продаж: {name}")
        self.window.geometry("1000x700")

        self.window.grid_rowconfigure(4, weight=1)
        self.window.grid_columnconfigure(0, weight=1)

        self._title = ctk.CTkLabel(self.window, text=f"История цен — {name} (последние {limit})",
                                    font=ctk.CTkFont(size=15, weight="bold"))


        filter_row = ctk.CTkFrame(self.window, fg_color="transparent")
        filter_row.grid(row=1, column=0, padx=12, pady=(0, 4), sticky="ew")

        ctk.CTkLabel(filter_row, text="Редкость:", font=ctk.CTkFont(size=11)).grid(row=0, column=0, padx=(0, 4), sticky="w")
        self._rarity_options = ["Все"] + [QLT_NAMES[i] for i in range(7)]
        self._rarity_var = ctk.StringVar(value="Все")
        self._rarity_menu = ctk.CTkOptionMenu(filter_row, values=self._rarity_options,
                                                variable=self._rarity_var,
                                                font=ctk.CTkFont(size=10),
                                                command=self._on_rarity_filter,
                                                fg_color=BG_MID, button_color=BG_HOVER,
                                                button_hover_color="#1e3050",
                                                dropdown_fg_color=BG_MID,
                                                dropdown_hover_color=BG_HOVER,
                                                text_color=TEXT_PRIMARY)
        self._rarity_menu.grid(row=0, column=1, padx=4, sticky="w")

        ctk.CTkLabel(filter_row, text="   Записей:", font=ctk.CTkFont(size=11)).grid(row=0, column=2, padx=(10, 4), sticky="w")
        self._limit_var = ctk.StringVar(value=str(limit))
        self._limit_entry = ctk.CTkEntry(filter_row, width=65, font=ctk.CTkFont(size=10),
                                          textvariable=self._limit_var, corner_radius=4,
                                          fg_color=BG_MID, border_color=BORDER,
                                          text_color=TEXT_PRIMARY)
        self._limit_entry.grid(row=0, column=3, padx=4, sticky="w")

        self._refresh_btn = ctk.CTkButton(filter_row, text="Обновить", width=80,
                                           font=ctk.CTkFont(size=10), corner_radius=4,
                                           command=self._on_refresh)
        self._refresh_btn.grid(row=0, column=5, padx=4, sticky="w")

        self._status = ctk.CTkLabel(self.window, text="Загрузка данных...",
                                     font=ctk.CTkFont(size=11), text_color=TEXT_SECONDARY)
        self._status.grid(row=2, column=0, padx=12, pady=(0, 4), sticky="w")

        self._canvas_frame = ctk.CTkFrame(self.window, fg_color=BG_DARK, height=280, corner_radius=8)
        self._canvas_frame.grid(row=3, column=0, sticky="ew", padx=12, pady=2)
        self._canvas_frame.grid_propagate(False)
        self._canvas_frame.grid_rowconfigure(0, weight=1)
        self._canvas_frame.grid_columnconfigure(0, weight=1)

        table_frame = ctk.CTkFrame(self.window, fg_color="transparent")
        table_frame.grid(row=4, column=0, sticky="nsew", padx=12, pady=(6, 10))
        table_frame.grid_rowconfigure(2, weight=1)
        table_frame.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(table_frame, text="История продаж:",
                      font=ctk.CTkFont(size=12, weight="bold")).grid(row=0, column=0, sticky="w", pady=(0, 4))

        hdr = ctk.CTkFrame(table_frame, fg_color=BG_HEADER, corner_radius=6, height=28)
        hdr.grid(row=1, column=0, sticky="ew")
        hdr.grid_columnconfigure(0, weight=0, minsize=100)
        hdr.grid_columnconfigure(1, weight=1)
        hdr.grid_columnconfigure(2, weight=0, minsize=100)
        hdr.grid_columnconfigure(3, weight=0, minsize=170)

        for i, h in enumerate(["Редкость", "Уровень", "Цена", "Время"]):
            ctk.CTkLabel(hdr, text=h, font=ctk.CTkFont(size=9, weight="bold"),
                          text_color=TEXT_SECONDARY).grid(row=0, column=i, padx=6, pady=3, sticky="w")

        self._table_scroll = ctk.CTkScrollableFrame(table_frame, fg_color="transparent",
                                                      scrollbar_button_color=SCROLLBAR_COLOR,
                                                      scrollbar_button_hover_color=BG_HOVER)
        self._table_scroll.grid(row=2, column=0, sticky="nsew", pady=(2, 0))
        self._table_scroll.grid_columnconfigure(0, weight=0, minsize=100)
        self._table_scroll.grid_columnconfigure(1, weight=1)
        self._table_scroll.grid_columnconfigure(2, weight=0, minsize=100)
        self._table_scroll.grid_columnconfigure(3, weight=0, minsize=170)

        self._table_empty = ctk.CTkLabel(self._table_scroll, text="Нет данных",
                                          font=ctk.CTkFont(size=10), text_color=TEXT_SECONDARY)
        self._table_empty.grid(row=0, column=0, columnspan=4, pady=20)

        threading.Thread(target=self._fetch_data, daemon=True).start()

    def _on_refresh(self):
        try:
            if not self.window.winfo_exists():
                return
            self._limit = max(1, min(10000, int(self._limit_var.get())))
        except ValueError:
            self._limit = 200
        except Exception:
            return
        self._limit_var.set(str(self._limit))
        self._title.configure(text=f"История цен — {self.name} (последние {self._limit})")
        self._status.configure(text="Загрузка данных...")
        try:
            for w in self._canvas_frame.winfo_children():
                w.destroy()
            for w in self._table_scroll.winfo_children():
                w.destroy()
        except Exception:
            pass
        self._table_empty = ctk.CTkLabel(self._table_scroll, text="Нет данных",
                                          font=ctk.CTkFont(size=10), text_color=TEXT_SECONDARY)
        self._table_empty.grid()
        self._all_rows = []
        self._groups = {}
        self._fetch_gen += 1
        threading.Thread(target=self._fetch_data, daemon=True).start()

    def _fetch_data(self):
        import asyncio
        logger.info(f"_fetch_data START для {self.name}, limit={self._limit}")
        gen = self._fetch_gen
        rows = []
        try:
            async def fetch():
                http = self.api.client._http if self.api.client else None
                if http:
                    http._session = None
                logger.info(f"_fetch_data: вызываю get_price_history_week для {self.name}, limit={self._limit}")
                return await asyncio.wait_for(
                    self.api.get_price_history_week(self.item_id, limit=self._limit),
                    timeout=30.0,
                )
            raw = asyncio.run(fetch())
            if self._fetch_gen != gen:
                logger.info(f"_fetch_data: stale gen, return")
                return
            if raw:
                seen = set()
                for p in raw:
                    add = p.additional or {}
                    qlt = add.get("qlt", 0)
                    ub = add.get("ptn", 0) or 0
                    key = (qlt, ub, p.price, p.time.isoformat() if p.time else "")
                    if key in seen:
                        continue
                    seen.add(key)
                    rows.append({
                        "qlt": qlt, "upgrade_bonus": ub,
                        "avg_buyout": p.price, "min_buyout": p.price,
                        "timestamp": p.time.isoformat() if p.time else "",
                    })
                logger.info(f"_fetch_data: {len(rows)} записей из API для {self.name}")
        except Exception as e:
            logger.warning(f"_fetch_data: API error для {self.name}: {e}")

        if not rows:
            try:
                db_rows = get_price_history(self.item_id, limit=500)
                if self._fetch_gen == gen:
                    seen = set()
                    for r in db_rows:
                        key = (r["qlt"], r["upgrade_bonus"], r["avg_buyout"], r["timestamp"])
                        if key not in seen:
                            seen.add(key)
                            rows.append(r)
                    logger.info(f"_fetch_data: {len(rows)} записей из БД для {self.name}")
            except Exception as dberr:
                if self._fetch_gen == gen:
                    logger.exception(f"_fetch_data: DB error: {dberr}")
                    self.window.after(0, lambda: self._status.configure(
                        text=f"Ошибка БД: {dberr}", text_color="#ff0044"))
                return

        if not rows or self._fetch_gen != gen:
            if self._fetch_gen == gen:
                logger.warning(f"_fetch_data: нет данных для {self.name}")
                self.window.after(0, lambda: self._status.configure(
                    text="Нет данных. Запустите мониторинг для сбора статистики", text_color="#888888"))
            return

        self._all_rows = rows
        groups = defaultdict(list)
        for r in rows:
            groups[r["qlt"]].append(r)
        self._groups = dict(groups)
        logger.info(f"_fetch_data: рендер для {self.name}, {len(groups)} групп")
        self.window.after(0, self._render)

    def _on_rarity_filter(self, choice: str):
        try:
            if not self.window.winfo_exists():
                return
        except Exception:
            return
        qlt_map = {name: q for q, name in QLT_NAMES.items()}
        self._filter_qlt = qlt_map.get(choice) if choice != "Все" else None
        self._render()

    def _render(self):
        try:
            if not self.window.winfo_exists():
                logger.info("_render: окно не существует, выход")
                return
        except Exception:
            return
        logger.info(f"_render вызван для {self.name}, groups={list(self._groups.keys()) if self._groups else None}, filter={self._filter_qlt}")
        if not self._groups:
            logger.info("_render: нет групп, выход")
            return
        if self._filter_qlt is not None:
            filtered = {k: v for k, v in self._groups.items() if k == self._filter_qlt}
        else:
            filtered = self._groups
        logger.info(f"_render: filtered keys={list(filtered.keys())}, total rows={sum(len(v) for v in filtered.values())}")
        try:
            canvas_children = self._canvas_frame.winfo_children()
            logger.info(f"_render: canvas_frame children={len(canvas_children)}")
            for w in canvas_children:
                w.destroy()
            table_children = self._table_scroll.winfo_children()
            logger.info(f"_render: table_scroll children={len(table_children)}")
            for w in table_children:
                w.destroy()
        except Exception as e:
            logger.exception(f"_render: ошибка при очистке виджетов: {e}")
            return
        self._table_empty = ctk.CTkLabel(self._table_scroll, text="Нет данных",
                                          font=ctk.CTkFont(size=10), text_color=TEXT_SECONDARY)
        if not filtered:
            self._table_empty.grid()
            self._status.configure(text="Нет данных для выбранной редкости")
            logger.info("_render: filtered пуст, показываю пустой экран")
            return
        try:
            self._plot_and_table(filtered)
            logger.info(f"_render: _plot_and_table завершён для {self.name}")
        except Exception as e:
            logger.exception(f"_render: исключение в _plot_and_table: {e}")
            self._status.configure(text=f"Ошибка рендера: {e}", text_color="#ff0044")

    def _plot_and_table(self, groups: dict):
        try:
            self._table_empty.grid_forget()
        except Exception:
            pass
        self._status.configure(text=f"Записей: {len(self._all_rows)}")

        import matplotlib
        matplotlib.use("TkAgg")
        from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
        from matplotlib.figure import Figure

        matplotlib.rcParams.update({
            "figure.facecolor": BG_DARK,
            "axes.facecolor": BG_DARK,
            "axes.edgecolor": BORDER,
            "axes.labelcolor": TEXT_PRIMARY,
            "xtick.color": TEXT_SECONDARY,
            "ytick.color": TEXT_SECONDARY,
            "grid.color": BORDER,
            "grid.alpha": 0.25,
            "legend.facecolor": BG_LIGHT,
            "legend.edgecolor": BORDER,
            "legend.labelcolor": TEXT_PRIMARY,
        })

        fig = Figure(figsize=(10, 2.6), dpi=100)
        ax = fig.add_subplot(111)

        line_colors = ["#4ade80", "#60a5fa", "#fb923c", "#f87171", "#a78bfa", "#22d3ee"]

        for idx, (qlt, rows) in enumerate(sorted(groups.items())):
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
        ax.set_title(f"История цен по редкости: {self.name}", color=TEXT_PRIMARY)
        ax.legend(loc="upper left", fontsize=8, framealpha=0.8)
        ax.grid(True, alpha=0.25)
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=self._canvas_frame)
        canvas.draw()
        canvas_widget = canvas.get_tk_widget()
        canvas_widget.grid(row=0, column=0, sticky="nsew")

        all_filtered = [r for rows in groups.values() for r in rows]
        for i, r in enumerate(sorted(all_filtered, key=lambda x: x.get("timestamp", ""), reverse=True)):
            bg = BG_MID if i % 2 == 0 else BG_LIGHT
            row_frame = ctk.CTkFrame(self._table_scroll, fg_color=bg, corner_radius=4)
            row_frame.grid_columnconfigure(0, weight=0, minsize=100)
            row_frame.grid_columnconfigure(1, weight=1)
            row_frame.grid_columnconfigure(2, weight=0, minsize=100)
            row_frame.grid_columnconfigure(3, weight=0, minsize=170)

            qlt = r["qlt"]
            qlt_color = QLT_COLORS.get(qlt, "#888888")
            qlt_name = QLT_NAMES.get(qlt, f"q{qlt}")

            ctk.CTkLabel(row_frame, text=qlt_name, font=ctk.CTkFont(size=10),
                          text_color=qlt_color).grid(row=0, column=0, padx=6, pady=2, sticky="w")

            ub = r["upgrade_bonus"]
            ctk.CTkLabel(row_frame, text=f"+{ub:.4g}" if ub else "+0",
                          font=ctk.CTkFont(size=10)).grid(row=0, column=1, padx=6, pady=2, sticky="w")

            ctk.CTkLabel(row_frame, text=f"{r['avg_buyout']:,}",
                          font=ctk.CTkFont(size=10, weight="bold"),
                          text_color=ACCENT_GREEN).grid(row=0, column=2, padx=6, pady=2, sticky="w")

            ts = r.get("timestamp", "")
            try:
                dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
                ts_fmt = dt.strftime("%d.%m.%Y %H:%M")
            except Exception:
                ts_fmt = ts
            ctk.CTkLabel(row_frame, text=ts_fmt, font=ctk.CTkFont(size=9),
                          text_color=TEXT_SECONDARY).grid(row=0, column=3, padx=6, pady=2, sticky="w")

            row_frame.pack(fill="x", pady=1)


class AppUI:
    def __init__(self, config: Config):
        self.config = config
        self.state: Optional[SharedState] = None
        self.monitor = None
        self._root: Optional[ctk.CTk] = None
        self._cards: dict[str, "ArtifactCard"] = {}
        self._search_text = ""
        self._monitoring = False
        self._monitor_panel: Optional["MonitoringPanel"] = None
        self._deals_panel: Optional["ProfitableDealsTab"] = None
        self._purchased_panel: Optional["PurchasedTab"] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitor_loop = None
        self._monitor_gen = 0
        self._current_days = 30

    def set_monitor(self, monitor):
        self.monitor = monitor

    def run(self):
        root = ctk.CTk()
        self._root = root
        root.title("Stalcraft — Монитор артефактов")
        root.geometry("1200x800")
        self._build_ui(root)
        root.protocol("WM_DELETE_WINDOW", self._on_close)
        root.after(500, self._delayed_load)
        root.mainloop()

    def _build_ui(self, root: ctk.CTk):
        root.grid_rowconfigure(0, weight=1)
        root.grid_columnconfigure(0, weight=1)

        tabview = ctk.CTkTabview(root, corner_radius=8, fg_color=BG_DARK)
        tabview._segmented_button.configure(fg_color=BG_MID, selected_color=BG_HEADER,
                                             unselected_color=BG_LIGHT,
                                             unselected_hover_color=BG_HOVER,
                                             font=ctk.CTkFont(size=14, weight="bold"))
        tabview.grid(row=0, column=0, sticky="nsew", padx=6, pady=6)
        tab_catalog = tabview.add("Каталог")
        tab_scan = tabview.add("Сканирование")

        tab_catalog.grid_rowconfigure(1, weight=1)
        tab_catalog.grid_columnconfigure(0, weight=1)
        tab_scan.grid_rowconfigure(5, weight=1)
        tab_scan.grid_columnconfigure(0, weight=1)

        self._search_timer: str | None = None
        search_var = ctk.StringVar()
        search_var.trace_add("write", lambda *a: self._on_search_debounce(search_var.get()))
        search_entry = ctk.CTkEntry(tab_catalog, placeholder_text="🔍 Поиск артефакта...",
                                     width=280, font=ctk.CTkFont(size=12), corner_radius=6,
                                     border_color=BORDER, fg_color=BG_MID,
                                     text_color=TEXT_PRIMARY)
        search_entry.grid(row=0, column=0, padx=10, pady=(8, 4), sticky="ew")

        scroll = ctk.CTkScrollableFrame(tab_catalog, corner_radius=6,
                                          scrollbar_button_color=SCROLLBAR_COLOR,
                                          scrollbar_button_hover_color=BG_HOVER)
        scroll.grid(row=1, column=0, sticky="nsew", padx=10, pady=4)
        for i in range(6):
            scroll.grid_columnconfigure(i, weight=1, uniform="card")
        self._scroll = scroll

        self._loading_label = ctk.CTkLabel(scroll, text="Загрузка каталога...",
                                            font=ctk.CTkFont(size=15, weight="bold"),
                                            text_color=TEXT_SECONDARY)
        self._loading_label.grid(row=0, column=0, columnspan=6, pady=60)

        sep = ctk.CTkFrame(tab_scan, height=1, fg_color=BORDER)
        sep.grid(row=0, column=0, padx=10, pady=(8, 4), sticky="ew")

        ctk.CTkLabel(tab_scan, text="Фильтр редкости для мониторинга:",
                      font=ctk.CTkFont(size=12, weight="bold")).grid(row=1, column=0, padx=12, pady=(4, 4), sticky="w")

        rarity_frame = ctk.CTkFrame(tab_scan, fg_color="transparent")
        rarity_frame.grid(row=2, column=0, padx=12, pady=2, sticky="w")
        self._rarity_vars = {}
        for idx, (key, name) in enumerate(COLOUR_NAMES.items()):
            var = ctk.BooleanVar(value=True)
            self._rarity_vars[key] = var
            cb = ctk.CTkCheckBox(rarity_frame, text=name, variable=var,
                                  font=ctk.CTkFont(size=11),
                                  command=self._update_monitor_btn,
                                  fg_color=COLOUR_COLORS.get(key, "#888888"))
            cb.grid(row=0, column=idx, padx=6)

        sep2 = ctk.CTkFrame(tab_scan, height=1, fg_color=BORDER)
        sep2.grid(row=3, column=0, padx=10, pady=4, sticky="ew")

        ctrl_frame = ctk.CTkFrame(tab_scan, fg_color="transparent")
        ctrl_frame.grid(row=4, column=0, padx=12, pady=4, sticky="ew")
        ctrl_frame.grid_columnconfigure(10, weight=1)

        self._select_all_btn = ctk.CTkButton(ctrl_frame, text="Выбрать все", width=100,
                                              font=ctk.CTkFont(size=11), corner_radius=6,
                                              fg_color=BG_LIGHT, hover_color=BG_HOVER,
                                              text_color=TEXT_PRIMARY, border_width=1, border_color=BORDER)
        self._select_all_btn.grid(row=0, column=0, padx=(0, 4))

        self._deselect_all_btn = ctk.CTkButton(ctrl_frame, text="Сбросить все", width=100,
                                                font=ctk.CTkFont(size=11), corner_radius=6,
                                                fg_color=BG_LIGHT, hover_color=BG_HOVER,
                                                text_color=TEXT_PRIMARY, border_width=1, border_color=BORDER)
        self._deselect_all_btn.grid(row=0, column=1, padx=4)

        entry_kw = dict(width=50, font=ctk.CTkFont(size=11), justify="center",
                        corner_radius=6, fg_color=BG_MID, border_color=BORDER,
                        border_width=1, text_color=TEXT_PRIMARY)

        ctk.CTkLabel(ctrl_frame, text="Мин. +:", font=ctk.CTkFont(size=11)).grid(row=0, column=2, padx=(12, 2))
        self._min_ptn_var = ctk.StringVar(value="0")
        ctk.CTkEntry(ctrl_frame, textvariable=self._min_ptn_var, **entry_kw).grid(row=0, column=3, padx=2)

        ctk.CTkLabel(ctrl_frame, text="Выгода:", font=ctk.CTkFont(size=11)).grid(row=0, column=4, padx=(12, 2))
        self._min_profit_var = ctk.StringVar(value="20")
        ctk.CTkEntry(ctrl_frame, textvariable=self._min_profit_var, **entry_kw).grid(row=0, column=5, padx=2)
        ctk.CTkLabel(ctrl_frame, text="%", font=ctk.CTkFont(size=11)).grid(row=0, column=6, padx=(0, 4))

        ctk.CTkLabel(ctrl_frame, text="Период:", font=ctk.CTkFont(size=11)).grid(row=0, column=7, padx=(12, 2))
        self._days_var = ctk.StringVar(value="30")
        ctk.CTkEntry(ctrl_frame, textvariable=self._days_var, **entry_kw).grid(row=0, column=8, padx=2)
        ctk.CTkLabel(ctrl_frame, text="д", font=ctk.CTkFont(size=11)).grid(row=0, column=9, padx=(0, 4))

        self._monitor_btn = ctk.CTkButton(ctrl_frame, text="Запустить мониторинг", width=220,
                                           font=ctk.CTkFont(size=13, weight="bold"),
                                           corner_radius=8,
                                           fg_color=GREEN_BTN, hover_color=GREEN_BTN_HOVER,
                                           command=self._toggle_monitoring)
        self._monitor_btn.grid(row=0, column=11, padx=(4, 0), sticky="e")

        self._monitor_container = ctk.CTkFrame(tab_scan, fg_color="transparent")
        self._monitor_container.grid(row=5, column=0, sticky="nsew", padx=10, pady=(4, 0))
        self._monitor_container.grid_rowconfigure(0, weight=1)
        self._monitor_container.grid_columnconfigure(0, weight=1)

        tab_deals = tabview.add("Выгодные")
        tab_purchased = tabview.add("Куплено")
        tab_deals.grid_rowconfigure(0, weight=1)
        tab_deals.grid_columnconfigure(0, weight=1)
        tab_purchased.grid_rowconfigure(0, weight=1)
        tab_purchased.grid_columnconfigure(0, weight=1)

        self._deals_panel = ProfitableDealsTab(tab_deals, self.state, self)
        self._deals_panel.grid(row=0, column=0, sticky="nsew")
        self._purchased_panel = PurchasedTab(tab_purchased, self.state, self)
        self._purchased_panel.grid(row=0, column=0, sticky="nsew")

        status = ctk.CTkFrame(root, height=28, fg_color=BG_MID, corner_radius=4)
        status.grid(row=1, column=0, padx=6, pady=(0, 6), sticky="ew")
        status.grid_columnconfigure(0, weight=1)
        status.grid_propagate(False)
        self._status_label = ctk.CTkLabel(status, text="Загрузка...",
                                           font=ctk.CTkFont(size=11), text_color=TEXT_SECONDARY)
        self._status_label.grid(row=0, column=0, padx=8, pady=2, sticky="w")

    def _delayed_load(self):
        if self.state and self.state.all_items_list:
            self._build_cards()
        else:
            self._root.after(500, self._delayed_load)

    def _build_cards(self):
        self._loading_label.grid_forget()
        for w in self._scroll.winfo_children():
            w.destroy()
        self._cards.clear()

        items = self.state.all_items_list
        cols = 6
        for i, (item_id, name, colour, cat, subcat, icon) in enumerate(items):
            row = i // cols
            col = i % cols
            icon_path = self.state.icon_map.get(item_id, "")
            tracked = is_tracked(item_id)
            card = ArtifactCard(self._scroll, item_id, name, colour, icon_path, tracked,
                                on_toggle=self._on_card_toggle,
                                on_show_history=self._show_history)
            card.grid(row=row, column=col, padx=4, pady=4, sticky="nsew")
            self._cards[item_id] = card

        self._apply_filters()
        self._update_status()

    def _on_search(self, text: str):
        self._search_text = text.lower()
        self._apply_filters()

    def _on_search_debounce(self, text: str):
        if self._search_timer is not None:
            self._root.after_cancel(self._search_timer)
        self._search_timer = self._root.after(200, lambda: self._on_search(text))

    def _apply_filters(self):
        search = self._search_text
        for item_id, card in self._cards.items():
            match_search = search == "" or search in card.name.lower()
            if match_search:
                card.grid()
            else:
                card.grid_remove()

    def _select_all(self):
        for card in self._cards.values():
            if card.winfo_viewable():
                card._switch_var.set(True)
                card._on_toggle()
        self._update_monitor_btn()

    def _deselect_all(self):
        for card in self._cards.values():
            if card.winfo_viewable():
                card._switch_var.set(False)
                card._on_toggle()
        self._update_monitor_btn()

    def _update_monitor_btn(self):
        selected_rarities = {k for k, v in self._rarity_vars.items() if v.get()}
        tracked = sum(1 for c in self._cards.values() if c.tracked and c.colour in selected_rarities)
        if self._monitoring:
            self._monitor_btn.configure(text="Остановить мониторинг",
                                        fg_color=RED_BTN, hover_color=RED_BTN_HOVER)
        else:
            self._monitor_btn.configure(text=f"Запустить мониторинг ({tracked})",
                                        fg_color=GREEN_BTN, hover_color=GREEN_BTN_HOVER)

    def _update_status(self):
        total = len(self._cards)
        selected_rarities = {k for k, v in self._rarity_vars.items() if v.get()}
        tracked = sum(1 for c in self._cards.values() if c.tracked and c.colour in selected_rarities)
        ts = self.state.last_scan_time if self.state else ""
        parts = [f"{total} артефактов", f"{tracked} отслеживается"]
        if ts:
            parts.append(f"последний цикл: {ts}")
        self._status_label.configure(text=" | ".join(parts))

    def _toggle_monitoring(self):
        if self._monitoring:
            self._stop_monitoring()
        else:
            self._start_monitoring()

    def _start_monitoring(self):
        if not self.monitor:
            return
        selected_rarities = {k for k, v in self._rarity_vars.items() if v.get()}
        tracked_ids = [cid for cid, c in self._cards.items() if c.tracked]
        if not tracked_ids:
            return

        try:
            min_ptn = int(self._min_ptn_var.get())
            if min_ptn < 0:
                min_ptn = 0
        except ValueError:
            min_ptn = 0
            self._min_ptn_var.set("0")

        try:
            min_profit = float(self._min_profit_var.get())
            if min_profit < 0:
                min_profit = 0
        except ValueError:
            min_profit = 20.0
            self._min_profit_var.set("20")

        try:
            days = int(self._days_var.get())
            if days < 1:
                days = 14
        except ValueError:
            days = 14
            self._days_var.set("30")

        self._current_days = days
        self._min_ptn = min_ptn
        self._monitoring = True
        self._monitor_gen += 1
        self._update_monitor_btn()
        all_tracked = len(tracked_ids)
        rarity_count = sum(1 for c in self._cards.values()
                           if c.tracked and c.colour in selected_rarities)
        logger.info(f"Запуск мониторинга: {rarity_count}/{all_tracked} артефактов, "
                    f"выгода ≥{min_profit}%, мин. +{min_ptn}, период {days}д")
        flush_logs()

        if self._monitor_panel:
            self._monitor_panel.destroy()
        self._monitor_panel = MonitoringPanel(self._monitor_container, self.state, self, min_profit=min_profit)
        self._monitor_panel.grid(row=0, column=0, sticky="nsew")

        current_gen = self._monitor_gen

        def on_result(item_id, per_qlt, icon_path):
            item = self.state.get_item(item_id)
            if item and self._monitor_panel:
                name = item["name"]
                colour = item["colour"]
                self._root.after(0, lambda: self._monitor_panel.add_result(
                    item_id, name, colour, icon_path, per_qlt
                ))
            self._root.after(0, self._update_status)

            if item and per_qlt:
                now_str = datetime.now().strftime("%d.%m.%Y %H:%M")
                for key, v in per_qlt.items():
                    if v["discount_percent"] >= min_profit:
                        self.state.scan_history.append({
                            "item_id": item_id,
                            "name": item["name"],
                            "colour": item["colour"],
                            "icon_path": icon_path,
                            "qlt": v["qlt"],
                            "upgrade_bonus": v["upgrade_bonus"],
                            "min_buyout": v["min_buyout"],
                            "hist_avg": v["hist_avg"],
                            "discount_percent": v["discount_percent"],
                            "speculation": v.get("speculation", False),
                            "timestamp": now_str,
                        })
                if len(self.state.scan_history) > 500:
                    self.state.scan_history = self.state.scan_history[-500:]
                self._root.after(0, lambda: self._deals_panel.refresh() if self._deals_panel else None)

        async def run():
            try:
                await self.monitor.monitor_loop(on_result, min_ptn=min_ptn,
                                                 rarity_filter=selected_rarities, days=days)
            except Exception as e:
                logger.exception(f"Ошибка в мониторинге: {e}")
                flush_logs()

        def thread_target():
            import asyncio
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                loop.run_until_complete(run())
            except Exception as e:
                logger.exception(f"Ошибка в цикле: {e}")
                flush_logs()
            finally:
                loop.close()
            self._root.after(0, lambda: self._on_monitor_stopped(current_gen))

        self._monitor_thread = threading.Thread(target=thread_target, daemon=True)
        self._monitor_thread.start()

    def _stop_monitoring(self):
        if self.monitor:
            self.monitor.stop()
        self._on_monitor_stopped()

    def _on_monitor_stopped(self, gen=None):
        if gen is not None and gen != self._monitor_gen:
            return
        self._monitoring = False
        self._update_monitor_btn()
        if self._monitor_panel:
            self._monitor_panel.on_monitor_stopped()
        self._monitor_thread = None
        self._update_status()
        logger.info("Мониторинг остановлен")
        flush_logs()

    def _show_history(self, item_id: str, name: str, icon_path: str):
        if not self.monitor:
            logger.warning("Монитор не инициализирован, история недоступна")
            return
        try:
            HistoryWindow(self._root, self.monitor.api, item_id, name, icon_path, limit=200)
        except Exception as e:
            logger.exception(f"Ошибка открытия истории: {e}")

    def _on_card_toggle(self):
        self._update_monitor_btn()
        self._update_status()

    def _on_close(self):
        if self.monitor:
            self.monitor.stop()
        if self._monitor_panel:
            self._monitor_panel.destroy()
            self._monitor_panel = None
        if self._root:
            self._root.destroy()



SCROLLBAR_COLOR = "#1a3050"
CARD_TRACKED_BG = "#1a3050"
CARD_UNTRACKED_BG = "#0e1625"

class ArtifactCard(ctk.CTkFrame):
    def __init__(self, parent, item_id: str, name: str, colour: str,
                 icon_path: str, tracked: bool = False, on_toggle=None,
                 on_show_history=None):
        bg = CARD_TRACKED_BG if tracked else CARD_UNTRACKED_BG
        super().__init__(parent, corner_radius=10, fg_color=bg,
                         width=CARD_SIZE[0], height=CARD_SIZE[1],
                         border_width=1, border_color=BORDER,
                         cursor="hand2")
        self.item_id = item_id
        self.name = name
        self.colour = colour
        self.icon_path = icon_path
        self.tracked = tracked
        self._on_toggle_callback = on_toggle
        self._on_show_history = on_show_history
        self.grid_propagate(False)

        self.bind("<Button-1>", lambda e: self._on_toggle())
        self.bind("<Button-3>", lambda e: self._on_icon_click())

        icon_frame = ctk.CTkFrame(self, fg_color="transparent", width=THUMB_SIZE[0], height=THUMB_SIZE[1])
        icon_frame.pack(pady=(10, 4))
        icon_frame.pack_propagate(False)
        icon_frame.bind("<Button-1>", lambda e: self._on_toggle())

        self._icon_label = ctk.CTkLabel(icon_frame, text="", width=THUMB_SIZE[0], height=THUMB_SIZE[1],
                                         cursor="hand2")
        self._icon_label.pack()
        self._icon_label.bind("<Button-1>", lambda e: self._on_icon_click())
        self._set_icon()

        self._name_label = ctk.CTkLabel(self, text=name, font=ctk.CTkFont(size=10, weight="bold"),
                                         anchor="center", wraplength=130, text_color=TEXT_PRIMARY)
        self._name_label.pack(pady=(0, 2))
        self._name_label.bind("<Button-1>", lambda e: self._on_toggle())

        rarity_color = COLOUR_COLORS.get(colour, "#888888")
        rarity_name = COLOUR_NAMES.get(colour, colour)
        self._rarity_label = ctk.CTkLabel(self, text=rarity_name, font=ctk.CTkFont(size=8, weight="bold"),
                                           text_color=rarity_color)
        self._rarity_label.pack()
        self._rarity_label.bind("<Button-1>", lambda e: self._on_toggle())

    def _on_icon_click(self):
        if self._on_show_history:
            self._on_show_history(self.item_id, self.name, self.icon_path)

    def _set_icon(self):
        if self.icon_path:
            cached = _icon_cache.get(self.icon_path)
            if cached is not None:
                self._icon_label.configure(image=cached, text="")
                return
            try:
                pil = Image.open(self.icon_path).resize(THUMB_SIZE, Image.LANCZOS)
                img = ctk.CTkImage(pil, size=THUMB_SIZE)
                _icon_cache[self.icon_path] = img
                self._icon_label.configure(image=img, text="")
                return
            except Exception as e:
                logger.warning(f"Icon error {self.item_id}: {e}")
        self._icon_label.configure(text=self.name[:2], font=ctk.CTkFont(size=16))

    def _on_toggle(self):
        self.tracked = not self.tracked
        set_tracked(self.item_id, self.tracked)
        self.configure(fg_color=CARD_TRACKED_BG if self.tracked else CARD_UNTRACKED_BG)
        if self._on_toggle_callback:
            self._on_toggle_callback()


class MonitoringPanel(ctk.CTkFrame):
    def __init__(self, parent, state: SharedState, app_ui: AppUI, min_profit: float = 20.0):
        super().__init__(parent, fg_color="transparent")
        self.state = state
        self.app_ui = app_ui
        self._rows: dict[str, list[ctk.CTkFrame]] = {}
        self._results_data: dict[str, tuple] = {}
        self._cycle_count = 0
        self._min_profit = min_profit
        self._build_ui()

    def _build_ui(self):
        self.grid_rowconfigure(3, weight=1)
        self.grid_columnconfigure(0, weight=1)

        status_frame = ctk.CTkFrame(self, fg_color="transparent")
        status_frame.grid(row=0, column=0, padx=2, pady=(4, 2), sticky="ew")
        status_frame.grid_columnconfigure(1, weight=1)

        self._status_label = ctk.CTkLabel(status_frame, text="Мониторинг запущен...",
                                           font=ctk.CTkFont(size=12, weight="bold"),
                                           text_color=ACCENT)
        self._status_label.grid(row=0, column=0, padx=4, sticky="w")

        filter_frame = ctk.CTkFrame(self, fg_color="transparent")
        filter_frame.grid(row=1, column=0, padx=2, pady=(0, 4), sticky="ew")

        ctk.CTkLabel(filter_frame, text="Мин. выгода:", font=ctk.CTkFont(size=11)).grid(row=0, column=0, padx=(0, 2))
        self._profit_var = ctk.StringVar(value=str(int(self._min_profit)))
        ctk.CTkEntry(filter_frame, width=50, textvariable=self._profit_var,
                      font=ctk.CTkFont(size=11), justify="center", corner_radius=6,
                      fg_color=BG_MID, border_color=BORDER, text_color=TEXT_PRIMARY).grid(row=0, column=1, padx=2)
        ctk.CTkLabel(filter_frame, text="%", font=ctk.CTkFont(size=11)).grid(row=0, column=2, padx=(0, 10))

        self._apply_btn = ctk.CTkButton(filter_frame, text="Применить", width=80,
                                         font=ctk.CTkFont(size=10), corner_radius=6,
                                         fg_color=BG_LIGHT, hover_color=BG_HOVER,
                                         text_color=TEXT_PRIMARY, border_width=1, border_color=BORDER)
        self._apply_btn.grid(row=0, column=3, padx=(10, 0))

        header_frame = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=6, height=28)
        header_frame.grid(row=2, column=0, padx=2, pady=(0, 2), sticky="ew")
        header_frame.grid_columnconfigure(0, weight=0, minsize=44)
        header_frame.grid_columnconfigure(1, weight=1)
        header_frame.grid_columnconfigure(2, weight=0, minsize=80)
        header_frame.grid_columnconfigure(3, weight=0, minsize=80)
        header_frame.grid_columnconfigure(4, weight=0, minsize=100)
        header_frame.grid_columnconfigure(5, weight=0, minsize=100)
        header_frame.grid_columnconfigure(6, weight=0, minsize=80)
        header_frame.grid_columnconfigure(7, weight=0, minsize=70)

        headers = ["", "Артефакт", "Редкость", "Уровень", "Цена мин", "Сред.(нед)", "Скидка", ""]
        for i, h in enumerate(headers):
            lbl = ctk.CTkLabel(header_frame, text=h, font=ctk.CTkFont(size=10, weight="bold"),
                                text_color=TEXT_SECONDARY)
            lbl.grid(row=0, column=i, padx=4, pady=4, sticky="w")

        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=6,
                                                scrollbar_button_color=SCROLLBAR_COLOR,
                                                scrollbar_button_hover_color=BG_HOVER)
        self._scroll.grid(row=3, column=0, sticky="nsew", padx=2, pady=2)
        self._scroll.grid_columnconfigure(1, weight=1)

        self._empty_label = ctk.CTkLabel(self._scroll, text="Ожидание результатов...",
                                          font=ctk.CTkFont(size=12), text_color=TEXT_SECONDARY)
        self._empty_label.grid(row=0, column=0, columnspan=8, pady=30)

    def on_monitor_stopped(self):
        self._status_label.configure(text="Мониторинг остановлен")

    def _apply_filter(self):
        try:
            val = float(self._profit_var.get())
            if val < 0:
                val = 0
            self._min_profit = val
        except ValueError:
            self._profit_var.set(str(int(self._min_profit)))
            return
        self._rebuild_all()

    def _rebuild_all(self):
        for frames in self._rows.values():
            for w in frames:
                w.destroy()
        self._rows.clear()
        if not self._results_data:
            self._empty_label.grid()
            return
        self._empty_label.grid_forget()
        shown = 0
        for item_id, (name, colour, icon_path, entries) in self._results_data.items():
            frames = self._build_entries_frames(item_id, name, colour, icon_path, entries)
            if frames:
                self._rows[item_id] = frames
                shown += len(frames)
        status_text = f"Фильтр: \u2265{int(self._min_profit)}% | показано: {shown}"
        self._status_label.configure(text=status_text)

    def _build_entries_frames(self, item_id, name, colour, icon_path, entries):
        frames = []
        for v in entries:
            discount = v["discount_percent"]
            if discount < self._min_profit:
                continue
            row_f = ctk.CTkFrame(self._scroll, fg_color="transparent")
            row_f.grid_columnconfigure(0, weight=0, minsize=44)
            row_f.grid_columnconfigure(1, weight=1)
            row_f.grid_columnconfigure(2, weight=0, minsize=80)
            row_f.grid_columnconfigure(3, weight=0, minsize=80)
            row_f.grid_columnconfigure(4, weight=0, minsize=100)
            row_f.grid_columnconfigure(5, weight=0, minsize=100)
            row_f.grid_columnconfigure(6, weight=0, minsize=80)
            row_f.grid_columnconfigure(7, weight=0, minsize=70)

            icon_lbl = ctk.CTkLabel(row_f, text="", width=32, height=32, cursor="hand2")
            icon_lbl.grid(row=0, column=0, padx=2, pady=1)
            if icon_path:
                cached = _icon_cache.get(icon_path)
                if cached:
                    icon_lbl.configure(image=cached, text="")
                else:
                    try:
                        pil = Image.open(icon_path).resize((32, 32), Image.LANCZOS)
                        img = ctk.CTkImage(pil, size=(32, 32))
                        _icon_cache[icon_path] = img
                        icon_lbl.configure(image=img, text="")
                    except Exception:
                        icon_lbl.configure(text=name[:1], font=ctk.CTkFont(size=12))
            icon_lbl.bind("<Button-1>", lambda e, iid=item_id, n=name, ip=icon_path:
                          self._show_history(iid, n, ip))

            ctk.CTkLabel(row_f, text=name, font=ctk.CTkFont(size=10, weight="bold"),
                          anchor="w", text_color=TEXT_PRIMARY).grid(row=0, column=1, padx=4, sticky="w")

            qlt_color = QLT_COLORS.get(v["qlt"], "#888888")
            qlt_name = QLT_NAMES.get(v["qlt"], f"q{v['qlt']}")
            ctk.CTkLabel(row_f, text=qlt_name, font=ctk.CTkFont(size=10),
                          text_color=qlt_color).grid(row=0, column=2, padx=4, sticky="w")

            ub = v["upgrade_bonus"]
            ctk.CTkLabel(row_f, text=f"+{ub:.4g}" if ub else "+0",
                          font=ctk.CTkFont(size=10)).grid(row=0, column=3, padx=4, sticky="w")

            ctk.CTkLabel(row_f, text=f"{v['min_buyout']:,}",
                          font=ctk.CTkFont(size=10, weight="bold"),
                          text_color=ACCENT_GREEN).grid(row=0, column=4, padx=4, sticky="w")

            ctk.CTkLabel(row_f, text=f"{v['hist_avg']:,}",
                          font=ctk.CTkFont(size=10)).grid(row=0, column=5, padx=4, sticky="w")

            disc_text = f"{discount:+.1f}%"
            disc_color = ACCENT_GREEN if discount >= self._min_profit else TEXT_SECONDARY
            status_text = "\u2705" if discount >= self._min_profit else "\u274c"

            if v.get("speculation"):
                status_text = "\u26a0\ufe0f " + status_text

            ctk.CTkLabel(row_f, text=disc_text, font=ctk.CTkFont(size=10, weight="bold"),
                          text_color=disc_color).grid(row=0, column=6, padx=4, sticky="w")
            ctk.CTkLabel(row_f, text=status_text, font=ctk.CTkFont(size=12)).grid(row=0, column=7, padx=4)

            row_f.pack(fill="x", pady=1)
            frames.append(row_f)
        return frames

    def _show_history(self, item_id: str, name: str, icon_path: str):
        if not (self.app_ui and self.app_ui.monitor):
            return
        try:
            HistoryWindow(self.winfo_toplevel(), self.app_ui.monitor.api, item_id, name, icon_path,
                          limit=200)
        except Exception as e:
            logger.exception(f"Ошибка открытия истории: {e}")

    def add_result(self, item_id: str, name: str, colour: str, icon_path: str, per_qlt: dict):
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        self._empty_label.grid_forget()
        self._cycle_count += 1
        entries = sorted(per_qlt.values(), key=lambda v: (v["qlt"], v["upgrade_bonus"]))
        self._results_data[item_id] = (name, colour, icon_path, entries)
        self._debounce_rebuild()

    def _debounce_rebuild(self):
        if hasattr(self, "_rebuild_timer") and self._rebuild_timer is not None:
            self.after_cancel(self._rebuild_timer)
        self._rebuild_timer = self.after(1200, self._do_rebuild)

    def _do_rebuild(self):
        self._rebuild_timer = None
        for item_id in list(self._rows.keys()):
            if item_id not in self._results_data:
                for w in self._rows.pop(item_id):
                    w.destroy()
        for item_id, (name, colour, icon_path, entries) in self._results_data.items():
            if item_id in self._rows:
                for w in self._rows[item_id]:
                    w.destroy()
                del self._rows[item_id]
            frames = self._build_entries_frames(item_id, name, colour, icon_path, entries)
            if frames:
                self._rows[item_id] = frames
        shown = sum(len(f) for f in self._rows.values())
        status_text = f"Фильтр: \u2265{int(self._min_profit)}% | показано: {shown}"
        self._status_label.configure(text=status_text)


class ProfitableDealsTab(ctk.CTkFrame):
    def __init__(self, parent, state: SharedState, app_ui: "AppUI"):
        super().__init__(parent, fg_color="transparent")
        self.state = state
        self.app_ui = app_ui
        self._rows: list[ctk.CTkFrame] = []
        self._build_ui()

    def _build_ui(self):
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="История выгодных предложений",
                      font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, padx=10, pady=(8, 4), sticky="w")

        hdr = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=6, height=28)
        hdr.grid(row=1, column=0, padx=10, pady=(0, 2), sticky="ew")
        cols = [("", 44), ("Артефакт", 1), ("Редкость", 80), ("Ур.", 60),
                ("Цена", 100), ("Сред.", 100), ("Скидка", 80), ("Время", 140), ("", 50)]
        for i, (txt, w) in enumerate(cols):
            w = w if isinstance(w, int) else 0
            hdr.grid_columnconfigure(i, weight=w, minsize=w if w else 0)
            ctk.CTkLabel(hdr, text=txt, font=ctk.CTkFont(size=9, weight="bold"),
                          text_color=TEXT_SECONDARY).grid(row=0, column=i, padx=4, pady=3, sticky="w")

        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=6,
                                                scrollbar_button_color=SCROLLBAR_COLOR,
                                                scrollbar_button_hover_color=BG_HOVER)
        self._scroll.grid(row=2, column=0, sticky="nsew", padx=10, pady=2)
        self._scroll.grid_columnconfigure(1, weight=1)

        self._empty = ctk.CTkLabel(self._scroll, text="Нет данных. Запустите мониторинг.",
                                    font=ctk.CTkFont(size=12), text_color=TEXT_SECONDARY)
        self._empty.grid(row=0, column=0, columnspan=9, pady=30)

    def refresh(self):
        for w in self._rows:
            w.destroy()
        self._rows.clear()
        history = self.state.scan_history[-200:]
        if not history:
            self._empty.grid()
            return
        self._empty.grid_forget()
        for entry in history:
            row = self._build_row(entry)
            row.pack(fill="x", pady=1)
            self._rows.append(row)

    def _build_row(self, entry) -> ctk.CTkFrame:
        row = ctk.CTkFrame(self._scroll, fg_color="transparent")
        row.grid_columnconfigure(0, weight=0, minsize=44)
        row.grid_columnconfigure(1, weight=1)
        row.grid_columnconfigure(2, weight=0, minsize=80)
        row.grid_columnconfigure(3, weight=0, minsize=60)
        row.grid_columnconfigure(4, weight=0, minsize=100)
        row.grid_columnconfigure(5, weight=0, minsize=100)
        row.grid_columnconfigure(6, weight=0, minsize=80)
        row.grid_columnconfigure(7, weight=0, minsize=140)
        row.grid_columnconfigure(8, weight=0, minsize=50)

        icon_path = entry.get("icon_path", "")
        item_id = entry["item_id"]
        name = entry["name"]

        icon_lbl = ctk.CTkLabel(row, text="", width=32, height=32, cursor="hand2")
        icon_lbl.grid(row=0, column=0, padx=2, pady=1)
        if icon_path:
            cached = _icon_cache.get(icon_path)
            if cached:
                icon_lbl.configure(image=cached, text="")
            else:
                try:
                    pil = Image.open(icon_path).resize((32, 32), Image.LANCZOS)
                    img = ctk.CTkImage(pil, size=(32, 32))
                    _icon_cache[icon_path] = img
                    icon_lbl.configure(image=img, text="")
                except Exception:
                    icon_lbl.configure(text=name[:1], font=ctk.CTkFont(size=12))
        icon_lbl.bind("<Button-1>", lambda e, iid=item_id, n=name, ip=icon_path:
                       self.app_ui._show_history(iid, n, ip))

        ctk.CTkLabel(row, text=name, font=ctk.CTkFont(size=10, weight="bold"),
                      anchor="w", text_color=TEXT_PRIMARY).grid(row=0, column=1, padx=4, sticky="w")

        qlt_color = QLT_COLORS.get(entry["qlt"], "#888888")
        qlt_name = QLT_NAMES.get(entry["qlt"], f"q{entry['qlt']}")
        ctk.CTkLabel(row, text=qlt_name, font=ctk.CTkFont(size=10),
                      text_color=qlt_color).grid(row=0, column=2, padx=4, sticky="w")

        ub = entry["upgrade_bonus"]
        ctk.CTkLabel(row, text=f"+{ub:.4g}" if ub else "+0",
                      font=ctk.CTkFont(size=10)).grid(row=0, column=3, padx=4, sticky="w")

        ctk.CTkLabel(row, text=f"{entry['min_buyout']:,}",
                      font=ctk.CTkFont(size=10, weight="bold"),
                      text_color=ACCENT_GREEN).grid(row=0, column=4, padx=4, sticky="w")

        ctk.CTkLabel(row, text=f"{entry['hist_avg']:,}",
                      font=ctk.CTkFont(size=10)).grid(row=0, column=5, padx=4, sticky="w")

        dis = entry["discount_percent"]
        status = "\u26a0\ufe0f " if entry.get("speculation") else ""
        status += "\u2705" if dis >= 0 else "\u274c"
        ctk.CTkLabel(row, text=f"{dis:+.1f}%", font=ctk.CTkFont(size=10, weight="bold"),
                      text_color=ACCENT_GREEN if dis >= 0 else TEXT_SECONDARY).grid(row=0, column=6, padx=4, sticky="w")

        ts = entry.get("timestamp", "")
        ctk.CTkLabel(row, text=ts, font=ctk.CTkFont(size=9),
                      text_color=TEXT_SECONDARY).grid(row=0, column=7, padx=4, sticky="w")

        chk = ctk.CTkCheckBox(row, text="", width=24, corner_radius=12,
                                fg_color=ACCENT_GREEN, hover_color="#00cc33",
                                command=lambda e=entry: self._on_purchase(e))
        chk.grid(row=0, column=8, padx=4)
        return row

    def _on_purchase(self, entry: dict):
        for p in self.state.purchased:
            key = f"{entry['item_id']}_{entry['qlt']}_{entry['upgrade_bonus']}"
            if f"{p['item_id']}_{p['qlt']}_{p['upgrade_bonus']}" == key:
                return
        purchase = dict(entry)
        purchase["purchased_at"] = datetime.now().strftime("%d.%m.%Y %H:%M")
        self.state.purchased.append(purchase)
        save_purchased(
            item_id=purchase["item_id"],
            name=purchase["name"],
            qlt=purchase["qlt"],
            ub=purchase["upgrade_bonus"],
            min_buyout=purchase["min_buyout"],
            hist_avg=purchase["hist_avg"],
            discount=purchase["discount_percent"],
            speculation=purchase.get("speculation", False),
            icon_path=purchase.get("icon_path", ""),
            timestamp=purchase.get("timestamp", ""),
            purchased_at=purchase["purchased_at"],
        )
        if self.app_ui._purchased_panel:
            self.app_ui._purchased_panel.refresh()


class PurchasedTab(ctk.CTkFrame):
    def __init__(self, parent, state: SharedState, app_ui: "AppUI"):
        super().__init__(parent, fg_color="transparent")
        self.state = state
        self.app_ui = app_ui
        self._rows: list[ctk.CTkFrame] = []
        self._build_ui()
        self.refresh()

    def _build_ui(self):
        self.grid_rowconfigure(2, weight=1)
        self.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(self, text="Купленные артефакты",
                      font=ctk.CTkFont(size=13, weight="bold")).grid(row=0, column=0, padx=10, pady=(8, 4), sticky="w")

        hdr = ctk.CTkFrame(self, fg_color=BG_HEADER, corner_radius=6, height=28)
        hdr.grid(row=1, column=0, padx=10, pady=(0, 2), sticky="ew")
        cols = [("", 44), ("Артефакт", 1), ("Редкость", 80), ("Ур.", 60),
                ("Цена покупки", 100), ("Сред. цена", 100), ("Скидка", 80), ("Куплено", 140)]
        for i, (txt, w) in enumerate(cols):
            w = w if isinstance(w, int) else 0
            hdr.grid_columnconfigure(i, weight=w, minsize=w if w else 0)
            ctk.CTkLabel(hdr, text=txt, font=ctk.CTkFont(size=9, weight="bold"),
                          text_color=TEXT_SECONDARY).grid(row=0, column=i, padx=4, pady=3, sticky="w")

        self._scroll = ctk.CTkScrollableFrame(self, fg_color="transparent", corner_radius=6,
                                                scrollbar_button_color=SCROLLBAR_COLOR,
                                                scrollbar_button_hover_color=BG_HOVER)
        self._scroll.grid(row=2, column=0, sticky="nsew", padx=10, pady=2)
        self._scroll.grid_columnconfigure(1, weight=1)

        self._empty = ctk.CTkLabel(self._scroll, text="Нет купленных артефактов.",
                                    font=ctk.CTkFont(size=12), text_color=TEXT_SECONDARY)
        self._empty.grid(row=0, column=0, columnspan=8, pady=30)

    def refresh(self):
        for w in self._rows:
            w.destroy()
        self._rows.clear()
        if not self.state.purchased:
            self._empty.grid()
            return
        self._empty.grid_forget()
        for entry in self.state.purchased:
            row = self._build_row(entry)
            row.pack(fill="x", pady=1)
            self._rows.append(row)

    def _build_row(self, entry) -> ctk.CTkFrame:
        row = ctk.CTkFrame(self._scroll, fg_color="transparent")
        row.grid_columnconfigure(0, weight=0, minsize=44)
        row.grid_columnconfigure(1, weight=1)
        row.grid_columnconfigure(2, weight=0, minsize=80)
        row.grid_columnconfigure(3, weight=0, minsize=60)
        row.grid_columnconfigure(4, weight=0, minsize=100)
        row.grid_columnconfigure(5, weight=0, minsize=100)
        row.grid_columnconfigure(6, weight=0, minsize=80)
        row.grid_columnconfigure(7, weight=0, minsize=140)

        icon_path = entry.get("icon_path", "")
        name = entry["name"]

        icon_lbl = ctk.CTkLabel(row, text="", width=32, height=32)
        icon_lbl.grid(row=0, column=0, padx=2, pady=1)
        if icon_path:
            cached = _icon_cache.get(icon_path)
            if cached:
                icon_lbl.configure(image=cached, text="")
            else:
                try:
                    pil = Image.open(icon_path).resize((32, 32), Image.LANCZOS)
                    img = ctk.CTkImage(pil, size=(32, 32))
                    _icon_cache[icon_path] = img
                    icon_lbl.configure(image=img, text="")
                except Exception:
                    icon_lbl.configure(text=name[:1], font=ctk.CTkFont(size=12))

        ctk.CTkLabel(row, text=name, font=ctk.CTkFont(size=10, weight="bold"),
                      anchor="w", text_color=TEXT_PRIMARY).grid(row=0, column=1, padx=4, sticky="w")

        qlt_color = QLT_COLORS.get(entry["qlt"], "#888888")
        qlt_name = QLT_NAMES.get(entry["qlt"], f"q{entry['qlt']}")
        ctk.CTkLabel(row, text=qlt_name, font=ctk.CTkFont(size=10),
                      text_color=qlt_color).grid(row=0, column=2, padx=4, sticky="w")

        ub = entry["upgrade_bonus"]
        ctk.CTkLabel(row, text=f"+{ub:.4g}" if ub else "+0",
                      font=ctk.CTkFont(size=10)).grid(row=0, column=3, padx=4, sticky="w")

        ctk.CTkLabel(row, text=f"{entry['min_buyout']:,}",
                      font=ctk.CTkFont(size=10, weight="bold"),
                      text_color=ACCENT_GREEN).grid(row=0, column=4, padx=4, sticky="w")

        ctk.CTkLabel(row, text=f"{entry['hist_avg']:,}",
                      font=ctk.CTkFont(size=10)).grid(row=0, column=5, padx=4, sticky="w")

        dis = entry["discount_percent"]
        ctk.CTkLabel(row, text=f"{dis:+.1f}%", font=ctk.CTkFont(size=10, weight="bold"),
                      text_color=ACCENT_GREEN if dis >= 0 else TEXT_SECONDARY).grid(row=0, column=6, padx=4, sticky="w")

        ctk.CTkLabel(row, text=entry.get("purchased_at", ""),
                      font=ctk.CTkFont(size=9), text_color=TEXT_SECONDARY).grid(row=0, column=7, padx=4, sticky="w")
        return row
