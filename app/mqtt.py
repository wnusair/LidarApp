"""
MQTT client manager for MTI (Miami Telemetry Interface).

Subscribes to:
    <MQTT_DEVICE_TOPIC_PREFIX>/<device_id>/data   (default: devices/+/data)

Accepted payload formats
------------------------
Single reading (flat dict):
    {"sensor_name": "CPU_Temp", "value": 45.2, "unit": "C"}

Batch of readings:
    [
        {"sensor_name": "CPU_Temp", "value": 45.2, "unit": "C"},
        {"sensor_name": "Humidity",  "value": 62.1, "unit": "%"}
    ]

Batch envelope (explicit device_id overrides topic-derived value):
    {
        "device_id": "pi_lab_01",
        "readings": [
            {"sensor_name": "CPU_Temp", "value": 45.2, "unit": "C"}
        ]
    }

On every inbound message, readings are:
  1. Persisted to the ``sensor_data`` table via SQLAlchemy.
  2. Broadcast to the WebSocket ``dashboard`` room so live charts update
     without polling.
"""
import json
import logging
import ssl
import threading

logger = logging.getLogger(__name__)

try:
    import paho.mqtt.client as paho
    _PAHO_AVAILABLE = True
except ImportError:  # pragma: no cover
    _PAHO_AVAILABLE = False
    paho = None


def _make_client(client_id):
    """Instantiate a paho Client compatible with both v1 and v2 APIs."""
    # paho-mqtt 2.x introduced CallbackAPIVersion; v1 API still works but
    # raises a deprecation warning unless the version is declared explicitly.
    try:
        from paho.mqtt.client import CallbackAPIVersion  # paho-mqtt >= 2.0
        return paho.Client(
            callback_api_version=CallbackAPIVersion.VERSION1,
            client_id=client_id,
            protocol=paho.MQTTv311,
        )
    except (ImportError, AttributeError):
        # paho-mqtt 1.x
        return paho.Client(client_id=client_id, protocol=paho.MQTTv311)


class MQTTManager:
    """Manages the MQTT client lifecycle within the Flask application context.

    Designed to mirror Flask extension conventions: instantiate once at module
    level, call ``init_app(app, socketio)`` inside the application factory.
    """

    def __init__(self):
        self._client = None
        self._app = None
        self._socketio = None
        self._topic_subscribe = 'devices/+/data'

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def init_app(self, app, socketio):
        """Wire the manager to a Flask app and the SocketIO instance.

        Reads all MQTT_* values from ``app.config``, creates the paho client,
        applies credentials/TLS, and starts the network loop in a daemon thread.
        """
        if not _PAHO_AVAILABLE:
            logger.error(
                'paho-mqtt is not installed.  '
                'Run: pip install paho-mqtt>=1.6.1'
            )
            return

        self._app = app
        self._socketio = socketio

        cfg = app.config
        broker_host = cfg.get('MQTT_BROKER_HOST', 'localhost')
        broker_port = int(cfg.get('MQTT_BROKER_PORT', 1883))
        client_id = cfg.get('MQTT_CLIENT_ID', 'mti_server')
        username = cfg.get('MQTT_USERNAME')
        password = cfg.get('MQTT_PASSWORD')
        use_tls = cfg.get('MQTT_USE_TLS', False)
        ca_certs = cfg.get('MQTT_TLS_CA_CERTS')
        topic_prefix = cfg.get('MQTT_DEVICE_TOPIC_PREFIX', 'devices')

        self._topic_subscribe = f'{topic_prefix}/+/data'

        client = _make_client(client_id)

        if username:
            client.username_pw_set(username, password)

        if use_tls:
            tls_kwargs = {'cert_reqs': ssl.CERT_REQUIRED}
            if ca_certs:
                tls_kwargs['ca_certs'] = ca_certs
            client.tls_set(**tls_kwargs)

        client.on_connect = self._on_connect
        client.on_disconnect = self._on_disconnect
        client.on_message = self._on_message

        self._client = client

        # Start the network loop in a daemon thread so the Flask process
        # does not block on the broker connection.
        thread = threading.Thread(
            target=self._connect_loop,
            args=(broker_host, broker_port),
            daemon=True,
            name='mqtt-manager',
        )
        thread.start()

        logger.info(
            'MQTT manager started – broker %s:%d, topic %s',
            broker_host, broker_port, self._topic_subscribe,
        )

    @property
    def client(self):
        """The underlying paho MQTT client (None until ``init_app`` called)."""
        return self._client

    def publish(self, topic, payload, qos=0, retain=False):
        """Publish a message to the broker.

        Args:
            topic:   MQTT topic string.
            payload: dict (JSON-encoded automatically) or str/bytes.
            qos:     Quality-of-Service level (0, 1 or 2).
            retain:  Whether the broker should retain the message.
        """
        if self._client is None:
            raise RuntimeError('MQTTManager: client not initialised – call init_app first')
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        self._client.publish(topic, payload, qos=qos, retain=retain)

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _connect_loop(self, host, port):
        """Connect to the broker and block in the paho network loop.

        ``loop_forever`` handles reconnections automatically; the thread is
        a daemon so it does not prevent process exit.
        """
        try:
            self._client.connect(host, port, keepalive=60)
            self._client.loop_forever(retry_first_connection=True)
        except Exception as exc:  # pragma: no cover
            logger.error('MQTT connection error: %s', exc)

    def _on_connect(self, client, userdata, flags, rc):
        """Callback: broker acknowledged the connection."""
        if rc == 0:
            logger.info('MQTT connected – subscribing to %s', self._topic_subscribe)
            client.subscribe(self._topic_subscribe, qos=1)
        else:
            logger.error('MQTT connection refused – return code %d', rc)

    def _on_disconnect(self, client, userdata, rc):
        """Callback: disconnected from broker (paho auto-reconnects via loop_forever)."""
        if rc != 0:
            logger.warning('MQTT unexpected disconnect (rc=%d) – will reconnect', rc)

    def _on_message(self, client, userdata, message):
        """Callback: inbound message from a subscribed topic."""
        topic = message.topic

        try:
            payload = json.loads(message.payload.decode('utf-8'))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            logger.warning('MQTT bad payload on topic %s: %s', topic, exc)
            return

        # Derive device_id from topic segment: devices/<device_id>/data
        topic_parts = topic.split('/')
        device_id = topic_parts[1] if len(topic_parts) >= 3 else 'unknown'

        # Normalise payload to a flat list of reading dicts.
        if isinstance(payload, list):
            # Already a list of readings.
            readings = payload
        elif isinstance(payload, dict) and 'readings' in payload:
            # Envelope format – device_id at envelope level takes precedence.
            device_id = payload.get('device_id', device_id)
            readings = payload['readings']
        else:
            # Single reading dict.
            readings = [payload]

        # All DB work must happen inside the application context.
        with self._app.app_context():
            self._persist_and_broadcast(device_id, readings)

    def _persist_and_broadcast(self, device_id, readings):
        """Persist a list of reading dicts and emit a WebSocket event.

        Args:
            device_id: Identifier of the originating device.
            readings:  List of dicts with keys sensor_name, value, unit, status.
        """
        from .extensions import db
        from .models import SensorData

        saved = []
        for item in readings:
            sensor_name = item.get('sensor_name')
            value = item.get('value')
            if not sensor_name or value is None:
                logger.debug('MQTT skipping malformed reading: %s', item)
                continue
            try:
                value = float(value)
            except (TypeError, ValueError):
                continue

            unit = item.get('unit', '')
            status = item.get('status', 'OK')
            # Per-reading device_id override (allows mixed-device batches).
            reading_device_id = item.get('device_id', device_id)

            record = SensorData(
                device_id=reading_device_id,
                sensor_name=sensor_name,
                value=value,
                unit=unit,
                status=status,
            )
            db.session.add(record)
            db.session.flush()
            saved.append(record.to_dict())

        if saved:
            db.session.commit()
            # Push to all WebSocket clients watching the dashboard room.
            self._socketio.emit(
                'sensor_data',
                {'readings': saved},
                room='dashboard',
                namespace='/',
            )
            logger.debug(
                'MQTT: persisted %d reading(s) from device_id=%s',
                len(saved), device_id,
            )
        else:
            logger.debug('MQTT: no valid readings in message from device_id=%s', device_id)


# Module-level singleton – import this in extensions and __init__.py.
mqtt_manager = MQTTManager()
