-- Идемпотентна, как и 001 -- см. её же для инструкций запуска:
--   mysql -u zenith -p z2r_genome < db/migrations/002_node_self_report.sql
--
-- Меняет модель регистрации нод: токен теперь создаётся ПУСТЫМ (только
-- node_uuid + сам токен) -- имя/провайдера панель больше не просит
-- вводить в UI заранее. Нода сообщает их САМА при первом push, из
-- собственных ZENITH_ENVIRONMENT_NAME/PROVIDER в .env (той же пары,
-- что уже используют main.py/bootstrap.py/sync_client.py по умолчанию,
-- см. orchestrator/config.py) -- то же самое значение не нужно вводить
-- второй раз в веб-форме.

USE z2r_genome;

SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'environments'
      AND COLUMN_NAME = 'node_uuid'
);
SET @sql := IF(@col_exists = 0,
    'ALTER TABLE environments
        ADD COLUMN node_uuid CHAR(36) NULL AFTER api_token_hash,
        ADD UNIQUE KEY uniq_node_uuid (node_uuid)',
    'SELECT ''environments.node_uuid already exists, skipping'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;

-- provider раньше был NOT NULL -- теперь неизвестен до первого self-report
-- пустого токена, поэтому допускаем NULL. name остаётся NOT NULL UNIQUE
-- (create_node подставляет 'pending-<uuid8>' как временное значение).
SET @provider_nullable := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'environments'
      AND COLUMN_NAME = 'provider' AND IS_NULLABLE = 'YES'
);
SET @sql2 := IF(@provider_nullable = 0,
    'ALTER TABLE environments MODIFY COLUMN provider VARCHAR(64) NULL',
    'SELECT ''environments.provider already nullable, skipping'''
);
PREPARE stmt2 FROM @sql2;
EXECUTE stmt2;
DEALLOCATE PREPARE stmt2;
