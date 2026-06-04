import asyncio
import logging
from collections import defaultdict
from datetime import datetime
from statistics import mean

from config import Config
from app.api import StalcraftAPI, QLT_NAMES
from app.database import save_item, set_tracked, log_scans_batch, is_tracked, get_tracked_ids, get_historical_avg, load_all_purchased
from app.notifier import send_telegram, format_alert

logger = logging.getLogger(__name__)


def flush_logs():
    for h in logging.getLogger().handlers:
        try:
            h.flush()
        except Exception:
            pass


class SharedState:
    def __init__(self):
        self.items: dict[str, dict] = {}
        self.all_items_list: list[tuple] = []
        self.icon_map: dict[str, str] = {}
        self.last_scan_time: str = ""
        self.scan_history: list[dict] = []
        self.purchased: list[dict] = load_all_purchased()
        self._rarity_filters: dict[str, bool] = {
            "DEFAULT": True, "RANK_NEWBIE": True, "RANK_STALKER": True,
            "RANK_VETERAN": True, "RANK_MASTER": True, "RANK_LEGEND": True,
        }

    def load_items(self, items: list[tuple]):
        self.all_items_list = items
        for item_id, name, colour, cat, subcat, icon in items:
            save_item(item_id, name, subcat, colour)
            set_tracked(item_id, True)
            if item_id not in self.items:
                self.items[item_id] = {
                    "id": item_id,
                    "name": name,
                    "subcategory": subcat,
                    "colour": colour,
                    "icon": icon,
                    "per_qlt": {},
                    "timestamp": "",
                }

    def update_item(self, item_id: str, per_qlt: dict, timestamp: str):
        if item_id in self.items:
            self.items[item_id]["per_qlt"] = per_qlt
            self.items[item_id]["timestamp"] = timestamp

    def get_item(self, item_id: str) -> dict | None:
        return self.items.get(item_id)

    def get_items_list(self) -> list[dict]:
        return list(self.items.values())

    def set_icon_map(self, icon_map: dict[str, str]):
        self.icon_map = icon_map


class PriceMonitor:
    def __init__(self, api: StalcraftAPI, config: Config, state: SharedState):
        self.api = api
        self.config = config
        self.state = state
        self._running = False
        self._all_items: list[tuple] = []
        self._notified: set[str] = set()

    async def load_catalog(self):
        all_items = await self.api.get_all_items()
        logger.info(f"Загружено {len(all_items)} артефактов")
        self._all_items = all_items
        self.state.load_items(all_items)

        icon_map = await self.api.download_all_icons(all_items)
        self.state.set_icon_map(icon_map)
        logger.info(f"Иконки загружены: {len(icon_map)}")
        return all_items

    async def scan_single(self, item_id: str, min_ptn: int = 0, weekly_avg: dict | None = None) -> tuple[dict | None, list[tuple]]:
        try:
            lots = await self.api.get_auction_lots(item_id, limit=50)
        except Exception as e:
            logger.error(f"Ошибка сканирования {item_id}: {e}")
            return None, []

        groups = defaultdict(list)
        for lot in lots:
            add = getattr(lot, "additional", None) or {}
            qlt = add.get("qlt", 0)
            ub = add.get("ptn", 0) or 0
            if ub < min_ptn:
                continue
            bp = lot.buyout_price
            if bp and bp > 0:
                groups[(qlt, ub)].append(bp)

        now = datetime.now().strftime("%H:%M:%S")
        per_qlt = {}
        db_rows: list[tuple] = []
        for (qlt, ub), buyouts in groups.items():
            min_p = min(buyouts)
            max_p = max(buyouts)
            avg_p = round(mean(buyouts))
            total = len(buyouts)
            db_rows.append((item_id, qlt, ub, min_p, avg_p, total))
            key = f"{qlt}_{ub}"

            if weekly_avg:
                wk = weekly_avg.get(key)
                if wk and wk.get("avg", 0) > 0:
                    hist_avg = wk["avg"]
                    discount = round((hist_avg - min_p) / hist_avg * 100, 1)
                else:
                    hist_avg = avg_p
                    discount = 0.0
            else:
                hist_avg = get_historical_avg(item_id, qlt, ub)
                if hist_avg and hist_avg > 0:
                    discount = round((hist_avg - min_p) / hist_avg * 100, 1)
                else:
                    discount = 0.0

            speculation = False
            if hist_avg and hist_avg > 0:
                if min_p > hist_avg * 1.3 and total <= 3:
                    speculation = True
                elif min_p > hist_avg * 1.5:
                    speculation = True

            per_qlt[key] = {
                "qlt": qlt,
                "upgrade_bonus": ub,
                "min_buyout": min_p,
                "max_buyout": max_p,
                "avg_buyout": avg_p,
                "total_lots": total,
                "qlt_name": QLT_NAMES.get(qlt, f"qlt_{qlt}"),
                "discount_percent": discount,
                "hist_avg": hist_avg or avg_p,
                "speculation": speculation,
            }

        return per_qlt, db_rows

    async def monitor_loop(self, on_result, min_ptn: int = 0, days: int = 14, clear_results=None):
        self._running = True
        await self.api.reinit()
        logger.info("Мониторинг запущен")
        flush_logs()
        self._current_days = days
        while self._running:
            try:
                if clear_results:
                    clear_results()
                all_tracked = get_tracked_ids()
                if not all_tracked:
                    await asyncio.sleep(2)
                    continue

                to_scan = []
                for item_id in all_tracked:
                    if not is_tracked(item_id):
                        continue
                    to_scan.append(item_id)

                if not to_scan:
                    await asyncio.sleep(2)
                    continue

                weekly = {}
                weekly_tasks = [
                    self.api.get_price_history_week_grouped(item_id, days=days)
                    for item_id in to_scan
                ]
                weekly_results = await asyncio.gather(*weekly_tasks, return_exceptions=True)
                for item_id, wr in zip(to_scan, weekly_results):
                    if isinstance(wr, dict):
                        weekly[item_id] = wr

                scan_tasks = []
                scan_ids = []
                for item_id in to_scan:
                    if not (self._running and is_tracked(item_id)):
                        continue
                    scan_tasks.append(self.scan_single(item_id, min_ptn=min_ptn, weekly_avg=weekly.get(item_id, {})))
                    scan_ids.append(item_id)

                if scan_tasks:
                    scan_results = await asyncio.gather(*scan_tasks, return_exceptions=True)
                    for item_id, result in zip(scan_ids, scan_results):
                        if not self._running:
                            break
                        if isinstance(result, Exception):
                            logger.error(f"Ошибка сканирования {item_id}: {result}")
                            continue
                        per_qlt, db_rows = result
                        if per_qlt:
                            if db_rows:
                                log_scans_batch(db_rows)
                            now_ts = datetime.now().strftime("%H:%M:%S")
                            self.state.update_item(item_id, per_qlt, now_ts)
                            if on_result:
                                try:
                                    on_result(item_id, per_qlt, self.state.icon_map.get(item_id, ""))
                                except Exception as e:
                                    logger.exception(f"on_result error: {e}")
                                    flush_logs()
                self.state.last_scan_time = datetime.now().strftime("%H:%M:%S")
                logger.info(f"Цикл: {len(all_tracked)} отсл, {len(to_scan)} к скану, {len(scan_ids)} проскан")
                await self._notify_new(to_scan)
                flush_logs()
                await asyncio.sleep(60)
            except Exception as e:
                logger.exception(f"Ошибка в цикле: {e}")
                flush_logs()
                await asyncio.sleep(5)
        logger.info("Мониторинг остановлен")
        flush_logs()

    async def _notify_new(self, tracked_ids: list[str]):
        token = self.config.telegram_token
        chat_id = self.config.telegram_chat_id
        api_url = self.config.telegram_api_url
        proxy = self.config.telegram_proxy if self.config.telegram_use_proxy else ""
        min_profit = self.config.min_profit_percent
        sent = 0
        for item_id in tracked_ids:
            item = self.state.get_item(item_id)
            if not item:
                continue
            per_qlt = item.get("per_qlt", {})
            for key, v in per_qlt.items():
                notify_key = f"{item_id}_{key}"
                if notify_key in self._notified:
                    continue
                discount = v["discount_percent"]
                if discount >= min_profit:
                    self._notified.add(notify_key)
                    text = format_alert(
                        item_name=item["name"],
                        qlt_name=v["qlt_name"],
                        ub=v["upgrade_bonus"],
                        min_price=v["min_buyout"],
                        hist_avg=v["hist_avg"],
                        discount=discount,
                        total_lots=v["total_lots"],
                        speculation=v.get("speculation", False),
                    )
                    ok = await send_telegram(text, token, chat_id, api_url, proxy)
                    if ok:
                        sent += 1
                        logger.info(f"Уведомление отправлено: {item['name']} +{v['upgrade_bonus']} ({discount:+.1f}%)")
                    else:
                        logger.warning(f"Не удалось отправить уведомление: {item['name']}")
                else:
                    logger.debug(f"Пропуск уведомления {item['name']} +{v['upgrade_bonus']}: скидка {discount:+.1f}% < {min_profit}%")
        if sent:
            logger.info(f"Отправлено уведомлений: {sent}")
            flush_logs()

    def start(self):
        self._running = True

    def stop(self):
        self._running = False
