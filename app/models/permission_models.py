"""
Permission models for granular role-based access control.
"""
from ..extensions import db


class RolePermission(db.Model):
    """Stores permissions for each role."""
    __tablename__ = 'role_permissions'
    
    id = db.Column(db.Integer, primary_key=True)
    role_id = db.Column(db.Integer, db.ForeignKey('roles.id'), nullable=False, unique=True)
    
    # Panel View Permissions
    can_view_panel_1 = db.Column(db.Boolean, default=True)   # Live Sensor Feed
    can_view_panel_2 = db.Column(db.Boolean, default=True)   # Current Status/KPIs
    can_view_panel_3 = db.Column(db.Boolean, default=False)  # Historical Logs
    can_view_panel_4 = db.Column(db.Boolean, default=False)  # Device Health
    
    # Action Permissions
    can_export_data = db.Column(db.Boolean, default=False)   # Download .XLSX
    can_edit_data = db.Column(db.Boolean, default=False)     # Write controls (future)
    can_manage_users = db.Column(db.Boolean, default=False)  # Admin panel access
    can_view_access_logs = db.Column(db.Boolean, default=False)  # View access logs
    
    # Relationship
    role = db.relationship('Role', backref=db.backref('permissions', uselist=False))

    def __repr__(self):
        return f'<RolePermission for Role {self.role_id}>'

    def to_dict(self):
        """Convert to dictionary for easy access."""
        return {
            'can_view_panel_1': self.can_view_panel_1,
            'can_view_panel_2': self.can_view_panel_2,
            'can_view_panel_3': self.can_view_panel_3,
            'can_view_panel_4': self.can_view_panel_4,
            'can_export_data': self.can_export_data,
            'can_edit_data': self.can_edit_data,
            'can_manage_users': self.can_manage_users,
            'can_view_access_logs': self.can_view_access_logs,
        }


# Default permissions for each role (most restrictive to least)
DEFAULT_PERMISSIONS = {
    'Investor': {
        'can_view_panel_1': True,   # Live feed only
        'can_view_panel_2': True,   # KPIs
        'can_view_panel_3': False,
        'can_view_panel_4': False,
        'can_export_data': False,
        'can_edit_data': False,
        'can_manage_users': False,
        'can_view_access_logs': False,
    },
    'Audit': {
        'can_view_panel_1': True,
        'can_view_panel_2': True,
        'can_view_panel_3': True,   # Can see logs
        'can_view_panel_4': False,
        'can_export_data': True,    # Can export for auditing
        'can_edit_data': False,
        'can_manage_users': False,
        'can_view_access_logs': True,  # Can see access logs
    },
    'Operator': {
        'can_view_panel_1': True,
        'can_view_panel_2': True,
        'can_view_panel_3': True,
        'can_view_panel_4': True,
        'can_export_data': False,
        'can_edit_data': False,
        'can_manage_users': False,
        'can_view_access_logs': False,
    },
    'Engineer': {
        'can_view_panel_1': True,
        'can_view_panel_2': True,
        'can_view_panel_3': True,
        'can_view_panel_4': True,
        'can_export_data': True,
        'can_edit_data': True,      # Can modify data
        'can_manage_users': False,
        'can_view_access_logs': False,
    },
    'Manager': {
        'can_view_panel_1': True,
        'can_view_panel_2': True,
        'can_view_panel_3': True,
        'can_view_panel_4': True,
        'can_export_data': True,
        'can_edit_data': True,
        'can_manage_users': True,   # Full admin access
        'can_view_access_logs': True,
    },
}
