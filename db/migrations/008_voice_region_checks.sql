-- Идемпотентна, как 001-007 -- запуск:
--   mysql -u zenith -p z2r_genome < db/migrations/008_voice_region_checks.sql
-- (или docker compose exec -T -e MYSQL_PWD=... mysql mysql -u... z2r_genome < этот файл).
--
-- voice_region_checks -- результаты периодического прогона ЖИВОЙ стратегии
-- VOICE_UDP по всем голосовым регионам Discord (z2r_autobench
-- voice_region_sweep.sh, таймер раз в 6 ч). Раньше регионы проверялись
-- только auto_promoter'ом при продвижении (а он выключен), autotune и
-- раунды Zenith ходили только в «CDN Auto» -- слепое пятно, из-за которого
-- стратегия могла работать в 1 из 12 регионов и никто бы не узнал.
-- Одна строка = один регион одного прогона (sweep_id объединяет прогон).
USE z2r_genome;

CREATE TABLE IF NOT EXISTS voice_region_checks (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    environment_id  INT NOT NULL,
    checked_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sweep_id        CHAR(36) NOT NULL,
    source          VARCHAR(32) NOT NULL DEFAULT 'sweep',
    strategy_n      INT NULL,
    region          VARCHAR(32) NOT NULL,
    success         BOOLEAN NOT NULL,
    connect_ms      INT NULL,
    note            VARCHAR(255) NULL,
    KEY idx_vrc_env_time (environment_id, checked_at),
    KEY idx_vrc_sweep (sweep_id)
);
