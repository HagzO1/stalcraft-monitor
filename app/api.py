import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
import logging
import os
from statistics import mean
import aiofiles
import aiohttp

logger = logging.getLogger(__name__)

_icon_cache_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "icons")
ICON_CACHE_DIR = _icon_cache_dir
ICON_BASE_URL = "https://raw.githubusercontent.com/EXBO-Studio/stalcraft-database/main/ru"

EAPI_BASE = "https://eapi.stalcraft.net"


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


class AuctionLot:
    def __init__(self, price: int, time: datetime, additional: dict | None = None, total: int = 1):
        self.price = price
        self.time = time
        self.additional = additional or {}
        self.total = total

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            price=d.get("price", 0),
            time=datetime.fromisoformat(d["time"]) if "time" in d and d["time"] else datetime.now(timezone.utc),
            additional=d.get("additional"),
            total=d.get("total", 1),
        )

    def __repr__(self):
        return f"AuctionLot(price={self.price}, time={self.time})"


class AuctionPrice:
    def __init__(self, price: int, time: datetime, additional: dict | None = None):
        self.price = price
        self.time = time
        self.additional = additional or {}

    @classmethod
    def from_dict(cls, d: dict):
        return cls(
            price=d.get("price", 0),
            time=datetime.fromisoformat(d["time"]) if "time" in d and d["time"] else datetime.now(timezone.utc),
            additional=d.get("additional"),
        )

    def __repr__(self):
        return f"AuctionPrice(price={self.price}, time={self.time})"


class StalcraftAPI:
    def __init__(self, config):
        self.config = config
        self._session: aiohttp.ClientSession | None = None
        self._token: str | None = None
        self._token_expires: datetime | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            connector = aiohttp.TCPConnector(ssl=False)
            self._session = aiohttp.ClientSession(base_url=EAPI_BASE, connector=connector)
        return self._session

    async def _get_token(self) -> str:
        if self._token and self._token_expires and datetime.now(timezone.utc) < self._token_expires:
            return self._token
        session = await self._get_session()
        async with session.post(
            "/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            },
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            self._token = data["access_token"]
            expires_in = data.get("expires_in", 3600)
            self._token_expires = datetime.now(timezone.utc) + timedelta(seconds=expires_in - 60)
            logger.debug("OAuth токен получен")
            return self._token

    async def _request(self, method: str, path: str, **kwargs) -> dict | list:
        token = await self._get_token()
        session = await self._get_session()
        headers = {"Authorization": f"Bearer {token}"}
        async with session.request(method, path, headers=headers, **kwargs) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def init(self):
        await self._get_session()
        logger.info("API инициализирован")

    async def _fetch_listing(self) -> dict:
        url = f"https://raw.githubusercontent.com/EXBO-Studio/stalcraft-database/main/{self.config.region}/listing.json"
        session = await self._get_session()
        async with session.get(url) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def get_all_items(self) -> list[tuple[str, str, str, str, str, str]]:
        entities = await self._fetch_listing()
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
        data = await self._request(
            "GET",
            f"/auction/{self.config.region}/lots/{item_id}",
            params={"limit": limit, "sort": "buyout_price", "order": "asc", "additional": "true"},
        )
        lots = data if isinstance(data, list) else data.get("lots", [])
        return [AuctionLot.from_dict(l) for l in lots]

    async def get_price_history(self, item_id: str, limit: int = 200) -> list[AuctionPrice]:
        data = await self._request(
            "GET",
            f"/auction/{self.config.region}/history/{item_id}",
            params={"limit": limit, "order": "asc", "additional": "true"},
        )
        prices = data if isinstance(data, list) else data.get("prices", [])
        return [AuctionPrice.from_dict(p) for p in prices]

    async def get_price_history_week(self, item_id: str, days: int = 14, limit: int = 200) -> list[AuctionPrice]:
        return await self.get_price_history(item_id, limit=limit)

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
        self._token = None
        self._token_expires = None
        await self._get_session()
        logger.debug("API клиент пересоздан в новом event loop")

    async def reset_http_session(self):
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
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
            ses = session or aiohttp.ClientSession(connector=aiohttp.TCPConnector(ssl=False))
            async with ses.get(url) as resp:
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
        async with aiohttp.ClientSession(connector=aiohttp.TCPConnector(limit=3, limit_per_host=2, ssl=False)) as session:
            results = []
            for i, (item_id, _name, _c, _cat, _subcat, icon) in enumerate(items):
                if icon:
                    path = await self.download_icon(icon, session)
                else:
                    path = None
                results.append(path)
                if i % 10 == 9:
                    await asyncio.sleep(0.3)
        icon_map = {}
        for (item_id, _name, _c, _cat, _subcat, icon), local_path in zip(items, results):
            if isinstance(local_path, str) and local_path:
                icon_map[item_id] = local_path
        logger.info(f"Загружено {len(icon_map)} иконок")
        return icon_map
