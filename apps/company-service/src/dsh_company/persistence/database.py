from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.pool import ConnectionPoolEntry

from . import chat_models as _chat_models  # noqa: F401
from . import work_models as _work_models  # noqa: F401
from .models import Base


def create_sqlite_engine(database_path: Path) -> Engine:
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(
        dbapi_connection: DBAPIConnection, _connection_record: ConnectionPoolEntry
    ) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    return engine


def create_tables(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.exec_driver_sql(
            "INSERT OR IGNORE INTO orchestration_capacity (id, revision) "
            "VALUES ('runtime', 0)"
        )
