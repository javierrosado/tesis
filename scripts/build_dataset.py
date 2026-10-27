#!/usr/bin/env python3
"""Construye el dataset sintético de fine-tuning de product-analyst-agent (Fase 3).

Origen: los 30 requerimientos de data/requerimientos (brief + restricciones) y el catálogo BR.
Método: para cada requerimiento se deriva una salida "oro" por reglas (plantillas deterministas que
cumplen el contrato y los criterios F5) y se generan variantes controladas de la entrada
(campaña, país, canal, puntos, orden y subconjunto de reglas, redacción) para ampliar la muestra.
Los prompts se construyen con el MISMO código que usa el orquestador en inferencia
(Orchestrator._messages + KnowledgeRag), de modo que la distribución de entrenamiento coincide con la de uso.

Declaración para la tesis: dataset sintético, generado por reglas, sin salidas de ningún modelo de lenguaje.
Partición por requerimiento (no por ejemplo) para evitar fuga entre train/val/test.

  python scripts/build_dataset.py --variants 12 --seed 2026
"""
import argparse, json, random, re, sys
from pathlib import Path
import jsonschema

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.registry import Registry            # noqa: E402
from core.intake import load_business_request  # noqa: E402
from core.orchestrator import Orchestrator     # noqa: E402
from core.telemetry import Telemetry           # noqa: E402
from core import verify                        # noqa: E402

PAISES = ["Perú", "Ecuador", "Colombia", "Bolivia", "México", "Chile", "Guatemala"]
CANALES = ["App móvil y web", "Web", "App móvil", "Plataforma"]
VERBOS = ["poder", "lograr", "tener la opción de", "contar con la posibilidad de"]
ROL_POR_SOLICITANTE = [("consultora", "consultora"), ("planeamiento", "analista de planeamiento de campaña"),
                       ("cumplimiento", "oficial de cumplimiento"), ("logística", "coordinador de logística"),
                       ("crédito", "analista de crédito y cobranza"), ("marketing", "analista de marketing"),
                       ("servicio", "consultora"), ("seguridad", "oficial de seguridad de la información"),
                       ("comercial", "líder de zona"), ("producto", "product owner")]


def load_br_catalog() -> dict:
    cat = {}
    for line in (ROOT / "data/knowledge/reglas_negocio/BR_catalogo.md").read_text(encoding="utf-8").splitlines():
        m = re.match(r"\|\s*(BR-\d{3})\s*\|\s*(.*?)\s*\|", line)
        if m:
            cat[m.group(1)] = m.group(2)
    return cat


def infer_rol(br: dict) -> str:
    m = re.match(r"\s*Como\s+(.+?),\s*quiero", br["resultado_esperado"], re.I)
    if m:
        return m.group(1).strip().lower()
    s = (br.get("solicitante", "") + " " + br.get("origen", "")).lower()
    for k, rol in ROL_POR_SOLICITANTE:
        if k in s:
            return rol
    return "consultora"


def first_sentence(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip()
    m = re.match(r"\s*Como\s+.+?,\s*quiero\s+(.+?),\s*para\s+(.+?)\.?$", t, re.I)
    if m:
        return m.group(1).strip()
    s = re.split(r"(?<=[.;])\s", t)[0].rstrip(".")
    s = re.sub(r"^(Necesitamos|Queremos|Se requiere|Se necesita|Buscamos|Requerimos)\s+(que\s+)?((la|el|los|las)\s+)?[\wáéíóúñ]+(\s+de\s+[\wáéíóúñ]+)?\s+(pueda|puedan|logre|logren|tenga|tengan)\s+", "", s, flags=re.I)
    s = re.sub(r"^(Necesitamos|Queremos|Se requiere|Se necesita|Buscamos|Requerimos)\s+(que\s+)?", "que ", s, flags=re.I)
    return s[0].lower() + s[1:]


def beneficio(br: dict) -> str:
    m = re.search(r",\s*para\s+(.+?)\.?$", first_sentence_full(br["resultado_esperado"]), re.I)
    if m:
        return m.group(1).strip()
    n = re.sub(r"\s+", " ", br["necesidad"]).strip()
    n = re.split(r"(?<=[.;])\s", n)[0].rstrip(".")
    return "atender la necesidad de negocio: " + n[0].lower() + n[1:]


def first_sentence_full(t: str) -> str:
    t = re.sub(r"\s+", " ", t).strip()
    return re.split(r"(?<=[.])\s", t)[0]


def gold_story_set(br: dict, cat: dict, rng: random.Random) -> dict:
    rol = infer_rol(br)
    quiero = first_sentence(br["resultado_esperado"])
    para = beneficio(br)
    reglas = [r for r in br["reglas_negocio"] if r in cat]
    historias = []
    # historia principal: el resultado esperado, con un criterio por regla (máx. 2) y uno general
    crit = [{"given": f"una {rol} autenticada en el portal con datos vigentes de la campaña {br['campana'] or 'actual'}",
             "when": f"{quiero[0].lower() + quiero[1:]}",
             "then": "el sistema responde en la misma sesión y registra la operación con fecha y usuario"}]
    for r in reglas[:2]:
        crit.append({"given": f"un caso cubierto por {r}", "when": "se ejecuta la operación descrita",
                     "then": f"se cumple {r}: {cat[r].rstrip('.')}"})
    pts_total = br["puntos_historia"]
    historias.append({"id": "US-01", "rol": rol, "quiero": quiero, "para": para, "criterios": crit,
                      "reglas_negocio": reglas[:2] or [], "puntos": min(8, max(1, pts_total - 2 * max(0, len(reglas) - 2)))})
    # una historia por regla adicional (3.ª en adelante): verificación explícita de la regla
    for i, r in enumerate(reglas[2:], start=2):
        historias.append({"id": f"US-{i:02d}", "rol": rol,
                          "quiero": f"que el sistema aplique la regla {r} en {quiero[0].lower() + quiero[1:]}",
                          "para": "evitar inconsistencias con las reglas de negocio vigentes",
                          "criterios": [{"given": f"una operación alcanzada por {r}", "when": "el sistema valida la solicitud",
                                         "then": f"se aplica {r}: {cat[r].rstrip('.')}"},
                                        {"given": f"una operación que incumple {r}", "when": "el sistema valida la solicitud",
                                         "then": "la operación se rechaza con un mensaje que cita la regla incumplida"}],
                          "reglas_negocio": [r], "puntos": 2})
    # historia de observabilidad si hay datos personales o NF
    if br.get("datos_personales") or br.get("tipo") == "No funcional":
        historias.append({"id": f"US-{len(historias) + 1:02d}", "rol": "oficial de cumplimiento",
                          "quiero": "que cada acceso o cambio derivado de esta funcionalidad quede registrado",
                          "para": "responder auditorías sin reconstruir evidencia a mano",
                          "criterios": [{"given": "una operación realizada por cualquier usuario", "when": "finaliza con éxito o con error",
                                         "then": "existe un registro con usuario, fecha-hora, operación y resultado, consultable por auditoría"}],
                          "reglas_negocio": [r for r in reglas if r in ("BR-050", "BR-051", "BR-052")][:1], "puntos": 1})
    # preguntas: se resuelven solo las que una regla citada responde literalmente
    resueltas, pendientes = [], []
    for q in br["preguntas_abiertas"]:
        hit = next((r for r in reglas if any(w in cat[r].lower() for w in _keywords(q))), None)
        if hit:
            resueltas.append({"pregunta": q, "respuesta": f"Según {hit}: {cat[hit].rstrip('.')}.", "fuente": hit})
        else:
            pendientes.append(q)
    refs = reglas + ["GLOS:Pedido"] if any("pedido" in h["quiero"].lower() for h in historias) else reglas
    return {"req_id": br["req_id"], "historias": historias[:8], "preguntas_resueltas": resueltas, "preguntas_pendientes": pendientes,
            "provenance": {"contract_version": "1.0", "req_id": br["req_id"], "agent": "product-analyst-agent", "phase": "discovery",
                           "inputs": ["input/brief.md", "input/restricciones.json"], "knowledge_refs": refs or ["GLOS:Pedido"], "assumptions": []}}


def _keywords(q: str) -> list[str]:
    return [w for w in re.findall(r"[a-záéíóúñ]{5,}", q.lower()) if w not in ("incluye", "muestra", "viene", "sistema", "cuándo", "quién", "cómo")]


def variants(br: dict, cat: dict, n: int, rng: random.Random):
    """Variantes controladas de la entrada. La primera es el original."""
    yield br
    for i in range(n - 1):
        v = json.loads(json.dumps(br))
        v["campana"] = f"C{rng.choice([2025, 2026])}-{rng.randint(1, 13):02d}"
        pais = rng.choice(PAISES)
        v["necesidad"] = re.sub(r"\b(Perú|Ecuador|Colombia|Bolivia|México|Chile|Guatemala)\b", pais, v["necesidad"])
        v["puntos_historia"] = max(1, min(13, v["puntos_historia"] + rng.choice([-2, -1, 0, 0, 1, 2, 3])))
        if len(v["reglas_negocio"]) > 1 and rng.random() < 0.4:
            v["reglas_negocio"] = rng.sample(v["reglas_negocio"], len(v["reglas_negocio"]) - 1)
        elif rng.random() < 0.3:
            extra = rng.choice([r for r in cat if r not in v["reglas_negocio"]])
            v["reglas_negocio"] = v["reglas_negocio"] + [extra]
        rng.shuffle(v["reglas_negocio"])
        if v["preguntas_abiertas"] and rng.random() < 0.3:
            v["preguntas_abiertas"] = v["preguntas_abiertas"][:-1]
        if rng.random() < 0.5:
            v["resultado_esperado"] = re.sub(r"\bquiero\b", "quiero " + rng.choice(VERBOS), v["resultado_esperado"], count=1)
        v["solicitante"] = v.get("solicitante") or "Analista funcional"
        yield v


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--variants", type=int, default=12)
    ap.add_argument("--seed", type=int, default=2026)
    ap.add_argument("--out", default="data/datasets/product-analyst")
    a = ap.parse_args()
    rng = random.Random(a.seed)
    reg = Registry(ROOT); agent = reg.agents["product-analyst-agent"]
    orch = Orchestrator(ROOT, Telemetry(ROOT / "telemetry/build_dataset.jsonl"), seed=a.seed)
    cat = load_br_catalog()
    reqs = sorted(p.name for p in (ROOT / "data/requerimientos").iterdir() if (p / "input").exists())
    rng.shuffle(reqs)
    split = {r: ("test" if i < 5 else "val" if i < 9 else "train") for i, r in enumerate(reqs)}
    out = Path(ROOT / a.out); out.mkdir(parents=True, exist_ok=True)
    files = {s: (out / f"{s}.jsonl").open("w", encoding="utf-8") for s in ("train", "val", "test")}
    stats = {"train": 0, "val": 0, "test": 0, "f5_ok": 0, "total": 0}
    for r in sorted(reqs):
        br0 = load_business_request(ROOT / "data/requerimientos" / r)
        n = a.variants if split[r] == "train" else max(3, a.variants // 3)
        for v in variants(br0, cat, n, rng):
            jsonschema.validate(v, agent.input_schema)
            gold = gold_story_set(v, cat, rng)
            jsonschema.validate(gold, agent.output_schema)
            ok, f5 = verify.evaluate(agent, gold, {"business_request": v}, {"refinement_rounds": 0})
            stats["f5_ok"] += int(ok); stats["total"] += 1
            knowledge, _ = orch.rag.context_block(orch._queries_for(agent, {"business_request": v}))
            msgs = orch._messages(agent, v, knowledge)
            ex = {"req_id": r, "split": split[r], "messages": msgs + [{"role": "assistant", "content": json.dumps(gold, ensure_ascii=False)}]}
            files[split[r]].write(json.dumps(ex, ensure_ascii=False) + "\n"); stats[split[r]] += 1
    for f in files.values():
        f.close()
    (out / "README.md").write_text(
        "# Dataset sintético — product-analyst-agent\n\n"
        f"Generado por `scripts/build_dataset.py` (semilla {a.seed}, {a.variants} variantes por requerimiento de train).\n"
        f"Partición por requerimiento: train {sum(1 for r in reqs if split[r]=='train')} req / val {sum(1 for r in reqs if split[r]=='val')} / test {sum(1 for r in reqs if split[r]=='test')}.\n"
        f"Ejemplos: train {stats['train']} · val {stats['val']} · test {stats['test']}. Salidas oro que cumplen F5: {stats['f5_ok']}/{stats['total']}.\n\n"
        "Formato: JSONL con `messages` (system, user, assistant). Sin salidas de ningún modelo de lenguaje.\n"
        f"Requerimientos de test (nunca vistos en entrenamiento): {sorted(r for r in reqs if split[r]=='test')}\n", encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False))


if __name__ == "__main__":
    main()
