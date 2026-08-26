-- Идемпотентна, как 001-004 -- см. их же для инструкций запуска:
--   mysql -u zenith -p z2r_genome < db/migrations/005_backfill_node_uuid.sql
--
-- node_uuid раньше выдавался ТОЛЬКО при создании токена удалённой ноды
-- (см. схему) -- локальные/прод-окружения (создаются
-- orchestrator/db_local.py::get_or_create_environment() напрямую, без
-- токена вообще, например 'prod-domru') оставались с node_uuid=NULL
-- навсегда. get_or_create_environment() теперь сама генерит uuid при
-- создании НОВОЙ строки -- эта миграция закрывает УЖЕ существующие.
-- UUID() в MySQL/MariaDB генерит новое значение НА КАЖДУЮ строку,
-- затронутую UPDATE, не один и тот же литерал на все строки разом.
USE z2r_genome;

UPDATE environments SET node_uuid = UUID() WHERE node_uuid IS NULL;
