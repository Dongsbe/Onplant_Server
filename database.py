from __future__ import annotations

import copy
import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import quote_plus

from dotenv import load_dotenv
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, create_engine, delete, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

LOGGER = logging.getLogger("onplant.database")
BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")


def _database_url() -> str:
    explicit = os.getenv("DATABASE_URL", "").strip()
    if explicit:
        return explicit
    values = {key: os.getenv(key, "").strip() for key in ("DB_HOST", "DB_USER", "DB_NAME")}
    missing = [key for key, value in values.items() if not value]
    if missing:
        raise RuntimeError(f"MySQL configuration is incomplete: {', '.join(missing)}")
    user = quote_plus(values["DB_USER"])
    password = quote_plus(os.getenv("DB_PASSWORD", ""))
    host = values["DB_HOST"]
    port = os.getenv("DB_PORT", "3306").strip()
    name = quote_plus(values["DB_NAME"])
    return f"mysql+pymysql://{user}:{password}@{host}:{port}/{name}?charset=utf8mb4"


def _dt(value: str | datetime | None) -> datetime | None:
    if value is None:
        return None
    parsed = value if isinstance(value, datetime) else datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


def _encode_value(value: Any) -> str | None:
    return None if value is None else json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _decode_value(value: str | None) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return value


class Base(DeclarativeBase):
    pass


class Robot(Base):
    __tablename__ = "robots"
    robot_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    plant_name: Mapped[str] = mapped_column(String(64), nullable=False)
    plant_avatar: Mapped[str] = mapped_column(Text, nullable=False, default="")
    camera_url: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    link_code: Mapped[str] = mapped_column(String(32), nullable=False, default="")
    assigned_username: Mapped[str | None] = mapped_column(String(32), nullable=True)


class User(Base):
    __tablename__ = "users"
    username: Mapped[str] = mapped_column(String(32), primary_key=True)
    password_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(32), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False, default="USER")
    robot_id: Mapped[str | None] = mapped_column(ForeignKey("robots.robot_id", ondelete="SET NULL"), nullable=True)


class RobotConfigRow(Base):
    __tablename__ = "robot_configs"
    robot_id: Mapped[str] = mapped_column(ForeignKey("robots.robot_id", ondelete="CASCADE"), primary_key=True)
    speaker_volume: Mapped[int] = mapped_column(Integer, nullable=False, default=60)
    display_brightness: Mapped[int] = mapped_column(Integer, nullable=False, default=80)
    display_text: Mapped[str] = mapped_column(String(80), nullable=False, default="OnPlant")
    drive_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    explore_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    lidar_speed: Mapped[int] = mapped_column(Integer, nullable=False, default=45)
    default_region: Mapped[str] = mapped_column(String(80), nullable=False, default="진주")
    daily_lux_min: Mapped[int] = mapped_column(Integer, nullable=False, default=300)
    daily_lux_max: Mapped[int] = mapped_column(Integer, nullable=False, default=800)
    search_lux_min: Mapped[int] = mapped_column(Integer, nullable=False, default=800)
    search_lux_max: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    excess_lux: Mapped[int] = mapped_column(Integer, nullable=False, default=1100)
    camera_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    camera_url: Mapped[str] = mapped_column(String(300), nullable=False, default="")
    # Legacy columns remain mapped so upgrades never discard existing installations.
    target_lux: Mapped[int] = mapped_column(Integer, nullable=False, default=900)
    auto_search_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    auto_search_seconds: Mapped[int] = mapped_column(Integer, nullable=False, default=50)
    auto_search_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DisplayStateRow(Base):
    __tablename__ = "display_states"
    robot_id: Mapped[str] = mapped_column(ForeignKey("robots.robot_id", ondelete="CASCADE"), primary_key=True)
    screen: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    camera_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    emotion_state: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    message: Mapped[str] = mapped_column(String(255), nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    report_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class SensorReadingRow(Base):
    __tablename__ = "sensor_readings"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    robot_id: Mapped[str] = mapped_column(ForeignKey("robots.robot_id", ondelete="CASCADE"), index=True)
    lux: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_moisture: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)


class LatestSensorReadingRow(Base):
    __tablename__ = "latest_sensor_readings"
    robot_id: Mapped[str] = mapped_column(ForeignKey("robots.robot_id", ondelete="CASCADE"), primary_key=True)
    reading_id: Mapped[int] = mapped_column(Integer, nullable=False)
    lux: Mapped[float | None] = mapped_column(Float, nullable=True)
    temperature: Mapped[float | None] = mapped_column(Float, nullable=True)
    humidity: Mapped[float | None] = mapped_column(Float, nullable=True)
    soil_moisture: Mapped[float | None] = mapped_column(Float, nullable=True)
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class MoveLogRow(Base):
    __tablename__ = "move_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    robot_id: Mapped[str] = mapped_column(ForeignKey("robots.robot_id", ondelete="CASCADE"), index=True)
    state: Mapped[str] = mapped_column(String(32), nullable=False)
    action: Mapped[str] = mapped_column(String(32), nullable=False)
    target_lux: Mapped[float | None] = mapped_column(Float, nullable=True)
    current_lux: Mapped[float | None] = mapped_column(Float, nullable=True)
    message: Mapped[str] = mapped_column(String(200), nullable=False, default="")
    source: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class CommandLogRow(Base):
    __tablename__ = "command_logs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    robot_id: Mapped[str] = mapped_column(ForeignKey("robots.robot_id", ondelete="CASCADE"), index=True)
    username: Mapped[str | None] = mapped_column(String(32), nullable=True)
    command: Mapped[str] = mapped_column(String(64), nullable=False)
    value: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


class BoardPostRow(Base):
    __tablename__ = "board_posts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    category: Mapped[str] = mapped_column(String(24), nullable=False)
    title: Mapped[str] = mapped_column(String(80), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    author: Mapped[str | None] = mapped_column(String(32), nullable=True)
    author_username: Mapped[str] = mapped_column(ForeignKey("users.username", ondelete="RESTRICT"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class MigrationRow(Base):
    __tablename__ = "onplant_migrations"
    migration_key: Mapped[str] = mapped_column(String(100), primary_key=True)
    applied_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)


DATABASE_URL = _database_url()
engine = create_engine(DATABASE_URL, pool_pre_ping=True, pool_recycle=1800)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def initialize_database() -> None:
    try:
        Base.metadata.create_all(engine)
        _upgrade_existing_schema()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        LOGGER.exception("MySQL initialization failed; JSON fallback is disabled")
        raise


def _upgrade_existing_schema() -> None:
    columns = {column["name"] for column in inspect(engine).get_columns("robot_configs")}
    additions = {
        "default_region": "VARCHAR(80) NOT NULL DEFAULT '진주'",
        "daily_lux_min": "INT NOT NULL DEFAULT 300",
        "daily_lux_max": "INT NOT NULL DEFAULT 800",
        "search_lux_min": "INT NOT NULL DEFAULT 800",
        "search_lux_max": "INT NOT NULL DEFAULT 900",
        "excess_lux": "INT NOT NULL DEFAULT 1100",
    }
    with engine.begin() as connection:
        for name, ddl in additions.items():
            if name not in columns:
                connection.execute(text(f"ALTER TABLE robot_configs ADD COLUMN `{name}` {ddl}"))
        board_columns = {column["name"] for column in inspect(engine).get_columns("board_posts")}
        if "author" not in board_columns:
            connection.execute(text("ALTER TABLE board_posts ADD COLUMN author VARCHAR(32) NULL AFTER body"))


def _reading_dict(row: SensorReadingRow | LatestSensorReadingRow) -> dict[str, Any]:
    return {"id": row.id if isinstance(row, SensorReadingRow) else row.reading_id, "robot_id": row.robot_id, "lux": row.lux, "temperature": row.temperature, "humidity": row.humidity, "soil_moisture": row.soil_moisture, "source": row.source, "received_at": _iso(row.received_at)}


def _group(rows: Iterable[Any], key: Any, encode: Any) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        result.setdefault(key(row), []).append(encode(row))
    return result


def load_state() -> dict[str, Any] | None:
    with SessionLocal() as session:
        robots = session.scalars(select(Robot)).all()
        if not robots:
            return None
        users = session.scalars(select(User)).all()
        configs = session.scalars(select(RobotConfigRow)).all()
        latest = session.scalars(select(LatestSensorReadingRow)).all()
        sensors = session.scalars(select(SensorReadingRow).order_by(SensorReadingRow.id)).all()
        commands = session.scalars(select(CommandLogRow).order_by(CommandLogRow.id)).all()
        moves = session.scalars(select(MoveLogRow).order_by(MoveLogRow.id)).all()
        posts = session.scalars(select(BoardPostRow).order_by(BoardPostRow.id)).all()
        displays = session.scalars(select(DisplayStateRow)).all()
        return {
            "next_sensor_id": max([*(x.id for x in sensors), *(x.reading_id for x in latest)], default=0) + 1,
            "next_command_id": max((x.id for x in commands), default=0) + 1,
            "next_post_id": max((x.id for x in posts), default=0) + 1,
            "next_move_log_id": max((x.id for x in moves), default=0) + 1,
            "robots": {x.robot_id: {"robot_id": x.robot_id, "name": x.name, "plant_name": x.plant_name, "plant_avatar": x.plant_avatar, "camera_url": x.camera_url, "created_at": _iso(x.created_at), "last_seen": _iso(x.last_seen), "link_code": x.link_code, "assigned_username": x.assigned_username} for x in robots},
            "users": {x.username: {"username": x.username, "password_hash": x.password_hash, "display_name": x.display_name, "role": x.role.lower(), "robot_id": x.robot_id or ""} for x in users},
            "configs": {x.robot_id: {"speaker_volume": x.speaker_volume, "display_brightness": x.display_brightness, "display_text": x.display_text, "drive_enabled": x.drive_enabled, "explore_seconds": x.explore_seconds, "lidar_speed": x.lidar_speed, "default_region": x.default_region, "daily_lux_min": x.daily_lux_min, "daily_lux_max": x.daily_lux_max, "search_lux_min": x.search_lux_min, "search_lux_max": x.search_lux_max, "excess_lux": x.excess_lux, "camera_enabled": x.camera_enabled, "camera_url": x.camera_url} for x in configs},
            "latest_readings": {x.robot_id: _reading_dict(x) for x in latest},
            "history": _group(sensors, lambda x: x.robot_id, _reading_dict),
            "commands": _group(commands, lambda x: x.robot_id, lambda x: {"id": x.id, "robot_id": x.robot_id, "command": x.command, "value": _decode_value(x.value), "created_at": _iso(x.created_at)}),
            "board_posts": [{"id": x.id, "category": x.category, "title": x.title, "body": x.body, "author": x.author or x.author_username, "author_username": x.author_username, "created_at": _iso(x.created_at), "updated_at": _iso(x.updated_at)} for x in posts],
            "move_logs": _group(moves, lambda x: x.robot_id, lambda x: {"id": x.id, "robot_id": x.robot_id, "state": x.state, "action": x.action, "target_lux": x.target_lux, "current_lux": x.current_lux, "message": x.message, "source": x.source, "created_at": _iso(x.created_at)}),
            "display_states": {x.robot_id: {"screen": x.screen, "camera_visible": x.camera_visible, "updated_at": _iso(x.updated_at), "report_until": _iso(x.report_until)} for x in displays},
        }


def _clear_all(session: Session) -> None:
    for model in (LatestSensorReadingRow, SensorReadingRow, MoveLogRow, CommandLogRow, BoardPostRow, DisplayStateRow, RobotConfigRow, User, Robot):
        session.execute(delete(model))


def _insert_state(session: Session, data: dict[str, Any]) -> None:
    for item in data.get("robots", {}).values():
        session.add(Robot(robot_id=item["robot_id"], name=item["name"], plant_name=item["plant_name"], plant_avatar=item.get("plant_avatar", ""), camera_url=item.get("camera_url", ""), created_at=_dt(item["created_at"]), last_seen=_dt(item.get("last_seen")), link_code=item.get("link_code", ""), assigned_username=item.get("assigned_username")))
    session.flush()
    for item in data.get("users", {}).values():
        session.add(User(username=item["username"], password_hash=item["password_hash"], display_name=item["display_name"], role=item.get("role", "USER").upper(), robot_id=item.get("robot_id") or None))
    session.flush()
    for robot_id, item in data.get("configs", {}).items():
        session.add(RobotConfigRow(robot_id=robot_id, **item, target_lux=item.get("search_lux_max", 900), auto_search_enabled=False, auto_search_seconds=item.get("explore_seconds", 50), auto_search_done=False))
    for item in data.get("latest_readings", {}).values():
        session.add(LatestSensorReadingRow(robot_id=item["robot_id"], reading_id=item["id"], lux=item.get("lux"), temperature=item.get("temperature"), humidity=item.get("humidity"), soil_moisture=item.get("soil_moisture"), source=item["source"], received_at=_dt(item["received_at"])))
    for rows in data.get("history", {}).values():
        for item in rows:
            session.add(SensorReadingRow(**{**item, "received_at": _dt(item["received_at"])}))
    for rows in data.get("commands", {}).values():
        for item in rows:
            session.add(CommandLogRow(id=item["id"], robot_id=item["robot_id"], username=item.get("username"), command=item["command"], value=_encode_value(item.get("value")), created_at=_dt(item["created_at"])))
    usernames = set(data.get("users", {}))
    fallback_author = "admin" if "admin" in usernames else next(iter(usernames), None)
    for item in data.get("board_posts", []):
        author_username = item.get("author_username") if item.get("author_username") in usernames else fallback_author
        if author_username:
            session.add(BoardPostRow(id=item["id"], category=item["category"], title=item["title"], body=item["body"], author=item.get("author"), author_username=author_username, created_at=_dt(item["created_at"]), updated_at=_dt(item.get("updated_at"))))
    for rows in data.get("move_logs", {}).values():
        for item in rows:
            session.add(MoveLogRow(**{**item, "created_at": _dt(item["created_at"])}))
    for robot_id, item in data.get("display_states", {}).items():
        session.add(DisplayStateRow(robot_id=robot_id, screen=item.get("screen", "idle"), camera_visible=item.get("camera_visible", False), emotion_state="idle", message="", updated_at=_dt(item["updated_at"]), report_until=_dt(item.get("report_until"))))


def _normalize_legacy_ids(data: dict[str, Any]) -> dict[str, Any]:
    normalized = copy.deepcopy(data)

    def normalize_rows(groups: Iterable[list[dict[str, Any]]]) -> int:
        rows = [row for group in groups for row in group]
        next_id = max((int(row.get("id", 0)) for row in rows), default=0) + 1
        seen: set[int] = set()
        for row in rows:
            row_id = int(row.get("id", 0))
            if row_id <= 0 or row_id in seen:
                while next_id in seen:
                    next_id += 1
                row_id = next_id
                row["id"] = row_id
                next_id += 1
            seen.add(row_id)
        return max(seen, default=0) + 1

    normalized["next_sensor_id"] = normalize_rows(normalized.get("history", {}).values())
    normalized["next_command_id"] = normalize_rows(normalized.get("commands", {}).values())
    normalized["next_move_log_id"] = normalize_rows(normalized.get("move_logs", {}).values())
    normalized["next_post_id"] = normalize_rows([normalized.get("board_posts", [])])
    return normalized


def migrate_json_once(path: Path) -> bool:
    migration_key = "onplant_state_json_v1"
    with SessionLocal() as session:
        if session.get(MigrationRow, migration_key):
            return False
    if not path.exists():
        LOGGER.info("Legacy JSON not found; no migration performed: %s", path)
        return False
    data = _normalize_legacy_ids(json.loads(path.read_text(encoding="utf-8")))
    with SessionLocal.begin() as session:
        _clear_all(session)
        _insert_state(session, data)
        session.add(MigrationRow(migration_key=migration_key, applied_at=datetime.utcnow()))
    LOGGER.info("Migrated legacy JSON to MySQL once; source retained: %s", path)
    return True


def save_state(data: dict[str, Any]) -> None:
    try:
        with SessionLocal.begin() as session:
            _clear_all(session)
            _insert_state(session, data)
    except Exception:
        LOGGER.exception("MySQL save failed; JSON fallback is disabled")
        raise
