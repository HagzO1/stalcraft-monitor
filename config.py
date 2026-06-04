import json
import os
from dataclasses import dataclass, asdict

_config_dir = os.path.join(os.path.dirname(__file__), "data")
CONFIG_PATH = os.path.join(_config_dir, "config.json")


def set_config_dir(path: str):
    global _config_dir, CONFIG_PATH
    _config_dir = path
    CONFIG_PATH = os.path.join(path, "config.json")


@dataclass
class Config:
    client_id: str = "3024"
    client_secret: str = "QCqnxrgLdDBjqqmDAnInQMgReihLunwfjPbpAivY"
    telegram_token: str = "1513216317:AAGhLxG_aj9_AiJ-ZOXrt6iWG50_CkuSDRg"
    telegram_chat_id: str = ""
    telegram_api_url: str = "https://api.telegram.org"
    telegram_proxy: str = ""
    telegram_use_proxy: bool = False
    region: str = "ru"
    min_profit_percent: float = 20.0
    enabled: bool = False

    def save(self):
        os.makedirs(os.path.dirname(CONFIG_PATH), exist_ok=True)
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, ensure_ascii=False, indent=2)

    @classmethod
    def load(cls) -> "Config":
        cfg = cls()
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            for k, v in data.items():
                if v not in (None, ""):
                    setattr(cfg, k, v)
        except (FileNotFoundError, json.JSONDecodeError):
            pass
        return cfg
