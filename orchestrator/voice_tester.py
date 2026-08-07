"""Тестовый клиент для VOICE_UDP — вызывает уже работающий и залогиненный
z2r_test-voice-bot через его локальный HTTP (POST /probe), а не отдельный
Discord-процесс/токен Zenith'а (см. z2r_test-voice-bot/README.md
"Интеграция с Zenith"): один бот, один токен, один владелец — по явному
запросу, вместо двух параллельных сессий на разных токенах.

Бот сам применяет присланный геном в СВОЕЙ песочнице (той же, что и
остальные профили Zenith) и тестирует реальным Discord voice
UDP-подключением (websocket handshake + IP discovery, не имитация) —
main.py для VOICE_UDP НЕ вызывает sandbox_apply.apply_genome() отдельно,
это сделал бы двойную (хоть и безвредную) работу.

Метрика — время подключения в мс (как connect_ms у бота), не байты:
возвращает ту же форму (success, bytes, latency_ms), что tester.probe(),
с bytes всегда 0 — для единообразия сигнатуры вызова в main.py.
"""
import json
import os
import urllib.request

PROBE_URL = os.environ.get("ZENITH_PROBE_URL", "http://127.0.0.1:8765/probe")
TIMEOUT_SECONDS = 40


def probe(lua_desync_lines: list) -> tuple:
    body = json.dumps({"lua_desync_lines": lua_desync_lines}).encode()
    req = urllib.request.Request(
        PROBE_URL, data=body, headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            result = json.loads(resp.read().decode())
    except Exception:
        return False, 0, 0
    return bool(result.get("success")), 0, int(result.get("connect_ms", 0))
