"""系统状态采集 — CPU / RAM / GPU / 温度 / 网络 / 磁盘 / 延迟 / 天气 / 运行时间"""

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

import psutil

# 网络速度采样缓存
_net_prev = None
_net_prev_time = None

# ping / 天气缓存（避免高频请求）
_ping_cache: dict = {"data": None, "time": 0}
_weather_cache: dict = {"data": None, "time": 0}

PING_HOST = os.environ.get("DESK_OS_PING_HOST", "1.1.1.1")
PING_INTERVAL = 10
WEATHER_LAT = os.environ.get("DESK_OS_WEATHER_LAT", "39.9")
WEATHER_LON = os.environ.get("DESK_OS_WEATHER_LON", "116.4")
WEATHER_INTERVAL = 900

# WMO 天气代码 → 简短英文描述
WMO_WEATHER = {
    0: "clear",
    1: "mainly clear",
    2: "partly cloudy",
    3: "overcast",
    45: "fog",
    48: "fog",
    51: "drizzle",
    53: "drizzle",
    55: "drizzle",
    61: "rain",
    63: "rain",
    65: "rain",
    71: "snow",
    73: "snow",
    75: "snow",
    80: "showers",
    81: "showers",
    82: "showers",
    95: "thunderstorm",
    96: "thunderstorm",
    99: "thunderstorm",
}

_CREATE_NO_WINDOW = (
    subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
)


def _format_bytes_per_sec(bps: float) -> str:
    if bps < 1024:
        return f"{bps:.0f} B/s"
    if bps < 1024 ** 2:
        return f"{bps / 1024:.1f} KB/s"
    return f"{bps / 1024 ** 2:.1f} MB/s"


def _format_gb(bytes_val: float) -> float:
    return round(bytes_val / (1024 ** 3), 1)


def get_gpu_status() -> dict:
    """GPU 使用率 + 显存 + 温度（nvidia-smi）"""
    try:
        result = subprocess.run(
            [
                "nvidia-smi",
                "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=3,
            creationflags=_CREATE_NO_WINDOW,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split("\n")[0].split(",")
            usage = int(parts[0].strip())
            mem_used = round(float(parts[1].strip()) / 1024, 1)  # MiB → GB
            mem_total = round(float(parts[2].strip()) / 1024, 1)
            temp_c = None
            if len(parts) > 3 and parts[3].strip():
                try:
                    temp_c = int(round(float(parts[3].strip())))
                except ValueError:
                    temp_c = None
            label = f"{usage}%  {mem_used} / {mem_total} GB"
            if temp_c is not None:
                label = f"{label}  {temp_c}°"
            return {
                "available": True,
                "usage": usage,
                "mem_used_gb": mem_used,
                "mem_total_gb": mem_total,
                "temp_c": temp_c,
                "label": label,
            }
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError, OSError, IndexError):
        pass
    return {"available": False, "usage": None, "temp_c": None, "label": "N/A"}


def get_disk_status() -> list[dict]:
    """各磁盘分区使用情况"""
    disks = []
    seen = set()

    for part in psutil.disk_partitions(all=False):
        if "cdrom" in part.opts.lower() or not part.fstype:
            continue

        drive = part.device.rstrip("\\/")
        if not drive or drive in seen:
            continue
        seen.add(drive)

        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            continue

        # Windows: C: → 显示为 C
        label = drive.rstrip(":")

        disks.append(
            {
                "drive": label,
                "used_gb": _format_gb(usage.used),
                "total_gb": _format_gb(usage.total),
                "label": f"{_format_gb(usage.used)} / {_format_gb(usage.total)} GB",
            }
        )

    return disks


def get_uptime() -> dict:
    """系统运行时间"""
    elapsed = time.time() - psutil.boot_time()
    days = int(elapsed // 86400)
    hours = int((elapsed % 86400) // 3600)
    minutes = int((elapsed % 3600) // 60)

    if days > 0:
        label = f"{days}d {hours}h"
    elif hours > 0:
        label = f"{hours}h {minutes}m"
    else:
        label = f"{minutes}m"

    return {"seconds": int(elapsed), "label": label}


def get_ping() -> dict:
    """Ping 指定主机（默认 1.1.1.1，可通过 DESK_OS_PING_HOST 配置）"""
    now = time.time()
    if _ping_cache["data"] and now - _ping_cache["time"] < PING_INTERVAL:
        return _ping_cache["data"]

    host = PING_HOST
    result_data = {"available": False, "host": host, "ms": None, "label": "N/A"}

    try:
        proc = subprocess.run(
            ["ping", "-n", "1", "-w", "1000", host],
            capture_output=True,
            text=True,
            timeout=3,
            encoding="utf-8",
            errors="replace",
            creationflags=_CREATE_NO_WINDOW,
        )
        output = proc.stdout + proc.stderr
        match = re.search(r"[=<](\d+)\s*ms", output, re.IGNORECASE)
        if match:
            ms = int(match.group(1))
            result_data = {
                "available": True,
                "host": host,
                "ms": ms,
                "label": f"{ms} ms",
            }
        elif re.search(r"[=<]\s*1\s*ms", output, re.IGNORECASE):
            result_data = {
                "available": True,
                "host": host,
                "ms": 1,
                "label": "<1 ms",
            }
    except (subprocess.TimeoutExpired, OSError):
        pass

    _ping_cache["data"] = result_data
    _ping_cache["time"] = now
    return result_data


def get_weather() -> dict:
    """天气（Open-Meteo，无需 API Key）"""
    now = time.time()
    if _weather_cache["data"] and now - _weather_cache["time"] < WEATHER_INTERVAL:
        return _weather_cache["data"]

    result_data = {"available": False, "label": "N/A"}

    try:
        url = (
            "https://api.open-meteo.com/v1/forecast"
            f"?latitude={WEATHER_LAT}&longitude={WEATHER_LON}"
            "&current=temperature_2m,weather_code"
            "&timezone=auto"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "DeskOS/1.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read().decode())

        current = data.get("current", {})
        temp = current.get("temperature_2m")
        code = current.get("weather_code", -1)
        desc = WMO_WEATHER.get(code, "unknown")

        if temp is not None:
            result_data = {
                "available": True,
                "temp_c": round(temp),
                "description": desc,
                "label": f"{round(temp)}°C  {desc}",
            }
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError, KeyError):
        pass

    _weather_cache["data"] = result_data
    _weather_cache["time"] = now
    return result_data


def get_network_speed() -> dict:
    global _net_prev, _net_prev_time

    counters = psutil.net_io_counters()
    now = time.time()

    download = 0.0
    upload = 0.0

    if _net_prev is not None and _net_prev_time is not None:
        dt = now - _net_prev_time
        if dt > 0:
            download = (counters.bytes_recv - _net_prev.bytes_recv) / dt
            upload = (counters.bytes_sent - _net_prev.bytes_sent) / dt

    _net_prev = counters
    _net_prev_time = now

    return {
        "download": _format_bytes_per_sec(max(download, 0)),
        "upload": _format_bytes_per_sec(max(upload, 0)),
    }


def get_system_status() -> dict:
    mem = psutil.virtual_memory()

    return {
        "cpu": round(psutil.cpu_percent(interval=0.1), 1),
        "ram": {
            "used_gb": _format_gb(mem.used),
            "total_gb": _format_gb(mem.total),
            "percent": round(mem.percent, 1),
        },
        "gpu": get_gpu_status(),
        "disks": get_disk_status(),
        "network": get_network_speed(),
        "ping": get_ping(),
        "uptime": get_uptime(),
        "weather": get_weather(),
    }
