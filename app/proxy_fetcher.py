import asyncio
import logging

import aiohttp

logger = logging.getLogger(__name__)

PROXY_SOURCES = [
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://raw.githubusercontent.com/TheSpeedX/SOCKS-List/master/http.txt",
    "https://raw.githubusercontent.com/ShiftyTR/Proxy-List/master/http.txt",
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=5000&country=all",
]

TELEGRAM_MIRRORS = [
    "https://api.telegram.org",
    "https://api.telegram.one",
    "https://api.telegram.bot",
    "https://api.tg.org",
    "https://botapi.telegram.one",
]


async def try_mirror(mirror: str, token: str, timeout: float = 5.0) -> str | None:
    url = f"{mirror}/bot{token}/getMe"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status == 200:
                    return mirror
    except Exception:
        pass
    return None


async def try_proxy(proxy: str, token: str, timeout: float = 5.0) -> bool:
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, proxy=proxy, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                return r.status == 200
    except Exception:
        return False


async def fetch_proxies(source: str, timeout: float = 10.0) -> list[str]:
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(source, timeout=aiohttp.ClientTimeout(total=timeout)) as r:
                if r.status != 200:
                    return []
                text = await r.text()
                proxies = []
                for line in text.strip().splitlines():
                    line = line.strip()
                    if line and ":" in line and not line.startswith("#"):
                        if not line.startswith("http"):
                            line = f"http://{line}"
                        proxies.append(line)
                return proxies
    except Exception as e:
        logger.debug(f"Proxy source failed: {source}: {e}")
        return []


async def find_working_proxy(token: str, timeout_per: float = 5.0) -> str | None:
    mirrors = await asyncio.gather(*[try_mirror(m, token, timeout_per) for m in TELEGRAM_MIRRORS])
    for m in mirrors:
        if m:
            logger.info(f"Найден рабочий mirror Telegram: {m}")
            return m

    logger.info("Mirrors не работают, пробую бесплатные прокси...")
    sources_results = await asyncio.gather(*[fetch_proxies(s) for s in PROXY_SOURCES])
    all_proxies = list(set(p for proxies in sources_results for p in proxies))
    logger.info(f"Загружено прокси: {len(all_proxies)}")

    batch_size = 20
    tested = 0
    for i in range(0, len(all_proxies), batch_size):
        batch = all_proxies[i:i + batch_size]
        results = await asyncio.gather(*[try_proxy(p, token, timeout_per) for p in batch])
        for proxy, ok in zip(batch, results):
            tested += 1
            if ok:
                logger.info(f"Найден рабочий прокси ({tested}/{len(all_proxies)}): {proxy}")
                return proxy
        if tested % 100 == 0:
            logger.info(f"Проверено прокси: {tested}/{len(all_proxies)}")

    logger.warning("Не найдено ни одного рабочего прокси")
    return None
