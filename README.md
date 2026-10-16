# OnPlant Server

<p align="center">
  <strong>OnPlant 반려식물 로봇의 데이터와 제어 요청을 연결하는 백엔드</strong><br/>
  Raspberry Pi와 웹 대시보드 사이에서 센서·로봇 상태를 전달하고 관리합니다.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3.x-3776AB?logo=python&logoColor=white" alt="Python"/>
  <img src="https://img.shields.io/badge/FastAPI-API-009688?logo=fastapi&logoColor=white" alt="FastAPI"/>
  <img src="https://img.shields.io/badge/MySQL-Database-4479A1?logo=mysql&logoColor=white" alt="MySQL"/>
  <img src="https://img.shields.io/badge/Status-Developing-orange" alt="Developing"/>
</p>

## 프로젝트 소개

OnPlant Server는 Raspberry Pi 로봇과 웹 대시보드가 주고받는 데이터를 처리하는 백엔드입니다. 센서 측정값과 로봇 제어·설정 정보를 API로 제공하고, 운영 데이터를 MySQL에 저장합니다.

| 항목 | 내용 |
|---|---|
| 프로젝트 | OnPlant 반려식물 로봇 |
| 담당 영역 | API 서버 및 데이터 관리 |
| 주요 기술 | Python, FastAPI, SQLAlchemy, MySQL |
| 화면 | FastAPI에서 제공하는 정적 웹 대시보드 |

## 시스템 흐름

```text
Raspberry Pi ── 센서 데이터 / 제어 요청 ──▶ FastAPI Server ──▶ MySQL
                                                │
                                                └── 정적 웹 대시보드
```

## 주요 기능

- 로봇 센서 데이터 수신 및 최신 측정값 조회
- 로봇 상태 요약, 화면 표시 정보 및 설정 조회·수정
- 로봇 명령과 이동 이력 관리
- 사용자 로그인 및 게시판 API
- 프런트 화면에서 사용할 정적 리소스 제공
- 음성 인식·응답 기능에서 사용하는 서버 측 의존성 구성

## 데이터 저장 정책

- MySQL을 런타임 데이터 저장소로 사용합니다.
- 최초 MySQL 기반 실행 시 기존 `onplant_state.json` 데이터를 가져오며, 가져오기 완료 정보는 `onplant_migrations`에서 관리합니다.
- 최신 센서 데이터는 수신할 때마다 `latest_sensor_readings`에 반영합니다.
- 센서 이력은 주기 저장과 의미 있는 상태 변화 기준으로 기록합니다.
- LiDAR 포인트와 프레임은 DB에 쌓지 않고 최신 프레임만 메모리에서 유지합니다.

## 기술 구성

- **API:** FastAPI, Uvicorn, Pydantic
- **Database:** MySQL, SQLAlchemy, PyMySQL
- **Web:** HTML, CSS, JavaScript
- **Integration:** Raspberry Pi 센서·로봇 클라이언트

## 시작하기

### 1. 환경 준비

Python과 MySQL을 설치하고, 저장소 루트에서 가상환경을 만든 뒤 패키지를 설치합니다.

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

### 2. 환경 변수 설정

`.env.example`을 `.env`로 복사하고 로컬 MySQL 접속 정보와 필요한 API 키를 입력합니다. 실제 비밀번호와 키가 담긴 `.env`는 저장소에 올리지 않습니다.

MySQL 데이터베이스와 계정은 서버 실행 전에 준비해야 합니다.

### 3. 서버 실행

```powershell
python -m uvicorn main:app --host 0.0.0.0 --port 5050
```

브라우저에서 `http://127.0.0.1:5050`에 접속합니다. 다른 기기에서 테스트할 때는 서버 PC의 IP 주소와 방화벽 설정을 확인하세요.

## 주요 API

| Method | Endpoint | 설명 |
|---|---|---|
| GET | `/api/health` | 서버 상태 확인 |
| POST | `/api/auth/login` | 로그인 |
| POST | `/api/sensors` | 센서 데이터 수신 |
| GET | `/api/sensors/latest` | 최신 센서 데이터 조회 |
| GET | `/api/robots/raspbot-a/summary` | 로봇 요약 정보 |
| GET / PATCH | `/api/robots/raspbot-a/config` | 로봇 설정 조회·수정 |
| GET / POST | `/api/robots/raspbot-a/commands` | 로봇 명령 조회·전달 |
| GET / POST | `/api/robots/raspbot-a/move-logs` | 이동 이력 조회·기록 |
| GET / POST | `/api/board` | 게시판 조회·작성 |

## 프로젝트 구조

```text
.
├─ main.py                 # API 라우트와 애플리케이션 진입점
├─ database.py             # DB 연결 및 테이블 초기화
├─ requirements.txt        # Python 의존성
├─ .env.example            # 환경 변수 템플릿
└─ static/                 # 대시보드 및 디스플레이 웹 리소스
```

## 보안 및 운영 메모

- `.env`에는 실제 DB 비밀번호와 API 키를 저장하고 Git에 커밋하지 않습니다.
- 서버와 Raspberry Pi 양쪽의 로봇·카메라 키 설정이 일치해야 합니다.
- 외부 기기에서 접속할 때는 방화벽에서 필요한 포트만 허용합니다.

---

OnPlant 프로젝트의 서버 영역을 기록하고 공유하기 위한 저장소입니다.
