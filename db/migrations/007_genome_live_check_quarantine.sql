-- Идемпотентна, как 001-006 -- см. их же для инструкций запуска:
--   mysql -u zenith -p z2r_genome < db/migrations/007_genome_live_check_quarantine.sql
-- (или docker compose exec -T -e MYSQL_PWD=... mysql mysql -u... z2r_genome
-- < этот файл -- MySQL в этом стеке обычно в контейнере, см. CLAUDE.md
-- "MySQL на этом хосте крутится в Docker").
--
-- genome_scores.live_check_fails/live_check_quarantined_until --
-- auto_promoter.py::try_promote() раньше не запоминал провал ЖИВОЙ
-- проверки (после restart+set, реальный curl в проде) отдельно от
-- "ещё не пробовали" -- _rollback() освобождает claim
-- (promoted_strategy обратно в NULL), и тот же самый геном, всё ещё
-- лидер по avg_score среди непродвинутых, выбирался бы заново на
-- каждом следующем цикле, бесконечно повторяя реальный рестарт прод-
-- zapret2 + гарантированный провал + откат без единого шанса на
-- прогресс. См. CLAUDE.md "Live-check quarantine for genomes that keep
-- failing production traffic checks" для полного разбора живого случая
-- (DS_TLS, геном 47b030d9..., discord.com).
USE z2r_genome;

SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'genome_scores'
      AND COLUMN_NAME = 'live_check_fails'
);
SET @sql := IF(@col_exists = 0,
    'ALTER TABLE genome_scores ADD COLUMN live_check_fails INT NOT NULL DEFAULT 0 AFTER promoted_strategy',
    'SELECT ''genome_scores.live_check_fails already exists, skipping'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'genome_scores'
      AND COLUMN_NAME = 'live_check_quarantined_until'
);
SET @sql := IF(@col_exists = 0,
    'ALTER TABLE genome_scores ADD COLUMN live_check_quarantined_until TIMESTAMP NULL AFTER live_check_fails',
    'SELECT ''genome_scores.live_check_quarantined_until already exists, skipping'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
