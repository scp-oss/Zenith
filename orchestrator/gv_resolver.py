"""Резолвит реальный googlevideo.com URL для тестирования GV_TLS (профиль
2) -- портированная логика z2r_autobench/z2r_autobench_lib.sh::
resolve_googlevideo_url()/get_gv_test_url(), с теми же живыми уроками
(см. CLAUDE.md z2r_autobench):

- --extractor-args player_client=android ОБЯЗАТЕЛЕН -- без него yt-dlp
  выбирает ANDROID_VR, который получает 403 с этого (датацентрового, не
  резидентского) IP; web/mweb не годятся без JS-раннера для sig/n-
  challenge; tv отдаёт "page needs to be reloaded". android -- единственный
  проверенный вживую рабочий клиент.
- Пул из нескольких video_id, не один фиксированный -- CDN "прилипает" к
  паре (video_id, IP): один и тот же ролик с одного и того же сервера
  почти всегда возвращает один и тот же эдж. Если тот эдж забанен, весь
  прогон ложно проваливается целиком, выглядя как "геном не работает",
  хотя на самом деле проблема в конкретном эдже.

Резолвинг сам по себе идёт НЕ через песочницу (обычный процесс
оркестратора, не sudo -u zenith-sandbox) -- это просто метаданные с
youtube.com, а не тестируемый трафик. Тестируется уже сам googlevideo.com
URL, отдельным curl через зенитового sandbox-юзера (см. tester.probe_url).
"""
import os
import random
import subprocess

YT_PLAYER_CLIENT = os.environ.get("YT_PLAYER_CLIENT", "android")
YT_RESOLVE_TIMEOUT = int(os.environ.get("YT_RESOLVE_TIMEOUT", "25"))

GV_TEST_VIDEO_IDS = ("dQw4w9WgXcQ", "9bZkp7q19f0", "kJQP7kiw5Fk", "jNQXAC9IVRw", "60ItHLz5WEA")


def resolve_googlevideo_url(video_id: str = None):
    """Возвращает свежерезолвленный googlevideo.com URL, или None, если
    yt-dlp недоступен или резолвинг не удался (сеть до youtube.com сама по
    себе сломана -- см. докстринг модуля, не тестируемая стратегия)."""
    video_id = video_id or random.choice(GV_TEST_VIDEO_IDS)
    try:
        out = subprocess.run(
            [
                "yt-dlp", "-f", "best[height<=480]", "--get-url",
                "--extractor-args", f"youtube:player_client={YT_PLAYER_CLIENT}",
                f"https://www.youtube.com/watch?v={video_id}",
            ],
            capture_output=True, text=True, timeout=YT_RESOLVE_TIMEOUT,
        )
    except Exception:
        return None
    lines = [ln for ln in out.stdout.strip().splitlines() if ln.strip()]
    return lines[-1] if lines else None
