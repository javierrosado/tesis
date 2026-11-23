#!/usr/bin/env python3
"""Contraste estadístico de H1–H6: piloto (G2) frente a la línea base (protocolo F5 v2 y Tabla 9 del Plan V2.7).

Grupos:
  G1* población sin el squad del piloto (n = 123)   · G1′ Squad Fuerza de Ventas, histórico (n = 27, SIM-P05-R001…R027)
  G2  piloto (hasta 30 requerimientos; R001…R027 emparejados con G1′, R028…R030 nuevos)

Pruebas (unilaterales, α = 5 %, Holm sobre H1–H3):
  H1  Wilcoxon de rangos con signo, 27 pares (G2 vs. G1′) · respaldo: Mann-Whitney G2 vs. G1*, global y por complejidad
      Efecto: Hodges-Lehmann de las diferencias con IC 95 % bootstrap (10 000 réplicas, semilla 2026).
  H2  Exacta de Fisher, despliegues del piloto vs. 40 históricos · IC 95 % de Newcombe (método 10) de la diferencia.
  H3  McNemar exacta, 27 pares · respaldo: Fisher G2 vs. G1* · IC 95 % de Newcombe para datos pareados.
  H4  Umbral (descriptivo): despliegues exitosos por mes con IC 95 % exacto de Poisson.
  H5, H6  Umbral: proporción con IC 95 % de Clopper-Pearson.
Regla: se acepta H1–H3 si se alcanza la meta y el p ajustado < 0,05; meta sin significación = mejora no concluyente.
Sensibilidad: H1 y H3 sin los requerimientos nuevos y sin los casos censurados.

Definiciones de la línea base: lead time = fecha_fin_pruebas − fecha_registro (registro → fin de pruebas, sin la espera
de la ventana de release); defecto = detectado en producción; despliegue fallido = columna «fallido».

Uso:
  python scripts/contraste.py --piloto piloto_por_req.csv [--linea-base data/linea_base/Linea_BaseV2.xlsx] [--md contraste.md] [--json contraste.json]
  (el CSV sale de: python scripts/indicadores.py ... --estado ... --piloto piloto1 --csv-req piloto_por_req.csv)
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.multitest import multipletests
from statsmodels.stats.proportion import proportion_confint

ROOT = Path(__file__).resolve().parents[1]
SQUAD = "SIM-P05"
SEMILLA, REPLICAS, ALFA = 2026, 10_000, 0.05
METAS = {"H1_d": 7.0, "H2": 0.15, "H4": 1.5, "H5": 1.0, "H6_auto": 0.90, "H6_reg": 1.0}


# ---------- intervalos ----------
def wilson(x: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    if n == 0:
        return (0.0, 1.0)
    p = x / n; den = 1 + z * z / n
    c = (p + z * z / (2 * n)) / den; h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return (max(0.0, c - h), min(1.0, c + h))


def newcombe_independiente(x1: int, n1: int, x2: int, n2: int) -> tuple[float, float, float]:
    """Diferencia p1 − p2 con IC 95 % de Newcombe (1998), método 10 (híbrido de Wilson)."""
    p1, p2 = x1 / n1, x2 / n2; l1, u1 = wilson(x1, n1); l2, u2 = wilson(x2, n2); d = p1 - p2
    return d, d - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2), d + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)


def newcombe_pareado(a: int, b: int, c: int, d: int) -> tuple[float, float, float]:
    """Diferencia p1 − p2 en datos pareados (p1 = (a+b)/n, p2 = (a+c)/n) con IC 95 % de Newcombe (1998b), método 10."""
    n = a + b + c + d; p1, p2 = (a + b) / n, (a + c) / n
    l1, u1 = wilson(a + b, n); l2, u2 = wilson(a + c, n)
    den = math.sqrt((a + b) * (c + d) * (a + c) * (b + d))
    phi = (a * d - b * c) / den if den else 0.0
    th = p1 - p2
    dl = (p1 - l1) ** 2 - 2 * phi * (p1 - l1) * (u2 - p2) + (u2 - p2) ** 2
    du = (u1 - p1) ** 2 - 2 * phi * (u1 - p1) * (p2 - l2) + (p2 - l2) ** 2
    return th, th - math.sqrt(max(dl, 0)), th + math.sqrt(max(du, 0))


def hodges_lehmann(d: np.ndarray) -> float:
    w = (d[:, None] + d[None, :]) / 2
    return float(np.median(w[np.triu_indices(len(d))]))


def hl_bootstrap(d: np.ndarray) -> tuple[float, float, float]:
    rng = np.random.default_rng(SEMILLA)
    reps = [hodges_lehmann(d[rng.integers(0, len(d), len(d))]) for _ in range(REPLICAS)]
    return hodges_lehmann(d), float(np.percentile(reps, 2.5)), float(np.percentile(reps, 97.5))


def poisson_exacto(k: int, t: float) -> tuple[float, float, float]:
    lo = stats.chi2.ppf(ALFA / 2, 2 * k) / 2 if k > 0 else 0.0
    hi = stats.chi2.ppf(1 - ALFA / 2, 2 * k + 2) / 2
    return k / t, lo / t, hi / t


def clopper(x: int, n: int) -> tuple[float, float, float]:
    lo, hi = proportion_confint(x, n, alpha=ALFA, method="beta")
    return x / n, float(lo), float(hi)


def mcnemar_exacta_menor(b: int, c: int) -> float:
    """H1: la proporción del piloto es menor. b = solo base con defecto, c = solo piloto con defecto."""
    return float(stats.binom.cdf(c, b + c, 0.5)) if b + c else 1.0


# ---------- datos ----------
def complejidad(puntos) -> str:
    p = float(puntos)
    return "baja (≤ 3)" if p <= 3 else "media (5)" if p <= 5 else "alta (≥ 8)"


def linea_base(xlsx: Path) -> dict:
    req = pd.read_excel(xlsx, "Requerimientos", header=1)
    dfc = pd.read_excel(xlsx, "Defectos", header=1)
    dep = pd.read_excel(xlsx, "Despliegues", header=1)
    req = req[req["req_id"].astype(str).str.startswith("SIM-")].copy()
    req["h1a_d"] = (pd.to_datetime(req["fecha_fin_pruebas"]) - pd.to_datetime(req["fecha_registro"])).dt.days.astype(float)
    prod = set(dfc.loc[dfc["fase_deteccion"].astype(str).str.lower().str.startswith("produc"), "req_id"])
    req["con_defecto_prod"] = req["req_id"].isin(prod).astype(int)
    req["complejidad"] = req["puntos_historia"].map(complejidad)
    dep = dep[dep["deploy_id"].astype(str).str.startswith("SIM-")]
    return {"req": req, "g1p": req[req["proyecto_id"] == SQUAD], "g1s": req[req["proyecto_id"] != SQUAD],
            "dep_total": int(len(dep)), "dep_fallidos": int(dep["fallido"].astype(int).sum())}


def puntos_piloto(req_id: str) -> float | None:
    f = ROOT / "data/requerimientos" / req_id / "input" / "restricciones.json"
    return float(json.loads(f.read_text(encoding="utf-8"))["puntos_historia"]) if f.exists() else None


# ---------- contraste ----------
def contrastar(piloto: pd.DataFrame, lb: dict) -> dict:
    piloto = piloto.copy()
    for col in ("h1a_d_censurado", "historico"):
        piloto[col] = piloto[col].astype(str).str.lower().isin(["true", "1"])
    piloto["complejidad"] = piloto["req_id"].map(lambda r: complejidad(puntos_piloto(r)) if puntos_piloto(r) is not None else None)
    g1p, g1s, pob = lb["g1p"].set_index("req_id"), lb["g1s"], lb["req"]
    res, pvals = {}, {}

    # H1 — velocidad
    par = piloto[piloto["req_id"].isin(g1p.index)].dropna(subset=["h1a_d"])
    d = par["h1a_d"].to_numpy(float) - g1p.loc[par["req_id"], "h1a_d"].to_numpy(float)
    w = stats.wilcoxon(d, alternative="less") if len(d) and np.any(d != 0) else None
    hl = hl_bootstrap(d) if len(d) else (None, None, None)
    mw = stats.mannwhitneyu(piloto["h1a_d"].dropna(), g1s["h1a_d"], alternative="less")
    estratos = {}
    for k, gp in piloto.dropna(subset=["h1a_d", "complejidad"]).groupby("complejidad"):
        gb = g1s[g1s["complejidad"] == k]["h1a_d"]
        if len(gp) and len(gb):
            estratos[k] = {"n_piloto": int(len(gp)), "n_g1*": int(len(gb)), "mediana_piloto": float(gp["h1a_d"].median()),
                           "mediana_g1*": float(gb.median()), "p": float(stats.mannwhitneyu(gp["h1a_d"], gb, alternative="less").pvalue)}
    pvals["H1"] = float(w.pvalue) if w else 1.0
    res["H1"] = {"pares": int(len(d)), "censurados_en_pares": int(par["h1a_d_censurado"].sum()),
                 "mediana_piloto_d": float(piloto["h1a_d"].median()), "mediana_g1p_d": float(g1p["h1a_d"].median()),
                 "mediana_g1*_d": float(g1s["h1a_d"].median()), "LB_H1a_poblacion_d": float(pob["h1a_d"].median()),
                 "wilcoxon_p": pvals["H1"], "hodges_lehmann_d": hl[0], "ic95": [hl[1], hl[2]],
                 "mann_whitney_g1*_p": float(mw.pvalue), "por_complejidad": estratos, "meta_d": METAS["H1_d"],
                 "meta_cumplida": bool(piloto["h1a_d"].median() <= METAS["H1_d"])}

    # H2 — estabilidad
    nd, nf = int(piloto["despliegues"].sum()), int(piloto["despliegues_fallidos"].sum())
    fisher2 = stats.fisher_exact([[nf, nd - nf], [lb["dep_fallidos"], lb["dep_total"] - lb["dep_fallidos"]]], alternative="less") if nd else None
    pvals["H2"] = float(fisher2.pvalue) if fisher2 else 1.0
    dif2 = newcombe_independiente(nf, nd, lb["dep_fallidos"], lb["dep_total"]) if nd else (None, None, None)
    res["H2"] = {"piloto": f"{nf}/{nd}", "tasa_piloto": nf / nd if nd else None, "linea_base": f"{lb['dep_fallidos']}/{lb['dep_total']}",
                 "tasa_lb": lb["dep_fallidos"] / lb["dep_total"], "fisher_p": pvals["H2"], "diferencia": dif2[0], "ic95": [dif2[1], dif2[2]],
                 "meta": METAS["H2"], "meta_cumplida": bool(nd and nf / nd <= METAS["H2"])}

    # H3 — calidad (escapados vs. detectados en producción)
    par3 = piloto[piloto["req_id"].isin(g1p.index)]
    base = g1p.loc[par3["req_id"], "con_defecto_prod"].to_numpy(int); pil = par3["con_escapado"].to_numpy(int)
    a, b = int(((base == 1) & (pil == 1)).sum()), int(((base == 1) & (pil == 0)).sum())
    c, dd = int(((base == 0) & (pil == 1)).sum()), int(((base == 0) & (pil == 0)).sum())
    pvals["H3"] = mcnemar_exacta_menor(b, c)
    th, lo, hi = newcombe_pareado(a, b, c, dd) if len(base) else (None, None, None)
    x2, n2 = int(piloto["con_escapado"].sum()), int(len(piloto))
    f3 = stats.fisher_exact([[x2, n2 - x2], [int(g1s["con_defecto_prod"].sum()), int(len(g1s) - g1s["con_defecto_prod"].sum())]], alternative="less")
    lb_h3 = float(pob["con_defecto_prod"].mean())
    res["H3"] = {"pares": int(len(base)), "tabla_pareada": {"ambos": a, "solo_base": b, "solo_piloto": c, "ninguno": dd},
                 "mcnemar_p": pvals["H3"], "diferencia_piloto_menos_base": -th if th is not None else None,
                 "ic95": [-hi, -lo] if th is not None else [None, None], "tasa_piloto": x2 / n2 if n2 else None,
                 "LB_H3_poblacion": lb_h3, "fisher_g1*_p": float(f3.pvalue), "meta": lb_h3 / 2,
                 "meta_cumplida": bool(n2 and x2 / n2 <= lb_h3 / 2)}

    # Holm sobre H1–H3 y regla de decisión
    ajust = multipletests([pvals["H1"], pvals["H2"], pvals["H3"]], alpha=ALFA, method="holm")[1]
    for h, pa in zip(("H1", "H2", "H3"), ajust):
        res[h]["p_ajustado_holm"] = float(pa)
        res[h]["decision"] = ("aceptada" if res[h]["meta_cumplida"] and pa < ALFA else
                              "mejora no concluyente" if res[h]["meta_cumplida"] else "no aceptada")

    # H4–H6 — umbrales
    ok = int((piloto["despliegues"] - piloto["despliegues_fallidos"]).sum())
    dias = float(piloto.attrs.get("dias_exposicion") or 12)
    t4 = poisson_exacto(ok, dias / 30)
    res["H4"] = {"exitosos": ok, "dias_exposicion": dias, "por_mes": t4[0], "ic95": [t4[1], t4[2]], "meta": METAS["H4"],
                 "decision": "cumple el umbral" if t4[0] >= METAS["H4"] else "no cumple el umbral", "nota": "descriptivo (D4)"}
    tz = clopper(int(piloto["trazable"].fillna(0).sum()), n2)
    res["H5"] = {"proporcion": tz[0], "ic95": [tz[1], tz[2]], "meta": METAS["H5"], "decision": "cumple el umbral" if tz[0] >= METAS["H5"] else "no cumple el umbral"}
    au = clopper(int(piloto["handoffs_auto"].sum()), int(piloto["handoffs"].sum()))
    rg = clopper(int(piloto["agentes_con_transicion"].sum()), int(piloto["agentes"].sum()))
    res["H6"] = {"auto": au[0], "auto_ic95": [au[1], au[2]], "registradas": rg[0], "registradas_ic95": [rg[1], rg[2]],
                 "decision": "cumple el umbral" if au[0] >= METAS["H6_auto"] and rg[0] >= METAS["H6_reg"] else "no cumple el umbral"}

    # Sensibilidad: sin requerimientos nuevos y sin casos censurados
    sens = {}
    for nombre, sub in (("sin_nuevos", piloto[piloto["historico"]]), ("sin_censurados", piloto[~piloto["h1a_d_censurado"]])):
        if len(sub):
            sens[nombre] = {"n": int(len(sub)), "H1_mann_whitney_p": float(stats.mannwhitneyu(sub["h1a_d"].dropna(), g1s["h1a_d"], alternative="less").pvalue),
                            "H3_fisher_p": float(stats.fisher_exact([[int(sub["con_escapado"].sum()), int(len(sub) - sub["con_escapado"].sum())],
                                                                       [int(g1s["con_defecto_prod"].sum()), int(len(g1s) - g1s["con_defecto_prod"].sum())]],
                                                                      alternative="less").pvalue)}
    res["sensibilidad"] = sens
    return res


def a_markdown(r: dict) -> str:
    f = lambda x, n=3: "—" if x is None else (f"{x:.{n}f}" if isinstance(x, float) else str(x))
    ic = lambda v: f"[{f(v[0])}; {f(v[1])}]"
    out = ["## Contraste de hipótesis (protocolo F5 v2)", "",
           "| Hipótesis | Piloto | Línea base | Prueba | p | p ajustado (Holm) | Efecto e IC 95 % | Meta | Decisión |", "|---|---|---|---|---|---|---|---|---|",
           f"| H1 velocidad | mediana {f(r['H1']['mediana_piloto_d'],1)} d | G1′ {f(r['H1']['mediana_g1p_d'],1)} d · población {f(r['H1']['LB_H1a_poblacion_d'],1)} d | Wilcoxon, {r['H1']['pares']} pares | {f(r['H1']['wilcoxon_p'],4)} | {f(r['H1']['p_ajustado_holm'],4)} | HL {f(r['H1']['hodges_lehmann_d'],1)} d {ic(r['H1']['ic95'])} | ≤ 7 d | {r['H1']['decision']} |",
           f"| H2 estabilidad | {r['H2']['piloto']} | {r['H2']['linea_base']} | Fisher | {f(r['H2']['fisher_p'],4)} | {f(r['H2']['p_ajustado_holm'],4)} | Δ {f(r['H2']['diferencia'])} {ic(r['H2']['ic95'])} | ≤ 15 % | {r['H2']['decision']} |",
           f"| H3 calidad | {f(r['H3']['tasa_piloto'])} | población {f(r['H3']['LB_H3_poblacion'])} | McNemar, {r['H3']['pares']} pares | {f(r['H3']['mcnemar_p'],4)} | {f(r['H3']['p_ajustado_holm'],4)} | Δ {f(r['H3']['diferencia_piloto_menos_base'])} {ic(r['H3']['ic95'])} | ≤ {f(r['H3']['meta'])} | {r['H3']['decision']} |",
           f"| H4 agilidad | {f(r['H4']['por_mes'],2)} / mes | 1,0 | Umbral (descriptivo) | — | — | IC {ic(r['H4']['ic95'])} | ≥ 1,5 | {r['H4']['decision']} |",
           f"| H5 gobernanza | {f(r['H5']['proporcion'])} | 0 | Umbral | — | — | Clopper-Pearson {ic(r['H5']['ic95'])} | 100 % | {r['H5']['decision']} |",
           f"| H6 coordinación | auto {f(r['H6']['auto'])} · registradas {f(r['H6']['registradas'])} | 0 · 0,309 | Umbral | — | — | {ic(r['H6']['auto_ic95'])} · {ic(r['H6']['registradas_ic95'])} | ≥ 90 % · 100 % | {r['H6']['decision']} |",
           "", "**Respaldo H1 (Mann-Whitney, piloto vs. G1\\*):** p = " + f(r["H1"]["mann_whitney_g1*_p"], 4) + ". Por complejidad: "
           + "; ".join(f"{k}: p = {f(v['p'],4)} (n = {v['n_piloto']} vs. {v['n_g1*']})" for k, v in r["H1"]["por_complejidad"].items()) + ".",
           "", "**Respaldo H3 (Fisher, piloto vs. G1\\*):** p = " + f(r["H3"]["fisher_g1*_p"], 4) + ".",
           "", "**Sensibilidad:** " + "; ".join(f"{k} (n = {v['n']}): H1 p = {f(v['H1_mann_whitney_p'],4)}, H3 p = {f(v['H3_fisher_p'],4)}" for k, v in r["sensibilidad"].items()) + "."]
    return "\n".join(out) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--piloto", required=True, help="CSV por requerimiento de scripts/indicadores.py --csv-req")
    ap.add_argument("--linea-base", default=str(ROOT / "data/linea_base/Linea_BaseV2.xlsx"))
    ap.add_argument("--dias-exposicion", type=float, default=12.0, help="días del piloto (30/11–11/12 = 12)")
    ap.add_argument("--md"); ap.add_argument("--json")
    a = ap.parse_args()
    pil = pd.read_csv(a.piloto); pil.attrs["dias_exposicion"] = a.dias_exposicion
    r = contrastar(pil, linea_base(Path(a.linea_base)))
    md = a_markdown(r); print(md)
    if a.md:
        Path(a.md).write_text(md, encoding="utf-8")
    if a.json:
        Path(a.json).write_text(json.dumps(r, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
