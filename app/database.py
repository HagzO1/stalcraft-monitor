import sqlite3
import os
import logging
import threading

logger = logging.getLogger(__name__)

_data_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
DB_PATH = os.path.join(_data_dir, "prices.db")


def set_data_dir(path: str):
    global _data_dir, DB_PATH
    _data_dir = path
    DB_PATH = os.path.join(path, "prices.db")


_local = threading.local()


def get_conn() -> sqlite3.Connection:
    conn = getattr(_local, "_conn", None)
    if conn is None:
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        conn = sqlite3.connect(DB_PATH, timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA busy_timeout=3000")
        conn.execute("PRAGMA cache_size=-8000")
        _local._conn = conn
    return conn


def close_conn():
    conn = getattr(_local, "_conn", None)
    if conn:
        conn.close()
        _local._conn = None


def init_db():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS items (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            rarity TEXT,
            icon_path TEXT
        );
        CREATE TABLE IF NOT EXISTS tracked_items (
            item_id TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0
        );
        DROP TABLE IF EXISTS scan_log;
        DROP TABLE IF EXISTS price_history;
        CREATE TABLE scan_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT NOT NULL,
            qlt INTEGER DEFAULT 0,
            upgrade_bonus REAL DEFAULT 0.0,
            min_buyout INTEGER DEFAULT 0,
            avg_buyout INTEGER DEFAULT 0,
            total_lots INTEGER DEFAULT 0,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (item_id) REFERENCES items(id)
        );
        CREATE INDEX IF NOT EXISTS idx_scan_log_item ON scan_log(item_id);
        CREATE INDEX IF NOT EXISTS idx_scan_log_ts ON scan_log(timestamp);
        CREATE TABLE IF NOT EXISTS purchased_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            item_id TEXT NOT NULL,
            name TEXT NOT NULL,
            qlt INTEGER DEFAULT 0,
            upgrade_bonus REAL DEFAULT 0.0,
            min_buyout INTEGER DEFAULT 0,
            hist_avg REAL DEFAULT 0.0,
            discount_percent REAL DEFAULT 0.0,
            speculation INTEGER DEFAULT 0,
            icon_path TEXT DEFAULT '',
            timestamp TEXT DEFAULT '',
            purchased_at TEXT NOT NULL,
            UNIQUE(item_id, qlt, upgrade_bonus)
        );
    """)
    conn.commit()


def save_item(item_id: str, name: str, subcategory: str, colour: str):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO items (id, name, category, rarity) VALUES (?, ?, ?, ?)",
        (item_id, name, subcategory, colour),
    )
    conn.commit()


def log_scan(item_id: str, qlt: int, ptn: int, min_buyout: int, avg_buyout: int, total_lots: int):
    conn = get_conn()
    conn.execute(
        """INSERT INTO scan_log (item_id, qlt, upgrade_bonus, min_buyout, avg_buyout, total_lots)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (item_id, qlt, ptn, min_buyout, avg_buyout, total_lots),
    )
    conn.commit()


def log_scans_batch(rows: list[tuple]):
    conn = get_conn()
    conn.executemany(
        """INSERT INTO scan_log (item_id, qlt, upgrade_bonus, min_buyout, avg_buyout, total_lots)
           VALUES (?, ?, ?, ?, ?, ?)""",
        rows,
    )
    conn.commit()


def get_price_history(item_id: str, limit: int = 1000) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        """SELECT qlt, upgrade_bonus, min_buyout, avg_buyout, total_lots, timestamp
           FROM scan_log WHERE item_id = ? AND min_buyout > 0
           ORDER BY timestamp DESC LIMIT ?""",
        (item_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_latest_per_qlt(item_id: str) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        """SELECT sl1.qlt, sl1.upgrade_bonus, sl1.min_buyout, sl1.avg_buyout, sl1.total_lots, sl1.timestamp
           FROM scan_log sl1
           WHERE sl1.item_id = ?
           AND sl1.id = (
               SELECT MAX(sl2.id) FROM scan_log sl2
               WHERE sl2.item_id = sl1.item_id
               AND sl2.qlt = sl1.qlt
               AND sl2.upgrade_bonus = sl1.upgrade_bonus
           )
           AND sl1.min_buyout > 0
           ORDER BY sl1.qlt, sl1.upgrade_bonus""",
        (item_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def is_tracked(item_id: str) -> bool:
    conn = get_conn()
    row = conn.execute(
        "SELECT enabled FROM tracked_items WHERE item_id = ?", (item_id,)
    ).fetchone()
    if row is None:
        return False
    return bool(row["enabled"])


def set_tracked(item_id: str, enabled: bool):
    conn = get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO tracked_items (item_id, enabled) VALUES (?, ?)",
        (item_id, 1 if enabled else 0),
    )
    conn.commit()


def get_tracked_ids() -> list[str]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT item_id FROM tracked_items WHERE enabled = 1"
    ).fetchall()
    return [r["item_id"] for r in rows]


def get_historical_avg(item_id: str, qlt: int, ptn: int) -> float | None:
    conn = get_conn()
    row = conn.execute(
        """SELECT AVG(avg_buyout) as avg_price
           FROM (
               SELECT avg_buyout FROM scan_log
               WHERE item_id = ? AND qlt = ? AND upgrade_bonus = ? AND min_buyout > 0
               ORDER BY id DESC LIMIT 20
           )""",
        (item_id, qlt, ptn),
    ).fetchone()
    if row and row["avg_price"]:
        return round(row["avg_price"])
    return None


def save_purchased(item_id: str, name: str, qlt: int, ub: int, min_buyout: int,
                   hist_avg: float, discount: float, speculation: bool,
                   icon_path: str, timestamp: str, purchased_at: str):
    conn = get_conn()
    conn.execute(
        """INSERT OR IGNORE INTO purchased_items
           (item_id, name, qlt, upgrade_bonus, min_buyout, hist_avg, discount_percent,
            speculation, icon_path, timestamp, purchased_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (item_id, name, qlt, ub, min_buyout, hist_avg, discount,
         1 if speculation else 0, icon_path, timestamp, purchased_at),
    )
    conn.commit()


def load_all_purchased() -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        """SELECT item_id, name, qlt, upgrade_bonus, min_buyout, hist_avg,
                  discount_percent, speculation, icon_path, timestamp, purchased_at
           FROM purchased_items ORDER BY purchased_at DESC"""
    ).fetchall()
    return [dict(r) for r in rows]


def remove_purchased(item_id: str, qlt: int, ub: int):
    conn = get_conn()
    conn.execute(
        "DELETE FROM purchased_items WHERE item_id = ? AND qlt = ? AND upgrade_bonus = ?",
        (item_id, qlt, ub),
    )
    conn.commit()
