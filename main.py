#!/usr/bin/env python3
"""
flask_network_monitor.py

Flask web application for real-time network monitoring.
Provides REST API endpoints and serves HTML frontend.
"""

import time
import json
import csv
import os
from datetime import datetime
from collections import deque
from threading import Thread, Lock
import psutil
from flask import Flask, render_template, jsonify, request, send_file
from flask_cors import CORS

app = Flask(__name__)
CORS(app)

class NetworkMonitor:
    def __init__(self, interval=1.0, window_size=60):
        self.interval = interval
        self.window_size = window_size
        self.running = False
        self.lock = Lock()
        
        # Data storage
        self.upload_history = deque(maxlen=window_size)
        self.download_history = deque(maxlen=window_size)
        self.timestamps = deque(maxlen=window_size)
        self.interface_data = {}
        
        # CSV logging
        self.csv_filename = f"network_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        self.init_csv()
        
        # Last counters for rate calculation
        self.last_counters = {}
        
    def init_csv(self):
        """Initialize CSV file with headers"""
        with open(self.csv_filename, 'w', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['timestamp', 'upload_kb_s', 'download_kb_s'])
    
    def get_network_counters(self, per_interface=True):
        """Get network I/O counters"""
        if per_interface:
            return psutil.net_io_counters(pernic=True)
        else:
            total = psutil.net_io_counters()
            return {'total': total}
    
    def calculate_rates(self, current_counters):
        """Calculate upload/download rates in KB/s"""
        total_upload = 0
        total_download = 0
        interface_rates = {}
        
        for interface, counters in current_counters.items():
            if interface in self.last_counters:
                last = self.last_counters[interface]
                
                # Calculate rates (bytes/s -> KB/s)
                upload_rate = (counters.bytes_sent - last.bytes_sent) / self.interval / 1024
                download_rate = (counters.bytes_recv - last.bytes_recv) / self.interval / 1024
                
                # Ensure non-negative rates
                upload_rate = max(0, upload_rate)
                download_rate = max(0, download_rate)
                
                total_upload += upload_rate
                total_download += download_rate
                
                interface_rates[interface] = {
                    'upload': upload_rate,
                    'download': download_rate,
                    'bytes_sent': counters.bytes_sent,
                    'bytes_recv': counters.bytes_recv
                }
        
        return total_upload, total_download, interface_rates
    
    def monitor_loop(self):
        """Main monitoring loop"""
        # Initialize counters
        self.last_counters = self.get_network_counters()
        time.sleep(self.interval)
        
        while self.running:
            try:
                current_time = datetime.now()
                current_counters = self.get_network_counters()
                
                # Calculate rates
                upload_rate, download_rate, interface_rates = self.calculate_rates(current_counters)
                
                # Update data with thread safety
                with self.lock:
                    self.upload_history.append(upload_rate)
                    self.download_history.append(download_rate)
                    self.timestamps.append(current_time.strftime('%H:%M:%S'))
                    self.interface_data = interface_rates
                
                # Log to CSV
                with open(self.csv_filename, 'a', newline='') as f:
                    writer = csv.writer(f)
                    writer.writerow([
                        current_time.strftime('%Y-%m-%d %H:%M:%S'),
                        f'{upload_rate:.2f}',
                        f'{download_rate:.2f}'
                    ])
                
                # Update last counters
                self.last_counters = current_counters
                
                time.sleep(self.interval)
                
            except Exception as e:
                print(f"Error in monitoring loop: {e}")
                time.sleep(self.interval)
    
    def start(self):
        """Start monitoring in background thread"""
        if not self.running:
            self.running = True
            self.monitor_thread = Thread(target=self.monitor_loop, daemon=True)
            self.monitor_thread.start()
    
    def stop(self):
        """Stop monitoring"""
        self.running = False
    
    def get_current_data(self):
        """Get current monitoring data"""
        with self.lock:
            return {
                'upload_history': list(self.upload_history),
                'download_history': list(self.download_history),
                'timestamps': list(self.timestamps),
                'interfaces': dict(self.interface_data),
                'current_upload': self.upload_history[-1] if self.upload_history else 0,
                'current_download': self.download_history[-1] if self.download_history else 0
            }

# Global monitor instance
monitor = NetworkMonitor()

@app.route('/')
def index():
    """Serve main page"""
    return render_template('index.html')

@app.route('/api/data')
def get_data():
    """API endpoint to get current network data"""
    return jsonify(monitor.get_current_data())

@app.route('/api/config', methods=['GET', 'POST'])
def config():
    """Get or update monitor configuration"""
    if request.method == 'POST':
        data = request.get_json()
        if 'interval' in data:
            monitor.interval = float(data['interval'])
        if 'window_size' in data:
            monitor.window_size = int(data['window_size'])
            # Recreate deques with new size
            with monitor.lock:
                monitor.upload_history = deque(monitor.upload_history, maxlen=monitor.window_size)
                monitor.download_history = deque(monitor.download_history, maxlen=monitor.window_size)
                monitor.timestamps = deque(monitor.timestamps, maxlen=monitor.window_size)
        return jsonify({'status': 'updated'})
    
    return jsonify({
        'interval': monitor.interval,
        'window_size': monitor.window_size,
        'running': monitor.running
    })

@app.route('/api/start', methods=['POST'])
def start_monitoring():
    """Start network monitoring"""
    monitor.start()
    return jsonify({'status': 'started'})

@app.route('/api/stop', methods=['POST'])
def stop_monitoring():
    """Stop network monitoring"""
    monitor.stop()
    return jsonify({'status': 'stopped'})

@app.route('/api/download-csv')
def download_csv():
    """Download CSV log file"""
    if os.path.exists(monitor.csv_filename):
        return send_file(monitor.csv_filename, as_attachment=True)
    return jsonify({'error': 'CSV file not found'}), 404

@app.route('/api/interfaces')
def get_interfaces():
    """Get available network interfaces"""
    interfaces = list(psutil.net_io_counters(pernic=True).keys())
    return jsonify({'interfaces': interfaces})

if __name__ == '__main__':
    # Start monitoring by default
    monitor.start()
    
    try:
        app.run(host='0.0.0.0', port=5000, debug=True, threaded=True)
    except KeyboardInterrupt:
        monitor.stop()
        print("\nNetwork monitor stopped.")