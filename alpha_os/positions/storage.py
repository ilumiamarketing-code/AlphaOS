import sqlite3
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)

DEFAULT_DB_PATH = Path(__file__).resolve().parent.parent.parent / "data" / "alphaos.db"


class SQLiteJSONStore:
    """Almacén clave→JSON sobre SQLite (un archivo, `data/alphaos.db`).
    Cada modelo pydantic se guarda como JSON completo en una columna — sin
    esquema relacional, suficiente para el volumen de este sistema y evita
    tener que mantener migraciones por cada campo nuevo en Position/
    JournalEntry. Nombres de tabla son constantes internas, no input
    externo, así que no hay riesgo de inyección al interpolarlos."""

    _TABLES = ("positions", "journal_entries")

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path) if db_path != ":memory:" else db_path
        if isinstance(self.db_path, Path):
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        for table in self._TABLES:
            self._conn.execute(
                f"CREATE TABLE IF NOT EXISTS {table} (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
        self._conn.commit()

    def put(self, table: str, key: str, model: BaseModel) -> None:
        self._conn.execute(
            f"INSERT INTO {table} (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, model.model_dump_json()),
        )
        self._conn.commit()

    def get(self, table: str, key: str, model_cls: type[T]) -> T | None:
        row = self._conn.execute(f"SELECT value FROM {table} WHERE key = ?", (key,)).fetchone()
        return model_cls.model_validate_json(row[0]) if row else None

    def get_all(self, table: str, model_cls: type[T]) -> list[T]:
        rows = self._conn.execute(f"SELECT value FROM {table}").fetchall()
        return [model_cls.model_validate_json(row[0]) for row in rows]
