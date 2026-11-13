"""Reward function for UCB/genome_scores. Раньше был чисто бинарным
(1.0/0.0) — байты/latency писались в experiments, но не влияли на выбор.
Теперь скорость тоже участвует: из двух одинаково успешных геномов UCB
предпочтёт более быстрый, но провал всегда хуже любого успеха (floor).
"""

LATENCY_PENALTY_MS = 3000  # к этому порогу штраф за задержку выходит на максимум
MIN_SUCCESS_REWARD = 0.5   # даже самый медленный успех не хуже провала с запасом


def compute_reward(success: bool, latency_ms: int) -> float:
    if not success:
        return 0.0
    penalty_fraction = min(max(latency_ms, 0) / LATENCY_PENALTY_MS, 1.0)
    return 1.0 - penalty_fraction * (1.0 - MIN_SUCCESS_REWARD)


GV_TARGET_BPS = 4_000_000  # 4 МБ/с -- с запасом хватает на 1080p; быстрее не поощряем


def compute_reward_throughput(success: bool, bytes_: int, latency_ms: int) -> float:
    """Для GV_TLS: wssize_ramp режет скорость (на NETH-4 ~65 -> ~16 МБ/с),
    поэтому из двух рабочих геномов UCB должен предпочесть более быстрый.
    Провал = 0, любой успех >= MIN_SUCCESS_REWARD."""
    if not success:
        return 0.0
    bps = bytes_ / max(latency_ms / 1000.0, 0.001)
    return MIN_SUCCESS_REWARD + (1.0 - MIN_SUCCESS_REWARD) * min(bps / GV_TARGET_BPS, 1.0)
