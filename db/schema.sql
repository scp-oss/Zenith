-- Схема БД для хранения генома стратегий, истории мутаций и результатов
-- тестирования. MySQL 8+ (нужны JSON-колонки и generated columns).

CREATE DATABASE IF NOT EXISTS z2r_genome CHARACTER SET utf8mb4;
USE z2r_genome;

-- Точки тестирования: сейчас прод-сервер (дом.ру), позже + ВМ ростелеком/МТС.
--
-- Панель (panel/) живёт на том же сервере, что и прод-нода, и делит с ней
-- эту же БД напрямую -- отдельной схемы для панели нет. Удалённые ноды
-- (другие провайдеры) MySQL-доступа НЕ получают вообще (порт наружу не
-- открывается -- решение сознательно ушло от roadmap-пункта "вынести
-- MySQL за localhost" в сторону hub-and-spoke: ноды толкают снапшот по
-- HTTP с собственным токеном, песочница/main.py каждой ноды продолжает
-- работать со своей ЛОКАЛЬНОЙ БД даже если панель временно недоступна).
-- api_token_hash != NULL -- это удалённая нода, синкающаяся через
-- panel/sync_api.py, а не локальный процесс, пишущий в БД напрямую.
-- Токен создаётся ПУСТЫМ (только node_uuid) -- name/provider панель не
-- просит вводить заранее в UI, нода сообщает их САМА при первом push из
-- своих ZENITH_ENVIRONMENT_NAME/PROVIDER (.env, см. orchestrator/config.py)
-- -- то же значение не нужно вводить второй раз в веб-форме. До первого
-- контакта name = 'pending-<uuid8>', provider = NULL.
CREATE TABLE environments (
    id              INT AUTO_INCREMENT PRIMARY KEY,
    name            VARCHAR(64) NOT NULL UNIQUE,   -- 'prod-domru', 'vm-rostelecom', 'vm-mts', или 'pending-<uuid8>' до первого push
    provider        VARCHAR(64) NULL,              -- 'domru', 'rostelecom', 'mts'; NULL пока нода не отчиталась сама
    is_production   BOOLEAN NOT NULL DEFAULT FALSE, -- прод-сервер = TRUE, остальные ВМ для рискованных тестов
    active          BOOLEAN NOT NULL DEFAULT TRUE,
    api_token_hash  CHAR(64) NULL,                 -- sha256(токена) удалённой ноды; NULL = локальная запись
    node_uuid       CHAR(36) NULL,                 -- стабильный идентификатор ноды, выдаётся при создании токена
    last_sync_at    TIMESTAMP NULL,                -- последний успешный push от этой ноды
    created_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_api_token_hash (api_token_hash),
    UNIQUE KEY uniq_node_uuid (node_uuid)
);

-- Геном одного протокольного блока (tcp/80, tcp/443, udp/443 — по аналогии
-- с тем, как z2r сам собирает профили через --new). Параметры в JSON, т.к. набор полей разный
-- для разных family (fake/split/disorder/syndata/...), но ключевые для
-- частых запросов и уникальности продублированы в обычные колонки.
--
-- profile — отдельный пул генома на каждый профиль z2r_autobench
-- (YT_TLS/GV_TLS/RKN_TLS/DS_TLS/...). Геномы НЕ шарятся между профилями,
-- даже если rendered_args совпадают дословно — у каждого профиля свои
-- домены/хостлисты, и то, что работает для YT_TLS, не обязано что-то
-- значить для RKN_TLS. Поэтому profile — часть дедуп-ключа id, не просто
-- метка.
CREATE TABLE genomes (
    id             CHAR(64) PRIMARY KEY,          -- sha256(profile || ':' || rendered_args)
    profile        VARCHAR(32) NOT NULL,          -- 'YT_TLS','GV_TLS','RKN_TLS','DS_TLS','YT_QUIC_UDP','VOICE_UDP','GAMES_UDP','FB_TLS','FB_HTTP'
    filter_type    ENUM('tcp/80','tcp/443','udp/443') NOT NULL,
    family         VARCHAR(64) NOT NULL,          -- 'fake','multisplit','disorder','syndata','hostfakesplit', комбинации через запятую
    fooling        VARCHAR(64) NULL,              -- 'badsum','badseq','datanoack','md5sig', null
    ttl_mode       VARCHAR(32) NULL,               -- 'fixed:6','autottl',NULL
    fake_payload   VARCHAR(128) NULL,              -- id blob'а / 'clone:<domain>' / 'synthetic'
    params_json    JSON NOT NULL,                  -- полный набор параметров-генов как есть
    rendered_args  TEXT NOT NULL,                  -- готовая строка для --lua-desync=...
    -- sync_import -- геном пришёл из panel/sync_api.py pull (найден на
    -- ДРУГОЙ ноде/провайдере), локально ещё ни разу не пробовался, пока
    -- нет genome_scores для этого environment_id -- main.py подбирает его
    -- наравне с сидами, а не как уже проверенного кандидата.
    source         ENUM('seed','mutation','crossover','research_agent','manual','sync_import') NOT NULL,
    parent1_id     CHAR(64) NULL REFERENCES genomes(id),
    parent2_id     CHAR(64) NULL REFERENCES genomes(id), -- заполнен только при crossover
    mutation_op    VARCHAR(64) NULL,              -- 'mutate_tcp_ttl', 'mutate_tcp_fooling', ... — какой оператор породил
    generation     INT NOT NULL DEFAULT 0,        -- 0 = seed, иначе max(parent.generation)+1
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_profile (profile),
    INDEX idx_filter_family (filter_type, family),
    INDEX idx_parent1 (parent1_id),
    INDEX idx_parent2 (parent2_id)
);

-- Домены/URL для проверки, с самообслуживанием (протухшие уходят в карантин).
CREATE TABLE domain_pool (
    id                 INT AUTO_INCREMENT PRIMARY KEY,
    host               VARCHAR(255) NOT NULL,
    path               VARCHAR(512) NOT NULL DEFAULT '/',
    min_bytes          INT NOT NULL DEFAULT 65536,
    profile_hint       VARCHAR(32) NULL,          -- к какому профилю относится (YT_TLS/RKN_TLS/FB_TLS/...)
    last_verified_at   TIMESTAMP NULL,
    last_verified_ok   BOOLEAN NULL,
    consecutive_fail   INT NOT NULL DEFAULT 0,
    quarantined_until  TIMESTAMP NULL,
    added_at           TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE KEY uniq_host_path (host, path)
);

-- Стартовые домены — те же самые, что уже использует z2r_autobench
-- (rank_strategies.sh) для соответствующих профилей, не новые.
-- rutor.info для RKN_TLS подтверждён живьём в /opt/zapret2/extra_strats/
-- TCP_RKN_list.txt (тот же хостлист, что реально маршрутизирует rutracker.org
-- через профиль 3 — см. README) — не наугад добавлен.
-- VOICE_UDP -- placeholder-запись, не настоящий домен: тест этого
-- профиля -- реальное Discord voice UDP-подключение к фиксированному
-- каналу (см. orchestrator/voice_tester.py), не HTTP-запрос к хосту.
-- host/path/min_bytes тут не используются voice_tester'ом, нужна только
-- сама строка ради domain_id (experiments.domain_id NOT NULL).
-- GV_TLS (добавлен 2026-08-26) -- та же логика: реальный тестовый URL
-- резолвится ЗАНОВО на каждый раунд через yt-dlp (см. orchestrator/
-- gv_resolver.py) -- CDN-эдж "прилипает" к паре video_id+IP, фиксированный
-- URL быстро протухает. Эта запись -- только ради domain_id.
INSERT INTO domain_pool (host, path, profile_hint, min_bytes) VALUES
    ('www.youtube.com', '/', 'YT_TLS', 65536),
    ('meduza.io', '/', 'RKN_TLS', 65536),
    ('rutor.info', '/', 'RKN_TLS', 65536),
    ('discord.com', '/', 'DS_TLS', 65536),
    ('discord-voice-test', '/', 'VOICE_UDP', 0),
    ('googlevideo.com', '/', 'GV_TLS', 65536);

-- Каждый прогон генома против домена/окружения — сырая история для скоринга.
CREATE TABLE experiments (
    id             BIGINT AUTO_INCREMENT PRIMARY KEY,
    genome_id      CHAR(64) NOT NULL REFERENCES genomes(id),
    environment_id INT NOT NULL REFERENCES environments(id),
    domain_id      INT NOT NULL REFERENCES domain_pool(id),
    success        BOOLEAN NOT NULL,
    bytes          INT NOT NULL DEFAULT 0,
    latency_ms     INT NULL,
    ban_suspected  BOOLEAN NOT NULL DEFAULT FALSE, -- проставляется circuit-breaker'ом постфактум
    tested_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_genome_env (genome_id, environment_id),
    INDEX idx_tested_at (tested_at)
);

-- Агрегированный score по геному+окружению — то, что реально читает UCB
-- и autopicker, чтобы не пересчитывать заново по experiments каждый раз.
CREATE TABLE genome_scores (
    genome_id       CHAR(64) NOT NULL REFERENCES genomes(id),
    environment_id  INT NOT NULL REFERENCES environments(id),
    pulls           INT NOT NULL DEFAULT 0,        -- сколько раз тестировали (для UCB)
    successes       INT NOT NULL DEFAULT 0,
    total_reward    DOUBLE NOT NULL DEFAULT 0,      -- сумма score, для среднего
    is_production   BOOLEAN NOT NULL DEFAULT FALSE, -- сейчас закреплён как боевой в этом окружении
    promoted_strategy INT NULL,                     -- номер strategy=N в /opt/zapret2/config этого окружения,
                                                      -- если человек продвинул геном туда (см. orchestrator/
                                                      -- promote.py -- сам скрипт это НЕ пишет, только печатает
                                                      -- инструкцию; колонку заполняет панель по явному действию
                                                      -- человека, см. db/migrations/003_promoted_strategy.sql)
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (genome_id, environment_id)
);

-- Статистика по мутационным операторам для UCB на уровне "что вообще
-- пробовать дальше" (перенесено из core_loop_v2.py::pick_operator_ucb).
CREATE TABLE operator_stats (
    environment_id  INT NOT NULL REFERENCES environments(id),
    filter_type     ENUM('tcp/80','tcp/443','udp/443') NOT NULL,
    operator        VARCHAR(64) NOT NULL,
    pulls           INT NOT NULL DEFAULT 0,
    total_reward    DOUBLE NOT NULL DEFAULT 0,
    updated_at      TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    PRIMARY KEY (environment_id, filter_type, operator)
);

-- Лог подозрений на бан/эскалацию ТСПУ — то, что двигает circuit breaker
-- и общий адаптивный backoff между тестами.
CREATE TABLE ban_events (
    id              BIGINT AUTO_INCREMENT PRIMARY KEY,
    environment_id  INT NOT NULL REFERENCES environments(id),
    detected_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    trigger_reason  VARCHAR(255) NOT NULL, -- напр. 'N разных геномов подряд провалились на одном домене'
    domain_id       INT NULL REFERENCES domain_pool(id),
    cooldown_until  TIMESTAMP NOT NULL,
    resolved        BOOLEAN NOT NULL DEFAULT FALSE
);
