"""
API routes for data export and sensor data ingestion.
"""
from io import BytesIO
from datetime import datetime, timezone, timedelta
from flask import jsonify, request, send_file, abort, current_app
from flask_login import login_required, current_user
import pandas as pd
from . import api_bp
from ...extensions import db
from ...models import SensorData


@api_bp.route('/sensor-data')
@login_required
def get_sensor_data():
    """Get sensor data for charts, with optional filtering."""
    sensor_name = request.args.get('sensor_name')
    hours = request.args.get('hours', 1, type=int)
    limit = request.args.get('limit', 100, type=int)

    query = SensorData.query

    if sensor_name:
        query = query.filter(SensorData.sensor_name == sensor_name)

    since = datetime.now(timezone.utc) - timedelta(hours=hours)
    query = query.filter(SensorData.timestamp >= since)

    data = query.order_by(SensorData.timestamp.desc()).limit(limit).all()

    return jsonify([item.to_dict() for item in reversed(data)])


@api_bp.route('/sensor-data/latest')
@login_required
def get_latest_sensor_data():
    """Get the latest reading for each sensor."""
    sensor_names = db.session.query(SensorData.sensor_name).distinct().all()
    sensor_names = [name[0] for name in sensor_names]

    latest_data = []
    for name in sensor_names:
        latest = SensorData.query.filter_by(sensor_name=name)\
            .order_by(SensorData.timestamp.desc()).first()
        if latest:
            latest_data.append(latest.to_dict())

    return jsonify(latest_data)


@api_bp.route('/sensor-data/stats')
@login_required
def get_sensor_stats():
    """Get statistics for dashboard KPIs."""
    hours = request.args.get('hours', 1, type=int)
    since = datetime.now(timezone.utc) - timedelta(hours=hours)

    data = SensorData.query.filter(SensorData.timestamp >= since).all()

    if not data:
        return jsonify({
            'total_readings': 0,
            'sensor_count': 0,
            'avg_value': 0,
            'status_summary': {}
        })

    sensor_names = set(d.sensor_name for d in data)
    status_counts = {}
    for d in data:
        status_counts[d.status] = status_counts.get(d.status, 0) + 1

    values = [d.value for d in data]
    avg_value = sum(values) / len(values) if values else 0

    return jsonify({
        'total_readings': len(data),
        'sensor_count': len(sensor_names),
        'avg_value': round(avg_value, 2),
        'status_summary': status_counts
    })


@api_bp.route('/export')
@login_required
def export_xlsx():
    """Export sensor data to XLSX file."""
    if not current_user.can_export():
        abort(403, description="You do not have permission to export data.")
    
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    query = SensorData.query

    if start_date:
        try:
            start = datetime.fromisoformat(start_date)
            query = query.filter(SensorData.timestamp >= start)
        except ValueError:
            pass

    if end_date:
        try:
            end = datetime.fromisoformat(end_date)
            query = query.filter(SensorData.timestamp <= end)
        except ValueError:
            pass

    data = query.order_by(SensorData.timestamp.desc()).all()

    if data:
        df = pd.DataFrame([{
            'Timestamp': d.timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'Sensor_ID': d.sensor_name,
            'Value': d.value,
            'Unit': d.unit,
            'Status': d.status
        } for d in data])
    else:
        df = pd.DataFrame(columns=['Timestamp', 'Sensor_ID', 'Value', 'Unit', 'Status'])


    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name='Sensor Data', index=False)
        
        worksheet = writer.sheets['Sensor Data']
        for idx, col in enumerate(df.columns):
            max_length = max(
                df[col].astype(str).map(len).max() if len(df) > 0 else 0,
                len(col)
            ) + 2
            worksheet.column_dimensions[chr(65 + idx)].width = max_length

    output.seek(0)

    filename = f'sensor_data_{datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")}.xlsx'

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=filename
    )


@api_bp.route('/devices')
@login_required
def get_devices():
    """Get list of distinct device IDs that have reported sensor data."""
    rows = db.session.query(SensorData.device_id).distinct().all()
    device_ids = sorted(set(r[0] or 'unknown' for r in rows))
    return jsonify({'devices': device_ids, 'count': len(device_ids)})


@api_bp.route('/disk-usage')
@login_required
def get_disk_usage():
    """Return disk usage stats for the paths configured in DISK_MONITOR_PATHS.

    Query params:
        paths  – optional comma-separated override, e.g. /,/home,/data
    """
    import shutil
    import subprocess
    import platform

    raw = request.args.get('paths', '')
    if raw:
        paths = [p.strip() for p in raw.split(',') if p.strip()]
    else:
        paths = current_app.config.get('DISK_MONITOR_PATHS', ['/'])

    is_linux = platform.system() != 'Windows'
    result = []

    for path in paths:
        if not os.path.exists(path):
            result.append({'label': path, 'error': 'path not found'})
            continue
        try:
            usage = shutil.disk_usage(path)
            total_gb = round(usage.total / 1_000_000_000, 2)
            used_gb  = round(usage.used  / 1_000_000_000, 2)
            free_gb  = round(usage.free  / 1_000_000_000, 2)
            pct      = round(usage.used / usage.total * 100, 1) if usage.total else 0
        except OSError as exc:
            result.append({'label': path, 'error': str(exc)})
            continue

        # Per-folder size via `du` (Linux/macOS only; falls back to None)
        folder_gb = None
        if is_linux:
            try:
                out = subprocess.check_output(
                    ['du', '-sb', '--', path],
                    stderr=subprocess.DEVNULL, timeout=5
                )
                folder_gb = round(int(out.split()[0]) / 1_000_000_000, 3)
            except Exception:
                pass

        result.append({
            'label':     path,
            'total_gb':  total_gb,
            'used_gb':   used_gb,
            'free_gb':   free_gb,
            'percent':   pct,
            'folder_gb': folder_gb,
        })

    return jsonify(result)


@api_bp.route('/ingest', methods=['POST'])
def ingest_sensor_data():
    """Ingest sensor data from external sources."""
    data = request.get_json()

    if not data:
        return jsonify({'error': 'No data provided'}), 400

    items = data if isinstance(data, list) else [data]

    # Top-level device_id provided at the batch level (optional).
    batch_device_id = data.get('device_id', 'unknown') if isinstance(data, dict) else 'unknown'

    created = []
    for item in items:
        sensor_name = item.get('sensor_name')
        value = item.get('value')
        unit = item.get('unit', '')
        status = item.get('status', 'OK')
        device_id = item.get('device_id', batch_device_id)

        if not sensor_name or value is None:
            continue

        try:
            value = float(value)
        except (TypeError, ValueError):
            continue

        sensor_data = SensorData(
            device_id=device_id,
            sensor_name=sensor_name,
            value=value,
            unit=unit,
            status=status
        )
        db.session.add(sensor_data)
        db.session.flush()
        created.append(sensor_data.to_dict())

    db.session.commit()

    return jsonify({
        'created': len(created),
        'data': created
    }), 201
