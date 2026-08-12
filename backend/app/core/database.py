from __future__ import annotations

import ssl
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import URL, Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.core.config import Settings


def build_database_url(settings: Settings) -> URL:
    """Construct the SQLAlchemy URL solely from explicit DB_* settings."""

    if settings.demo_mode or settings.app_env == "test":
        database = str(settings.demo_db_path)
        if database != ":memory:":
            database = str(Path(database).expanduser().resolve())
        return URL.create("sqlite+pysqlite", database=database)

    db_password = settings.db_password
    if not all((settings.db_host, settings.db_name, settings.db_user)) or db_password is None:
        raise RuntimeError(
            "Database is not configured. Set DB_HOST, DB_NAME, DB_USER, and DB_PASSWORD, "
            "or explicitly enable demo mode outside production."
        )
    return URL.create(
        "mysql+pymysql",
        username=settings.db_user,
        password=db_password.get_secret_value(),
        host=settings.db_host,
        port=settings.db_port or 3306,
        database=settings.db_name,
        query={"charset": "utf8mb4"},
    )


def create_ssl_context(settings: Settings) -> ssl.SSLContext:
    """Create the TLS policy requested by DB_SSL_MODE.

    REQUIRED encrypts the connection but intentionally does not authenticate the
    server certificate. VERIFY_CA authenticates the configured CA chain, while
    VERIFY_IDENTITY additionally checks DB_HOST against the certificate identity.
    """

    if settings.db_ssl_mode == "REQUIRED":
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    else:
        if settings.db_ssl_ca is None:
            raise RuntimeError(f"DB_SSL_CA is required when DB_SSL_MODE={settings.db_ssl_mode}")
        context = ssl.create_default_context(
            purpose=ssl.Purpose.SERVER_AUTH,
            cafile=str(settings.db_ssl_ca.expanduser()),
        )
        context.verify_mode = ssl.CERT_REQUIRED
        context.check_hostname = settings.db_ssl_mode == "VERIFY_IDENTITY"

    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context


def _mysql_connect_args(settings: Settings) -> dict[str, Any]:
    args: dict[str, Any] = {
        "connect_timeout": 10,
        "read_timeout": 30,
        "write_timeout": 30,
    }
    if settings.db_ssl_required:
        args["ssl"] = create_ssl_context(settings)
    return args


def verify_tls_cipher(dbapi_connection: Any) -> None:
    """Fail closed when a required MySQL connection did not negotiate TLS."""

    socket = getattr(dbapi_connection, "_sock", None)
    cipher = socket.cipher() if socket is not None and hasattr(socket, "cipher") else None
    if not cipher:
        raise ConnectionError("The database connection did not negotiate TLS")


def create_database_engine(settings: Settings) -> Engine:
    url = build_database_url(settings)
    if url.get_backend_name() == "sqlite":
        options: dict[str, Any] = {
            "connect_args": {"check_same_thread": False},
            "pool_pre_ping": True,
        }
        if url.database == ":memory:":
            options["poolclass"] = StaticPool
        engine = create_engine(url, **options)
        event.listen(
            engine,
            "connect",
            lambda connection, _: connection.execute("PRAGMA foreign_keys=ON"),
        )
        return engine

    engine = create_engine(
        url,
        connect_args=_mysql_connect_args(settings),
        pool_size=2,
        max_overflow=1,
        pool_timeout=10,
        pool_recycle=900,
        pool_pre_ping=True,
        pool_use_lifo=True,
    )
    if settings.db_ssl_required:
        event.listen(engine, "connect", lambda connection, _: verify_tls_cipher(connection))
    return engine


@dataclass(slots=True)
class Database:
    engine: Engine
    session_factory: sessionmaker[Session]

    @classmethod
    def from_settings(cls, settings: Settings) -> Database:
        engine = create_database_engine(settings)
        return cls(
            engine=engine,
            session_factory=sessionmaker(
                bind=engine,
                class_=Session,
                autoflush=False,
                expire_on_commit=False,
            ),
        )

    def session(self) -> Iterator[Session]:
        session = self.session_factory()
        try:
            yield session
        finally:
            session.close()
