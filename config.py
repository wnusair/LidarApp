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


class DevelopmentConfig(Config):
    """Development configuration."""
    DEBUG = True


class ProductionConfig(Config):
    """Production configuration."""
    DEBUG = False


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
