"""
Dashboard routes for the 4-panel grid view.
"""
from flask import render_template
from flask_login import login_required, current_user
from . import dashboard_bp


@dashboard_bp.route('/')
@login_required
def grid_view():
    """Display the main 4-panel dashboard grid."""
    # Get user permissions
    perms = current_user.get_permissions()
    
    # Build permission context for template
    panel_access = {
        'panel_1': current_user.can_view_panel(1),
        'panel_2': current_user.can_view_panel(2),
        'panel_3': current_user.can_view_panel(3),
        'panel_4': current_user.can_view_panel(4),
    }
    
    return render_template(
        'dashboard/grid_view.html',
        panel_access=panel_access,
        can_export=current_user.can_export(),
        can_edit=current_user.can_edit(),
        is_admin=current_user.can_access_admin()
    )
