#!/usr/bin/env python3
"""
MTI MQTT Device Client
======================
General-purpose MQTT publisher that can run on any Linux system including
Raspberry Pi.  Reads sensors, formats the payload, and publishes to:

    devices/<DEVICE_ID>/data

The MTI server subscribes to this topic and persists readings automatically.

Quick start (Pi)
----------------
1.  Install dependency (once):
        pip install paho-mqtt

2.  Copy this file to your device, e.g.:
        scp scripts/mqtt_device.py pi@<pi-ip>:~/mti_device.py

3.  Create a config file   ~/.mti_device.env   on the Pi (see ENV VARS below).

4.  Run:
        python3 mti_device.py

ENV VARS (read from environment or ~/.mti_device.env)
------------------------------------------------------
MQTT_BROKER_HOST    Broker hostname / IP       (required)
MQTT_BROKER_PORT    Broker port                (default 1883 / 8883 with TLS)
MQTT_DEVICE_ID      Unique name for this unit  (default: hostname)
MQTT_USERNAME       Broker username            (optional)
MQTT_PASSWORD       Broker password            (optional)
MQTT_USE_TLS        true/false                 (default false)
MQTT_TLS_CA_CERTS   Path to CA cert bundle     (optional, uses system roots)
MQTT_TOPIC_PREFIX   Topic prefix               (default devices)
MQTT_INTERVAL       Seconds between readings   (default 0.05 = 50 ms)
MQTT_QOS            MQTT QoS level 0/1/2       (default 1)

Sensor configuration
---------------------
Edit SENSORS list below.  Each entry is a callable that returns:
    {"sensor_name": str, "value": float, "unit": str, "status": str}

Pi-specific helpers (_read_cpu_temp, _read_cpu_load, etc.) are included.
They fall back gracefully on non-Pi hardware.
"""

import json
import logging
import os
import platform
import signal
import socket
import ssl
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%H:%M:%S',
)
logger = logging.getLogger('mti.device')


# ---------------------------------------------------------------------------
# Load .env file (if present) – no external dependency required
# ---------------------------------------------------------------------------
def _load_dotenv(path=None):
    """Load key=value pairs from a file into os.environ (no-op if missing)."""
    candidates = [
        path,
        Path.home() / '.mti_device.env',
        Path(__file__).parent / '.env',
    ]
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            with open(candidate) as fh:
                for line in fh:
                    line = line.strip()
                    if line and not line.startswith('#') and '=' in line:
                        key, _, value = line.partition('=')
                        os.environ.setdefault(key.strip(), value.strip())
            logger.debug('Loaded env from %s', candidate)
            return


_load_dotenv()


# ---------------------------------------------------------------------------
# Configuration (all from env or sensible defaults)
# ---------------------------------------------------------------------------
BROKER_HOST = os.environ.get('MQTT_BROKER_HOST', '')
BROKER_PORT = int(os.environ.get('MQTT_BROKER_PORT', 0))
DEVICE_ID = os.environ.get('MQTT_DEVICE_ID', socket.gethostname())
USERNAME = os.environ.get('MQTT_USERNAME')
PASSWORD = os.environ.get('MQTT_PASSWORD')
USE_TLS = os.environ.get('MQTT_USE_TLS', 'false').lower() == 'true'
CA_CERTS = os.environ.get('MQTT_TLS_CA_CERTS')
TOPIC_PREFIX = os.environ.get('MQTT_TOPIC_PREFIX', 'devices')
INTERVAL = float(os.environ.get('MQTT_INTERVAL', 0.05))
QOS = int(os.environ.get('MQTT_QOS', 1))

# Default port: 8883 when TLS enabled, 1883 otherwise
if BROKER_PORT == 0:
    BROKER_PORT = 8883 if USE_TLS else 1883


# ---------------------------------------------------------------------------
# Pi / generic sensor helpers
# ---------------------------------------------------------------------------

def _read_cpu_temp():
    """Read CPU temperature (works on Raspberry Pi and most Linux SBCs)."""
    thermal_zone = Path('/sys/class/thermal/thermal_zone0/temp')
    if thermal_zone.is_file():
        raw = thermal_zone.read_text().strip()
        return round(int(raw) / 1000.0, 2)
    # macOS / non-Pi fallback
    return None


def _read_cpu_load():
    """Return 1-minute CPU load average (0-100 scale, works on all POSIX)."""
    try:
        load_1min = os.getloadavg()[0]
        cpu_count = os.cpu_count() or 1
        return round((load_1min / cpu_count) * 100.0, 2)
    except (AttributeError, OSError):
        return None


def _read_memory_used_pct():
    """Return used memory percentage (reads /proc/meminfo if available)."""
    meminfo = Path('/proc/meminfo')
    if meminfo.is_file():
        info = {}
        for line in meminfo.read_text().splitlines():
            parts = line.split()
            if len(parts) >= 2:
                info[parts[0].rstrip(':')] = int(parts[1])
        total = info.get('MemTotal', 0)
        available = info.get('MemAvailable', 0)
        if total:
            return round((1 - available / total) * 100.0, 2)
    return None


def _read_disk_used_pct(path='/'):
    """Return used disk percentage for the given mount point."""
    try:
        stat = os.statvfs(path)
        total = stat.f_blocks * stat.f_frsize
        free = stat.f_bfree * stat.f_frsize
        if total:
            return round((1 - free / total) * 100.0, 2)
    except (AttributeError, OSError):
        pass
    return None


def _status_from_thresholds(value, warn=80.0, error=95.0):
    """Map a percentage value to OK / WARNING / ERROR status."""
    if value is None:
        return 'UNKNOWN'
    if value >= error:
        return 'ERROR'
    if value >= warn:
        return 'WARNING'
    return 'OK'


# ---------------------------------------------------------------------------
# SENSORS list
# ---------------------------------------------------------------------------
# Add, remove or extend entries here.  Each callable returns a dict or None
# (if the reading is unavailable on this hardware).

def _sensor_cpu_temp():
    v = _read_cpu_temp()
    if v is None:
        return None
    return {
        'sensor_name': 'CPU_Temp',
        'value': v,
        'unit': 'C',
        'status': _status_from_thresholds(v, warn=70, error=85),
    }


def _sensor_cpu_load():
    v = _read_cpu_load()
    if v is None:
        return None
    return {
        'sensor_name': 'CPU_Load',
        'value': v,
        'unit': '%',
        'status': _status_from_thresholds(v, warn=80, error=95),
    }


def _sensor_memory():
    v = _read_memory_used_pct()
    if v is None:
        return None
    return {
        'sensor_name': 'Memory_Used',
        'value': v,
        'unit': '%',
        'status': _status_from_thresholds(v, warn=80, error=95),
    }


def _sensor_disk():
    v = _read_disk_used_pct('/')
    if v is None:
        return None
    return {
        'sensor_name': 'Disk_Used',
        'value': v,
        'unit': '%',
        'status': _status_from_thresholds(v, warn=75, error=90),
    }


# Master list – add your custom sensor functions here.
SENSORS = [
    _sensor_cpu_temp,
    _sensor_cpu_load,
    _sensor_memory,
    _sensor_disk,
    # Example custom sensor:
    # lambda: {'sensor_name': 'Soil_Moisture', 'value': read_adc_channel(0), 'unit': '%'},
]


# ---------------------------------------------------------------------------
# MQTT client setup
# ---------------------------------------------------------------------------

def _make_client(device_id):
    """Create a paho Client compatible with both v1 and v2 APIs."""
    import paho.mqtt.client as paho_lib

    try:
        from paho.mqtt.client import CallbackAPIVersion
        return paho_lib.Client(
            callback_api_version=CallbackAPIVersion.VERSION1,
            client_id=f'mti_device_{device_id}',
            protocol=paho_lib.MQTTv311,
        )
    except (ImportError, AttributeError):
        return paho_lib.Client(
            client_id=f'mti_device_{device_id}',
            protocol=paho_lib.MQTTv311,
        )


def build_client():
    """Build, configure and return an MQTT client (not yet connected)."""
    try:
        import paho.mqtt.client  # noqa: F401
    except ImportError:
        logger.error(
            'paho-mqtt is not installed.  Run: pip install paho-mqtt'
        )
        sys.exit(1)

    client = _make_client(DEVICE_ID)

    if USERNAME:
        client.username_pw_set(USERNAME, PASSWORD)

    if USE_TLS:
        tls_kwargs = {'cert_reqs': ssl.CERT_REQUIRED}
        if CA_CERTS:
            tls_kwargs['ca_certs'] = CA_CERTS
        client.tls_set(**tls_kwargs)
        logger.info('TLS enabled (CA: %s)', CA_CERTS or 'system roots')

    def on_connect(client, userdata, flags, rc):
        if rc == 0:
            logger.info('Connected to broker %s:%d', BROKER_HOST, BROKER_PORT)
        else:
            logger.error('Connection refused – return code %d', rc)

    def on_disconnect(client, userdata, rc):
        if rc != 0:
            logger.warning('Disconnected unexpectedly (rc=%d) – reconnecting…', rc)

    def on_publish(client, userdata, mid):
        logger.debug('Message %d acknowledged by broker', mid)

    client.on_connect = on_connect
    client.on_disconnect = on_disconnect
    client.on_publish = on_publish

    return client


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def collect_readings():
    """Poll all sensor functions and return a list of valid reading dicts."""
    readings = []
    for sensor_fn in SENSORS:
        try:
            result = sensor_fn()
            if result is not None:
                readings.append(result)
        except Exception as exc:
            logger.warning('Sensor %s raised: %s', getattr(sensor_fn, '__name__', '?'), exc)
    return readings


def publish_readings(client, readings):
    """Publish a batch of readings to the device topic."""
    if not readings:
        logger.debug('No readings this cycle – nothing to publish')
        return

    topic = f'{TOPIC_PREFIX}/{DEVICE_ID}/data'
    payload = json.dumps({
        'device_id': DEVICE_ID,
        'readings': readings,
    })
    result = client.publish(topic, payload, qos=QOS)
    result.wait_for_publish()
    logger.info(
        'Published %d reading(s) → %s  (mid=%d)',
        len(readings), topic, result.mid,
    )


def main():
    """Entry point – validate config, connect, and loop."""
    if not BROKER_HOST:
        logger.error(
            'MQTT_BROKER_HOST is not set.  '
            'Create ~/.mti_device.env or export the variable.'
        )
        sys.exit(1)

    print('=' * 60)
    print('MTI MQTT Device Client')
    print('=' * 60)
    print(f'  Device ID   : {DEVICE_ID}')
    print(f'  Broker      : {BROKER_HOST}:{BROKER_PORT}')
    print(f'  TLS         : {USE_TLS}')
    print(f'  Topic prefix: {TOPIC_PREFIX}')
    print(f'  Interval    : {INTERVAL}s')
    print(f'  Sensors     : {len(SENSORS)}')
    print('-' * 60)

    client = build_client()

    # Graceful shutdown on Ctrl-C / SIGTERM.
    _running = [True]

    def _stop(signum, frame):
        logger.info('Shutdown signal received')
        _running[0] = False
        client.disconnect()

    signal.signal(signal.SIGINT, _stop)
    signal.signal(signal.SIGTERM, _stop)

    # Connect (blocking, no auto-reconnect at this point).
    client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
    client.loop_start()

    try:
        while _running[0]:
            readings = collect_readings()
            publish_readings(client, readings)
            time.sleep(INTERVAL)
    finally:
        client.loop_stop()
        logger.info('MTI device client stopped.')


if __name__ == '__main__':
    main()
