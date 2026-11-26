"""Integração com systemd, logs e métricas do Pi (somente leitura)."""

import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

from config import CONFIG

PROJECT = Path(__file__).parent.parent
CTL = "/usr/local/bin/academia-seeker-ctl"
ALLOWED_ACTIONS = {"start", "stop", "status", "apply-schedule", "logs"}


def ctl(action: str, timeout: int = 20) -> tuple[int, str]:
    if action not in ALLOWED_ACTIONS:
        return 1, "ação não permitida"
    try:
        proc = subprocess.run(
            ["sudo", "-n", CTL, action],
            capture_output=True, text=True, timeout=timeout, cwd=str(PROJECT),
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except FileNotFoundError:
        return 1, "helper academia-seeker-ctl não encontrado"
    except subprocess.TimeoutExpired:
        return 1, "tempo limite ao chamar o helper"


def service_state() -> str:
    """Sem 'is-active -q': neste systemd ele retorna 3 durante activating."""
    try:
        proc = subprocess.run(
            ["systemctl", "is-active", "academia-seeker.service"],
            capture_output=True, text=True, timeout=10)
        state = proc.stdout.strip()
        return state if state in ("active", "activating", "inactive", "failed", "unknown") else "unknown"
    except Exception:
        return "unknown"


def timer_state() -> dict:
    out = {"active": False, "next": "—", "unit": "academia-seeker.timer"}
    try:
        p = subprocess.run(
            ["systemctl", "is-enabled", "academia-seeker.timer"],
            capture_output=True, text=True, timeout=10)
        out["active"] = p.stdout.strip() in ("enabled", "enabled-runtime")
        p2 = subprocess.run(
            ["systemctl", "list-timers", "academia-seeker.timer",
             "--no-pager", "-n", "1"],
            capture_output=True, text=True, timeout=10)
        line = next((l for l in p2.stdout.splitlines()
                     if "academia-seeker.timer" in l), "")
        if line:
            parts = line.split()
            if len(parts) >= 4:
                out["next"] = " ".join(parts[:4])
    except Exception:
        pass
    return out


def schedule_expression() -> str:
    """OnCalendar equivalente ao registro escolhido na webview."""
    s = CONFIG.get("schedule", {}) or {}
    mode = s.get("mode", "weekly")
    time_ = s.get("time", "03:17")
    if mode == "daily":
        return f"*-*-* {time_}:00"
    if mode == "every_n_days":
        n = max(1, min(30, int(s.get("every_n_days", 7))))
        return f"*-*-{n}/{n} {time_}:00"
    weekday = s.get("weekday", "sun")
    names = {"mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu",
             "fri": "Fri", "sat": "Sat", "sun": "Sun"}
    return f"{names.get(weekday, 'Sun')} {time_}:00"


def latest_log(lines: int = 60) -> tuple[str, str]:
    logs = PROJECT / "logs"
    files = sorted(logs.glob("weekly_*.log"), key=lambda p: p.stat().st_mtime,
                   reverse=True) if logs.exists() else []
    if not files:
        return "Sem logs ainda.", ""
    path = files[0]
    try:
        content = path.read_text(encoding="utf-8", errors="replace").splitlines()
        return "\n".join(content[-lines:]), path.name
    except Exception as exc:
        return f"Não foi possível ler o log: {exc}", path.name


def system_info() -> dict:
    info = {}
    try:
        st = os.statvfs(PROJECT)
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        info["disk"] = {"total": round(total / 2**30, 1),
                        "free": round(free / 2**30, 1),
                        "pct": round(100 * (1 - free / total), 1) if total else 0}
    except Exception:
        info["disk"] = {}
    try:
        meminfo = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            k, v = line.split(":", 1)
            meminfo[k] = int(v.strip().split()[0]) / 1024  # MB
        total = meminfo.get("MemTotal", 0)
        avail = meminfo.get("MemAvailable", 0)
        info["mem"] = {"total": round(total), "available": round(avail),
                       "swap_total": round(meminfo.get("SwapTotal", 0)),
                       "swap_free": round(meminfo.get("SwapFree", 0))}
    except Exception:
        info["mem"] = {}
    try:
        info["commit"] = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(PROJECT),
            capture_output=True, text=True, timeout=5).stdout.strip()
    except Exception:
        info["commit"] = "?"
    info["now"] = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    return info


def neighbors() -> list[dict]:
    units = ["casaos.service", "pihole-FTL.service", "nginx.service", "trilium.service"]
    out = []
    for unit in units:
        try:
            p = subprocess.run(["systemctl", "is-active", unit],
                               capture_output=True, text=True, timeout=5)
            state = p.stdout.strip()
        except Exception:
            state = "unknown"
        out.append({"unit": unit, "state": state})
    return out
