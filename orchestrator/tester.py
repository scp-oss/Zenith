"""Пробный коннект от имени юзера песочницы (sandbox/README.md) — только
его трафик заворачивается в песочный nfqws2 узким iptables-правилом.

Порог байт (65536) — тот же MIN_BYTES_THRESHOLD, что использует
z2r_autobench (см. CLAUDE.md z2r_autobench): просто "curl не упал"
недостаточно, страница может отдать пустой/усечённый ответ и всё равно
вернуть код успеха.
"""
import subprocess
import time

import config

DEFAULT_TIMEOUT = 5


def _curl_probe(url: str, min_bytes: int) -> tuple:
    start = time.monotonic()
    bytes_ = 0
    try:
        out = subprocess.run(
            [
                "sudo", "-u", config.SANDBOX_USER, "curl", "-s", "-o", "/dev/null",
                "-w", "%{size_download}",
                "--connect-timeout", "3", "--max-time", str(DEFAULT_TIMEOUT),
                url,
            ],
            capture_output=True, text=True, timeout=DEFAULT_TIMEOUT + 3,
        )
        bytes_ = int((out.stdout or "0").strip() or 0)
    except Exception:
        bytes_ = 0
    latency_ms = int((time.monotonic() - start) * 1000)
    success = bytes_ >= min_bytes
    return success, bytes_, latency_ms


def probe(host: str, path: str, min_bytes: int) -> tuple:
    return _curl_probe(f"https://{host}{path}", min_bytes)


def probe_url(url: str, min_bytes: int) -> tuple:
    """Как probe(), но берёт готовый URL целиком -- для GV_TLS, чей
    реальный тестовый адрес резолвится динамически (см. gv_resolver.py),
    а не берётся из фиксированного host/path в domain_pool."""
    return _curl_probe(url, min_bytes)


LAST_MEDIA = {}  # код ответа/ошибка последнего probe_media -- для логов и диагностики
GV_MEDIA_WANT_BYTES = 4_000_000   # тянем до 4 МБ видеопотока
GV_MEDIA_MIN_BYTES = 1_000_000    # провал, если за отведённое время меньше 1 МБ
GV_MEDIA_MAX_TIME = 15


def probe_media(url: str, want_bytes: int = GV_MEDIA_WANT_BYTES, min_bytes: int = GV_MEDIA_MIN_BYTES,
                max_time: int = GV_MEDIA_MAX_TIME) -> tuple:
    """Реальная закачка куска видеопотока googlevideo через песочницу
    (Range 0..want_bytes). Обновлённый ТСПУ рвёт/душит ИМЕННО поток
    сервер->клиент после первых десятков КБ -- 64 КБ и 5 с прежнего теста
    это не ловят. Возвращает (success, bytes, latency_ms) -- latency тут =
    полное время закачки, скорость считает scoring.compute_reward_throughput."""
    start = time.monotonic()
    bytes_ = 0
    try:
        out = subprocess.run(
            ["sudo", "-u", config.SANDBOX_USER, "curl", "-s", "-o", "/dev/null", "-w", "%{size_download} %{http_code} %{exitcode}",
             "-r", f"0-{want_bytes - 1}", "--connect-timeout", "4", "--max-time", str(max_time), url],
            capture_output=True, text=True, timeout=max_time + 5,
        )
        b, code, rc = ((out.stdout or "0 000 0").split() + ["000", "0"])[:3]
        bytes_ = int(b or 0)
        LAST_MEDIA.update(http=code, curl_rc=rc)
    except Exception as e:
        bytes_ = 0
        LAST_MEDIA.update(http="000", curl_rc=str(e)[:60])
    latency_ms = int((time.monotonic() - start) * 1000)
    return bytes_ >= min_bytes, bytes_, latency_ms
