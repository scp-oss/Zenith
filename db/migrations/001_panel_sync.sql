-- Миграция для УЖЕ РАБОТАЮЩЕЙ прод-БД (schema.sql трогает только свежую
-- установку через CREATE TABLE). Идемпотентна -- проверяет
-- information_schema перед каждым ALTER, безопасно гонять повторно.
--
--   mysql -u zenith -p z2r_genome < db/migrations/001_panel_sync.sql
--
-- Добавляет: колонки под панель/удалённые ноды в environments, и
-- 'sync_import' в genomes.source (геномы, найденные на другой ноде и
-- затянутые сюда через pull, см. panel/sync_api.py и
-- orchestrator/sync_client.py).

USE z2r_genome;

SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'environments'
      AND COLUMN_NAME = 'api_token_hash'
);
SET @sql := IF(@col_exists = 0,
    'ALTER TABLE environments
        ADD COLUMN api_token_hash CHAR(64) NULL AFTER active,
        ADD COLUMN last_sync_at TIMESTAMP NULL AFTER api_token_hash,
        ADD UNIQUE KEY uniq_api_token_hash (api_token_hash)',
    'SELECT ''environments.api_token_hash already exists, skipping'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- genomes.source ENUM -- MySQL не даёт ALTER ... ADD VALUE напрямую для
-- ENUM, единственный способ -- MODIFY COLUMN с полным новым списком
-- значений. Идемпотентно за счёт проверки текущего COLUMN_TYPE.
SET @enum_has_sync_import := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'genomes'
      AND COLUMN_NAME = 'source' AND COLUMN_TYPE LIKE '%sync_import%'
);
SET @sql2 := IF(@enum_has_sync_import = 0,
    "ALTER TABLE genomes MODIFY COLUMN source
        ENUM('seed','mutation','crossover','research_agent','manual','sync_import') NOT NULL",
    'SELECT ''genomes.source already has sync_import, skipping'''
);
PREPARE stmt2 FROM @sql2;
EXECUTE stmt2;
DEALLOCATE PREPARE stmt2;
