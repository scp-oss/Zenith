"""Mutation operators over a Genome, plus the escalation chain that biases
which operator UCB should try first on a failing parent (see README:
"Мутация по цепочке эскалации, а не вслепую").

Every operator is a pure function: Genome -> new Genome (parent unchanged).
Operator names are the fixed arms UCB picks between -- keep this list
short and meaningful, not "every possible parameter combination".
"""
import copy
from dataclasses import replace
from genome import Genome

# Полный набор маркеров позиции из манула zapret2 (числовые + логические
# для tls_client_hello/http_req), не только 4 исходных. sniext+1/sniext+4
# добавлены не наугад -- это подтверждённые боевые значения из реального
# конфига (strategy=4/6 z2r), которые мы раньше вообще не генерировали.
POS_MARKERS = ("1", "2", "sld", "endsld", "midsld", "host", "endhost", "sniext+1", "sniext+4", "extlen")


def mutate_ttl_fixed(g: Genome) -> Genome:
    cur = 6
    if g.ttl_mode and g.ttl_mode.startswith("fixed:"):
        try:
            cur = int(g.ttl_mode.split(":", 1)[1])
        except ValueError:
            pass
    nxt = cur + 1 if cur < 10 else 3
    return replace(g, ttl_mode=f"fixed:{nxt}", source="mutation", mutation_op="mutate_ttl_fixed")


def mutate_ttl_autottl(g: Genome) -> Genome:
    return replace(g, ttl_mode="autottl:1,3-64", source="mutation", mutation_op="mutate_ttl_autottl")


def mutate_add_tcp_ts(g: Genome) -> Genome:
    fooling = _add_fooling(g.fooling, "tcp_ts=-1")
    return replace(g, fooling=fooling, source="mutation", mutation_op="mutate_add_tcp_ts")


def mutate_add_tcp_md5(g: Genome) -> Genome:
    fooling = _add_fooling(g.fooling, "tcp_md5")
    return replace(g, fooling=fooling, source="mutation", mutation_op="mutate_add_tcp_md5")


def mutate_to_multisplit(g: Genome) -> Genome:
    return replace(
        g, family="multisplit", pos="2", fake_payload=None,
        source="mutation", mutation_op="mutate_to_multisplit",
    )


def mutate_to_multidisorder(g: Genome) -> Genome:
    return replace(
        g, family="multidisorder", pos="midsld", fake_payload=None,
        source="mutation", mutation_op="mutate_to_multidisorder",
    )


def mutate_to_fakeddisorder(g: Genome) -> Genome:
    return replace(
        g, family="fakeddisorder", pos="midsld", fake_payload=None,
        seqovl=None, nodrop=False,
        source="mutation", mutation_op="mutate_to_fakeddisorder",
    )


def mutate_to_hostfakesplit(g: Genome) -> Genome:
    """hostfakesplit требует фулинга на фейковых частях, иначе сервер их
    примет -- tcp_ack=-66000:tcp_ts_up это самая частая связка в реальном
    боевом конфиге (strategy=11/12/15/133/137 и т.д.), не наугад
    подобрано. pos тут не используется как cut-маркер multisplit'а,
    render_args() в genome.py сам рендерит его как midhost=."""
    fooling = _add_fooling(g.fooling, "tcp_ack=-66000")
    fooling = _add_fooling(fooling, "tcp_ts_up")
    return replace(
        g, family="hostfakesplit", pos=None, seqovl=None, nodrop=False,
        fake_payload=None, fooling=fooling,
        source="mutation", mutation_op="mutate_to_hostfakesplit",
    )


def mutate_add_disorder_after(g: Genome) -> Genome:
    """Только для hostfakesplit -- реальная связка disorder_after
    (strategy=14/15/134/136/166), без явного значения маркера (боевой
    конфиг тоже так делает -- голый флаг)."""
    if g.family != "hostfakesplit":
        return replace(g, source="mutation", mutation_op="mutate_add_disorder_after")
    return replace(g, disorder_after=True, source="mutation", mutation_op="mutate_add_disorder_after")


def mutate_add_midhost(g: Genome) -> Genome:
    """Только для hostfakesplit -- задать midhost (реальный пример:
    strategy=138, midhost=midsld)."""
    if g.family != "hostfakesplit":
        return replace(g, source="mutation", mutation_op="mutate_add_midhost")
    return replace(g, pos="midsld", source="mutation", mutation_op="mutate_add_midhost")


def mutate_add_blob_nodrop(g: Genome) -> Genome:
    """Только для multisplit/multidisorder -- подмена пейлоада на фейковый
    blob + nodrop, тот же паттерн, что боевая strategy=5
    (multisplit:blob=fake_default_tls:...:nodrop)."""
    if g.family not in ("multisplit", "multidisorder"):
        return replace(g, source="mutation", mutation_op="mutate_add_blob_nodrop")
    return replace(
        g, fake_payload="fake_default_tls", nodrop=True,
        source="mutation", mutation_op="mutate_add_blob_nodrop",
    )


def mutate_pos(g: Genome) -> Genome:
    cur = g.pos or "2"
    idx = POS_MARKERS.index(cur) if cur in POS_MARKERS else -1
    nxt = POS_MARKERS[(idx + 1) % len(POS_MARKERS)]
    return replace(g, pos=nxt, source="mutation", mutation_op="mutate_pos")


def mutate_seqovl(g: Genome) -> Genome:
    seqovl = "midsld-1" if g.family == "multidisorder" else "1"
    return replace(g, seqovl=seqovl, source="mutation", mutation_op="mutate_seqovl")


def mutate_add_repeats(g: Genome) -> Genome:
    """repeats= -- confirmed real usage: RKN_TLS боевая strategy=1
    (fake:blob=fake_default_tls:tcp_ts=-1000:repeats=2). Cycles 2 -> 3 ->
    off, since the manual doesn't document a max and we have exactly one
    confirmed real value (2) to anchor near."""
    nxt = {None: 2, 2: 3}.get(g.repeats, None)
    return replace(g, repeats=nxt, source="mutation", mutation_op="mutate_add_repeats")


def mutate_pos_combine(g: Genome) -> Genome:
    """Комбинирует ТЕКУЩИЙ маркер с ещё одним через запятую -- pos=
    принимает список (манул: `100,midsld,sniext+1,...`), и реальная боевая
    RKN_TLS strategy=1 использует именно двухмаркерный список
    (multisplit:pos=1,midsld), а не одиночный маркер. Наша модель раньше
    такое не генерировала (только сырые controls.py могли)."""
    if g.family not in ("multisplit", "multidisorder", "fakeddisorder"):
        return replace(g, source="mutation", mutation_op="mutate_pos_combine")
    existing = (g.pos or "2").split(",")
    for candidate in ("1", "midsld"):
        if candidate not in existing:
            combined = ",".join(existing + [candidate])
            return replace(g, pos=combined, source="mutation", mutation_op="mutate_pos_combine")
    return replace(g, pos="1,midsld", source="mutation", mutation_op="mutate_pos_combine")


def _add_fooling(existing: str, addition: str) -> str:
    if not existing:
        return addition
    parts = existing.split(":")
    if addition.split("=")[0] in [p.split("=")[0] for p in parts]:
        return existing
    return existing + ":" + addition


OPERATORS = {
    "mutate_ttl_fixed": mutate_ttl_fixed,
    "mutate_ttl_autottl": mutate_ttl_autottl,
    "mutate_add_tcp_ts": mutate_add_tcp_ts,
    "mutate_add_tcp_md5": mutate_add_tcp_md5,
    "mutate_to_multisplit": mutate_to_multisplit,
    "mutate_to_multidisorder": mutate_to_multidisorder,
    "mutate_to_fakeddisorder": mutate_to_fakeddisorder,
    "mutate_add_blob_nodrop": mutate_add_blob_nodrop,
    "mutate_to_hostfakesplit": mutate_to_hostfakesplit,
    "mutate_add_disorder_after": mutate_add_disorder_after,
    "mutate_add_midhost": mutate_add_midhost,
    "mutate_pos": mutate_pos,
    "mutate_seqovl": mutate_seqovl,
    "mutate_add_repeats": mutate_add_repeats,
    "mutate_pos_combine": mutate_pos_combine,
}

# Порядок эскалации со слов автора z2r: TTL не проходит -> autottl -> DPI
# научился детектить кривой TTL -> tcp_ts -> tcp_ts ломает сайты ->
# tcp_md5(+seqovl) -> известные фейки палятся -> сегментация (multisplit/
# multidisorder/fakeddisorder). Не жёсткая ветка, а приоритет: применяется
# как более высокая стартовая оценка для UCB, а не единственный
# разрешённый путь. mutate_to_fakeddisorder/mutate_add_blob_nodrop
# добавлены после живой проверки 2026-08-06 -- боевая strategy=5
# (multisplit+blob+nodrop, затем fakeddisorder) сработала там, где 4
# более простых сгенерированных генома подряд провалились.
# mutate_to_hostfakesplit идёт ближе к концу цепочки -- это самая
# продвинутая техника разреза (замешивание фейков прямо в имя хоста),
# логично пробовать после более простых сегментаций, а не раньше них.
#
# mutate_add_repeats поставлен рядом с tcp_md5 -- дешёвый, подтверждённый
# боевой параметр (RKN_TLS strategy=1), не требует смены family.
# mutate_pos_combine -- сразу после mutate_pos/mutate_seqovl, т.к. это тоже
# уточнение сегментации, но воспроизводит конкретно боевой RKN_TLS
# strategy=1 паттерн (pos=1,midsld), который одиночные маркеры не покрывают.
ESCALATION_ORDER = [
    "mutate_ttl_fixed",
    "mutate_ttl_autottl",
    "mutate_add_tcp_ts",
    "mutate_add_tcp_md5",
    "mutate_add_repeats",
    "mutate_to_multisplit",
    "mutate_add_blob_nodrop",
    "mutate_pos",
    "mutate_seqovl",
    "mutate_pos_combine",
    "mutate_to_multidisorder",
    "mutate_to_fakeddisorder",
    "mutate_to_hostfakesplit",
    "mutate_add_disorder_after",
    "mutate_add_midhost",
]


def apply_operator(g: Genome, op_name: str) -> Genome:
    fn = OPERATORS.get(op_name)
    if not fn:
        raise ValueError(f"unknown operator: {op_name}")
    child = fn(g)
    child.parent1_id = g.compute_id()
    child.parent2_id = None
    child.generation = g.generation + 1
    return child


def crossover(a: Genome, b: Genome) -> Genome:
    """Скрещивание: family/pos/seqovl от a, fooling/ttl_mode от b."""
    if a.profile != b.profile:
        raise ValueError("crossover across different profiles doesn't make sense")
    child = Genome(
        profile=a.profile,
        family=a.family,
        pos=a.pos,
        seqovl=a.seqovl,
        fake_payload=a.fake_payload,
        fooling=b.fooling,
        ttl_mode=b.ttl_mode,
        source="crossover",
        parent1_id=a.compute_id(),
        parent2_id=b.compute_id(),
        generation=max(a.generation, b.generation) + 1,
    )
    return child
