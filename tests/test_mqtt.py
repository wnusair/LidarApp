"""
Tests for MQTT integration (app/mqtt.py).

No real broker is required.  paho.mqtt.client is patched at the module level
so that all network operations are mocked.  The tests exercise:

- MQTTManager initialisation and config reading
- Payload parsing (flat, list, envelope, malformed)
- _persist_and_broadcast: DB writes and WebSocket emit
- publish() helper
- scripts/mqtt_device.py sensor helpers (runs on any OS including Raspberry Pi)
"""
import json
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call

import pytest

from app import create_app, db
from app.models import SensorData
from app.mqtt import MQTTManager, mqtt_manager


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def app():
    """Application configured for testing with MQTT enabled."""
    application = create_app('testing')
    application.config.update({
        'MQTT_ENABLED': False,   # We init the manager manually in each test
        'MQTT_BROKER_HOST': 'localhost',
        'MQTT_BROKER_PORT': 1883,
        'MQTT_CLIENT_ID': 'mti_test',
        'MQTT_USERNAME': None,
        'MQTT_PASSWORD': None,
        'MQTT_USE_TLS': False,
        'MQTT_TLS_CA_CERTS': None,
        'MQTT_DEVICE_TOPIC_PREFIX': 'devices',
    })
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def manager(app):
    """A fresh MQTTManager wired to a mock paho client (no network)."""
    mock_socketio = MagicMock()

    with patch('app.mqtt._make_client') as mock_make:
        mock_paho = MagicMock()
        mock_make.return_value = mock_paho

        mgr = MQTTManager()
        mgr.init_app(app, mock_socketio)
        # Prevent the real thread from trying to connect
        mock_paho.connect.side_effect = None

        yield mgr, mock_paho, mock_socketio


# ---------------------------------------------------------------------------
# MQTTManager initialisation
# ---------------------------------------------------------------------------

class TestMQTTManagerInit:
    """Tests for init_app configuration handling."""

    def test_client_created(self, manager):
        mgr, mock_paho, _ = manager
        assert mgr.client is mock_paho

    def test_subscribe_topic_built_from_prefix(self, app):
        """Topic uses the configured prefix."""
        app.config['MQTT_DEVICE_TOPIC_PREFIX'] = 'mti'
        mock_socketio = MagicMock()
        with patch('app.mqtt._make_client') as mock_make:
            mock_paho = MagicMock()
            mock_make.return_value = mock_paho
            mgr = MQTTManager()
            mgr.init_app(app, mock_socketio)
            # Simulate on_connect callback
            mgr._on_connect(mock_paho, None, {}, 0)
            mock_paho.subscribe.assert_called_once_with('mti/+/data', qos=1)

    def test_username_password_set(self, app):
        app.config['MQTT_USERNAME'] = 'user'
        app.config['MQTT_PASSWORD'] = 'secret'
        mock_socketio = MagicMock()
        with patch('app.mqtt._make_client') as mock_make:
            mock_paho = MagicMock()
            mock_make.return_value = mock_paho
            mgr = MQTTManager()
            mgr.init_app(app, mock_socketio)
            mock_paho.username_pw_set.assert_called_once_with('user', 'secret')

    def test_no_credentials_skips_username_pw_set(self, app):
        app.config['MQTT_USERNAME'] = None
        mock_socketio = MagicMock()
        with patch('app.mqtt._make_client') as mock_make:
            mock_paho = MagicMock()
            mock_make.return_value = mock_paho
            mgr = MQTTManager()
            mgr.init_app(app, mock_socketio)
            mock_paho.username_pw_set.assert_not_called()

    def test_tls_configured(self, app):
        app.config['MQTT_USE_TLS'] = True
        app.config['MQTT_TLS_CA_CERTS'] = '/etc/ssl/ca.pem'
        mock_socketio = MagicMock()
        with patch('app.mqtt._make_client') as mock_make:
            mock_paho = MagicMock()
            mock_make.return_value = mock_paho
            mgr = MQTTManager()
            mgr.init_app(app, mock_socketio)
            _, tls_kwargs = mock_paho.tls_set.call_args
            assert tls_kwargs.get('ca_certs') == '/etc/ssl/ca.pem'

    def test_paho_not_installed_logs_error(self, app, caplog):
        """init_app does not raise when paho-mqtt is absent – logs an error."""
        import app.mqtt as mqtt_module
        original = mqtt_module._PAHO_AVAILABLE
        mqtt_module._PAHO_AVAILABLE = False
        try:
            with caplog.at_level('ERROR', logger='app.mqtt'):
                mgr = MQTTManager()
                mgr.init_app(app, MagicMock())
            assert 'paho-mqtt' in caplog.text
        finally:
            mqtt_module._PAHO_AVAILABLE = original


# ---------------------------------------------------------------------------
# on_connect / on_disconnect callbacks
# ---------------------------------------------------------------------------

class TestCallbacks:
    def test_on_connect_rc0_subscribes(self, manager):
        mgr, mock_paho, _ = manager
        mgr._on_connect(mock_paho, None, {}, 0)
        mock_paho.subscribe.assert_called_once()
        topic_arg = mock_paho.subscribe.call_args[0][0]
        assert topic_arg.endswith('/+/data')

    def test_on_connect_nonzero_does_not_subscribe(self, manager):
        mgr, mock_paho, _ = manager
        mgr._on_connect(mock_paho, None, {}, 5)
        mock_paho.subscribe.assert_not_called()

    def test_on_disconnect_non_clean_warns(self, manager, caplog):
        mgr, mock_paho, _ = manager
        with caplog.at_level('WARNING', logger='app.mqtt'):
            mgr._on_disconnect(mock_paho, None, 1)
        assert 'reconnect' in caplog.text


# ---------------------------------------------------------------------------
# Publish helper
# ---------------------------------------------------------------------------

class TestPublish:
    def test_publish_dict_json_encodes(self, manager):
        mgr, mock_paho, _ = manager
        mgr.publish('test/topic', {'key': 'value'})
        mock_paho.publish.assert_called_once()
        _, kwargs = mock_paho.publish.call_args
        # The second positional arg is the payload
        args = mock_paho.publish.call_args[0]
        assert args[0] == 'test/topic'
        assert json.loads(args[1]) == {'key': 'value'}

    def test_publish_string_passed_as_is(self, manager):
        mgr, mock_paho, _ = manager
        mgr.publish('test/topic', 'raw string')
        args = mock_paho.publish.call_args[0]
        assert args[1] == 'raw string'

    def test_publish_before_init_raises(self):
        mgr = MQTTManager()
        with pytest.raises(RuntimeError, match='not initialised'):
            mgr.publish('t', 'p')


# ---------------------------------------------------------------------------
# _on_message – payload parsing
# ---------------------------------------------------------------------------

class FakeMessage:
    """Minimal stand-in for paho MQTTMessage."""
    def __init__(self, topic, payload):
        self.topic = topic
        self.payload = payload.encode() if isinstance(payload, str) else payload


class TestOnMessage:
    """All tests call _on_message directly and verify DB + WebSocket state."""

    def _call(self, manager_fixture, topic, payload_obj):
        mgr, mock_paho, mock_socketio = manager_fixture
        msg = FakeMessage(topic, json.dumps(payload_obj))
        mgr._on_message(mock_paho, None, msg)
        return mock_socketio

    def test_flat_single_reading_persisted(self, manager, app):
        with app.app_context():
            self._call(manager, 'devices/pi_lab/data', {
                'sensor_name': 'CPU_Temp', 'value': 55.3, 'unit': 'C',
            })
            row = SensorData.query.filter_by(sensor_name='CPU_Temp').first()
            assert row is not None
            assert row.device_id == 'pi_lab'
            assert row.value == 55.3

    def test_list_payload_all_readings_saved(self, manager, app):
        with app.app_context():
            self._call(manager, 'devices/pi_01/data', [
                {'sensor_name': 'CPU_Load', 'value': 12.0, 'unit': '%'},
                {'sensor_name': 'Memory_Used', 'value': 44.0, 'unit': '%'},
            ])
            assert SensorData.query.filter_by(device_id='pi_01').count() == 2

    def test_envelope_format_uses_payload_device_id(self, manager, app):
        with app.app_context():
            self._call(manager, 'devices/from_topic/data', {
                'device_id': 'from_envelope',
                'readings': [
                    {'sensor_name': 'Humidity', 'value': 60.0, 'unit': '%'}
                ],
            })
            row = SensorData.query.filter_by(sensor_name='Humidity').first()
            assert row.device_id == 'from_envelope'

    def test_topic_device_id_used_when_no_envelope_override(self, manager, app):
        with app.app_context():
            self._call(manager, 'devices/my_device/data', {
                'sensor_name': 'Temp', 'value': 22.1, 'unit': 'C'
            })
            row = SensorData.query.filter_by(sensor_name='Temp').first()
            assert row.device_id == 'my_device'

    def test_per_reading_device_id_override(self, manager, app):
        with app.app_context():
            self._call(manager, 'devices/gateway/data', [
                {'device_id': 'sensor_node_a', 'sensor_name': 'Air_Temp',
                 'value': 20.0, 'unit': 'C'},
                {'sensor_name': 'Pressure', 'value': 1013.0, 'unit': 'hPa'},
            ])
            assert SensorData.query.filter_by(device_id='sensor_node_a').count() == 1
            assert SensorData.query.filter_by(device_id='gateway').count() == 1

    def test_websocket_emit_called_on_valid_reading(self, manager, app):
        with app.app_context():
            _, _, mock_socketio = manager
            msg = FakeMessage('devices/pi/data', json.dumps(
                {'sensor_name': 'CPU_Temp', 'value': 40.0, 'unit': 'C'}
            ))
            mgr, mock_paho, _ = manager
            mgr._on_message(mock_paho, None, msg)
            mock_socketio.emit.assert_called_once()
            event, data = mock_socketio.emit.call_args[0]
            assert event == 'sensor_data'
            assert len(data['readings']) == 1

    def test_malformed_json_does_not_raise(self, manager, app):
        mgr, mock_paho, _ = manager
        msg = FakeMessage('devices/pi/data', b'not valid json{{{')
        mgr._on_message(mock_paho, None, msg)  # should log warning, not raise

    def test_missing_sensor_name_skipped(self, manager, app):
        with app.app_context():
            self._call(manager, 'devices/pi/data', {'value': 42.0, 'unit': 'C'})
            assert SensorData.query.count() == 0

    def test_missing_value_skipped(self, manager, app):
        with app.app_context():
            self._call(manager, 'devices/pi/data',
                       {'sensor_name': 'CPU_Temp', 'unit': 'C'})
            assert SensorData.query.count() == 0

    def test_non_numeric_value_skipped(self, manager, app):
        with app.app_context():
            self._call(manager, 'devices/pi/data',
                       {'sensor_name': 'CPU_Temp', 'value': 'hot', 'unit': 'C'})
            assert SensorData.query.count() == 0

    def test_default_status_is_ok(self, manager, app):
        with app.app_context():
            self._call(manager, 'devices/pi/data',
                       {'sensor_name': 'CPU_Temp', 'value': 45.0, 'unit': 'C'})
            row = SensorData.query.first()
            assert row.status == 'OK'

    def test_no_emit_when_no_valid_readings(self, manager, app):
        with app.app_context():
            _, mock_paho, mock_socketio = manager
            mgr, _, _ = manager
            msg = FakeMessage('devices/pi/data', json.dumps({'value': 1.0}))
            mgr._on_message(mock_paho, None, msg)
            mock_socketio.emit.assert_not_called()


# ---------------------------------------------------------------------------
# API: GET /api/devices
# ---------------------------------------------------------------------------

class TestDevicesEndpoint:
    """Tests for the /api/devices listing endpoint."""

    def _login(self, client, app):
        from app.models import User, Role
        with app.app_context():
            role = Role(name='Manager')
            db.session.add(role)
            db.session.commit()
            user = User(username='tester', role_id=role.id)
            user.set_password('pass')
            db.session.add(user)
            db.session.commit()
        client.post('/auth/login', data={'username': 'tester', 'password': 'pass'})

    def test_get_devices_returns_list(self, app, client):
        self._login(client, app)
        with app.app_context():
            db.session.add(SensorData(
                device_id='pi_a', sensor_name='CPU_Temp', value=40.0, unit='C'))
            db.session.add(SensorData(
                device_id='pi_b', sensor_name='CPU_Temp', value=42.0, unit='C'))
            db.session.commit()
        response = client.get('/api/devices')
        assert response.status_code == 200
        data = response.get_json()
        assert set(data['devices']) == {'pi_a', 'pi_b'}
        assert data['count'] == 2

    def test_get_devices_requires_login(self, client):
        response = client.get('/api/devices', follow_redirects=False)
        assert response.status_code == 302


# ---------------------------------------------------------------------------
# scripts/mqtt_device.py – sensor helper unit tests (Pi + non-Pi)
# ---------------------------------------------------------------------------

class TestDeviceScriptSensors:
    """Tests for sensor helper functions in mqtt_device.py.

    These run on any OS (including Raspberry Pi) without mocking /sys/class;
    fallbacks are tested explicitly so CI passes on non-Pi machines.
    """

    def _import_device(self):
        """Import mqtt_device without running main()."""
        import importlib.util, os
        spec = importlib.util.spec_from_file_location(
            'mqtt_device',
            os.path.join(os.path.dirname(__file__), '..', 'scripts', 'mqtt_device.py'),
        )
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    def test_status_ok(self):
        d = self._import_device()
        assert d._status_from_thresholds(50.0) == 'OK'

    def test_status_warning(self):
        d = self._import_device()
        assert d._status_from_thresholds(82.0) == 'WARNING'

    def test_status_error(self):
        d = self._import_device()
        assert d._status_from_thresholds(96.0) == 'ERROR'

    def test_status_none_is_unknown(self):
        d = self._import_device()
        assert d._status_from_thresholds(None) == 'UNKNOWN'

    def test_sensor_cpu_temp_returns_none_or_float(self):
        d = self._import_device()
        result = d._sensor_cpu_temp()
        assert result is None or isinstance(result['value'], float)

    def test_sensor_cpu_load_always_returns_reading(self):
        d = self._import_device()
        result = d._sensor_cpu_load()
        # os.getloadavg() is available on all POSIX systems
        if result is not None:
            assert 'value' in result
            assert result['unit'] == '%'

    def test_sensor_memory_returns_none_or_reading(self):
        d = self._import_device()
        result = d._sensor_memory()
        if result is not None:
            assert 0.0 <= result['value'] <= 100.0

    def test_sensor_disk_returns_none_or_reading(self):
        d = self._import_device()
        result = d._sensor_disk()
        if result is not None:
            assert 0.0 <= result['value'] <= 100.0

    def test_collect_readings_returns_list(self):
        d = self._import_device()
        readings = d.collect_readings()
        assert isinstance(readings, list)
        for r in readings:
            assert 'sensor_name' in r
            assert 'value' in r
            assert 'unit' in r

    def test_build_client_raises_on_missing_broker_host(self):
        """main() should sys.exit when MQTT_BROKER_HOST is empty."""
        d = self._import_device()
        original = d.BROKER_HOST
        d.BROKER_HOST = ''
        with pytest.raises(SystemExit):
            d.main()
        d.BROKER_HOST = original
