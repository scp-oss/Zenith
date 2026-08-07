import hashlib
import json

import mysql.connector
import config


def connect():
    return mysql.connector.connect(
        host=config.MYSQL_HOST,
        port=config.MYSQL_PORT,
        user=config.MYSQL_USER,
        password=config.MYSQL_PASSWORD,
        database=config.MYSQL_DATABASE,
        autocommit=True,
    )


def get_or_create_environment(conn, name: str, provider: str) -> int:
    cur = conn.cursor()
    cur.execute("SELECT id FROM environments WHERE name=%s", (name,))
    row = cur.fetchone()
    if row:
        return row[0]
    cur.execute(
        "INSERT INTO environments (name, provider) VALUES (%s, %s)",
        (name, provider),
    )
    return cur.lastrowid


def get_domains_for_profile(conn, profile: str):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT id, host, path, min_bytes FROM domain_pool
           WHERE profile_hint=%s
             AND (quarantined_until IS NULL OR quarantined_until < NOW())""",
        (profile,),
    )
    return cur.fetchall()


def insert_control_genome(conn, profile: str, lines: list) -> str:
    """Control-геном (боевая ручная стратегия, см. controls.py) как
    отдельная запись в genomes: family='control', source='manual' --
    чтобы его успешность копилась в genome_scores так же, как у
    сгенерированных геномов, а не терялась после разового прогона
    compare_control.py, и её можно было честно сравнить в БД, а не
    только в момент вывода на экран. rendered_args -- склеенные строкой
    через \\n все инстансы (control часто многоинстансный)."""
    rendered = "\n".join(lines)
    gid = hashlib.sha256(f"{profile}:{rendered}".encode()).hexdigest()
    cur = conn.cursor()
    cur.execute(
        """INSERT IGNORE INTO genomes
           (id, profile, filter_type, family, fooling, ttl_mode, fake_payload,
            params_json, rendered_args, source, generation)
           VALUES (%s,%s,'tcp/443','control',NULL,NULL,NULL,%s,%s,'manual',0)""",
        (gid, profile, json.dumps({"lines": lines}, ensure_ascii=False), rendered),
    )
    return gid


def insert_genome(conn, g) -> str:
    gid = g.compute_id()
    cur = conn.cursor()
    cur.execute(
        """INSERT IGNORE INTO genomes
           (id, profile, filter_type, family, fooling, ttl_mode, fake_payload,
            params_json, rendered_args, source, parent1_id, parent2_id,
            mutation_op, generation)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
        (
            gid, g.profile, g.filter_type, g.family, g.fooling, g.ttl_mode,
            g.fake_payload, g.params_json(), g.render_args(), g.source,
            g.parent1_id, g.parent2_id, g.mutation_op, g.generation,
        ),
    )
    return gid


def record_experiment(conn, genome_id, environment_id, domain_id, success, bytes_, latency_ms, ban_suspected=False):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO experiments
           (genome_id, environment_id, domain_id, success, bytes, latency_ms, ban_suspected)
           VALUES (%s,%s,%s,%s,%s,%s,%s)""",
        (genome_id, environment_id, domain_id, success, bytes_, latency_ms, ban_suspected),
    )


def get_genomes_with_scores(conn, profile: str, environment_id: int):
    """Для genome-level UCB в main.py -- все геномы профиля, которые уже
    хоть раз пробовались в этом окружении, с накопленной статистикой
    (не только сиды, но и любые ранее сгенерированные мутанты).
    family != 'control' обязателен: control-геномы (см.
    insert_control_genome) хранят params_json={'lines': [...]}, а не
    поля Genome -- genome.from_params() упадёт, если UCB попробует их
    как родителя для мутации."""
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT g.params_json, g.generation, gs.pulls, gs.total_reward
           FROM genome_scores gs
           JOIN genomes g ON g.id = gs.genome_id AND g.profile = %s
           WHERE gs.environment_id = %s AND gs.pulls > 0 AND g.family != 'control'""",
        (profile, environment_id),
    )
    return cur.fetchall()


def upsert_genome_score(conn, genome_id, environment_id, success: bool, reward: float):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO genome_scores (genome_id, environment_id, pulls, successes, total_reward)
           VALUES (%s,%s,1,%s,%s)
           ON DUPLICATE KEY UPDATE
             pulls = pulls + 1,
             successes = successes + %s,
             total_reward = total_reward + %s""",
        (genome_id, environment_id, int(success), reward, int(success), reward),
    )


def upsert_operator_stat(conn, environment_id, filter_type, operator, reward):
    if not operator:
        return
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO operator_stats (environment_id, filter_type, operator, pulls, total_reward)
           VALUES (%s,%s,%s,1,%s)
           ON DUPLICATE KEY UPDATE pulls = pulls + 1, total_reward = total_reward + %s""",
        (environment_id, filter_type, operator, reward, reward),
    )


def get_operator_stats(conn, environment_id, filter_type):
    cur = conn.cursor(dictionary=True)
    cur.execute(
        "SELECT operator, pulls, total_reward FROM operator_stats WHERE environment_id=%s AND filter_type=%s",
        (environment_id, filter_type),
    )
    return {row["operator"]: row for row in cur.fetchall()}


def recent_domain_experiments(conn, domain_id, limit=5):
    """Для circuit breaker'а: смотрим на корреляцию провалов МЕЖДУ разными
    геномами на одном домене, а не на один провалившийся геном."""
    cur = conn.cursor(dictionary=True)
    cur.execute(
        """SELECT genome_id, success FROM experiments
           WHERE domain_id=%s ORDER BY tested_at DESC LIMIT %s""",
        (domain_id, limit),
    )
    return cur.fetchall()


def log_ban_event(conn, environment_id, domain_id, reason, cooldown_seconds):
    cur = conn.cursor()
    cur.execute(
        """INSERT INTO ban_events (environment_id, domain_id, trigger_reason, cooldown_until)
           VALUES (%s,%s,%s, NOW() + INTERVAL %s SECOND)""",
        (environment_id, domain_id, reason, cooldown_seconds),
    )
