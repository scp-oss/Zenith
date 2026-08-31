-- Идемпотентна, как 001-005 -- см. их же для инструкций запуска:
--   mysql -u zenith -p z2r_genome < db/migrations/006_domain_pool_unique_per_profile.sql
-- (на хосте с MySQL в Docker -- см. z0r-panel/CLAUDE.md "MySQL на этом
-- хосте живёт в Docker": docker compose exec -T mysql mysql
-- -u"$MYSQL_USER" -p"$MYSQL_PASSWORD" z2r_genome <
-- db/migrations/006_domain_pool_unique_per_profile.sql, из $ZENITH_DIR).
--
-- domain_pool.uniq_host_path было UNIQUE (host, path) -- ГЛОБАЛЬНО по
-- всем профилям сразу, не per-профильно. get_or_create_domain()'s
-- INSERT ... ON DUPLICATE KEY UPDATE матчит существующую строку по
-- host+path и оставляет её profile_hint как есть (см. докстринг самой
-- функции в orchestrator/db_local.py/z0r-panel/db.py -- поведение было
-- намеренным, писалось под main.py --domain: разовый кастомный домен не
-- должен плодить дублирующую строку, если тот же host/path уже кем-то
-- зарегистрирован). Но это ломает ДРУГОЙ, более новый и explicit сценарий
-- -- "каждый профиль сам ведёт свой независимый тестовый список" (см.
-- z2r_autobench CLAUDE.md "Test domains" и z0r-panel CLAUDE.md "/domains"
-- -- прямой запрос ещё в начале этого проекта: "для каждого профиля свой
-- тестер"), где ОДИН И ТОТ ЖЕ домен (напр. www.youtube.com) законно
-- должен независимо существовать в domain_pool под НЕСКОЛЬКИМИ разными
-- профилями сразу (YT_TLS и YT_QUIC_UDP синхронизируют СВОИ курированные
-- списки, russia-youtube.txt/russia-youtubeQ.txt -- реально
-- пересекающиеся по составу доменов).
--
-- Живой симптом, 2026-08-31: синхронизация YT_QUIC_UDP через
-- /domains?profile=YT_QUIC_UDP -> "Синхронизировано 11" (get_or_create_domain
-- рапортует успех на каждой ON DUPLICATE KEY ветке), но ни одна из 11
-- строк не появилась в СОБСТВЕННОМ списке YT_QUIC_UDP -- все они уже
-- существовали в domain_pool под YT_TLS (тот же host, тот же путь "/"),
-- и UNIQUE (host, path) тихо не дал завести для них вторую, независимую
-- строку под YT_QUIC_UDP.
--
-- Фикс: сузить UNIQUE до (profile_hint, host, path) -- тот же самый
-- host/path теперь МОЖЕТ независимо существовать под разными профилями,
-- дедупликация внутри ОДНОГО профиля работает как и раньше. Код менять
-- не нужно -- INSERT уже передаёт profile_hint в VALUES, ему просто
-- не хватало ключа, который бы на него смотрел. Миграция всегда
-- применяется без конфликтов на существующих данных: раз (host, path)
-- было уникально ГЛОБАЛЬНО, оно тем более уникально в разрезе
-- (profile_hint, host, path) -- сужение ограничения, не наоборот.
USE z2r_genome;

SET @idx_exists := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'domain_pool'
      AND INDEX_NAME = 'uniq_host_path'
);
SET @sql := IF(@idx_exists > 0,
    'ALTER TABLE domain_pool DROP INDEX uniq_host_path',
    'SELECT ''domain_pool.uniq_host_path already gone, skipping'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @idx_exists := (
    SELECT COUNT(*) FROM information_schema.STATISTICS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'domain_pool'
      AND INDEX_NAME = 'uniq_profile_host_path'
);
SET @sql := IF(@idx_exists = 0,
    'ALTER TABLE domain_pool ADD UNIQUE KEY uniq_profile_host_path (profile_hint, host, path)',
    'SELECT ''domain_pool.uniq_profile_host_path already exists, skipping'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
