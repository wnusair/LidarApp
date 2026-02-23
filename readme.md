# Miami Telemetry Interface

## File Structure

```
app/
  blueprints/
    admin/
    api/
    auth/
    dashboard/
    game/
    websocket/
  models/
    user_models.py        # User, Role
    sensor_models.py      # SensorData (includes device_id)
    permission_models.py  # RolePermission, DEFAULT_PERMISSIONS
  static/
    css/
    js/                   # dashboard.js (Chart.js, WebSocket client)
  templates/
  mqtt.py                 # MQTT subscriber manager
scripts/
  mqtt_device.py          # Device-side MQTT publisher (run on Pi or any device)
  mock_data_stream.py     # Development-only fake data generator
  seed_database.py
  reset_passwords.py
tests/
  test_mqtt.py            # MQTT integration tests (broker-free, runs on Pi too)
  test_routes.py
  test_permissions.py
  test_config.py
  test_edge_cases.py
  test_app.py
config.py
run.py
```

## Nomenclature

- Models use PascalCase: `SensorData`, `RolePermission`
- Routes use snake_case: `grid_view()`, `get_sensor_data()`
- Database tables use snake_case: `sensor_data`, `role_permissions`
- Blueprints registered with `_bp` suffix: `admin_bp`, `api_bp`
- Templates organized by blueprint in `templates/{blueprint}/`

## Comment Style

Docstrings on all modules, classes, and public functions. Inline comments only for non-obvious logic. Routes have single-line docstrings describing purpose. Models include field-level comments for permissions.

## Code Organization

Application factory pattern in `app/__init__.py`. Extensions initialized in `extensions.py` to avoid circular imports. MQTT manager in `app/mqtt.py` mirrors Flask extension conventions. Blueprints keep routes and logic separate. Decorators like `@login_required` and `@manager_required` enforce access control. Config loaded from environment via `python-dotenv`.

---

## Setup

### Environment Variables

Create a `.env` file in the project root:

```env
SECRET_KEY=your-secret-key-here
FLASK_CONFIG=development
DATABASE_URL=sqlite:///db.sqlite3
SOCKETIO_CORS_ORIGINS=*

# MQTT (leave MQTT_ENABLED=false for local dev without a broker)
MQTT_ENABLED=false
MQTT_BROKER_HOST=localhost
MQTT_BROKER_PORT=1883
MQTT_CLIENT_ID=mti_server
MQTT_USERNAME=
MQTT_PASSWORD=
MQTT_USE_TLS=false
MQTT_TLS_CA_CERTS=
MQTT_DEVICE_TOPIC_PREFIX=devices
```

Generate secret key:
```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

### Initialize Database

```bash
python scripts/seed_database.py
```

Creates 5 roles (Manager, Engineer, Operator, Investor, Audit), sets default permissions, generates admin user with random password.

### Run Development Server

```bash
python run.py
```

Runs on `http://localhost:5000` with WebSocket support.

---

## MQTT Device Integration

Real devices publish sensor readings over MQTT. The server subscribes and persists readings automatically — the same pipeline used by the dashboard.

### How it works

```
Device (Pi / any hardware)          MTI Server
──────────────────────────          ─────────────────────────────────────
mqtt_device.py                      app/mqtt.py  (MQTTManager)
   │                                   │
   │  devices/<device_id>/data  →      │  _on_message()
   │  {"device_id":"pi_01",            │     ├─ parse JSON
   │   "readings":[                    │     ├─ INSERT sensor_data rows
   │     {"sensor_name":"CPU_Temp",    │     └─ emit('sensor_data') → WebSocket
   │      "value":45.2,               │                                │
   │      "unit":"C"}                 │                         dashboard clients
   │   ]}                             │
```

### Topic structure

```
devices/<device_id>/data
```

`<device_id>` is any string that uniquely identifies the physical device (e.g. hostname). All readings from a device share the same topic.

### Payload formats

All three formats are accepted:

**Single reading:**
```json
{"sensor_name": "CPU_Temp", "value": 45.2, "unit": "C"}
```

**Array of readings:**
```json
[
  {"sensor_name": "CPU_Temp",    "value": 45.2, "unit": "C"},
  {"sensor_name": "CPU_Load",    "value": 23.0, "unit": "%"},
  {"sensor_name": "Memory_Used", "value": 61.8, "unit": "%"}
]
```

**Envelope (recommended):**
```json
{
  "device_id": "pi_lab_01",
  "readings": [
    {"sensor_name": "CPU_Temp", "value": 45.2, "unit": "C", "status": "OK"}
  ]
}
```

`status` is optional and defaults to `"OK"`. Per-reading `device_id` override also works to multiplex a gateway publishing for multiple downstream sensors.

---

### Setting up a local Mosquitto broker

Install and start Mosquitto on the MTI server:

```bash
sudo apt install mosquitto mosquitto-clients -y
sudo systemctl enable mosquitto
sudo systemctl start mosquitto
```

Verify it is running:
```bash
mosquitto_sub -t "devices/#" -v
```

Enable MQTT in `.env`:
```env
MQTT_ENABLED=true
MQTT_BROKER_HOST=localhost
```

Restart the MTI server.

---

### Securing the broker (production)

Create a password file and restrict anonymous access:

```bash
sudo mosquitto_passwd -c /etc/mosquitto/passwd mti_server
sudo mosquitto_passwd /etc/mosquitto/passwd pi_lab_01
```

Create `/etc/mosquitto/conf.d/mti.conf`:
```
listener 8883
cafile   /etc/mosquitto/certs/ca.crt
certfile /etc/mosquitto/certs/server.crt
keyfile  /etc/mosquitto/certs/server.key
require_certificate false

allow_anonymous false
password_file /etc/mosquitto/passwd
```

Restart Mosquitto:
```bash
sudo systemctl restart mosquitto
```

Update the server `.env`:
```env
MQTT_BROKER_PORT=8883
MQTT_USERNAME=mti_server
MQTT_PASSWORD=<server-password>
MQTT_USE_TLS=true
MQTT_TLS_CA_CERTS=/etc/mosquitto/certs/ca.crt
```

---

### Connecting a Raspberry Pi

**Step 1 – Install dependency (once per Pi):**
```bash
pip install paho-mqtt
```

**Step 2 – Copy the device client to the Pi:**
```bash
scp scripts/mqtt_device.py pi@<pi-ip>:~/mti_device.py
```

**Step 3 – Create `~/.mti_device.env` on the Pi:**
```env
MQTT_BROKER_HOST=mti.wnusair.org
MQTT_BROKER_PORT=8883
MQTT_DEVICE_ID=pi_lab_01
MQTT_USERNAME=pi_lab_01
MQTT_PASSWORD=<device-password>
MQTT_USE_TLS=true
MQTT_TLS_CA_CERTS=/home/pi/certs/ca.crt
MQTT_INTERVAL=1.0
```

Copy the broker CA certificate to the Pi:
```bash
scp /etc/mosquitto/certs/ca.crt pi@<pi-ip>:~/certs/ca.crt
```

**Step 4 – Run:**
```bash
python3 ~/mti_device.py
```

Output confirms the connection and each publish cycle:
```
============================================================
MTI MQTT Device Client
============================================================
  Device ID   : pi_lab_01
  Broker      : mti.wnusair.org:8883
  TLS         : True
  Topic prefix: devices
  Interval    : 1.0s
  Sensors     : 4
------------------------------------------------------------
12:00:01 [INFO] Connected to broker mti.wnusair.org:8883
12:00:01 [INFO] Published 4 reading(s) → devices/pi_lab_01/data  (mid=1)
```

**Step 5 – Run as a systemd service (recommended for production):**

Create `/etc/systemd/system/mti-device.service`:
```ini
[Unit]
Description=MTI MQTT Device Client
After=network-online.target
Wants=network-online.target

[Service]
ExecStart=/usr/bin/python3 /home/pi/mti_device.py
WorkingDirectory=/home/pi
Restart=always
RestartSec=5
User=pi
EnvironmentFile=/home/pi/.mti_device.env

[Install]
WantedBy=multi-user.target
```

Enable:
```bash
sudo systemctl daemon-reload
sudo systemctl enable mti-device
sudo systemctl start mti-device
```

---

### Adding custom sensors to the device client

Open `scripts/mqtt_device.py` and add a function to the `SENSORS` list:

```python
def _sensor_soil_moisture():
    # example: read from ADC channel 0
    value = read_adc(channel=0)
    return {
        'sensor_name': 'Soil_Moisture',
        'value': round(value, 2),
        'unit': '%',
        'status': 'OK' if value < 80 else 'WARNING',
    }

SENSORS = [
    _sensor_cpu_temp,
    _sensor_cpu_load,
    _sensor_memory,
    _sensor_disk,
    _sensor_soil_moisture,   # <-- added
]
```

Any function that returns `None` is silently skipped — useful for optional hardware.

---

### Connecting additional devices

Repeat Steps 1–5 on each new device, using a unique `MQTT_DEVICE_ID`. No server-side changes are needed. After the first message arrives, the device appears in:

- `GET /api/devices` — lists all device IDs that have reported data
- Dashboard Panel 1 — live sensor feed (data arrives via WebSocket)
- `GET /api/sensor-data` — historical data (filterable by `sensor_name`)

---

## Role Permissions

5 roles with hierarchical permissions:

- Investor: Panels 1–2 only (live feed, KPIs)
- Audit: Panels 1–3, export data, view access logs
- Operator: All 4 panels, no export
- Engineer: All panels, export, edit data
- Manager: Full access, admin panel, user management

Configurable per-role via admin interface at `/admin/permissions`.

---

## Features

### Authentication

Login at `/auth/login`. Logout at `/auth/logout`. Passwords hashed with `werkzeug.security`. Session management via Flask-Login.

### Dashboard

4-panel grid at `/dashboard/`:

1. Live sensor feed with Chart.js line charts
2. Current status KPIs (readings count, sensor count, avg value, status summary)
3. Historical logs (time-range filtering)
4. Device health (VR game embed + camera feed)

Each panel has fullscreen toggle. Data auto-refreshes every 50ms. WebSocket updates for real-time streaming. MQTT readings arrive via the `sensor_data` WebSocket event so charts update immediately without frontend changes.

### Admin Panel

Manager-only routes at `/admin/`:

- `/admin/users` — create, delete, reset passwords
- `/admin/permissions` — configure role permissions via checkboxes

### API Endpoints

REST API at `/api/`:

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/api/sensor-data` | login | Query sensor data (filters: `sensor_name`, `hours`, `limit`) |
| GET | `/api/sensor-data/latest` | login | Latest reading per sensor |
| GET | `/api/sensor-data/stats` | login | Aggregate stats for KPIs |
| GET | `/api/devices` | login | List distinct device IDs |
| GET | `/api/export` | login + export perm | Download XLSX |
| POST | `/api/ingest` | none | Insert readings from external sources (accepts `device_id`) |

### WebSocket Events

Real-time bidirectional communication:

Server emits:
- `sensor_data` — new reading(s) arrived (from MQTT or any source)

Server handles:
- `connect` / `disconnect` — client tracking
- `join_room` / `leave_room` — room management
- `panel_update` — targeted data push
- `ping_latency` — latency measurement

Demo page at `/ws/demo` for testing WebSocket connectivity.

### Game Integration

itch.io embed proxy at `/game/frame`. Fetches game HTML server-side, rewrites URLs to bypass X-Frame-Options restrictions. Login required.

### Data Export

Excel export with openpyxl formatting. Columns auto-sized. Filename includes timestamp. Respects user export permission.

---

## Scripts

### seed_database.py

Full database initialization with roles, permissions, and admin user. Generates secure random passwords.

### mqtt_device.py

Device-side MQTT publisher. Runs on any Linux system including Raspberry Pi. Reads CPU temperature, load, memory, and disk usage by default. Extend the `SENSORS` list for custom hardware. Connects over TLS with broker authentication for production. See [MQTT Device Integration](#mqtt-device-integration) above.

### mock_data_stream.py

**Development only.** Simulates sensor telemetry by writing random values directly to the database. Use when no physical devices or broker is available:

```bash
python scripts/mock_data_stream.py
```

Generates 6 sensor readings per second (Arm_Servo_1, Arm_Servo_2, Motor_Temp, Motor_RPM, Battery_Voltage, System_Load).

### reset_passwords.py

```bash
# Reset single user
python scripts/reset_passwords.py --user alice --password NewPass123!

# Reset all users to random passwords
python scripts/reset_passwords.py --all --random --length 16
```

### websocket_client_app.py

Standalone WebSocket test client. Flask app on port 5001. Tests latency, stress testing, message broadcasting. DELETE WHEN DONE TESTING.

---

## Testing

pytest configuration in `pytest.ini`. Tests use in-memory SQLite. MQTT tests mock the paho broker — no running broker needed. All tests run on the server or on a Raspberry Pi.

### Run All Tests

```bash
pytest
```

### Run MQTT Tests Only

```bash
pytest tests/test_mqtt.py -v
```

### Run Specific Test File

```bash
pytest tests/test_routes.py
pytest tests/test_permissions.py
```

### Run with Coverage

```bash
pytest --cov=app --cov-report=html
```

Test files:
- `test_mqtt.py` — MQTTManager init, payload parsing, DB writes, WebSocket emit, sensor helpers, device endpoint (36 tests)
- `test_routes.py` — all HTTP endpoints (auth, admin, API, dashboard)
- `test_permissions.py` — role-based access control (tests all 5 roles)
- `test_config.py` — environment configuration
- `test_edge_cases.py` — error handling, edge conditions
- `test_app.py` — app factory, extensions

---

## CLI Commands

```bash
flask seed_roles      # Seed roles
flask seed_admin      # Create admin user
flask shell           # Interactive shell with models loaded
```

---

## Deployment

### Production Config

```env
FLASK_CONFIG=production
SOCKETIO_CORS_ORIGINS=https://mti.wnusair.org,https://www.mti.wnusair.org
MQTT_ENABLED=true
MQTT_BROKER_HOST=localhost
MQTT_BROKER_PORT=8883
MQTT_USERNAME=mti_server
MQTT_PASSWORD=<server-password>
MQTT_USE_TLS=true
MQTT_TLS_CA_CERTS=/etc/mosquitto/certs/ca.crt
```

### Run with Gunicorn

```bash
gunicorn -k eventlet -w 1 -b 0.0.0.0:5000 run:app
```

Single worker with eventlet required for WebSocket support.

---

## Database Schema

4 core tables:

- `users` — id, username, password_hash, role_id
- `roles` — id, name
- `role_permissions` — id, role_id, 8 boolean permission fields
- `sensor_data` — id, timestamp, **device_id**, sensor_name, value, unit, status

`device_id` is nullable for backward-compatibility with existing rows. New rows from MQTT or the updated `/api/ingest` endpoint always populate it.

**Migrate an existing database:**
```bash
flask db migrate -m "add device_id to sensor_data"
flask db upgrade
```

Foreign keys: `User.role_id → Role.id`, `RolePermission.role_id → Role.id`

---

## Frontend

Chart.js for live/historical charts. Socket.IO client for WebSocket. Vanilla JS, no framework. Miami University brand colors (red `#C3142D`, black `#000000`, gray `#757575`). Responsive grid layout. Fullscreen panel mode with ESC key exit.

---

## Security

- Password hashing via werkzeug
- SECRET_KEY validation at startup
- Role-based route decorators
- CSRF protection (can be disabled for testing)
- Login required on all dashboard/admin routes
- MQTT broker-level auth: username/password + TLS (see [Securing the broker](#securing-the-broker-production))
- `/api/ingest` has no HTTP auth (intended for trusted-network IoT devices; prefer MQTT + TLS for production)

---

## Error Handling

404/403 errors return flash messages. Validation errors on user creation. Permission checks return 403 with descriptive message. Database commit failures rolled back. MQTT connection errors logged without crashing the server; paho auto-reconnects.

---

## Monitoring

Connected client count tracked in memory. WebSocket latency via ping/pong. Sensor `status` field (OK/WARNING/ERROR) based on value thresholds. `GET /api/devices` shows all reporting device IDs.

---

## What This App Does

Receives sensor telemetry from physical MQTT devices (Raspberry Pi or any hardware) or via `POST /api/ingest`, stores in SQLite/PostgreSQL, displays on a real-time dashboard with role-based access, exports to Excel, streams live updates via WebSocket, embeds VR visualization, enforces granular permissions per role, manages users via admin interface.

---

## Removing Test Code

Delete these when testing is complete:

1. `app/blueprints/websocket/routes.py` lines marked `DELETE WHEN DONE TESTING`
2. `app/templates/websocket/demo.html`
3. `scripts/websocket_client_app.py`
4. WebSocket nav link in `app/templates/base.html`

Keep core WebSocket handlers: `connect`, `disconnect`, `join_room`, `leave_room`, `panel_update`, `ping_latency`, `sensor_data`.
