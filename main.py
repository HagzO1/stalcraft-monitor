import asyncio
import logging
import os
import sys

from config import Config, set_config_dir
from app.api import StalcraftAPI, set_icon_cache_dir
from app.monitor import PriceMonitor, SharedState
from app.database import set_data_dir, init_db
from app.ui import AppUI

data_dir = os.path.join(os.path.dirname(__file__), "data")
os.makedirs(data_dir, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(data_dir, "monitor.log"), encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
    force=True,
)
logger = logging.getLogger(__name__)


async def async_init(config, state):
    api = StalcraftAPI(config)
    await api.init()
    logger.info("API инициализирован")

    monitor = PriceMonitor(api, config, state)
    monitor.start()

    await monitor.load_catalog()
    logger.info(f"Каталог загружен: {len(state.all_items_list)} артефактов")

    await monitor.load_icons()
    logger.info(f"Иконки загружены: {len(state.icon_map)}")

    return api, monitor


def main():
    set_data_dir(data_dir)
    set_config_dir(data_dir)
    set_icon_cache_dir(os.path.join(data_dir, "icons"))
    init_db()

    config = Config.load()
    state = SharedState()

    logger.info("Загрузка каталога артефактов...")
    api, monitor = asyncio.run(async_init(config, state))
    logger.info("Загрузка завершена")

    app = AppUI(config)
    app.state = state
    app.set_monitor(monitor)
    app.run()


if __name__ == "__main__":
    main()
