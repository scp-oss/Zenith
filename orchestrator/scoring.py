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
