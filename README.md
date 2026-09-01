# OnPlant Server

FastAPI + MySQL server for the OnPlant dashboard and `raspbot-a`.

## Storage behavior

- MySQL is the only runtime persistence layer. A database error is logged and is not hidden by a JSON fallback.
- `onplant_state.json` is imported once on the first MySQL-backed startup. The marker is stored in `onplant_migrations`; the JSON file is retained for verification.
- The latest sensor sample is updated on every POST (normally every 5 seconds) in `latest_sensor_readings`.
- Historical `sensor_readings` follow the application policy: normally one row per 10 minutes, plus meaningful state-band changes or a large lux change after at least one minute.
- LiDAR points/frames are kept only as the newest in-memory frame and are not stored in MySQL.

Core tables are `users`, `robots`, `robot_configs`, `display_states`, `sensor_readings`, `move_logs`, `command_logs`, and `board_posts`. The two operational tables are `latest_sensor_readings` and `onplant_migrations`.

## Configuration

Copy `.env.example` to `.env` and set the local MySQL credentials:

```dotenv
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=onplant
DB_PASSWORD=replace-this
DB_NAME=onplant
ONPLANT_DATA=onplant_state.json
```

`DATABASE_URL=mysql+pymysql://...` remains supported for existing installations. If it is set, it takes precedence over the individual `DB_*` variables. Do not commit `.env`.

The MySQL database and account must exist before startup. The application creates and validates its tables and adds columns needed by newer builds.

## Windows setup and run

```powershell
cd D:\Onplant_Server
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
.\start_server.ps1
```

Equivalent direct command:

```powershell
.\.venv\Scripts\python.exe -m uvicorn main:app --host 0.0.0.0 --port 5050
```

Open `http://127.0.0.1:5050`. Other devices on the LAN should use `http://SERVER_IP:5050`; Windows Firewall must allow inbound TCP 5050.

## Main checks

```text
GET  /api/health
POST /api/auth/login
POST /api/sensors
GET  /api/sensors/latest
GET  /api/robots/raspbot-a/summary
GET  /api/robots/raspbot-a/display
GET/PATCH /api/robots/raspbot-a/config
GET/POST  /api/robots/raspbot-a/commands
GET/POST  /api/board
GET/POST  /api/robots/raspbot-a/move-logs
```

Sensor POST example:

```json
{
  "robot_id": "raspbot-a",
  "lux": 850,
  "temperature": 24.5,
  "humidity": 50,
  "soil_moisture": 35,
  "source": "raspberry-pi"
}
```
