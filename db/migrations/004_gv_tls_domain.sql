-- Идемпотентна, как 001/002/003 -- см. их же для инструкций запуска:
--   mysql -u zenith -p z2r_genome < db/migrations/004_gv_tls_domain.sql
--
-- GV_TLS placeholder-запись в domain_pool -- та же роль, что у
-- 'discord-voice-test' для VOICE_UDP (см. схему): GV_TLS теперь тоже
-- тестируется через orchestrator/main.py (сандбокс + реальный коннект),
-- но её реальный тестовый URL резолвится динамически через yt-dlp
-- (gv_resolver.resolve_googlevideo_url) на каждый раунд заново -- один и
-- тот же googlevideo.com эдж не переиспользуется (CDN "прилипает" к паре
-- video_id+IP, см. z2r_autobench/z2r_autobench_lib.sh про забаненный эдж,
-- ложно проваливающий весь прогон). host/path тут не используются для
-- реального запроса, нужны только ради domain_id (experiments.domain_id
-- NOT NULL) -- host отображается на панели просто как метка профиля, не
-- как реальный адрес, который дёргался.
USE z2r_genome;

INSERT INTO domain_pool (host, path, profile_hint, min_bytes)
SELECT 'googlevideo.com', '/', 'GV_TLS', 65536
WHERE NOT EXISTS (
    SELECT 1 FROM domain_pool WHERE host = 'googlevideo.com' AND path = '/'
);
