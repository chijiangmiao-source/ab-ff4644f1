"""Exact, arbitrary-precision comparison of two stochastic procedures.

A *procedure* is defined by:

* a finite ordered set of states ``0..n-1``,
* an initial rational distribution ``pi`` over those states,
* a set of safe states,
* a finite alphabet of ASCII commands,
* one row-stochastic rational transition matrix per command.

For a command word ``w = c1 c2 ... ck`` the final distribution is
``pi * M_{c1} * ... * M_{ck}`` and the probability of ending in a safe
state is the corresponding linear functional applied to it.

Two procedures are equivalent iff their safe probabilities agree for
**every** finite word (including the empty word).

The decision procedure below never enumerates words up to a length bound
and never uses floating point.  Reaching a word under the two procedures
yields a pair of row vectors ``(u, v)`` embedded in ``Q^(n_a+n_b)``.  A
newly reached pair is expanded only when it is linearly independent of
the previously accumulated pairs (exact Gaussian elimination over the
rationals).  The ambient space has finite dimension, so the expansion
terminates after at most ``n_a+n_b`` basis elements.

Soundness of the pruning: every pair admitted to the basis is checked to
be orthogonal to ``g = (1_S | -1_S)`` (otherwise it is a witness).  A
pair lying in the basis span is therefore itself orthogonal to ``g``, so
discarding it can never discard a witness.  Its descendants are reached
through the basis nodes anyway because the transition maps are linear.

The shortest witness (and, among words of equal length, the ASCII
lexicographically smallest one) is obtained by exploring pairs in BFS
order with commands sorted by ASCII code.
"""

from __future__ import annotations

from fractions import Fraction
from math import gcd
from dataclasses import dataclass, field


def _lcm(x, y):
    return x // gcd(x, y) * y


def _primitive(vec):
    """Convert a rational vector to a primitive integer vector.

    All entries are scaled by their common denominator, then divided by
    the gcd of the resulting integers.  This keeps a canonical,
    digit-minimal representative and prevents denominators compounding
    during Gaussian elimination.  Scaling does not change membership in a
    rational span.
    """
    den = 1
    for x in vec:
        if x.denominator != 1:
            den = _lcm(den, x.denominator)
    nums = [int(x * den) for x in vec]
    g = 0
    for z in nums:
        g = gcd(g, abs(z))
    if g > 1:
        nums = [z // g for z in nums]
    return tuple(nums)


class ValidationError(Exception):
    """Structured, field-locatable validation errors.

    Each error is a dict::

        {"side": "a"|"b", "area": str, "message": str,
         "index": int|None, "command": str|None,
         "row": int|None, "col": int|None}
    """

    def __init__(self, errors):
        self.errors = list(errors)
        super().__init__("; ".join(e["message"] for e in self.errors))


# ---------------------------------------------------------------------------
# Rational linear algebra
# ---------------------------------------------------------------------------


def in_span(x, basis_with_pivots):
    """Exact rational-span membership test.

    ``x`` is a rational vector; ``basis_with_pivots`` is a list of
    primitive integer rows ``(vector, pivot_column)`` in row-echelon
    style.  Elimination uses exact integer cross multiplication
    (``v := b[p]*v - v[p]*b``) followed by gcd normalization, so no
    denominators ever accumulate.
    """
    v = list(_primitive(x))
    for b, p in basis_with_pivots:
        if v[p] != 0:
            scale = b[p]
            v = [scale * y - v[p] * z for y, z in zip(v, b)]
            g = 0
            for z in v:
                g = gcd(g, abs(z))
            if g > 1:
                v = [z // g for z in v]
    return all(y == 0 for y in v)


# ---------------------------------------------------------------------------
# Parsing / validation
# ---------------------------------------------------------------------------


def parse_fraction(text):
    """Parse ``p/q`` or an integer as an exact :class:`Fraction`.

    Raises ``ValueError`` with a descriptive message on bad syntax or a
    zero denominator.
    """
    if text is None:
        raise ValueError("缺失")
    s = str(text).strip()
    if not s:
        raise ValueError("空分数")
    if "/" in s:
        num_s, den_s = s.split("/", 1)
        num_s, den_s = num_s.strip(), den_s.strip()
        if not num_s or not den_s:
            raise ValueError("分数格式应为 p/q")
        try:
            num = int(num_s)
            den = int(den_s)
        except ValueError:
            raise ValueError("分子分母必须是整数")
        if den == 0:
            raise ValueError("分母不能为零")
        if den < 0:
            num, den = -num, -den
        return Fraction(num, den)
    try:
        return Fraction(int(s), 1)
    except ValueError:
        raise ValueError("不是合法整数或 p/q 分数")


def frac_str(v: Fraction | None) -> str:
    if v is None:
        return "未定义"
    if v.denominator == 1:
        return str(v.numerator)
    return f"{v.numerator}/{v.denominator}"


@dataclass
class Procedure:
    side: str
    states: list[str]
    initial: list[Fraction]
    safe: list[bool]
    commands: list[str]
    matrices: dict[str, list[list[Fraction]]]

    @property
    def n(self):
        return len(self.states)


def _err(side, area, message, index=None, command=None, row=None, col=None):
    return {
        "side": side,
        "area": area,
        "message": message,
        "index": index,
        "command": command,
        "row": row,
        "col": col,
    }


def _parse_command(raw, side, i, errors):
    if raw is None:
        errors.append(_err(side, "commands", "命令缺失", index=i))
        return None
    ch = str(raw).strip()
    if len(ch) != 1:
        errors.append(_err(side, "commands", "每条命令必须是单个 ASCII 字符", index=i))
        return None
    if ord(ch) > 127:
        errors.append(_err(side, "commands", "命令必须是 ASCII 字符", index=i))
        return None
    return ch


def _ch_label(ch):
    if ch == " ":
        return "空格(0x20)"
    if ch.isprintable():
        return ch
    return f"0x{ord(ch):02X}"


def build_procedure(spec, side):
    """Validate a raw JSON-ish spec and build a :class:`Procedure`.

    All problems found are collected into structured errors and raised
    together as :class:`ValidationError`.
    """
    errors = []
    if not isinstance(spec, dict):
        raise ValidationError([_err(side, "form", "规程数据格式错误")])

    raw_states = spec.get("states", [])
    states = [str(s).strip() for s in raw_states] if isinstance(raw_states, list) else []
    if not states:
        errors.append(_err(side, "states", "至少需要一个状态"))
    seen = set()
    for i, name in enumerate(states):
        if not name:
            errors.append(_err(side, "states", "状态名不能为空", index=i))
        if name in seen:
            errors.append(_err(side, "states", f"状态名重复 “{name}”", index=i))
        seen.add(name)

    n = len(states)
    index = {name: i for i, name in enumerate(states)}

    # ---- initial distribution ------------------------------------------
    raw_init = spec.get("initial", [])
    initial = [Fraction(0)] * n
    init_parse_failed = False
    if isinstance(raw_init, list) and len(raw_init) == n:
        for i, cell in enumerate(raw_init):
            try:
                v = parse_fraction(cell)
            except ValueError as exc:
                errors.append(_err(side, "initial", f"{exc}", index=i))
                init_parse_failed = True
                continue
            if v < 0:
                errors.append(_err(side, "initial", "初始概率不能为负", index=i))
                init_parse_failed = True
            initial[i] = v
        if not init_parse_failed:
            total = sum(initial)
            if total != 1:
                errors.append(
                    _err(side, "initial", f"初始概率之和必须为 1，当前为 {frac_str(total)}")
                )
    else:
        errors.append(_err(side, "initial", f"必须为每个状态填写初始概率（共 {n} 项）"))

    # ---- safe states ----------------------------------------------------
    raw_safe = spec.get("safe", [])
    safe = [False] * n
    if not isinstance(raw_safe, list):
        errors.append(_err(side, "safe", "安全状态数据格式错误"))
        raw_safe = []
    for item in raw_safe:
        name = str(item).strip()
        if name in index:
            safe[index[name]] = True
        else:
            errors.append(_err(side, "safe", f"安全状态 “{item}” 不在状态列表中（悬空状态）"))
    if not any(safe):
        errors.append(_err(side, "safe", "必须至少指定一个安全状态"))

    # ---- commands -------------------------------------------------------
    raw_commands = spec.get("commands", []) or []
    commands = []
    if not isinstance(raw_commands, list):
        errors.append(_err(side, "commands", "命令数据格式错误"))
        raw_commands = []
    for i, c in enumerate(raw_commands):
        ch = _parse_command(c, side, i, errors)
        if ch is None:
            continue
        if ch in commands:
            errors.append(_err(side, "commands", f"命令 “{_ch_label(ch)}” 重复", index=i))
            continue
        commands.append(ch)
    commands.sort(key=ord)

    # ---- matrices -------------------------------------------------------
    matrices = {}
    raw_matrices = spec.get("matrices", {})
    if not isinstance(raw_matrices, dict):
        errors.append(_err(side, "matrices", "转移矩阵数据格式错误"))
        raw_matrices = {}

    for ch in commands:
        mat = [[Fraction(0) for _ in range(n)] for _ in range(n)]
        mraw = raw_matrices.get(ch)
        if mraw is None:
            errors.append(_err(side, "matrices", f"缺少命令 “{_ch_label(ch)}” 的转移矩阵", command=ch))
            matrices[ch] = mat
            continue
        shape_ok = (
            isinstance(mraw, list)
            and len(mraw) == n
            and all(isinstance(row, list) and len(row) == n for row in mraw)
        )
        if not shape_ok:
            errors.append(
                _err(side, "matrices", f"命令 “{_ch_label(ch)}” 的矩阵必须为 {n}×{n}", command=ch)
            )
            matrices[ch] = mat
            continue

        parse_failed = False
        for i in range(n):
            for j in range(n):
                try:
                    v = parse_fraction(mraw[i][j])
                except ValueError as exc:
                    errors.append(
                        _err(
                            side,
                            "matrices",
                            f"{states[i]}→{states[j]}: {exc}",
                            command=ch,
                            row=i,
                            col=j,
                        )
                    )
                    parse_failed = True
                    continue
                if v < 0:
                    errors.append(
                        _err(
                            side,
                            "matrices",
                            f"{states[i]}→{states[j]}: 转移概率不能为负",
                            command=ch,
                            row=i,
                            col=j,
                        )
                    )
                    parse_failed = True
                mat[i][j] = v
        if not parse_failed:
            for i in range(n):
                total = sum(mat[i])
                if total != 1:
                    errors.append(
                        _err(
                            side,
                            "matrices",
                            f"命令 “{_ch_label(ch)}”：行 “{states[i]}” 转出概率之和必须为 1，当前为 {frac_str(total)}",
                            command=ch,
                            row=i,
                        )
                    )
        matrices[ch] = mat

    for key in (raw_matrices.keys() if isinstance(raw_matrices, dict) else []):
        s = str(key)
        if len(s) == 1 and ord(s) <= 127 and s not in commands:
            errors.append(
                _err(side, "matrices", f"命令 “{_ch_label(s)}” 的矩阵存在，但该命令未在命令列表中声明", command=s)
            )

    if errors:
        raise ValidationError(errors)

    return Procedure(side, states, initial, safe, commands, matrices)


# ---------------------------------------------------------------------------
# Exact equivalence decision
# ---------------------------------------------------------------------------


@dataclass
class Step:
    command: str | None
    distribution: list[Fraction]
    safe_prob: Fraction | None


@dataclass
class Witness:
    word: str
    steps_a: list[Step] = field(default_factory=list)
    steps_b: list[Step] = field(default_factory=list)
    final_a: Fraction | None = None
    final_b: Fraction | None = None

    @property
    def difference(self):
        if self.final_a is None or self.final_b is None:
            return None
        return self.final_a - self.final_b


def compare_procedures(a: Procedure, b: Procedure):
    """Return ``None`` if equivalent, else the minimal :class:`Witness`.

    Minimal means shortest word, and among equal-length words the ASCII
    lexicographically smallest one (commands are processed in ASCII
    order in BFS).
    """
    # An alphabet mismatch makes the one-letter word incomparable: on the
    # side lacking the command there is no defined transition.
    only_a = sorted(set(a.commands) - set(b.commands))
    only_b = sorted(set(b.commands) - set(a.commands))
    if only_a or only_b:
        return _missing_command_witness(a, b, (only_a or only_b)[0], "a" if only_a else "b")

    commands = a.commands  # ASCII sorted, identical on both sides
    n_a, n_b = a.n, b.n

    g_a = [Fraction(1) if s else Fraction(0) for s in a.safe]
    g_b = [Fraction(1) if s else Fraction(0) for s in b.safe]

    def safe_probs(u, v):
        return (
            sum(x * y for x, y in zip(u, g_a)),
            sum(x * y for x, y in zip(v, g_b)),
        )

    root = (tuple(a.initial), tuple(b.initial))
    pa0, pb0 = safe_probs(a.initial, b.initial)
    if pa0 != pb0:
        return _build_witness(a, b, "", g_a, g_b)

    # Echelon basis of embedded reachable pairs, kept as primitive
    # integer vectors with strictly increasing pivot columns.
    pivot = next(j for j, x in enumerate(tuple(root[0]) + tuple(root[1])) if x != 0)
    basis = [(_primitive(root[0] + root[1]), pivot)]

    queue = [{"word": "", "u": list(a.initial), "v": list(b.initial)}]
    head = 0
    while head < len(queue):
        node = queue[head]
        head += 1
        u, v, word = node["u"], node["v"], node["word"]
        for ch in commands:
            Ma, Mb = a.matrices[ch], b.matrices[ch]
            nu = tuple(sum(u[i] * Ma[i][j] for i in range(n_a)) for j in range(n_a))
            nv = tuple(sum(v[i] * Mb[i][j] for i in range(n_b)) for j in range(n_b))
            nword = word + ch

            pa, pb = safe_probs(nu, nv)
            if pa != pb:
                return _build_witness(a, b, nword, g_a, g_b)

            pair = nu + nv
            if in_span(pair, basis):
                continue
            reduced = list(_primitive(pair))
            for bv, p in basis:
                if reduced[p] != 0:
                    reduced = [bv[p] * y - reduced[p] * z for y, z in zip(reduced, bv)]
                    g = 0
                    for z in reduced:
                        g = gcd(g, abs(z))
                    if g > 1:
                        reduced = [z // g for z in reduced]
            piv = next(j for j, x in enumerate(reduced) if x != 0)
            basis.append((tuple(reduced), piv))
            queue.append({"word": nword, "u": list(nu), "v": list(nv)})
            # Pairs live in dimension n_a+n_b; reaching full rank with
            # every basis vector g-orthogonal proves equivalence.
            if len(basis) >= n_a + n_b:
                return None
    return None


def _apply_prefix(proc: Procedure, prefix: str | None):
    """Replay a concrete word, returning per-step distributions."""
    u = list(proc.initial)
    dists = [list(u)]
    for ch in prefix or "":
        M = proc.matrices[ch]
        u = [sum(u[i] * M[i][j] for i in range(proc.n)) for j in range(proc.n)]
        dists.append(list(u))
    return dists


def _build_witness(a, b, word, g_a, g_b) -> Witness:
    da = _apply_prefix(a, word)
    db = _apply_prefix(b, word)
    w = Witness(word=word)
    w.steps_a = [
        Step(None if k == 0 else word[k - 1], d, sum(x * y for x, y in zip(d, g_a)))
        for k, d in enumerate(da)
    ]
    w.steps_b = [
        Step(None if k == 0 else word[k - 1], d, sum(x * y for x, y in zip(d, g_b)))
        for k, d in enumerate(db)
    ]
    w.final_a = w.steps_a[-1].safe_prob
    w.final_b = w.steps_b[-1].safe_prob
    return w


def _missing_command_witness(a, b, ch, side):
    g_a = [Fraction(1) if s else Fraction(0) for s in a.safe]
    g_b = [Fraction(1) if s else Fraction(0) for s in b.safe]
    w = Witness(word=ch)
    if side == "a":
        da = _apply_prefix(a, ch)
        w.steps_a = [
            Step(None if k == 0 else ch, d, sum(x * y for x, y in zip(d, g_a)))
            for k, d in enumerate(da)
        ]
        d0 = list(b.initial)
        w.steps_b = [Step(None, d0, sum(x * y for x, y in zip(d0, g_b)))]
        w.final_a = w.steps_a[-1].safe_prob
        w.final_b = None
    else:
        db = _apply_prefix(b, ch)
        d0 = list(a.initial)
        w.steps_a = [Step(None, d0, sum(x * y for x, y in zip(d0, g_a)))]
        w.steps_b = [
            Step(None if k == 0 else ch, d, sum(x * y for x, y in zip(d, g_b)))
            for k, d in enumerate(db)
        ]
        w.final_a = None
        w.final_b = w.steps_b[-1].safe_prob
    return w
