import os
from app import create_app, db
from app.models import User, Role, SensorData, RolePermission

app = create_app(os.environ.get('FLASK_CONFIG') or 'default')


@app.shell_context_processor
def make_shell_context():
    """Make database models available in flask shell."""
    return dict(db=db, User=User, Role=Role, SensorData=SensorData, RolePermission=RolePermission)


@app.cli.command()
def seed_roles():
    """Seed the database with default roles."""
    roles = ['Manager', 'Engineer', 'Operator', 'Investor', 'Audit']
    for role_name in roles:
        role = Role.query.filter_by(name=role_name).first()
        if role is None:
            role = Role(name=role_name)
            db.session.add(role)
            print(f'Added role: {role_name}')
        else:
            print(f'Role already exists: {role_name}')
    db.session.commit()
    print('Role seeding complete.')


@app.cli.command()
def seed_admin():
    """Create a default admin user (Manager role)."""
    import secrets
    import string
    
    manager_role = Role.query.filter_by(name='Manager').first()
    if manager_role is None:
        print('Error: Manager role not found. Run seed_roles first.')
        return
    
    admin = User.query.filter_by(username='admin').first()
    if admin is None:
        # Generate a secure random password
        alphabet = string.ascii_letters + string.digits + string.punctuation
        secure_password = ''.join(secrets.choice(alphabet) for _ in range(16))
        
        admin = User(username='admin', role_id=manager_role.id)
        admin.set_password(secure_password)
        db.session.add(admin)
        db.session.commit()
        print(f'Created admin user (username: admin)')
        print(f'Generated secure password: {secure_password}')
        print('IMPORTANT: Save this password now! It will not be shown again.')
    else:
        print('Admin user already exists.')


if __name__ == '__main__':
    # SECURITY: Never run with debug=True in production
    # Set FLASK_DEBUG=1 in development only
    import os
    debug_mode = os.environ.get('FLASK_DEBUG', '0') == '1'
    app.run(debug=debug_mode)
