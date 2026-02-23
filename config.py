"""
Configuration settings for the MTI (Miami Telemetry Interface) application.
"""
import os
from dotenv import load_dotenv

# Load environment variables from a .env file if present. This ensures
# scripts that directly import the app (not just run.py) pick up values.
load_dotenv()

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY')
    
    @staticmethod
    def init_app(app):
        """Validate SECRET_KEY is set and sufficiently strong."""
        if not app.config['SECRET_KEY']:
            raise ValueError(
                "SECRET_KEY is not set. Set the SECRET_KEY environment variable. "
                "Generate one with: python -c \"import secrets; print(secrets.token_hex(32))\""
            )
        if len(app.config['SECRET_KEY']) < 16:
            raise ValueError("SECRET_KEY is too short. Use at least 16 characters.")
    
    SQLALCHEMY_DATABASE_URI = os.environ.get('DATABASE_URL') or \
        'sqlite:///' + os.path.join(basedir, 'db.sqlite3')
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    
    @staticmethod
    def parse_cors_origins(origins_str):
        """Parse CORS origins from environment variable."""
        if not origins_str or origins_str == '*':
            return '*'
        return [origin.strip() for origin in origins_str.split(',') if origin.strip()]
    
    SOCKETIO_CORS_ALLOWED_ORIGINS = parse_cors_origins.__func__(
        os.environ.get('SOCKETIO_CORS_ORIGINS', '*')
    )

    # --- MQTT device integration ---
    # Set MQTT_ENABLED=true in .env to activate the embedded MQTT subscriber.
    MQTT_ENABLED = os.environ.get('MQTT_ENABLED', 'false').lower() == 'true'
    MQTT_BROKER_HOST = os.environ.get('MQTT_BROKER_HOST', 'localhost')
    MQTT_BROKER_PORT = int(os.environ.get('MQTT_BROKER_PORT', 1883))
    # Unique client identifier for this server instance.
    MQTT_CLIENT_ID = os.environ.get('MQTT_CLIENT_ID', 'mti_server')
    # Broker credentials (leave blank for anonymous brokers).
    MQTT_USERNAME = os.environ.get('MQTT_USERNAME')
    MQTT_PASSWORD = os.environ.get('MQTT_PASSWORD')
    # TLS – set MQTT_USE_TLS=true and point MQTT_TLS_CA_CERTS at your CA bundle.
    MQTT_USE_TLS = os.environ.get('MQTT_USE_TLS', 'false').lower() == 'true'
    MQTT_TLS_CA_CERTS = os.environ.get('MQTT_TLS_CA_CERTS')
    # Topic prefix – server subscribes to <prefix>/+/data.
    MQTT_DEVICE_TOPIC_PREFIX = os.environ.get('MQTT_DEVICE_TOPIC_PREFIX', 'devices')

    # --- Disk usage monitoring (Storage Monitor panel) ---
    # Comma-separated server paths shown in panel 5.
    # Example: DISK_MONITOR_PATHS=/,/home,/var/log,/srv/app
    DISK_MONITOR_PATHS = [
        p.strip()
        for p in os.environ.get('DISK_MONITOR_PATHS', '/').split(',')
        if p.strip()
    ]


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False
    SOCKETIO_CORS_ALLOWED_ORIGINS = Config.parse_cors_origins(
        os.environ.get(
            'SOCKETIO_CORS_ORIGINS', 
            'https://mti.wnusair.org,https://www.mti.wnusair.org'
        )
    )


class TestingConfig(Config):
    """Testing configuration."""
    TESTING = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    WTF_CSRF_ENABLED = False


config = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig,
    'default': DevelopmentConfig
}
