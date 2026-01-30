"""
Configuration settings for the MTI (Miami Telemetry Interface) application.
"""
import os

basedir = os.path.abspath(os.path.dirname(__file__))


class Config:
    """Base configuration."""
    SECRET_KEY = os.environ.get('SECRET_KEY')
    
    # SECURITY: Validate SECRET_KEY is set and sufficiently strong
    @staticmethod
    def init_app(app):
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
    
    # WebSocket configuration - parse comma-separated origins into a list
    @staticmethod
    def parse_cors_origins(origins_str):
        """Parse CORS origins from environment variable."""
        if not origins_str or origins_str == '*':
            return '*'
        # Split by comma and strip whitespace
        return [origin.strip() for origin in origins_str.split(',') if origin.strip()]
    
    SOCKETIO_CORS_ALLOWED_ORIGINS = parse_cors_origins.__func__(
        os.environ.get('SOCKETIO_CORS_ORIGINS', '*')
    )


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
