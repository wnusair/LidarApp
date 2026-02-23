"""
Sensor data models for telemetry storage.
"""
from datetime import datetime, timezone
from ..extensions import db


class SensorData(db.Model):
    """Sensor telemetry data model."""
    __tablename__ = 'sensor_data'

    id = db.Column(db.Integer, primary_key=True)
    timestamp = db.Column(db.DateTime, default=lambda: datetime.now(timezone.utc), index=True, nullable=False)
    # device_id identifies the physical device that produced the reading.
    # Nullable for backward-compatibility with existing rows written before
    # MQTT integration was added.
    device_id = db.Column(db.String(64), nullable=True, index=True, default='unknown')
    sensor_name = db.Column(db.String(64), nullable=False, index=True)
    value = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), nullable=False)
    status = db.Column(db.String(20), default='OK')

    def __repr__(self):
        return f'<SensorData {self.device_id}/{self.sensor_name}: {self.value}{self.unit}>'

    def to_dict(self):
        """Convert sensor data to dictionary for JSON serialization."""
        return {
            'id': self.id,
            'timestamp': self.timestamp.isoformat(),
            'device_id': self.device_id or 'unknown',
            'sensor_name': self.sensor_name,
            'value': self.value,
            'unit': self.unit,
            'status': self.status
        }
