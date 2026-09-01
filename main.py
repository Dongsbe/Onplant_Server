from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import urllib.error
import urllib.request
import uuid
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from random import choices, uniform
from threading import Lock
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from dotenv import load_dotenv


BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

import database

STATIC_DIR = BASE_DIR / "static"
DATA_PATH = Path(os.getenv("ONPLANT_DATA", BASE_DIR / "onplant_state.json"))
VOICE_DIR = BASE_DIR / "voice_outputs"
VOICE_DIR.mkdir(exist_ok=True)

app = FastAPI(title="OnPlant Server", version="0.5.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")
app.mount("/voice_outputs", StaticFiles(directory=VOICE_DIR), name="voice_outputs")


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=4, max_length=128)
    display_name: str = Field(default="사용자", min_length=1, max_length=32)
    plant_name: str = Field(default="토로예", min_length=1, max_length=64)


class LoginIn(BaseModel):
    username: str = Field(min_length=2, max_length=32)
    password: str = Field(min_length=4, max_length=128)


class UserPublic(BaseModel):
    username: str
    display_name: str
    robot_id: str
    role: str = "user"


class RobotCreate(BaseModel):
    robot_id: str = Field(min_length=1, max_length=64)
    name: str = Field(default="Raspbot A", min_length=1, max_length=64)
    plant_name: str = Field(default="나의 반려 식물", min_length=1, max_length=64)
    robot_key: str | None = Field(default=None, max_length=128)
    camera_url: str = Field(default="", max_length=300)


class RobotUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    plant_name: str | None = Field(default=None, min_length=1, max_length=64)
    plant_avatar: str | None = Field(default=None, max_length=300000)
    camera_url: str | None = Field(default=None, max_length=300)


class RobotPublic(BaseModel):
    robot_id: str
    name: str
    plant_name: str
    plant_avatar: str = ""
    camera_url: str = ""
    created_at: str
    last_seen: str | None = None
    link_code: str = ""
    assigned_username: str | None = None


class SensorReadingIn(BaseModel):
    robot_id: str = Field(default="raspbot-a", min_length=1, max_length=64)
    robot_key: str | None = Field(default=None, max_length=128)
    lux: float | None = Field(default=None, ge=0)
    temperature: float | None = Field(default=None)
    humidity: float | None = Field(default=None, ge=0, le=100)
    soil_moisture: float | None = Field(default=None, ge=0, le=100)
    source: str = Field(default="dummy", min_length=1, max_length=64)


class StoredReading(BaseModel):
    id: int
    robot_id: str
    lux: float | None = None
    temperature: float | None = None
    humidity: float | None = None
    soil_moisture: float | None = None
    source: str
    received_at: str


class LidarPoint(BaseModel):
    x: float
    y: float
    distance: float | None = None
    angle: float | None = None
    ignored: bool = False


class LidarFrameIn(BaseModel):
    points: list[LidarPoint] = Field(default_factory=list, max_length=720)
    state: str = Field(default="UNKNOWN", max_length=32)
    action: str = Field(default="STOP", max_length=32)
    current_lux: float | None = None
    best_lux: float | None = None
    lux_error: float | None = None
    best_time: float = 0.0
    explore_elapsed: float = 0.0
    return_index: int = 0
    return_total: int = 0
    return_avoid_count: int = 0
    return_elapsed: float = 0.0
    seek_elapsed: float = 0.0
    seek_seconds: float = 0.0
    pose_x: float | None = None
    pose_y: float | None = None
    heading: str | None = Field(default=None, max_length=16)
    best_x: float | None = None
    best_y: float | None = None
    blocked_count: int = 0
    front_blocked: bool = False
    danger: bool = False
    emergency: bool = False
    front_points: int = 0
    left_score: float | None = None
    right_score: float | None = None
    source: str = Field(default="raspberry-pi", max_length=64)


class StoredLidarFrame(LidarFrameIn):
    robot_id: str
    received_at: str


class RobotConfig(BaseModel):
    speaker_volume: int = Field(default=60, ge=0, le=100)
    display_brightness: int = Field(default=80, ge=0, le=100)
    display_text: str = Field(default="OnPlant", max_length=80)
    drive_enabled: bool = False
    explore_seconds: int = Field(default=50, ge=5, le=600)
    lidar_speed: int = Field(default=45, ge=0, le=100)
    default_region: str = Field(default="진주", max_length=80)
    daily_lux_min: int = Field(default=300, ge=0, le=20000)
    daily_lux_max: int = Field(default=800, ge=0, le=20000)
    search_lux_min: int = Field(default=800, ge=0, le=20000)
    search_lux_max: int = Field(default=900, ge=0, le=20000)
    excess_lux: int = Field(default=1100, ge=0, le=20000)
    camera_enabled: bool = True
    camera_url: str = Field(default="", max_length=300)


class CommandIn(BaseModel):
    command: str = Field(min_length=1, max_length=64)
    value: str | int | float | bool | None = None


class LlmChatIn(BaseModel):
    message: str = Field(min_length=1, max_length=500)
    username: str = Field(default="demo", max_length=32)
    speak: bool = False


class StoredCommand(CommandIn):
    id: int
    robot_id: str
    created_at: str


class LlmChatOut(BaseModel):
    reply: str
    intent: str
    listening: bool = False
    command: StoredCommand | None = None
    display: DisplayState | None = None


class TextToSpeechIn(BaseModel):
    text: str = Field(min_length=1, max_length=800)


class TextToSpeechOut(BaseModel):
    audio_url: str


class VoiceChatOut(BaseModel):
    transcript: str
    reply: str
    intent: str
    listening: bool = False
    command: StoredCommand | None = None
    display: DisplayState | None = None
    audio_url: str | None = None


class BoardPostIn(BaseModel):
    category: str = Field(default="공지", min_length=1, max_length=24)
    title: str = Field(min_length=1, max_length=80)
    body: str = Field(min_length=1, max_length=1000)
    author: str = Field(default="관리자", min_length=1, max_length=32)
    author_username: str = Field(default="admin", min_length=1, max_length=32)


class BoardPostUpdate(BaseModel):
    category: str | None = Field(default=None, min_length=1, max_length=24)
    title: str | None = Field(default=None, min_length=1, max_length=80)
    body: str | None = Field(default=None, min_length=1, max_length=1000)


class BoardPost(BoardPostIn):
    id: int
    created_at: str
    updated_at: str | None = None



class MoveLogIn(BaseModel):
    state: str = Field(default="UNKNOWN", max_length=32)
    action: str = Field(default="STOP", max_length=32)
    message: str = Field(default="", max_length=200)
    target_lux: float | None = None
    current_lux: float | None = None
    source: str = Field(default="fsm", max_length=64)


class StoredMoveLog(MoveLogIn):
    id: int
    robot_id: str
    created_at: str


class DisplayState(BaseModel):
    screen: str = Field(default="idle", max_length=32)
    camera_visible: bool = False
    updated_at: str
    report_until: str | None = None


class RemoteIn(BaseModel):
    key: str = Field(min_length=1, max_length=8)


_lock = Lock()
_next_sensor_id = 1
_next_command_id = 1
_next_post_id = 1
_robots: dict[str, RobotPublic] = {}
_users: dict[str, dict[str, str]] = {}
_configs: dict[str, RobotConfig] = {}
_latest_readings: dict[str, StoredReading] = {}
_history: dict[str, deque[StoredReading]] = defaultdict(lambda: deque(maxlen=500))
_commands: dict[str, deque[StoredCommand]] = defaultdict(lambda: deque(maxlen=100))
_board_posts: deque[BoardPost] = deque(maxlen=200)
_lidar_latest: dict[str, StoredLidarFrame] = {}
_move_logs: dict[str, deque[StoredMoveLog]] = defaultdict(lambda: deque(maxlen=200))
_display_states: dict[str, DisplayState] = {}
_llm_listen_until: dict[str, datetime] = {}
_next_move_log_id = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _hash_password(password: str) -> str:
    return hashlib.sha256(password.encode("utf-8")).hexdigest()


def _robot_link_code(robot_id: str) -> str:
    digest = hashlib.sha1(robot_id.encode("utf-8")).hexdigest().upper()
    return f"OP-{digest[:4]}-{digest[4:8]}"


def _plant_profile() -> dict[str, Any]:
    return {
        "species": "하월시아",
        "lux_target": 850,
        "daily_lux_range": "300~800 lux",
        "lux_range": "800~900 lux",
        "excess_lux": "1100 lux 이상",
        "temperature_range": "18~28°C",
        "humidity_range": "35~60%",
        "soil_moisture_range": "20~45%",
        "note": "",
    }


def _normalize_board_category(category: str | None) -> str:
    return "자유게시판" if category == "자유게시판" else "공지"


def _user_public(username: str) -> UserPublic:
    user = _users[username]
    return UserPublic(
        username=user["username"],
        display_name=user["display_name"],
        robot_id=user["robot_id"],
        role=user.get("role", "admin" if username == "admin" else "user"),
    )


def _default_robot() -> None:
    if "raspbot-a" not in _robots:
        _robots["raspbot-a"] = RobotPublic(
            robot_id="raspbot-a",
            name="Raspbot A",
            plant_name="토로예",
            created_at=_now_iso(),
            link_code=_robot_link_code("raspbot-a"),
            assigned_username="demo",
        )
    if not _robots["raspbot-a"].link_code:
        _robots["raspbot-a"].link_code = _robot_link_code("raspbot-a")
    if "raspbot-a" not in _configs:
        _configs["raspbot-a"] = RobotConfig()
    if "demo" not in _users:
        _users["demo"] = {
            "username": "demo",
            "display_name": "사용자",
            "password_hash": _hash_password("1234"),
            "robot_id": "raspbot-a",
            "role": "user",
        }
    else:
        _users["demo"].setdefault("role", "user")
    if "admin" not in _users:
        _users["admin"] = {
            "username": "admin",
            "display_name": "관리자",
            "password_hash": _hash_password("1234"),
            "robot_id": "raspbot-a",
            "role": "admin",
        }
    else:
        _users["admin"].setdefault("role", "admin")


def _ensure_robot(robot_id: str) -> None:
    if robot_id not in _robots:
        _robots[robot_id] = RobotPublic(
            robot_id=robot_id,
            name=robot_id,
            plant_name="나의 반려 식물",
            created_at=_now_iso(),
            link_code=_robot_link_code(robot_id),
        )
    if not _robots[robot_id].link_code:
        _robots[robot_id].link_code = _robot_link_code(robot_id)
    if robot_id not in _configs:
        _configs[robot_id] = RobotConfig(camera_url=_robots[robot_id].camera_url)


def _serialize_state() -> dict[str, Any]:
    return {
        "next_sensor_id": _next_sensor_id,
        "next_command_id": _next_command_id,
        "next_post_id": _next_post_id,
        "robots": {key: value.model_dump() for key, value in _robots.items()},
        "users": _users,
        "configs": {key: value.model_dump() for key, value in _configs.items()},
        "latest_readings": {key: value.model_dump() for key, value in _latest_readings.items()},
        "history": {
            key: [item.model_dump() for item in values]
            for key, values in _history.items()
        },
        "commands": {
            key: [item.model_dump() for item in values]
            for key, values in _commands.items()
        },
        "board_posts": [item.model_dump() for item in _board_posts],
        "move_logs": {key: [item.model_dump() for item in values] for key, values in _move_logs.items()},
        "display_states": {key: value.model_dump() for key, value in _display_states.items()},
        "next_move_log_id": _next_move_log_id,
    }


def _save_state() -> None:
    database.save_state(_serialize_state())


def _load_state() -> None:
    global _next_sensor_id, _next_command_id, _next_post_id, _next_move_log_id

    database.initialize_database()
    database.migrate_json_once(DATA_PATH)
    data = database.load_state()
    if data is None:
        _default_robot()
        _board_posts.extend(
            [
                BoardPost(
                    id=1,
                    category="공지",
                    title="조도 탐색 테스트 순서",
                    body="센서값이 안정적으로 들어오는지 확인한 뒤 탐색 시간을 50초로 두고 주행 로그를 비교합니다.",
                    author="OnPlant",
                    created_at=_now_iso(),
                ),
                BoardPost(
                    id=2,
                    category="공지",
                    title="라즈봇 I2C 확인",
                    body="BH1750이 0x23으로 잡히면 Pi I2C는 정상입니다. 확장보드 주소는 별도로 확인합니다.",
                    author="OnPlant",
                    created_at=_now_iso(),
                ),
            ]
        )
        _next_post_id = 3
        _save_state()
        return

    _next_sensor_id = int(data.get("next_sensor_id", 1))
    _next_command_id = int(data.get("next_command_id", 1))
    _next_post_id = int(data.get("next_post_id", 1))
    _next_move_log_id = int(data.get("next_move_log_id", 1))

    _robots.clear()
    for key, value in data.get("robots", {}).items():
        _robots[key] = RobotPublic(**value)

    _users.clear()
    _users.update(data.get("users", {}))

    _configs.clear()
    for key, value in data.get("configs", {}).items():
        _configs[key] = RobotConfig(**value)

    _latest_readings.clear()
    for key, value in data.get("latest_readings", {}).items():
        _latest_readings[key] = StoredReading(**value)

    _history.clear()
    for key, values in data.get("history", {}).items():
        _history[key] = deque((StoredReading(**item) for item in values), maxlen=500)
        if key not in _latest_readings and _history[key]:
            _latest_readings[key] = _history[key][-1]

    _commands.clear()
    for key, values in data.get("commands", {}).items():
        _commands[key] = deque((StoredCommand(**item) for item in values), maxlen=100)

    _board_posts.clear()
    for item in data.get("board_posts", []):
        item["category"] = _normalize_board_category(item.get("category"))
        item.setdefault("updated_at", None)
        item.setdefault("author_username", "admin")
        _board_posts.append(BoardPost(**item))

    _move_logs.clear()
    for key, values in data.get("move_logs", {}).items():
        _move_logs[key] = deque((StoredMoveLog(**item) for item in values), maxlen=200)

    _display_states.clear()
    for key, value in data.get("display_states", {}).items():
        _display_states[key] = DisplayState(**value)
    _default_robot()


def _append_move_log_locked(robot_id: str, log: MoveLogIn) -> StoredMoveLog:
    global _next_move_log_id
    stored = StoredMoveLog(
        id=_next_move_log_id,
        robot_id=robot_id,
        created_at=_now_iso(),
        **log.model_dump(),
    )
    _next_move_log_id += 1
    _move_logs[robot_id].append(stored)
    return stored


def _append_command_locked(robot_id: str, command: CommandIn) -> StoredCommand:
    global _next_command_id
    _ensure_robot(robot_id)
    stored = StoredCommand(
        id=_next_command_id,
        robot_id=robot_id,
        created_at=_now_iso(),
        **command.model_dump(),
    )
    _next_command_id += 1
    _commands[robot_id].append(stored)
    return stored


def _latest_for(robot_id: str) -> StoredReading | None:
    if robot_id in _latest_readings:
        return _latest_readings[robot_id]
    items = _history.get(robot_id)
    return items[-1] if items else None


def _status_from(reading: StoredReading | None, config: RobotConfig | None = None) -> dict[str, str]:
    if not reading:
        return {
            "level": "대기",
            "tone": "idle",
            "emoji": "⏳",
            "message": "아직 수신된 센서 데이터가 없습니다.",
            "recommendation": "더미 데이터를 보내거나 라즈베리파이 센서 POST를 연결하세요.",
        }

    config = config or RobotConfig()
    problems: list[str] = []
    notices: list[str] = []
    if reading.temperature is not None and not 18 <= reading.temperature <= 28:
        problems.append("온도")
    if reading.humidity is not None and not 35 <= reading.humidity <= 60:
        problems.append("습도")
    if reading.lux is not None:
        if reading.lux < config.daily_lux_min:
            problems.append("조도 부족")
        elif config.search_lux_min <= reading.lux <= config.search_lux_max:
            notices.append("최적 조도 근접")
        elif reading.lux >= config.excess_lux:
            problems.append("조도 과다")
        elif reading.lux > config.daily_lux_max:
            notices.append("밝은 편")
    if reading.soil_moisture is not None and not 20 <= reading.soil_moisture <= 45:
        problems.append("토양수분")

    if not problems:
        message = "식물이 안정적인 상태입니다."
        recommendation = "현재 환경을 유지하고 주기적으로 센서 기록을 확인하세요."
        if notices:
            message = ", ".join(notices) + " 상태입니다."
            recommendation = "빛 조건이 좋은 편입니다. 최적 조도 탐색 결과와 함께 관찰하세요."
        return {
            "level": "건강",
            "tone": "good",
            "emoji": "😊",
            "message": message,
            "recommendation": recommendation,
        }

    label = ", ".join(problems)
    return {
        "level": "주의",
        "tone": "warn",
        "emoji": "🙂",
        "message": f"{label} 값을 확인해야 합니다.",
        "recommendation": f"{label} 범위가 적정값에서 벗어났습니다. 환경을 조정하고 다음 데이터를 확인하세요.",
    }


def _should_store_sensor_reading(robot_id: str, reading: StoredReading) -> bool:
    history = _history.get(robot_id)
    if not history:
        return True

    previous = history[-1]
    previous_time = _parse_iso_time(previous.received_at)
    current_time = _parse_iso_time(reading.received_at)
    if previous_time and current_time and current_time - previous_time >= timedelta(minutes=10):
        return True

    config = _configs.get(robot_id) or RobotConfig()

    def sensor_band(value: float | None, low: float, high: float) -> str:
        if value is None:
            return "missing"
        if value < low:
            return "low"
        if value > high:
            return "high"
        return "normal"

    current_bands = (
        sensor_band(reading.lux, config.daily_lux_min, config.excess_lux),
        sensor_band(reading.temperature, 10, 35),
        sensor_band(reading.humidity, 20, 80),
        sensor_band(reading.soil_moisture, 15, 80),
    )
    previous_bands = (
        sensor_band(previous.lux, config.daily_lux_min, config.excess_lux),
        sensor_band(previous.temperature, 10, 35),
        sensor_band(previous.humidity, 20, 80),
        sensor_band(previous.soil_moisture, 15, 80),
    )
    # Keep live updates at five seconds, but rate-limit persisted transitions so
    # values oscillating around a threshold cannot flood the history table.
    if (
        current_bands != previous_bands
        and previous_time
        and current_time
        and current_time - previous_time >= timedelta(minutes=1)
    ):
        return True

    # A sudden lux change is useful, but never persist it every five seconds.
    if (
        previous_time
        and current_time
        and current_time - previous_time >= timedelta(minutes=1)
        and reading.lux is not None
        and previous.lux is not None
        and abs(reading.lux - previous.lux) >= 250
    ):
        return True

    return False


def _display_screen_for_robot(robot_id: str) -> str:
    return "idle"


def _report_is_active(state: DisplayState) -> bool:
    if not state.report_until:
        return False
    try:
        return datetime.fromisoformat(state.report_until) > datetime.now(timezone.utc)
    except ValueError:
        return False


def _display_state_for_response(robot_id: str, state: DisplayState) -> DisplayState:
    screen = "report" if _report_is_active(state) else _display_screen_for_robot(robot_id)
    return state.model_copy(update={"screen": screen})


def _classify_robot_intent(message: str) -> tuple[str, str | None]:
    text = message.lower().replace(" ", "")
    if any(word in text for word in ("멈춰", "정지", "그만", "스탑", "stop")):
        return "robot_command", "stop"
    if any(word in text for word in ("최적조도", "조도찾", "빛찾", "밝은곳", "탐색", "search")):
        return "robot_command", "start_light_search"
    if any(word in text for word in ("상태", "보여줘", "리포트", "보고", "status")):
        return "robot_command", "show_status"
    if any(word in text for word in ("온도", "습도", "토양", "수분", "조도", "센서")):
        return "sensor_query", None
    return "chat", None


def _sensor_reply(robot_id: str) -> str:
    latest = _latest_for(robot_id)
    if not latest:
        return "아직 수신된 센서 데이터가 없습니다."
    return (
        f"현재 상태는 조도 {latest.lux if latest.lux is not None else '--'} lux, "
        f"온도 {latest.temperature if latest.temperature is not None else '--'}도, "
        f"습도 {latest.humidity if latest.humidity is not None else '--'}%, "
        f"토양수분 {latest.soil_moisture if latest.soil_moisture is not None else '--'}%입니다."
    )


def _fallback_llm_reply(robot_id: str, message: str, intent: str, command_name: str | None) -> str:
    if command_name == "show_status":
        return _sensor_reply(robot_id) + " 전면 디스플레이에 상태 화면을 표시했습니다."
    if command_name == "start_light_search":
        return "최적 조도 탐색 명령을 보냈습니다. 로봇 명령 대기 루프에서 이 명령을 받아 탐색을 시작합니다."
    if command_name == "stop":
        return "정지 명령을 보냈습니다. 로봇은 현재 동작을 멈추도록 처리합니다."
    if intent == "sensor_query":
        return _sensor_reply(robot_id)
    return "일상 대화는 연결 준비 중입니다. 지금은 상태 조회, 최적 조도 탐색, 정지 명령을 처리할 수 있습니다."


def _classify_robot_intent(message: str) -> tuple[str, str | None]:
    text = message.lower().replace(" ", "")

    stop_words = ("멈춰", "정지", "그만", "스탑", "stop", "움직이지마")
    search_words = ("최적조도", "조도찾", "빛찾", "밝은곳", "탐색", "햇빛좋은", "빛좋은", "search")
    status_words = (
        "상태",
        "상처",
        "어때",
        "어떠",
        "보여줘",
        "리포트",
        "보고",
        "컨디션",
        "건강",
        "괜찮",
        "잘크",
        "잘살",
        "status",
    )
    sensor_words = ("온도", "습도", "토양", "수분", "조도", "센서")
    vague_robot_words = ("가줘", "움직", "찾아", "해줘", "동스비", "라즈봇", "식물")

    if any(word in text for word in stop_words):
        return "robot_command", "stop"
    if any(word in text for word in search_words):
        return "robot_command", "start_light_search"
    if any(word in text for word in status_words):
        return "robot_command", "show_status"
    if any(word in text for word in sensor_words):
        return "sensor_query", None
    if any(word in text for word in vague_robot_words):
        return "clarify", None
    return "chat", None


def _sensor_reply(robot_id: str) -> str:
    latest = _latest_for(robot_id)
    if not latest:
        return "아직 수신된 센서 데이터가 없습니다."
    return (
        f"현재 상태는 조도 {latest.lux if latest.lux is not None else '--'} lux, "
        f"온도 {latest.temperature if latest.temperature is not None else '--'}도, "
        f"습도 {latest.humidity if latest.humidity is not None else '--'}%, "
        f"토양수분 {latest.soil_moisture if latest.soil_moisture is not None else '--'}%입니다."
    )


def _fallback_llm_reply(robot_id: str, message: str, intent: str, command_name: str | None) -> str:
    if command_name == "show_status":
        return _sensor_reply(robot_id) + " 전면 디스플레이에 상태 화면을 표시했습니다."
    if command_name == "start_light_search":
        return "최적 조도 탐색 명령을 보냈습니다. 로봇 명령 대기 루프에서 이 명령을 받아 탐색을 시작합니다."
    if command_name == "stop":
        return "정지 명령을 보냈습니다. 로봇은 현재 동작을 멈추도록 처리합니다."
    if intent == "sensor_query":
        return _sensor_reply(robot_id)
    if intent == "clarify":
        return "상태 확인, 최적 조도 탐색, 정지 중 어떤 동작을 원하시는지 다시 말해 주세요."
    if intent == "daily_weather":
        region = (_configs.get(robot_id) or RobotConfig()).default_region
        return f"{region} 기준 날씨 질문으로 이해했습니다. 실시간 기상 API는 아직 연결 전이라 정확한 현재 날씨 대신, 날씨 정보를 확인한 뒤 옷차림과 식물 위치를 조정해 주세요."
    if intent == "daily_outfit":
        region = (_configs.get(robot_id) or RobotConfig()).default_region
        return f"{region} 기준으로 날씨를 확인한 뒤 옷차림을 정하는 것이 좋습니다. 쌀쌀하면 겉옷을 챙기고, 비 예보가 있으면 우산을 준비하세요."
    if intent == "daily_time":
        return "현재 시간은 서버 기준 " + datetime.now().strftime("%Y년 %m월 %d일 %H시 %M분") + "입니다."
    if intent == "plant_question":
        return "하월시아는 과습을 피하고 밝은 간접광에서 관리하는 것이 좋습니다. 흙이 충분히 말랐을 때 물을 주세요."
    if intent == "smalltalk":
        return "좋아요. 저는 식물 상태 확인, 최적 조도 탐색, 정지 명령을 도와줄 수 있습니다."
    return "상태 확인, 최적 조도 탐색, 정지 명령을 처리할 수 있습니다."


def _normalize_speech_text(message: str) -> str:
    return message.lower().replace(" ", "").strip()


WAKE_WORDS = (
    "동스비",
    "동시비",
    "동습이",
    "동습비",
    "동수비",
    "동쓰비",
    "동스피",
    "돈스비",
)


def _looks_like_wake_word(text: str) -> bool:
    normalized = _normalize_speech_text(text).strip(".,!?야아")
    return normalized in WAKE_WORDS


def _is_wake_word_only(message: str) -> bool:
    return _looks_like_wake_word(message)


def _strip_wake_word(message: str) -> str:
    text = message.strip()
    for wake_word in WAKE_WORDS:
        if text.startswith(wake_word):
            return text[len(wake_word):].strip(" ,.!?야아")
    first_token = text.split(maxsplit=1)[0] if text else ""
    if first_token and _looks_like_wake_word(first_token):
        return text[len(first_token):].strip(" ,.!?야아")
    first_three = text[:3]
    if first_three and _looks_like_wake_word(first_three):
        return text[3:].strip(" ,.!?야아")
    return text


def _classify_daily_chat(message: str) -> str:
    text = message.lower().replace(" ", "")
    if any(word in text for word in ("날씨", "비와", "비오", "기온", "춥", "덥")):
        return "daily_weather"
    if any(word in text for word in ("뭐입", "옷", "겉옷", "반팔", "긴팔", "우산")):
        return "daily_outfit"
    if any(word in text for word in ("몇시", "시간", "며칠", "날짜", "요일")):
        return "daily_time"
    if any(word in text for word in ("하월시아", "다육", "식물", "물얼마", "햇빛", "잎이", "분갈이")):
        return "plant_question"
    if any(word in text for word in ("심심", "피곤", "힘들", "안녕", "고마", "뭐할수")):
        return "smalltalk"
    return "chat"


def _chat_system_prompt(robot_id: str) -> str:
    config = _configs.get(robot_id) or RobotConfig()
    latest = _latest_for(robot_id)
    sensor_context = "아직 센서 데이터가 없습니다."
    if latest:
        sensor_context = (
            f"현재 센서값: 조도 {latest.lux} lux, 온도 {latest.temperature}도, "
            f"습도 {latest.humidity}%, 토양수분 {latest.soil_moisture}%."
        )
    return (
        "너는 OnPlant 반려식물 로봇 '동스비'의 짧고 자연스러운 한국어 응답 담당이다. "
        "모터를 직접 제어한다고 말하지 말고, 실제 명령은 서버가 처리한다고 전제한다. "
        f"기본 지역은 {config.default_region}이다. "
        "실시간 날씨 API가 연결되어 있지 않으면 현재 날씨를 단정하지 말고, 확인 필요하다고 말한다. "
        "답변은 1~3문장으로 짧게 한다. "
        f"{sensor_context}"
    )


def _is_listening(robot_id: str) -> bool:
    until = _llm_listen_until.get(robot_id)
    if not until:
        return False
    if until <= datetime.now(timezone.utc):
        _llm_listen_until.pop(robot_id, None)
        return False
    return True


def _start_listening(robot_id: str, seconds: int = 10) -> None:
    _llm_listen_until[robot_id] = datetime.now(timezone.utc) + timedelta(seconds=seconds)


def _parse_iso_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _is_recent(value: str | None, seconds: int = 20) -> bool:
    parsed = _parse_iso_time(value)
    if not parsed:
        return False
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    age = datetime.now(timezone.utc) - parsed
    return timedelta(seconds=-5) <= age <= timedelta(seconds=seconds)


def _current_robot_motion_state(robot_id: str) -> tuple[str, bool]:
    """Return current FSM state and whether the robot should be treated as moving."""
    latest_lidar_time = 0.0
    latest_log_time = 0.0
    latest_lidar_state: tuple[str, str] | None = None
    latest_log_state: tuple[str, str] | None = None

    lidar = _lidar_latest.get(robot_id)
    if lidar and _is_recent(lidar.received_at):
        parsed = _parse_iso_time(lidar.received_at)
        latest_lidar_time = parsed.timestamp() if parsed else 0.0
        latest_lidar_state = ((lidar.state or "UNKNOWN").upper(), (lidar.action or "STOP").upper())

    logs = _move_logs.get(robot_id)
    if logs:
        latest_log = logs[-1]
        if _is_recent(latest_log.created_at):
            parsed = _parse_iso_time(latest_log.created_at)
            latest_log_time = parsed.timestamp() if parsed else 0.0
            latest_log_state = ((latest_log.state or "UNKNOWN").upper(), (latest_log.action or "STOP").upper())

    if latest_log_state and latest_log_time >= latest_lidar_time:
        state, action = latest_log_state
        return state, state not in {"IDLE", "WAIT", "STOP", "UNKNOWN", "MAIN"} or action not in {"STOP", "WAIT", "IDLE"}

    if latest_lidar_state:
        state, action = latest_lidar_state
        return state, state not in {"IDLE", "WAIT", "STOP", "UNKNOWN"} or action not in {"STOP", "WAIT", "IDLE"}

    return "IDLE", False


def _blocked_while_running_reply(state: str) -> str:
    return (
        f"현재 로봇이 {state} 상태로 이동 중이라 정지 명령만 받을 수 있어요. "
        "멈추려면 '동스비 멈춰'라고 말해 주세요."
    )


def _nvidia_llm_reply(message: str, system_prompt: str) -> str | None:
    api_key = os.getenv("NVIDIA_API_KEY") or os.getenv("NVIDIA_NIM_API_KEY")
    if not api_key:
        return None

    base_url = os.getenv("NVIDIA_BASE_URL", "https://integrate.api.nvidia.com/v1").rstrip("/")
    model = os.getenv("NVIDIA_MODEL", "google/gemma-4-31b-it")
    max_tokens = int(os.getenv("NVIDIA_MAX_TOKENS", "16384"))
    temperature = float(os.getenv("NVIDIA_TEMPERATURE", "1"))
    top_p = float(os.getenv("NVIDIA_TOP_P", "0.95"))
    enable_thinking = os.getenv("NVIDIA_ENABLE_THINKING", "true").lower() in {"1", "true", "yes", "on"}
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message},
        ],
        "chat_template_kwargs": {"enable_thinking": enable_thinking},
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
        "stream": False,
    }
    authorization = api_key if api_key.lower().startswith("bearer ") else f"Bearer {api_key}"
    request = urllib.request.Request(
        f"{base_url}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": authorization,
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            data = json.loads(response.read().decode("utf-8"))
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, OSError, TimeoutError, urllib.error.URLError):
        return None


def _process_llm_chat_locked(robot_id: str, chat: LlmChatIn) -> LlmChatOut:
    raw_message = chat.message.strip()
    command: StoredCommand | None = None
    display: DisplayState | None = None

    _ensure_robot(robot_id)
    motion_state, is_moving = _current_robot_motion_state(robot_id)
    if _is_wake_word_only(raw_message):
        _start_listening(robot_id, seconds=15)
        reply = "네, 말씀하세요."
        if chat.speak:
            _append_command_locked(robot_id, CommandIn(command="speak", value=reply))
        _save_state()
        return LlmChatOut(reply=reply, intent="wake", listening=True)

    listening = _is_listening(robot_id)
    message = _strip_wake_word(raw_message)
    intent, command_name = _classify_robot_intent(message)
    if intent == "chat":
        intent = _classify_daily_chat(message)

    if listening and intent == "chat":
        intent = "clarify"

    if is_moving and command_name != "stop":
        _llm_listen_until.pop(robot_id, None)
        reply = _blocked_while_running_reply(motion_state)
        if chat.speak:
            _append_command_locked(robot_id, CommandIn(command="speak", value=reply))
        _save_state()
        return LlmChatOut(
            reply=reply,
            intent="blocked_while_running",
            listening=False,
        )

    if command_name:
        command = _append_command_locked(
            robot_id,
            CommandIn(command=command_name, value=raw_message),
        )
        _llm_listen_until.pop(robot_id, None)
        if command_name == "show_status":
            current = _display_states.get(robot_id) or DisplayState(updated_at=_now_iso())
            current.screen = "report"
            current.report_until = (datetime.now(timezone.utc) + timedelta(seconds=12)).isoformat()
            current.updated_at = _now_iso()
            _display_states[robot_id] = current
            display = _display_state_for_response(robot_id, current)

    reply = _fallback_llm_reply(robot_id, chat.message, intent, command_name)
    if intent in {"daily_weather", "daily_outfit", "daily_time", "plant_question", "smalltalk", "chat"}:
        llm_reply = _nvidia_llm_reply(chat.message, _chat_system_prompt(robot_id))
        if llm_reply:
            reply = llm_reply

    if chat.speak and reply:
        _append_command_locked(robot_id, CommandIn(command="speak", value=reply))

    _save_state()
    return LlmChatOut(reply=reply, intent=intent, listening=_is_listening(robot_id), command=command, display=display)


_stt_model_cache: Any | None = None


def _transcribe_audio(audio_path: Path) -> str:
    global _stt_model_cache
    try:
        from faster_whisper import WhisperModel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is not installed on the server PC") from exc

    if _stt_model_cache is None:
        model_name = os.getenv("ONPLANT_STT_MODEL", "base")
        device = os.getenv("ONPLANT_STT_DEVICE", "cpu")
        compute_type = os.getenv("ONPLANT_STT_COMPUTE_TYPE", "int8")
        _stt_model_cache = WhisperModel(model_name, device=device, compute_type=compute_type)

    initial_prompt = os.getenv(
        "ONPLANT_STT_PROMPT",
        "동스비. 오늘 상태 어때. 최적 조도 찾아줘. 멈춰. 오늘 날씨 어때.",
    )
    segments, _info = _stt_model_cache.transcribe(
        str(audio_path),
        language="ko",
        vad_filter=True,
        beam_size=5,
        temperature=0,
        condition_on_previous_text=False,
        initial_prompt=initial_prompt,
    )
    text = " ".join(segment.text.strip() for segment in segments).strip()
    if not text:
        raise RuntimeError("STT returned empty text")
    return text


def _make_edge_tts_audio(text: str) -> Path | None:
    output_path = VOICE_DIR / f"tts_{uuid.uuid4().hex}.mp3"
    edge_tts_module = shutil.which("edge-tts")
    voice = os.getenv("ONPLANT_TTS_VOICE", "ko-KR-InJoonNeural")
    rate = os.getenv("ONPLANT_TTS_RATE", "+0%")
    pitch = os.getenv("ONPLANT_TTS_PITCH", "+0Hz")
    volume = os.getenv("ONPLANT_TTS_VOLUME", "+0%")
    command: list[str]

    if edge_tts_module:
        command = [
            edge_tts_module,
            "--voice",
            voice,
            "--rate",
            rate,
            "--pitch",
            pitch,
            "--volume",
            volume,
            "--text",
            text,
            "--write-media",
            str(output_path),
        ]
    else:
        command = [
            sys.executable,
            "-m",
            "edge_tts",
            "--voice",
            voice,
            "--rate",
            rate,
            "--pitch",
            pitch,
            "--volume",
            volume,
            "--text",
            text,
            "--write-media",
            str(output_path),
        ]

    try:
        subprocess.run(command, check=True, timeout=30)
    except Exception:
        return None
    return output_path if output_path.exists() else None


def _make_tts_audio(text: str) -> Path | None:
    edge_audio = _make_edge_tts_audio(text)
    if edge_audio:
        return edge_audio

    output_path = VOICE_DIR / f"tts_{uuid.uuid4().hex}.wav"

    if os.name == "nt":
        powershell = shutil.which("powershell.exe") or shutil.which("powershell")
        if not powershell:
            return None
        with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as text_file:
            text_file.write(text)
            text_path = Path(text_file.name)
        script = (
            "Add-Type -AssemblyName System.Speech; "
            f"$text = Get-Content -LiteralPath '{text_path}' -Raw -Encoding UTF8; "
            "$synth = New-Object System.Speech.Synthesis.SpeechSynthesizer; "
            "$synth.Rate = 0; "
            "$synth.Volume = 90; "
            f"$synth.SetOutputToWaveFile('{output_path}'); "
            "$synth.Speak($text); "
            "$synth.Dispose();"
        )
        try:
            subprocess.run([powershell, "-NoProfile", "-Command", script], check=True, timeout=25)
        finally:
            try:
                text_path.unlink()
            except OSError:
                pass
        return output_path if output_path.exists() else None

    espeak = shutil.which("espeak-ng")
    if not espeak:
        return None
    subprocess.run([espeak, "-v", "ko", "-w", str(output_path), text], check=True, timeout=25)
    return output_path if output_path.exists() else None


def _dummy_reading(robot_id: str) -> SensorReadingIn:

    return SensorReadingIn(
        robot_id=robot_id,
        lux=round(uniform(220.0, 720.0), 1),
        temperature=round(uniform(21.0, 26.0), 1),
        humidity=round(uniform(42.0, 62.0), 1),
        soil_moisture=round(uniform(34.0, 66.0), 1),
        source="dummy",
    )


_load_state()


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/dashboard")
@app.get("/live")
@app.get("/sensors")
@app.get("/logs")
@app.get("/control")
@app.get("/board")
@app.get("/admin")
@app.get("/kiosk")
def app_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/display")
def display_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "display.html")


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/register", response_model=UserPublic)
def register_user(user: UserCreate) -> UserPublic:
    with _lock:
        if user.username in _users:
            raise HTTPException(status_code=409, detail="username already exists")
        robot_id = f"{user.username}-robot"
        _robots[robot_id] = RobotPublic(
            robot_id=robot_id,
            name=f"{user.display_name}의 라즈봇",
            plant_name=user.plant_name,
            created_at=_now_iso(),
        )
        _configs[robot_id] = RobotConfig()
        _users[user.username] = {
            "username": user.username,
            "display_name": user.display_name,
            "password_hash": _hash_password(user.password),
            "robot_id": robot_id,
        }
        _save_state()
        return _user_public(user.username)


@app.post("/api/auth/login", response_model=UserPublic)
def login_user(login: LoginIn) -> UserPublic:
    with _lock:
        user = _users.get(login.username)
        if not user or user["password_hash"] != _hash_password(login.password):
            raise HTTPException(status_code=401, detail="invalid username or password")
        _ensure_robot(user["robot_id"])
        return _user_public(login.username)


@app.get("/api/robots", response_model=list[RobotPublic])
def list_robots() -> list[RobotPublic]:
    with _lock:
        return sorted(_robots.values(), key=lambda item: item.robot_id)


@app.post("/api/robots", response_model=RobotPublic)
def create_robot(robot: RobotCreate) -> RobotPublic:
    with _lock:
        if robot.robot_id in _robots:
            raise HTTPException(status_code=409, detail="robot_id already exists")
        public = RobotPublic(
            robot_id=robot.robot_id,
            name=robot.name,
            plant_name=robot.plant_name,
            camera_url=robot.camera_url,
            created_at=_now_iso(),
        )
        _robots[robot.robot_id] = public
        _configs[robot.robot_id] = RobotConfig(camera_url=robot.camera_url)
        _save_state()
        return public


@app.patch("/api/robots/{robot_id}", response_model=RobotPublic)
def update_robot(robot_id: str, robot: RobotUpdate) -> RobotPublic:
    with _lock:
        _ensure_robot(robot_id)
        current = _robots[robot_id]
        if robot.name is not None:
            current.name = robot.name
        if robot.plant_name is not None:
            current.plant_name = robot.plant_name
        if robot.plant_avatar is not None:
            current.plant_avatar = robot.plant_avatar
        if robot.camera_url is not None:
            current.camera_url = robot.camera_url
            _configs[robot_id].camera_url = robot.camera_url
        _save_state()
        return current


@app.get("/api/robots/{robot_id}/summary")
def robot_summary(robot_id: str) -> dict[str, Any]:
    with _lock:
        _ensure_robot(robot_id)
        latest = _latest_for(robot_id)
        last_seen = _robots[robot_id].last_seen
        online = _is_recent(last_seen, seconds=30)
        return {
            "robot": _robots[robot_id],
            "connection": {
                "online": online,
                "last_seen": last_seen,
                "stale_after_seconds": 30,
            },
            "latest": latest,
            "config": _configs[robot_id],
            "status": _status_from(latest, _configs[robot_id]),
            "history_count": len(_history.get(robot_id, [])),
            "command_count": len(_commands.get(robot_id, [])),
            "plant_profile": _plant_profile(),
            "display": _display_states.get(robot_id) or DisplayState(updated_at=_now_iso()),
        }


@app.post("/api/robots/{robot_id}/lidar", response_model=StoredLidarFrame)
def receive_lidar_frame(robot_id: str, frame: LidarFrameIn) -> StoredLidarFrame:
    with _lock:
        _ensure_robot(robot_id)
        stored = StoredLidarFrame(
            robot_id=robot_id,
            received_at=_now_iso(),
            **frame.model_dump(),
        )
        _lidar_latest[robot_id] = stored
        _robots[robot_id].last_seen = stored.received_at
        message = "전방 위험 감지" if frame.front_blocked or frame.danger or frame.emergency else "FSM 주행 상태 갱신"
        previous_log = _move_logs.get(robot_id, [])[-1] if _move_logs.get(robot_id) else None
        if (
            previous_log is None
            or previous_log.state != frame.state
            or previous_log.action != frame.action
            or previous_log.message != message
        ):
            _append_move_log_locked(
                robot_id,
                MoveLogIn(
                    state=frame.state,
                    action=frame.action,
                    message=message,
                    target_lux=frame.best_lux,
                    current_lux=frame.current_lux,
                    source=frame.source,
                ),
            )
        _save_state()
        return stored


@app.get("/api/robots/{robot_id}/lidar", response_model=StoredLidarFrame | None)
def latest_lidar_frame(robot_id: str) -> StoredLidarFrame | None:
    with _lock:
        return _lidar_latest.get(robot_id)


@app.post("/api/sensors", response_model=StoredReading)
def receive_sensor(reading: SensorReadingIn) -> StoredReading:
    global _next_sensor_id

    with _lock:
        _ensure_robot(reading.robot_id)
        stored = StoredReading(
            id=_next_sensor_id,
            robot_id=reading.robot_id,
            lux=reading.lux,
            temperature=reading.temperature,
            humidity=reading.humidity,
            soil_moisture=reading.soil_moisture,
            source=reading.source,
            received_at=_now_iso(),
        )
        should_store = _should_store_sensor_reading(reading.robot_id, stored)
        if should_store:
            _next_sensor_id += 1
            _history[reading.robot_id].append(stored)
        elif _history.get(reading.robot_id):
            stored = stored.model_copy(update={"id": _history[reading.robot_id][-1].id})
        _latest_readings[reading.robot_id] = stored
        _robots[reading.robot_id].last_seen = stored.received_at
        _save_state()
        return stored


@app.post("/api/sensors/dummy", response_model=StoredReading)
def create_dummy_sensor(robot_id: str = "raspbot-a") -> StoredReading:
    return receive_sensor(_dummy_reading(robot_id))


@app.get("/api/robots/{robot_id}/history", response_model=list[StoredReading])
def sensor_history(robot_id: str, limit: int = 100) -> list[StoredReading]:
    limit = max(1, min(limit, 500))
    with _lock:
        return list(_history.get(robot_id, []))[-limit:]


@app.delete("/api/robots/{robot_id}/history")
def clear_sensor_history(robot_id: str) -> dict[str, Any]:
    global _next_sensor_id

    with _lock:
        count = len(_history.get(robot_id, []))
        _history[robot_id].clear()
        if not any(_history.values()):
            _next_sensor_id = 1
        _save_state()
        return {"robot_id": robot_id, "cleared": count}


@app.get("/api/robots/{robot_id}/config", response_model=RobotConfig)
def get_robot_config(robot_id: str) -> RobotConfig:
    with _lock:
        _ensure_robot(robot_id)
        return _configs[robot_id]


@app.patch("/api/robots/{robot_id}/config", response_model=RobotConfig)
def update_robot_config(robot_id: str, config: RobotConfig) -> RobotConfig:
    with _lock:
        _ensure_robot(robot_id)
        _configs[robot_id] = config
        _robots[robot_id].camera_url = config.camera_url
        _save_state()
        return config


@app.post("/api/robots/{robot_id}/commands", response_model=StoredCommand)
def create_robot_command(robot_id: str, command: CommandIn) -> StoredCommand:
    with _lock:
        stored = _append_command_locked(robot_id, command)
        _save_state()
        return stored


@app.get("/api/robots/{robot_id}/commands", response_model=list[StoredCommand])
def list_robot_commands(robot_id: str, limit: int = 30) -> list[StoredCommand]:
    limit = max(1, min(limit, 100))
    with _lock:
        return list(_commands.get(robot_id, []))[-limit:]


@app.post("/api/robots/{robot_id}/llm/chat", response_model=LlmChatOut)
def llm_chat(robot_id: str, chat: LlmChatIn) -> LlmChatOut:
    with _lock:
        return _process_llm_chat_locked(robot_id, chat)


@app.post("/api/tts", response_model=TextToSpeechOut)
async def text_to_speech(tts: TextToSpeechIn) -> TextToSpeechOut:
    try:
        tts_path = await asyncio.to_thread(_make_tts_audio, tts.text)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"TTS failed: {exc}") from exc
    if not tts_path:
        raise HTTPException(status_code=500, detail="TTS output was not created")
    return TextToSpeechOut(audio_url=f"/voice_outputs/{tts_path.name}")


@app.post("/api/robots/{robot_id}/voice/chat", response_model=VoiceChatOut)
async def voice_chat(
    robot_id: str,
    audio: UploadFile = File(...),
    username: str = Form(default="demo"),
    phase: str = Form(default="direct"),
) -> VoiceChatOut:
    suffix = Path(audio.filename or "voice.wav").suffix or ".wav"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_audio:
        shutil.copyfileobj(audio.file, temp_audio)
        audio_path = Path(temp_audio.name)

    try:
        transcript = await asyncio.to_thread(_transcribe_audio, audio_path)
    except Exception as exc:
        if "STT returned empty text" in str(exc):
            return VoiceChatOut(transcript="", reply="", intent="no_speech", listening=False)
        raise HTTPException(status_code=500, detail=f"STT failed: {exc}") from exc
    finally:
        try:
            audio_path.unlink()
        except OSError:
            pass

    phase = phase.lower().strip()
    with _lock:
        if phase == "wake":
            if _looks_like_wake_word(transcript):
                _start_listening(robot_id, seconds=15)
                chat_result = LlmChatOut(
                    reply="네, 말씀하세요.",
                    intent="wake",
                    listening=True,
                )
            else:
                chat_result = LlmChatOut(
                    reply="",
                    intent="ignored",
                    listening=False,
                )
        elif phase == "command":
            if not _is_listening(robot_id):
                chat_result = LlmChatOut(
                    reply="",
                    intent="ignored",
                    listening=False,
                )
            else:
                chat_result = _process_llm_chat_locked(
                    robot_id,
                    LlmChatIn(message=transcript, username=username),
                )
                _llm_listen_until.pop(robot_id, None)
        else:
            chat_result = _process_llm_chat_locked(
                robot_id,
                LlmChatIn(message=transcript, username=username),
            )

    audio_url = None
    try:
        tts_path = await asyncio.to_thread(_make_tts_audio, chat_result.reply) if chat_result.reply else None
        if tts_path:
            audio_url = f"/voice_outputs/{tts_path.name}"
    except Exception as exc:
        print("TTS ERROR", exc)

    return VoiceChatOut(
        transcript=transcript,
        reply=chat_result.reply,
        intent=chat_result.intent,
        listening=chat_result.listening,
        command=chat_result.command,
        display=chat_result.display,
        audio_url=audio_url,
    )


@app.get("/api/board", response_model=list[BoardPost])
def list_board_posts(category: str | None = None) -> list[BoardPost]:
    with _lock:
        posts = list(_board_posts)
        if category and category != "전체":
            target = _normalize_board_category(category)
            posts = [post for post in posts if post.category == target]
        return posts


@app.post("/api/board", response_model=BoardPost)
def create_board_post(post: BoardPostIn) -> BoardPost:
    global _next_post_id

    with _lock:
        data = post.model_dump()
        data["category"] = _normalize_board_category(data.get("category"))
        stored = BoardPost(id=_next_post_id, created_at=_now_iso(), **data)
        _next_post_id += 1
        _board_posts.appendleft(stored)
        _save_state()
        return stored


@app.get("/api/board/{post_id}", response_model=BoardPost)
def get_board_post(post_id: int) -> BoardPost:
    with _lock:
        for post in _board_posts:
            if post.id == post_id:
                return post
        raise HTTPException(status_code=404, detail="post not found")


@app.patch("/api/board/{post_id}", response_model=BoardPost)
def update_board_post(post_id: int, update: BoardPostUpdate) -> BoardPost:
    with _lock:
        for index, post in enumerate(_board_posts):
            if post.id == post_id:
                patched = post.model_copy(
                    update={
                        **({"category": update.category} if update.category is not None else {}),
                        **({"title": update.title} if update.title is not None else {}),
                        **({"body": update.body} if update.body is not None else {}),
                        "updated_at": _now_iso(),
                    }
                )
                patched.category = _normalize_board_category(patched.category)
                _board_posts[index] = patched
                _save_state()
                return patched
        raise HTTPException(status_code=404, detail="post not found")


@app.delete("/api/board/{post_id}")
def delete_board_post(post_id: int) -> dict[str, int]:
    with _lock:
        remaining = [post for post in _board_posts if post.id != post_id]
        removed = len(_board_posts) - len(remaining)
        _board_posts.clear()
        _board_posts.extend(remaining)
        _save_state()
        return {"deleted": removed}


@app.get("/api/robots/{robot_id}/move-logs", response_model=list[StoredMoveLog])
def list_move_logs(robot_id: str, limit: int = 80) -> list[StoredMoveLog]:
    limit = max(1, min(limit, 200))
    with _lock:
        return list(_move_logs.get(robot_id, []))[-limit:]


@app.post("/api/robots/{robot_id}/move-logs", response_model=StoredMoveLog)
def create_move_log(robot_id: str, log: MoveLogIn) -> StoredMoveLog:
    with _lock:
        _ensure_robot(robot_id)
        stored = _append_move_log_locked(robot_id, log)
        _save_state()
        return stored


@app.delete("/api/robots/{robot_id}/activity")
def clear_robot_activity(robot_id: str) -> dict[str, Any]:
    with _lock:
        _ensure_robot(robot_id)
        move_count = len(_move_logs.get(robot_id, []))
        command_count = len(_commands.get(robot_id, []))
        _move_logs[robot_id].clear()
        _commands[robot_id].clear()
        _save_state()
        return {
            "robot_id": robot_id,
            "cleared_move_logs": move_count,
            "cleared_commands": command_count,
        }


@app.get("/api/robots/{robot_id}/display", response_model=DisplayState)
def get_display_state(robot_id: str) -> DisplayState:
    with _lock:
        _ensure_robot(robot_id)
        if robot_id not in _display_states:
            _display_states[robot_id] = DisplayState(updated_at=_now_iso())
        return _display_state_for_response(robot_id, _display_states[robot_id])


@app.post("/api/robots/{robot_id}/remote", response_model=DisplayState)
def remote_button(robot_id: str, remote: RemoteIn) -> DisplayState:
    with _lock:
        _ensure_robot(robot_id)
        current = _display_states.get(robot_id) or DisplayState(updated_at=_now_iso())
        if remote.key == "3":
            current.screen = "report"
            current.report_until = (datetime.now(timezone.utc) + timedelta(seconds=12)).isoformat()
        elif remote.key == "4":
            current.camera_visible = True
        elif remote.key == "5":
            current.camera_visible = False
        else:
            raise HTTPException(status_code=400, detail="unsupported remote key")
        current.updated_at = _now_iso()
        _display_states[robot_id] = current
        response = _display_state_for_response(robot_id, current)
        _append_command_locked(robot_id, CommandIn(command=f"remote-{remote.key}", value=response.screen))
        _save_state()
        return response


@app.get("/api/admin/users")
def admin_users() -> list[dict[str, str]]:
    with _lock:
        return [
            {
                "username": user["username"],
                "display_name": user.get("display_name", user["username"]),
                "robot_id": user.get("robot_id", ""),
                "role": user.get("role", "admin" if user["username"] == "admin" else "user"),
            }
            for user in sorted(_users.values(), key=lambda item: item["username"])
        ]


@app.post("/api/admin/link-robot", response_model=UserPublic)
def admin_link_robot(payload: dict[str, str]) -> UserPublic:
    username = payload.get("username", "").strip()
    code = payload.get("link_code", "").strip().upper()
    robot_id = payload.get("robot_id", "").strip()
    with _lock:
        if username not in _users:
            raise HTTPException(status_code=404, detail="user not found")
        if code:
            for robot in _robots.values():
                if robot.link_code.upper() == code:
                    robot_id = robot.robot_id
                    break
        if not robot_id:
            raise HTTPException(status_code=400, detail="robot_id or link_code required")
        _ensure_robot(robot_id)
        _users[username]["robot_id"] = robot_id
        _robots[robot_id].assigned_username = username
        _save_state()
        return _user_public(username)


@app.get("/api/sensors/latest", response_model=StoredReading | None)
def latest_sensor_compat() -> StoredReading | None:
    with _lock:
        return _latest_for("raspbot-a")


@app.get("/api/sensors/history", response_model=list[StoredReading])
def sensor_history_compat(limit: int = 100) -> list[StoredReading]:
    return sensor_history("raspbot-a", limit)


@app.delete("/api/sensors/history")
def clear_sensor_history_compat() -> dict[str, Any]:
    return clear_sensor_history("raspbot-a")
