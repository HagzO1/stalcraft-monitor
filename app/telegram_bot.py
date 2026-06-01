import asyncio
import logging

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command

from config import Config
from app.database import get_unnotified_deals, mark_deals_notified

logger = logging.getLogger(__name__)

RARITY_EMOJI = {
    "DEFAULT": "⚪",
    "RANK_NEWBIE": "🟢",
    "RANK_STALKER": "🔵",
    "RANK_VETERAN": "🟣",
    "RANK_MASTER": "🟠",
    "RANK_LEGEND": "🔴",
}

RARITY_NAME = {
    "DEFAULT": "Обычный",
    "RANK_NEWBIE": "Новичок",
    "RANK_STALKER": "Сталкер",
    "RANK_VETERAN": "Ветеран",
    "RANK_MASTER": "Мастер",
    "RANK_LEGEND": "Легенда",
}


class TelegramNotifier:
    def __init__(self, config: Config):
        self.config = config
        self.bot: Bot | None = None
        self.dp: Dispatcher | None = None
        self._ready = asyncio.Event()

    async def start(self):
        if not self.config.telegram_token:
            logger.warning("Telegram токен не указан, бот не запущен")
            return

        self.bot = Bot(token=self.config.telegram_token)
        self.dp = Dispatcher()

        @self.dp.message(Command("start"))
        async def cmd_start(message: types.Message):
            chat_id = str(message.chat.id)
            self.config.telegram_chat_id = chat_id
            self.config.save()
            await message.answer(
                "👋 Привет! Я бот для мониторинга цен артефактов Stalcraft.\n\n"
                "Я буду присылать выгодные предложения с аукциона.\n"
                f"Твой Chat ID: {chat_id}\n\n"
                "Используй /status для проверки статуса."
            )

        @self.dp.message(Command("status"))
        async def cmd_status(message: types.Message):
            deals = get_unnotified_deals()
            if deals:
                text = f"📊 Найдено {len(deals)} выгодных предложений:\n\n"
                for d in deals[:10]:
                    emoji = RARITY_EMOJI.get(d["rarity"], "❓")
                    text += f"{emoji} {d['item_name']} — {d['buyout_price']} руб. (скидка {d['discount_percent']:.0f}%)\n"
            else:
                text = "📊 Новых предложений пока нет. Мониторинг активен."
            await message.answer(text)

        self._ready.set()
        try:
            await self.dp.start_polling(self.bot)
        except Exception as e:
            logger.warning(f"Telegram бот не запущен (ошибка подключения): {e}")

    async def stop(self):
        if self.bot:
            await self.bot.session.close()

    async def wait_ready(self):
        await self._ready.wait()

    async def send_deal_notification(self, item_name: str, rarity: str,
                                      price: int, avg_price: float,
                                      discount: float):
        if not self.bot or not self.config.telegram_chat_id:
            return

        emoji = RARITY_EMOJI.get(rarity, "❓")
        rarity_name = RARITY_NAME.get(rarity, rarity)
        text = (
            f"{emoji} *Выгодное предложение!*\n\n"
            f"📦 *{item_name}*\n"
            f"🏷 Редкость: {rarity_name}\n"
            f"💰 Цена: {price:,} руб.\n"
            f"📊 Средняя цена: {avg_price:,.0f} руб.\n"
            f"📉 Скидка: {discount:.1f}%\n\n"
            f"#stalcraft #артефакт #{rarity.lower()}"
        )
        try:
            await self.bot.send_message(
                self.config.telegram_chat_id,
                text,
                parse_mode="Markdown",
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.error(f"Ошибка отправки в Telegram: {e}")
