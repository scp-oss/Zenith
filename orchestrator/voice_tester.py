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

region (добавлено 2026-10-08): без него все раунды main.py тестируют
ТОЛЬКО тот голосовой регион, который Discord выбрал бы для
TEST_VOICE_CHANNEL_ID автоматически -- тот самый слепой пятно, из-за
которого strategy=35 продвинулась на одном регионе и реально работала
в 1 из 12 (см. ДСП-запись 2026-10-08, auto_promoter.py
_voice_udp_region_check). ZENITH_VOICE_TEST_REGION задаёт регион для
ВСЕГО прогона main.py разом (не per-раунд -- та же причина, что
ZENITH_PROBE_URL: читается один раз при импорте, менять нужно между
запусками main.py, не посреди одного). Пусто/не задано -- старое
поведение (auto), обратная совместимость с обоими вызовами в main.py,
которые передают только lua_desync_lines."""
import json
import os
import urllib.request

PROBE_URL = os.environ.get("ZENITH_PROBE_URL", "http://127.0.0.1:8765/probe")
TEST_REGION = os.environ.get("ZENITH_VOICE_TEST_REGION") or None
TIMEOUT_SECONDS = 40


def probe(lua_desync_lines: list, region: str | None = None) -> tuple:
    body = {"lua_desync_lines": lua_desync_lines}
    region = region or TEST_REGION
    if region:
        body["region"] = region
    req = urllib.request.Request(
        PROBE_URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SECONDS) as resp:
            result = json.loads(resp.read().decode())
    except Exception:
        return False, 0, 0
    return bool(result.get("success")), 0, int(result.get("connect_ms", 0))
