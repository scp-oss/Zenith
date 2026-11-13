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
import ipaddress
import os
import random
import socket
import subprocess

# 2026-11-13: "" = стандартный набор клиентов yt-dlp. android по-прежнему
# можно включить через env (датацентровые IP), но на NETH-4 он не нужен.
YT_PLAYER_CLIENT = os.environ.get("YT_PLAYER_CLIENT", "")
# Прогрессивный itag 18 (best[height<=480]) теперь отдаёт 403 Forbidden без
# PO-токена -- закачка падала за ~0.3с при ЛЮБОМ геноме. Берём адаптивный
# видеопоток (как реальный плеер).
YT_FORMAT = os.environ.get("YT_FORMAT", "bv*[protocol=https][height<=720]/bv*[protocol=https]")
YT_RESOLVE_TIMEOUT = int(os.environ.get("YT_RESOLVE_TIMEOUT", "25"))

# 2026-11-13: популярные ролики почти всегда отдаёт кэш провайдера (GGC,
# напр. sn-xguxaxjvh = 109.194.137.x у Дом.ру), где ТСПУ видео не режет --
# такой тест проходил бы при любом геноме. Пул сменён на малопросматриваемые
# ролики (браузерный A/B на NETH-4 2026-11-13: именно они шли с серверов
# Google и именно у них воспроизводился «не стартует»). Плюс resolve()
# предпочитает URL, чей хост резолвится в сеть Google (GOOGLE_NETS).
GV_TEST_VIDEO_IDS = tuple(os.environ.get("GV_TEST_VIDEO_IDS", "").split(",")) if os.environ.get("GV_TEST_VIDEO_IDS") else (
    "4sUWZh8FiMU", "9T1zvYgtgO8", "ixoYrFlndK4", "gXQLa_nIZXg", "vyVKklMx4Cg", "-anP8Nge3kg", "HR-lzgRjSlg", "OHBe9iurt-o",
)
GOOGLE_NETS = tuple(ipaddress.ip_network(n) for n in (
    "74.125.0.0/16", "173.194.0.0/16", "209.85.128.0/17", "172.217.0.0/16", "172.253.0.0/16",
    "142.250.0.0/15", "108.177.0.0/17", "64.233.160.0/19", "66.102.0.0/20", "66.249.64.0/19",
    "216.58.192.0/19", "216.239.32.0/19", "192.178.0.0/15", "34.0.0.0/9",
))


def host_ip(url: str):
    try:
        host = url.split("/")[2].split(":")[0]
        return socket.gethostbyname(host)
    except Exception:
        return None


def is_google_ip(ip) -> bool:
    try:
        a = ipaddress.ip_address(ip)
    except Exception:
        return False
    return any(a in n for n in GOOGLE_NETS)


def resolve_googlevideo_url(video_id: str = None):
    """Возвращает свежерезолвленный googlevideo.com URL, или None, если
    yt-dlp недоступен или резолвинг не удался (сеть до youtube.com сама по
    себе сломана -- см. докстринг модуля, не тестируемая стратегия)."""
    video_id = video_id or random.choice(GV_TEST_VIDEO_IDS)
    try:
        cmd = ["yt-dlp", "-q", "--no-warnings", "-f", YT_FORMAT, "--get-url"]
        if YT_PLAYER_CLIENT:
            cmd += ["--extractor-args", f"youtube:player_client={YT_PLAYER_CLIENT}"]
        cmd.append(f"https://www.youtube.com/watch?v={video_id}")
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=YT_RESOLVE_TIMEOUT)
    except Exception:
        return None
    lines = [ln for ln in out.stdout.strip().splitlines() if ln.strip().startswith("http")]
    return lines[0] if lines else None


SEARCH_WORDS = ("обзор", "влог", "рецепт", "ремонт", "прохождение", "кавер", "рыбалка", "урок", "тест", "путешествие")


def fresh_low_view_ids(n: int = 8) -> list:
    """Свежие малопросматриваемые ролики через поиск YouTube (сортировка по
    дате). Популярное оседает в кэше провайдера -- в т.ч. после наших же
    тестов, -- а нам нужен поток с сервера Google, где ТСПУ и режет."""
    q = random.choice(SEARCH_WORDS)
    try:
        out = subprocess.run(
            ["yt-dlp", "-q", "--no-warnings", "--flat-playlist", "--print", "%(id)s %(view_count)s %(duration)s",
             f"https://www.youtube.com/results?search_query={q}&sp=CAI%253D"],
            capture_output=True, text=True, timeout=YT_RESOLVE_TIMEOUT + 15)
    except Exception:
        return []
    rows = []
    for ln in out.stdout.splitlines():
        parts = ln.split()
        if len(parts) == 3 and parts[1].isdigit() and parts[2].replace(".", "").isdigit() and float(parts[2]) >= 60:
            rows.append((int(parts[1]), parts[0]))
    return [vid for _, vid in sorted(rows)[:n]]


def google_variant(url: str):
    """Если URL ведёт на кэш провайдера, строит URL на запасной узел из
    параметра mn= (так же делает плеер при 503/ошибке кэша): хост
    rr<fvip>---<mn_i>.googlevideo.com. Возвращает (url, ip) первого узла в
    сети Google или (None, None). Проверено 2026-11-13: mn=sn-xguxaxjvh-2x1e
    (кэш Дом.ру, 503 на некэшированное) , sn-aj5go5-5i (173.194.160.162, 206)."""
    from urllib.parse import urlsplit, parse_qs
    try:
        parts = urlsplit(url)
        q = parse_qs(parts.query)
        nodes = (q.get("mn") or [""])[0].split(",")
        fvip = (q.get("fvip") or ["1"])[0]
    except Exception:
        return None, None
    for node in nodes:
        if not node:
            continue
        rrs = [fvip] + [str(i) for i in range(1, 6) if str(i) != fvip]
        for rr in rrs:
            host = f"rr{rr}---{node}.googlevideo.com"
            try:
                ip = socket.gethostbyname(host)
            except Exception:
                continue
            if not is_google_ip(ip):
                break  # узел провайдера -- остальные rr у него тоже провайдерские
            # fallback_count=1 обязателен: без него узел Google отвечает 302
            # обратно на кэш (проверено 2026-11-13), плеер шлёт его так же.
            new = url.replace(parts.netloc, host, 1)
            if "fallback_count=" not in new:
                new += "&fallback_count=1"
            return new, ip
    return None, None


def url_valid(url: str) -> bool:
    """Ссылка вообще рабочая (подпись/узел)? 1 байт обычным путём хоста:
    206 -- да. Отсекает 302/403/503 от неподходящего узла ДО теста генома,
    иначе такие ответы засчитывались бы геному как провал (видели
    2026-11-13: «отказ за ~0.7с» у любого генома)."""
    try:
        out = subprocess.run(["curl", "-s", "-o", "/dev/null", "-r", "0-0", "--max-time", "8", "-w", "%{http_code}", url],
                             capture_output=True, text=True, timeout=12)
        return out.stdout.strip() == "206"
    except Exception:
        return False


def resolve_google_served(tries: int = 4):
    """Как resolve_googlevideo_url(), но перебирает ролики пула, пока не
    найдёт URL, отдаваемый сервером Google (а не кэшем провайдера).
    Возвращает (url, ip, google: bool) или (None, None, False)."""
    pool = list(GV_TEST_VIDEO_IDS); random.shuffle(pool)
    pool = pool[:max(1, tries)]
    last = (None, None, False)
    for vid in pool + ["__fresh__"]:
        if vid == "__fresh__":
            for fvid in fresh_low_view_ids():
                url = resolve_googlevideo_url(fvid)
                ip = host_ip(url) if url else None
                if url and is_google_ip(ip):
                    return url, ip, True
                gurl, gip = google_variant(url) if url else (None, None)
                if gurl and url_valid(gurl):
                    return gurl, gip, True
                if url:
                    last = (url, ip, False)
            break
        url = resolve_googlevideo_url(vid)
        if not url:
            continue
        ip = host_ip(url)
        if is_google_ip(ip) and url_valid(url):
            return url, ip, True
        gurl, gip = google_variant(url)
        if gurl and url_valid(gurl):
            return gurl, gip, True
        last = (url, ip, False)
    return last
