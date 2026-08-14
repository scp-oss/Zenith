-- Идемпотентна, как 001/002 -- см. их же для инструкций запуска:
--   mysql -u zenith -p z2r_genome < db/migrations/003_promoted_strategy.sql
--
-- genome_scores.promoted_strategy -- номер боевой strategy=N (см.
-- orchestrator/promote.py), в которую человек РУКАМИ продвинул этот
-- геном в этом окружении (promote.py сам ничего в БД не пишет, только
-- печатает готовый блок конфига + команду переключения -- см. её же
-- докстринг "Zenith НЕ имеет exec-доступа к боевому серверу"). Колонка
-- существует только для того, чтобы панель могла ПОКАЗАТЬ, каким
-- номером конкретный геном сейчас живёт в /opt/zapret2/config -- сама
-- панель её не заполняет автоматически, только по явному действию
-- человека на странице /genome/<id> (см. z0r-panel main.py::
-- genome_promote_strategy). Per (genome_id, environment_id) -- у разных
-- окружений может быть разный боевой конфиг и разная нумерация.
USE z2r_genome;

SET @col_exists := (
    SELECT COUNT(*) FROM information_schema.COLUMNS
    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'genome_scores'
      AND COLUMN_NAME = 'promoted_strategy'
);
SET @sql := IF(@col_exists = 0,
    'ALTER TABLE genome_scores ADD COLUMN promoted_strategy INT NULL AFTER is_production',
    'SELECT ''genome_scores.promoted_strategy already exists, skipping'''
);
PREPARE stmt FROM @sql;
EXECUTE stmt;
DEALLOCATE PREPARE stmt;
