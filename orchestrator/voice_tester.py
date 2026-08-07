"""Тестовый клиент для VOICE_UDP — реальное Discord voice UDP-подключение
(websocket handshake + IP discovery), не имитация. discord.py использует
свой event loop, несовместимый с обычным sync-вызовом из main.py, поэтому
запускается отдельным процессом от имени SANDBOX_USER (см.
sandbox/voice_probe.py) — так его UDP-трафик попадает в узкое
iptables-правило песочницы, как и curl у tester.py для TCP-профилей.

Метрика — время подключения в мс (как connect_ms у z2r_test-voice-bot),
не байты: возвращает ту же форму (success, bytes, latency_ms), что
tester.probe(), с bytes всегда 0 — для единообразия сигнатуры в main.py,
не потому что байты что-то значат тут.
"""
import json
import subprocess

import config

VOICE_PROBE_SCRIPT = f"{config.SANDBOX_DIR}/voice_probe.py"
VENV_PYTHON = f"{config.ZENITH_DIR}/orchestrator/venv/bin/python3"
TIMEOUT_SECONDS = 40  # держим с запасом сверх ZENITH_VOICE_HOLD_SECONDS+CONNECT_TIMEOUT из voice.env


def probe() -> tuple:
    try:
        out = subprocess.run(
            ["sudo", "-u", config.SANDBOX_USER, VENV_PYTHON, VOICE_PROBE_SCRIPT],
            capture_output=True, text=True, timeout=TIMEOUT_SECONDS,
        )
        lines = [l for l in out.stdout.strip().splitlines() if l.strip()]
        if not lines:
            return False, 0, 0
        result = json.loads(lines[-1])
    except Exception:
        return False, 0, 0
    return bool(result.get("success")), 0, int(result.get("connect_ms", 0))
