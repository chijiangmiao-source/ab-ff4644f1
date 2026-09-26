"""HTTP API for exact stochastic-procedure equivalence review."""

from __future__ import annotations

import os
from fractions import Fraction

from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .equivalence import (
    Procedure,
    ValidationError,
    Witness,
    build_procedure,
    compare_procedures,
)

APP_PORT = int(os.environ.get("APP_PORT", "8080"))

app = FastAPI(title="声学应急控制器规程等价复核", version="1.0")


class CompareRequest(BaseModel):
    a: dict
    b: dict


def _frac(v: Fraction | None):
    if v is None:
        return None
    if v.denominator == 1:
        return str(v.numerator)
    return f"{v.numerator}/{v.denominator}"


def _float_like(v: Fraction | None):
    """A decimal companion used purely for display, never for the verdict."""
    if v is None:
        return None
    return float(v)  # noqa: B008 (display only; comparison used exact rationals)


def _serialize_witness(w: Witness, a: Procedure, b: Procedure):
    steps = []
    max_steps = max(len(w.steps_a), len(w.steps_b))
    for k in range(max_steps):
        sa = w.steps_a[k] if k < len(w.steps_a) else None
        sb = w.steps_b[k] if k < len(w.steps_b) else None
        cmd = (sa.command if sa is not None else None) or (
            sb.command if sb is not None else None
        )
        steps.append(
            {
                "index": k,
                "command": cmd,
                "distA": [_frac(x) for x in sa.distribution] if sa is not None else [],
                "distB": [_frac(x) for x in sb.distribution] if sb is not None else [],
                "safeA": _frac(sa.safe_prob) if sa is not None else None,
                "safeB": _frac(sb.safe_prob) if sb is not None else None,
            }
        )
    diff = None
    if w.final_a is not None and w.final_b is not None:
        diff = w.final_a - w.final_b
    return {
        "word": w.word,
        "length": len(w.word),
        "wordCodes": [ord(c) for c in w.word],
        "steps": steps,
        "statesA": a.states,
        "statesB": b.states,
        "finalA": _frac(w.final_a),
        "finalB": _frac(w.final_b),
        "difference": _frac(diff),
        "differenceDecimal": _float_like(diff),
        "note": (
            "该命令仅在一侧规程中定义，命令串在另一侧无对应转移，无法比较"
            if (w.final_a is None or w.final_b is None)
            else None
        ),
    }


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/api/compare")
def compare(req: CompareRequest):
    try:
        pa = build_procedure(req.a, "a")
        pb = build_procedure(req.b, "b")
    except ValidationError as exc:
        # 422 with located errors; the client clears any stale conclusion.
        return JSONResponse(
            status_code=422,
            content={"ok": False, "errors": exc.errors},
        )

    witness = compare_procedures(pa, pb)
    if witness is None:
        return {
            "ok": True,
            "equivalent": True,
            "message": "两份规程对任意有限命令串的最终安全态概率均精确相等（有理数精确判定）。",
            "alphabet": pa.commands,
            "statesA": pa.states,
            "statesB": pb.states,
        }
    return {
        "ok": True,
        "equivalent": False,
        "message": "存在安全概率不一致的命令串，以下为按长度最短、同长度按 ASCII 字典序最小的反例。",
        "alphabet": sorted(set(pa.commands) | set(pb.commands)),
        "statesA": pa.states,
        "statesB": pb.states,
        "witness": _serialize_witness(witness, pa, pb),
    }


@app.get("/")
def index():
    return FileResponse(os.path.join(os.path.dirname(__file__), "..", "static", "index.html"))


app.mount("/static", StaticFiles(directory=os.path.join(os.path.dirname(__file__), "..", "static")), name="static")
