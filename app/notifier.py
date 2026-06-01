import logging

import aiohttp

from app.proxy_fetcher import find_working_proxy

logger = logging.getLogger(__name__)

_cached_proxy: str | None = None


async def send_telegram(text: str, token: str, chat_id: str,
                        api_url: str = "https://api.telegram.org",
                        proxy: str = "") -> bool:
    global _cached_proxy

    if not token or not chat_id:
        logger.warning("Telegram token/chat_id not configured")
        return False

    async def _try(url: str, p: str = "") -> bool:
        kwargs = {}
        if p:
            kwargs["proxy"] = p
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(url, json={
                    "chat_id": chat_id,
                    "text": text,
                    "parse_mode": "HTML",
                }, timeout=aiohttp.ClientTimeout(total=15), **kwargs) as resp:
                    return resp.status == 200
        except Exception:
            return False

    send_url = f"{api_url}/bot{token}/sendMessage"

    if proxy:
        ok = await _try(send_url, proxy)
        if ok:
            return True
        logger.warning(f"Указанный прокси не работает: {proxy}")

    ok = await _try(send_url)
    if ok:
        return True

    if _cached_proxy:
        ok = await _try(send_url, _cached_proxy)
        if ok:
            return True
        _cached_proxy = None

    logger.info("Прямое соединение не работает, ищу прокси...")
    found = await find_working_proxy(token)
    if found:
        _cached_proxy = found
        is_mirror = found.startswith("http") and "telegram" in found
        if is_mirror:
            send_url = f"{found}/bot{token}/sendMessage"
            return await _try(send_url)
        else:
            return await _try(send_url, found)

    logger.error("Не удалось найти рабочий прокси или mirror для Telegram")
    return False


def format_alert(item_name: str, qlt_name: str, ub: int, min_price: int,
                 hist_avg: int, discount: float, total_lots: int,
                 speculation: bool) -> str:
    flag = " \u26a0\ufe0f" if speculation else ""
    return (
        f"\U0001f514 <b>Выгодный артефакт!</b>{flag}\n"
        f"\U0001f4a0 {item_name}\n"
        f"\U0001f7e5 {qlt_name}\n"
        f"\u2b06 +{ub}\n"
        f"\U0001f4b5 Цена: {min_price:,}\n"
        f"\U0001f4ca Средняя: {hist_avg:,}\n"
        f"\U0001f4c9 Скидка: {discount:+.1f}%\n"
        f"\U0001f4e6 Лотов: {total_lots}"
    )
