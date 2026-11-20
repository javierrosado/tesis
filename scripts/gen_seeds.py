#!/usr/bin/env python3
"""Semillas de requerimientos de ENTRENAMIENTO (F2-A). Determinista (semilla fija).

Garantía contra fuga: las semillas usan proyectos SIM-T01..T05 (squads distintos del piloto) y nunca
reutilizan títulos ni ids de data/requerimientos/SIM-P05-* (los 30 del piloto, que quedan como prueba).

  python scripts/gen_seeds.py --n 200 --seed 2026 --out seeds.jsonl
"""
import argparse, json, random, re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AREAS = [  # (área, reglas candidatas, solicitante, rol del usuario)
    ("pedidos", ["BR-003", "BR-005", "BR-008", "BR-010", "BR-011", "BR-012", "BR-020", "BR-021"], "Gerencia Comercial", "consultora"),
    ("cierre de campaña", ["BR-001", "BR-030", "BR-031", "BR-130"], "Planeamiento Comercial", "líder de zona"),
    ("promociones", ["BR-006", "BR-040", "BR-120", "BR-150"], "Marketing", "analista de marketing"),
    ("privacidad y consentimiento", ["BR-050", "BR-051", "BR-052"], "Cumplimiento", "oficial de cumplimiento"),
    ("puntos y premios", ["BR-060", "BR-061", "BR-062"], "Fidelización", "consultora"),
    ("incorporación", ["BR-070", "BR-071", "BR-002"], "Desarrollo de Fuerza de Ventas", "nueva consultora"),
    ("seguridad de acceso", ["BR-080", "BR-081"], "Seguridad de la Información", "oficial de seguridad de la información"),
    ("notificaciones", ["BR-090", "BR-010"], "Servicio a la Consultora", "consultora"),
    ("crédito y cobranza", ["BR-100", "BR-101", "BR-102"], "Crédito y Cobranza", "analista de crédito y cobranza"),
    ("reclamos y devoluciones", ["BR-110", "BR-111", "BR-160"], "Servicio a la Consultora", "consultora"),
    ("facturación", ["BR-140", "BR-008"], "Finanzas", "consultora"),
    ("niveles y descuentos", ["BR-002", "BR-003", "BR-100"], "Gerencia Comercial", "consultora"),
]
TIPOS = [("Funcional", 0.7), ("No funcional", 0.15), ("Técnico", 0.1), ("Regulatorio", 0.05)]
PAISES = ["Perú", "Ecuador", "Colombia", "Bolivia", "México", "Chile", "Guatemala"]
CANALES = ["App móvil y web", "Web", "App móvil"]
PUNTOS = [1, 2, 3, 5, 5, 8, 8, 13]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=200); ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default="seeds.jsonl")
    ap.add_argument("--start", type=int, default=0, help="índice inicial: lotes disjuntos de semillas (R{start+1}…)")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    cat = {}
    for line in (ROOT / "data/knowledge/reglas_negocio/BR_catalogo.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*(BR-\d{3})\s*\|\s*(.*?)\s*\|", line)
        if m:
            cat[m.group(1)] = m.group(2)
    pilot_titles = {json.loads(p.read_text(encoding="utf-8"))["req_id"] for p in (ROOT / "data/requerimientos").glob("*/input/restricciones.json")}
    with open(a.out, "w", encoding="utf-8") as f:
        for _ in range(a.start):            # avanza el generador para que el lote sea idéntico al de una corrida única
            rng.choice([1, 1, 2, 2, 3]); rng.sample(range(10), 1); rng.choices([0], [1]); rng.choice(PAISES); rng.choice(CANALES); rng.choice(PUNTOS); rng.randint(1, 13); rng.random()
        for i in range(a.start, a.start + a.n):
            area, brs, solicitante, rol = AREAS[i % len(AREAS)]
            k = rng.choice([1, 1, 2, 2, 3]); reglas = sorted(rng.sample(brs, min(k, len(brs))))
            tipo = rng.choices([t for t, _ in TIPOS], [w for _, w in TIPOS])[0]
            proyecto = f"SIM-T0{1 + i % 5}"
            req_id = f"{proyecto}-R{i + 1:03d}"
            assert req_id not in pilot_titles
            f.write(json.dumps({"req_id": req_id, "proyecto": proyecto, "area": area, "tipo": tipo, "solicitante": solicitante, "rol": rol,
                                "pais": rng.choice(PAISES), "canal": rng.choice(CANALES), "puntos": rng.choice(PUNTOS),
                                "campana": f"C2026-{rng.randint(1, 13):02d}", "datos_personales": area in ("privacidad y consentimiento", "incorporación", "seguridad de acceso") or rng.random() < 0.15,
                                "reglas": [{"id": r, "texto": cat.get(r, "")} for r in reglas]}, ensure_ascii=False) + "\n")
    print(f"{a.n} semillas → {a.out}")


if __name__ == "__main__":
    main()
