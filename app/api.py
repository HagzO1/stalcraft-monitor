import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging
import os
from statistics import mean
import aiofiles
import aiohttp

from scapi import AppClient, DatabaseLookup
from scapi.enums import SortAuction, Order
from scapi.client import AuctionLot, AuctionPrice

logger = logging.getLogger(__name__)

_icon_cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "icons")
ICON_CACHE_DIR = _icon_cache_dir
ICON_BASE_URL = "https://raw.githubusercontent.com/EXBO-Studio/stalcraft-database/main/ru"


def set_icon_cache_dir(path: str):
    global ICON_CACHE_DIR
    ICON_CACHE_DIR = path

QLT_NAMES = {
    0: "Обычный",
    1: "Необычный",
    2: "Особый",
    3: "Редкий",
    4: "Исключительный",
    5: "Легендарный",
    6: "Легендарный",
}


class StalcraftAPI:
    def __init__(self, config):
        self.config = config
        self.client: AppClient | None = None
        self.db: DatabaseLookup | None = None

    async def init(self):
        self.client = AppClient(
            region=self.config.region,
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
        )
        self.db = DatabaseLookup(realm=self.config.region)
        logger.info("API инициализирован")

    async def get_all_items(self) -> list[tuple[str, str, str, str, str, str]]:
        entities = await self.db.get_all("listing.json")
        result = []
        for item_id, data in entities.items():
            path = data.get("data", "")
            if not path.startswith("/items/artefact/"):
                continue
            icon = data.get("icon", "")
            colour = data.get("color", "") or "DEFAULT"
            subcat = path.replace("/items/artefact/", "").split("/")[0] if path else ""
            name = data.get("name", {}).get("lines", {}).get("ru", item_id)
            category = "artefact"
            result.append((item_id, name, colour, category, subcat, icon))
        result.sort(key=lambda x: x[1])
        return result

    async def get_auction_lots(self, item_id: str, limit: int = 50) -> list[AuctionLot]:
        endpoint = self.client.auction(item_id=item_id, region=self.config.region)
        lots = await endpoint.lots(
            limit=limit,
            sort=SortAuction.BUYOUT_PRICE,
            order=Order.ASCENDING,
            additional=True,
        )
        return list(lots)

    async def get_price_history(self, item_id: str, limit: int = 200) -> list[AuctionPrice]:
        endpoint = self.client.auction(item_id=item_id, region=self.config.region)
        history = await endpoint.price_history(limit=limit, additional=True)
        return list(history)

    async def get_price_history_week(self, item_id: str, days: int = 14, limit: int = 200) -> list[AuctionPrice]:
        return list(await self.get_price_history(item_id, limit=limit))

    async def get_price_history_week_grouped(self, item_id: str, days: int = 14) -> dict:
        prices = await self.get_price_history_week(item_id, days=days)
        groups = defaultdict(list)
        for p in prices:
            add = p.additional or {}
            qlt = add.get("qlt", 0)
            ub = add.get("ptn", 0) or 0
            groups[(qlt, ub)].append(p.price)
        result = {}
        for (qlt, ub), prices_list in groups.items():
            result[f"{qlt}_{ub}"] = {
                "qlt": qlt,
                "upgrade_bonus": ub,
                "min": min(prices_list),
                "max": max(prices_list),
                "avg": round(mean(prices_list)),
                "count": len(prices_list),
            }
        return result

    async def reinit(self):
        self.client = AppClient(
            region=self.config.region,
            client_id=self.config.client_id,
            client_secret=self.config.client_secret,
        )
        self.db = DatabaseLookup(realm=self.config.region)
        logger.debug("API клиент пересоздан в новом event loop")

    async def reset_http_session(self):
        if self.client and self.client._http._session:
            await self.client._http._session.close()
            self.client._http._session = None
            logger.debug("HTTP сессия сброшена")

    async def download_icon(self, icon_path: str, session: aiohttp.ClientSession | None = None) -> str | None:
        if not icon_path:
            return None
        os.makedirs(ICON_CACHE_DIR, exist_ok=True)
        fname = icon_path.replace("/icons/", "").replace("/", "_")
        local_path = os.path.join(ICON_CACHE_DIR, fname)
        if os.path.exists(local_path):
            return local_path

        url = f"{ICON_BASE_URL}{icon_path}"
        try:
            async with (session or aiohttp.ClientSession()).get(url) as resp:
                if resp.status != 200:
                    logger.warning(f"Не удалось загрузить иконку: {url} -> {resp.status}")
                    return None
                data = await resp.read()
            async with aiofiles.open(local_path, "wb") as f:
                await f.write(data)
            logger.debug(f"Иконка сохранена: {local_path}")
            return local_path
        except Exception as e:
            logger.error(f"Ошибка загрузки иконки {url}: {e}")
            return None

    async def download_all_icons(self, items: list[tuple]) -> dict[str, str]:
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=10, limit_per_host=5)) as session:
            tasks = []
            for item_id, _name, _c, _cat, _subcat, icon in items:
                if icon:
                    tasks.append(self.download_icon(icon, session))
            results = await asyncio.gather(*tasks, return_exceptions=True)
        icon_map = {}
        for (item_id, _name, _c, _cat, _subcat, icon), local_path in zip(items, results):
            if isinstance(local_path, str) and local_path:
                icon_map[item_id] = local_path
        logger.info(f"Загружено {len(icon_map)} иконок")
        return icon_map
