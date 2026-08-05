-- Схема БД для хранения генома стратегий, истории мутаций и результатов
-- тестирования. MySQL 8+ (нужны JSON-колонки и generated columns).

CREATE DATABASE IF NOT EXISTS z2r_genome CHARACTER SET utf8mb4;
USE z2r_genome;

-- Точки тестирования: сейчас NETH-4 (дом.ру), позже + ВМ ростелеком/МТС.
CREATE TABLE environments (
    id            INT AUTO_INCREMENT PRIMARY KEY,
    name          VARCHAR(64) NOT NULL UNIQUE,   -- 'neth4-domru', 'vm-rostelecom', 'vm-mts'
    provider      VARCHAR(64) NOT NULL,          -- 'domru', 'rostelecom', 'mts'
    is_production BOOLEAN NOT NULL DEFAULT FALSE, -- NETH-4 = TRUE, остальные ВМ для рискованных тестов
    active        BOOLEAN NOT NULL DEFAULT TRUE,
    created_at    TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP
);

-- Геном одного протокольного блока (tcp/80, tcp/443, udp/443 — по аналогии
-- с ComboBuilder из ansp-mvp). Параметры в JSON, т.к. набор полей разный
-- для разных family (fake/split/disorder/syndata/...), но ключевые для
-- частых запросов и уникальности продублированы в обычные колонки.
CREATE TABLE genomes (
    id             CHAR(64) PRIMARY KEY,          -- sha256(rendered_args), естественный дедуп-ключ
    filter_type    ENUM('tcp/80','tcp/443','udp/443') NOT NULL,
    family         VARCHAR(64) NOT NULL,          -- 'fake','multisplit','disorder','syndata','hostfakesplit', комбинации через запятую
    fooling        VARCHAR(64) NULL,              -- 'badsum','badseq','datanoack','md5sig', null
    ttl_mode       VARCHAR(32) NULL,               -- 'fixed:6','autottl',NULL
    fake_payload   VARCHAR(128) NULL,              -- id blob'а / 'clone:<domain>' / 'synthetic'
    params_json    JSON NOT NULL,                  -- полный набор параметров-генов как есть
    rendered_args  TEXT NOT NULL,                  -- готовая строка для --lua-desync=...
    source         ENUM('seed','mutation','crossover','research_agent','manual') NOT NULL,
    parent1_id     CHAR(64) NULL REFERENCES genomes(id),
    parent2_id     CHAR(64) NULL REFERENCES genomes(id), -- заполнен только при crossover
    mutation_op    VARCHAR(64) NULL,              -- 'mutate_tcp_ttl', 'mutate_tcp_fooling', ... — какой оператор породил
    generation     INT NOT NULL DEFAULT 0,        -- 0 = seed, иначе max(parent.generation)+1
    created_at     TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
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
