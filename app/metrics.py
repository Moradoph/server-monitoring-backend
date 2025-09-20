import os
import threading
import psutil
import time
from typing import Dict


class MetricsProvider:
    def __init__(self):
        self._lock = threading.Lock()
        self._latest = {}
        self._running = False
        self._thread = None

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=1)

    def _run(self):
        while self._running:
            data = self._collect()
            with self._lock:
                self._latest = data
            time.sleep(1)

    def _collect(self) -> Dict:
        cpu = psutil.cpu_percent(interval=None)
        virtual = psutil.virtual_memory()
        disk = psutil.disk_usage('/')
        net_io = psutil.net_io_counters()
        # collect processes by CPU
        procs = []
        try:
            for p in psutil.process_iter(['pid', 'name', 'username', 'cpu_percent', 'memory_percent', 'memory_info', 'cmdline']):
                info = p.info
                procs.append({
                    'pid': info.get('pid'),
                    'name': info.get('name') or '',
                    'user': info.get('username') or '',
                    'cpu_percent': float(info.get('cpu_percent') or 0.0),
                    'mem_percent': float(info.get('memory_percent') or 0.0),
                    'rss': int(info.get('memory_info').rss) if info.get('memory_info') else 0,
                    'cmd': ' '.join(info.get('cmdline') or [])
                })
        except Exception:
            procs = []

        # sort and take top N (controlled by PROCESS_LIMIT env var)
        limit_env = os.getenv('PROCESS_LIMIT', '')
        try:
            limit = int(limit_env) if limit_env != '' else 400
        except Exception:
            limit = 400

        procs_sorted_all = sorted(procs, key=lambda x: x.get('cpu_percent', 0), reverse=True)
        if limit <= 0:
            procs_sorted = procs_sorted_all
        else:
            procs_sorted = procs_sorted_all[:limit]

        # detailed memory
        memory = {
            'total': virtual.total,
            'available': virtual.available,
            'used': virtual.used,
            'free': getattr(virtual, 'free', 0),
            'cached': getattr(virtual, 'cached', 0),
            'percent': virtual.percent,
        }

        # swap
        swap = psutil.swap_memory()
        swap_info = {
            'total': swap.total,
            'used': swap.used,
            'free': swap.free,
            'percent': swap.percent,
        }

        # disks: enumerate partitions and report usage for common mountpoints
        disks = []
        try:
            parts = psutil.disk_partitions(all=False)
            for part in parts:
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    disks.append({
                        'device': part.device,
                        'mountpoint': part.mountpoint,
                        'fstype': part.fstype,
                        'total': usage.total,
                        'used': usage.used,
                        'free': usage.free,
                        'percent': usage.percent,
                    })
                except Exception:
                    continue
        except Exception:
            disks = []

        # per-core CPU
        try:
            per_core = psutil.cpu_percent(interval=None, percpu=True)
        except Exception:
            per_core = []

        # load average
        try:
            load1, load5, load15 = os.getloadavg()
            load_avg = {'1': load1, '5': load5, '15': load15}
        except Exception:
            load_avg = {'1': 0.0, '5': 0.0, '15': 0.0}

        # temperatures (may not be available on all systems)
        temps = {}
        try:
            sensors = psutil.sensors_temperatures()
            for name, entries in sensors.items():
                # pick the first entry per sensor
                if entries:
                    temps[name] = [float(getattr(e, 'current', 0.0)) for e in entries]
        except Exception:
            temps = {}

        return {
            'cpu_percent': cpu,
            'per_core': per_core,
            'load_avg': load_avg,
            'temps': temps,
            'memory': memory,
            'swap': swap_info,
            'disk_percent': disk.percent,
            'disk_used': disk.used,
            'disk_total': disk.total,
            'disks': disks,
            'net_bytes_sent': net_io.bytes_sent,
            'net_bytes_recv': net_io.bytes_recv,
            'timestamp': time.time(),
            'processes': procs_sorted,
        }

    def snapshot(self) -> Dict:
        with self._lock:
            return dict(self._latest)
