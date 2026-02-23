/**
 * Dashboard JavaScript for MTI (Miami Telemetry Interface)
 * Handles chart rendering, data fetching, real-time updates, and panel controls
 */

// Chart.js default configuration
Chart.defaults.font.family = "'Inter', sans-serif";
Chart.defaults.color = '#757575';

// Color palette matching Miami University theme
const COLORS = {
    miamiRed: '#C3142D',
    foundationBlack: '#000000',
    academicGray: '#757575',
    lightGray: '#E5E7EB',
    success: '#059669',
    warning: '#D97706'
};

// Chart instances
let liveChart = null;
let diskChart = null;

// Camera state
let cameraStream = null;
let isCameraActive = false;

// WebSocket connection
let socket = null;

// Update interval (milliseconds)
const UPDATE_INTERVAL = 5000;

/**
 * Initialize the dashboard on page load
 */
document.addEventListener('DOMContentLoaded', function() {
    initializeDatePickers();
    initializeCharts();
    initializeCamera();
    initializeWebSocket();
    loadAllData();
    
    // Start auto-refresh
    setInterval(loadAllData, UPDATE_INTERVAL);
    
    // Handle ESC key for fullscreen exit
    document.addEventListener('keydown', function(e) {
        if (e.key === 'Escape') {
            exitFullscreen();
        }
    });
});

/**
 * Initialize WebSocket connection for real-time updates
 */
function initializeWebSocket() {
    if (typeof io !== 'undefined') {
        socket = io();
        
        socket.on('connect', function() {
            console.log('WebSocket connected');
            socket.emit('join_dashboard', { room: 'dashboard' });
        });
        
        socket.on('panel_data', function(data) {
            handlePanelUpdate(data);
        });
        
        socket.on('number_received', function(data) {
            console.log('Number received:', data.value);
        });

        // Real-time MQTT push: update charts immediately without waiting for the poll cycle
        socket.on('sensor_data', function(data) {
            if (!data.readings || !data.readings.length) return;

            const MAX_POINTS = 100;
            const colors = [COLORS.miamiRed, '#1D4ED8', '#059669', '#7C3AED', '#D97706'];
            const now = new Date().toLocaleTimeString('en-US', {
                hour: '2-digit', minute: '2-digit', second: '2-digit'
            });

            if (liveChart) {
                liveChart.data.labels.push(now);
                if (liveChart.data.labels.length > MAX_POINTS) liveChart.data.labels.shift();

                data.readings.forEach(function(reading) {
                    let dataset = liveChart.data.datasets.find(function(d) {
                        return d.label === reading.sensor_name;
                    });
                    if (!dataset) {
                        const idx = liveChart.data.datasets.length;
                        dataset = {
                            label: reading.sensor_name,
                            data: new Array(liveChart.data.labels.length - 1).fill(null),
                            borderColor: colors[idx % colors.length],
                            backgroundColor: colors[idx % colors.length] + '20',
                            borderWidth: 2,
                            fill: false,
                            tension: 0.1,
                            pointRadius: 2
                        };
                        liveChart.data.datasets.push(dataset);
                    }
                    dataset.data.push(reading.value);
                    if (dataset.data.length > MAX_POINTS) dataset.data.shift();
                });
                liveChart.update('none');
            }
        });
    }
}

/**
 * Handle real-time panel updates from WebSocket
 */
function handlePanelUpdate(data) {
    if (data.panel_id === 'sensor_data') {
        loadSensorData();
    } else if (data.panel_id === 'disk_usage') {
        loadDiskUsage();
    }
}

/**
 * Toggle fullscreen mode for a panel
 */
function toggleFullscreen(panelId) {
    const panel = document.getElementById(panelId);
    const overlay = document.getElementById('fullscreen-overlay');
    
    if (panel.classList.contains('fullscreen')) {
        exitFullscreen();
    } else {
        document.querySelectorAll('.panel.fullscreen').forEach(p => {
            p.classList.remove('fullscreen');
        });
        
        panel.classList.add('fullscreen');
        overlay.classList.add('active');
        
        clearInlineSizes(panel);
        resizeAllCharts();
    }
}

/**
 * Exit fullscreen mode
 */
function exitFullscreen() {
    document.querySelectorAll('.panel.fullscreen').forEach(panel => {
        panel.classList.remove('fullscreen');
    });
    document.getElementById('fullscreen-overlay').classList.remove('active');
    
    document.querySelectorAll('.panel').forEach(clearInlineSizes);

    const _reflow = document.body.offsetHeight;

    resizeAllCharts();
}

function clearInlineSizes(root) {
    if (!root) return;

    if (typeof root === 'string') {
        root = document.getElementById(root);
    }

    const elems = root.querySelectorAll('canvas, iframe, video, img');
    elems.forEach(el => {
        if (el.style) {
            el.style.width = '';
            el.style.height = '';
        }

        if (el.tagName.toLowerCase() === 'canvas') {
            el.removeAttribute('width');
            el.removeAttribute('height');
        }
    });
}

function resizeAllCharts() {
    setTimeout(() => {
        if (liveChart) {
            liveChart.resize();
            liveChart.update('none');
        }
        if (diskChart) {
            diskChart.resize();
            diskChart.update('none');
        }
    }, 150);
}

/**
 * Initialize camera device enumeration
 */
async function initializeCamera() {
    const select = document.getElementById('camera-select');
    if (!select) return;
    
    try {
        const devices = await navigator.mediaDevices.enumerateDevices();
        const videoDevices = devices.filter(device => device.kind === 'videoinput');
        
        select.innerHTML = '<option value="">Select Camera</option>';
        videoDevices.forEach((device, index) => {
            const option = document.createElement('option');
            option.value = device.deviceId;
            option.textContent = device.label || `Camera ${index + 1}`;
            select.appendChild(option);
        });
        
        if (videoDevices.length > 0) {
            select.value = videoDevices[0].deviceId;
        }
    } catch (error) {
        console.error('Error enumerating cameras:', error);
    }
}

/**
 * Toggle camera on/off
 */
async function toggleCamera() {
    const button = document.getElementById('camera-toggle');
    const video = document.getElementById('camera-video');
    const placeholder = document.getElementById('camera-placeholder');
    const select = document.getElementById('camera-select');
    
    if (isCameraActive) {
        stopCamera();
        button.textContent = 'Start Camera';
        video.style.display = 'none';
        placeholder.style.display = 'flex';
    } else {
        try {
            const deviceId = select.value;
            const constraints = {
                video: deviceId ? { deviceId: { exact: deviceId } } : true
            };
            
            cameraStream = await navigator.mediaDevices.getUserMedia(constraints);
            video.srcObject = cameraStream;
            video.style.display = 'block';
            placeholder.style.display = 'none';
            button.textContent = 'Stop Camera';
            isCameraActive = true;
            
            await initializeCamera();
        } catch (error) {
            console.error('Error accessing camera:', error);
            alert('Could not access camera. Please ensure camera permissions are granted.');
        }
    }
}

/**
 * Stop camera stream
 */
function stopCamera() {
    if (cameraStream) {
        cameraStream.getTracks().forEach(track => track.stop());
        cameraStream = null;
    }
    isCameraActive = false;
}

/**
 * Initialize date pickers with default values
 */
function initializeDatePickers() {
    const startDateInput = document.getElementById('start-date');
    const endDateInput = document.getElementById('end-date');
    
    if (startDateInput) {
        startDateInput.max = formatDateTimeLocal(new Date());
    }
    if (endDateInput) {
        endDateInput.max = formatDateTimeLocal(new Date());
    }
}

/**
 * Format date for datetime-local input
 */
function formatDateTimeLocal(date) {
    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, '0');
    const day = String(date.getDate()).padStart(2, '0');
    const hours = String(date.getHours()).padStart(2, '0');
    const minutes = String(date.getMinutes()).padStart(2, '0');
    return `${year}-${month}-${day}T${hours}:${minutes}`;
}

/**
 * Initialize Chart.js charts
 */
function initializeCharts() {
    // Live Sensor Feed Chart
    const liveChartCanvas = document.getElementById('liveChart');
    if (liveChartCanvas) {
        const ctx = liveChartCanvas.getContext('2d');
        liveChart = new Chart(ctx, {
            type: 'line',
            data: {
                labels: [],
                datasets: []
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                interaction: {
                    mode: 'index',
                    intersect: false
                },
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: {
                            usePointStyle: true,
                            boxWidth: 6
                        }
                    }
                },
                scales: {
                    x: {
                        grid: {
                            color: COLORS.lightGray
                        }
                    },
                    y: {
                        grid: {
                            color: COLORS.lightGray
                        }
                    }
                }
            }
        });
    }
    
    // Storage Monitor Chart (horizontal stacked bar: used vs free per path)
    const diskChartCanvas = document.getElementById('diskChart');
    if (diskChartCanvas) {
        const ctx = diskChartCanvas.getContext('2d');
        diskChart = new Chart(ctx, {
            type: 'bar',
            data: {
                labels: [],
                datasets: [
                    {
                        label: 'Used (GB)',
                        data: [],
                        backgroundColor: COLORS.miamiRed,
                        borderColor: COLORS.miamiRed,
                        borderWidth: 1
                    },
                    {
                        label: 'Free (GB)',
                        data: [],
                        backgroundColor: COLORS.lightGray,
                        borderColor: COLORS.lightGray,
                        borderWidth: 1
                    }
                ]
            },
            options: {
                indexAxis: 'y',
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        position: 'bottom',
                        labels: { usePointStyle: true, boxWidth: 6 }
                    },
                    tooltip: {
                        callbacks: {
                            label: function(context) {
                                const row = diskChart.data.labels[context.dataIndex];
                                const extra = context.dataset.label === 'Used (GB)'
                                    ? ` (${context.chart.data.datasets[0].data[context.dataIndex] /
                                        (context.chart.data.datasets[0].data[context.dataIndex] +
                                         context.chart.data.datasets[1].data[context.dataIndex]) * 100 || 0).toFixed(1)}%)`
                                    : '';
                                return ` ${context.dataset.label}: ${context.parsed.x.toFixed(1)} GB${extra}`;
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        stacked: true,
                        grid: { color: COLORS.lightGray },
                        title: { display: true, text: 'Gigabytes' }
                    },
                    y: {
                        stacked: true,
                        grid: { display: false }
                    }
                }
            }
        });
    }
}

/**
 * Load all dashboard data
 */
async function loadAllData() {
    await Promise.all([
        loadSensorData(),
        loadKPIs(),
        loadHistoricalLogs(),
        loadDiskUsage()
    ]);
}

/**
 * Refresh data manually
 */
function refreshData() {
    loadAllData();
}

/**
 * Load live sensor data for the line chart
 */
async function loadSensorData() {
    if (!liveChart) return;

    const noData = document.getElementById('live-no-data');

    try {
        const response = await fetch('/api/sensor-data?hours=1&limit=100');
        const data = await response.json();

        if (data.length === 0) {
            liveChart.data.labels = [];
            liveChart.data.datasets = [];
            liveChart.update('none');
            if (noData) noData.classList.add('visible');
            return;
        }

        if (noData) noData.classList.remove('visible');

        const sensorGroups = {};
        data.forEach(item => {
            if (!sensorGroups[item.sensor_name]) {
                sensorGroups[item.sensor_name] = [];
            }
            sensorGroups[item.sensor_name].push(item);
        });

        const timestamps = [...new Set(data.map(d => d.timestamp))].sort();
        const labels = timestamps.map(t => {
            const date = new Date(t);
            return date.toLocaleTimeString('en-US', {
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit'
            });
        });

        const colors = [COLORS.miamiRed, '#1D4ED8', '#059669', '#7C3AED', '#D97706'];
        const datasets = Object.keys(sensorGroups).map((sensorName, index) => {
            const sensorData = sensorGroups[sensorName];
            const values = timestamps.map(timestamp => {
                const point = sensorData.find(d => d.timestamp === timestamp);
                return point ? point.value : null;
            });

            return {
                label: sensorName,
                data: values,
                borderColor: colors[index % colors.length],
                backgroundColor: colors[index % colors.length] + '20',
                borderWidth: 2,
                fill: false,
                tension: 0.1,
                pointRadius: 2
            };
        });

        liveChart.data.labels = labels;
        liveChart.data.datasets = datasets;
        liveChart.update('none');

    } catch (error) {
        console.error('Error loading sensor data:', error);
    }
}

/**
 * Load KPI statistics
 */
async function loadKPIs() {
    try {
        const response = await fetch('/api/sensor-data/stats?hours=1');
        const stats = await response.json();
        
        const totalReadings = document.getElementById('kpi-total-readings');
        const sensorCount = document.getElementById('kpi-sensor-count');
        const avgValue = document.getElementById('kpi-avg-value');
        const statusOk = document.getElementById('kpi-status-ok');
        
        if (totalReadings) totalReadings.textContent = stats.total_readings || 0;
        if (sensorCount) sensorCount.textContent = stats.sensor_count || 0;
        if (avgValue) avgValue.textContent = stats.avg_value || 0;
        if (statusOk) statusOk.textContent = stats.status_summary?.OK || 0;
        
    } catch (error) {
        console.error('Error loading KPIs:', error);
    }
}

/**
 * Load historical logs for the data table
 */
async function loadHistoricalLogs() {
    const tbody = document.getElementById('logs-tbody');
    if (!tbody) return;
    
    try {
        const response = await fetch('/api/sensor-data?hours=24&limit=50');
        const data = await response.json();
        
        tbody.innerHTML = '';
        
        if (data.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = '<td colspan="5" class="text-center">No data available</td>';
            tbody.appendChild(row);
            return;
        }
        
        // Reverse to show newest first
        data.reverse().forEach(item => {
            const row = document.createElement('tr');
            const timestamp = new Date(item.timestamp).toLocaleString();
            const statusClass = item.status === 'OK' ? 'status-ok' : 
                               item.status === 'WARNING' ? 'status-warning' : 'status-error';
            
            row.innerHTML = `
                <td>${timestamp}</td>
                <td>${item.sensor_name}</td>
                <td>${item.value.toFixed(2)}</td>
                <td>${item.unit}</td>
                <td class="${statusClass}">${item.status}</td>
            `;
            tbody.appendChild(row);
        });
        
    } catch (error) {
        console.error('Error loading historical logs:', error);
    }
}

/**
 * Load disk usage for the Storage Monitor panel
 */
async function loadDiskUsage() {
    if (!diskChart) return;

    const noData = document.getElementById('disk-no-data');

    try {
        const response = await fetch('/api/disk-usage');
        if (!response.ok) {
            if (noData) noData.classList.add('visible');
            return;
        }
        const data = await response.json();
        const valid = data.filter(d => !d.error);
        if (!valid.length) {
            if (noData) noData.classList.add('visible');
            return;
        }

        if (noData) noData.classList.remove('visible');
        diskChart.data.labels = valid.map(d => d.label);
        diskChart.data.datasets[0].data = valid.map(d => d.used_gb);
        diskChart.data.datasets[1].data = valid.map(d => d.free_gb);
        diskChart.update('none');
    } catch (error) {
        if (noData) noData.classList.add('visible');
        console.error('Error loading disk usage:', error);
    }
}

/**
 * Download XLSX export
 */
function downloadExport() {
    const startDate = document.getElementById('start-date')?.value;
    const endDate = document.getElementById('end-date')?.value;
    
    let url = '/api/export';
    const params = [];
    
    if (startDate) {
        params.push(`start_date=${encodeURIComponent(startDate)}`);
    }
    if (endDate) {
        params.push(`end_date=${encodeURIComponent(endDate)}`);
    }
    
    if (params.length > 0) {
        url += '?' + params.join('&');
    }
    
    window.location.href = url;
}
