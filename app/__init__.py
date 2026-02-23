"""
Application factory for MTI (Miami Telemetry Interface).
"""
from flask import Flask
from config import config
from .extensions import db, login_manager, migrate, socketio
from .mqtt import mqtt_manager


def create_app(config_name='default'):
    """Create and configure the Flask application."""
    app = Flask(__name__)
    app.config.from_object(config[config_name])

    config_class = config[config_name]
    if hasattr(config_class, 'init_app'):
        config_class.init_app(app)

    db.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)

    cors_origins = app.config.get('SOCKETIO_CORS_ALLOWED_ORIGINS', '*')
    socketio.init_app(app, cors_allowed_origins=cors_origins, async_mode='threading')

    # Start the MQTT subscriber only when explicitly enabled.  This keeps
    # development setups working without a running broker.
    if app.config.get('MQTT_ENABLED', False):
        mqtt_manager.init_app(app, socketio)

    from .blueprints.auth import auth_bp
    from .blueprints.admin import admin_bp
    from .blueprints.dashboard import dashboard_bp
    from .blueprints.api import api_bp
    from .blueprints.websocket import websocket_bp
    from .blueprints.game import game_bp

    app.register_blueprint(auth_bp, url_prefix='/auth')
    app.register_blueprint(admin_bp, url_prefix='/admin')
    app.register_blueprint(dashboard_bp, url_prefix='/dashboard')
    app.register_blueprint(api_bp, url_prefix='/api')
    app.register_blueprint(websocket_bp, url_prefix='/ws')
    app.register_blueprint(game_bp, url_prefix='/game')

    @app.route('/')
    def index():
        from flask import redirect, url_for
        return redirect(url_for('auth.login'))

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    return app
