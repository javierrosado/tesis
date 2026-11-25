#!/usr/bin/env python3
"""eval_n3 · paso 1: requerimientos de evaluación SIM-E01..E05 (BusinessRequest v1.1), escritos por el maestro open-weight.

Se usan semillas con prefijo SIM-E0 (proyectos distintos del piloto SIM-P05 y del entrenamiento SIM-T0x). El maestro
(Qwen3-32B-AWQ, en el mismo job) redacta brief, restricciones e historia original; los criterios (30 %) y las notas de
refinamiento siguen la misma convención que G4 (scripts/g4_contexto.py). Luego el pipeline v1 corre en modo automático y
sus artefactos aprobados quedan como entradas congeladas de los agentes N3 (scripts/eval_n3/congelar.py).

  python scripts/eval_n3/preparar_brs.py --n 30 --url http://localhost:8001/v1 --modelo Qwen/Qwen3-32B-AWQ
Imprime los req_id creados (uno por línea)."""
import argparse, json, subprocess, sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT)); sys.path.insert(0, str(ROOT / "scripts"))
from core.adapters.openai_compat import OpenAICompatAdapter  # noqa: E402
from core.intake import load_business_request              # noqa: E402
import g4_contexto as g4                                    # noqa: E402

SCHEMA = {"title": "BriefEval", "type": "object", "additionalProperties": False,
          "required": ["titulo", "necesidad", "resultado_esperado", "restricciones", "preguntas_abiertas", "historia_original"],
          "properties": {"titulo": {"type": "string", "minLength": 10, "maxLength": 90}, "necesidad": {"type": "string", "minLength": 150},
                         "resultado_esperado": {"type": "string", "minLength": 40},
                         "restricciones": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 4},
                         "preguntas_abiertas": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
                         "historia_original": {"type": "string", "minLength": 60}}}


def redactar(m: OpenAICompatAdapter, s: dict, documentado: bool) -> str:
    reglas = "\n".join(f"- {r['id']}: {r['texto']}" for r in s["reglas"])
    prompt = (f"Redacta un requerimiento realista de software para una empresa de venta directa de cosméticos por catálogo (consultoras, campañas, zonas).\n"
              f"Área: {s['area']}. Tipo: {s['tipo']}. País: {s['pais']}. Canal: {s['canal']}. Solicitante: {s['solicitante']}. Complejidad: {s['puntos']} puntos.\n"
              f"Reglas de negocio que el requerimiento debe involucrar:\n{reglas}\n"
              f"El requerimiento debe pedir un servicio con endpoints HTTP concretos (consultas y al menos una operación que cambie datos).\n"
              f"resultado_esperado empieza con 'Como {s['rol']}, quiero ... para ...'. historia_original es el texto libre, informal y a veces ambiguo, "
              f"con que el negocio lo pidió, con una primera línea entre corchetes que diga de dónde salió.\nNo inventes reglas distintas de las listadas. Responde solo con el JSON.")
    d = json.loads(m.complete([{"role": "user", "content": prompt}], SCHEMA).text)
    inp = ROOT / "data/requerimientos" / s["req_id"] / "input"; inp.mkdir(parents=True, exist_ok=True)
    restr = "\n".join(f"- {r}" for r in d["restricciones"])
    (inp / "brief.md").write_text(
        f"# Brief — {d['titulo']}\n\n| Campo | Valor |\n|---|---|\n| Requerimiento | {s['req_id']} |\n| Proyecto | {s['proyecto']} |\n| Tipo | {s['tipo']} |\n"
        f"| Solicitante | {s['solicitante']} |\n| Campaña objetivo | {s['campana']} |\n| Alcance geográfico | {s['pais']} |\n| Canal | {s['canal']} |\n"
        f"| Complejidad estimada | {s['puntos']} puntos |\n\n## Necesidad de negocio\n\n{d['necesidad']}\n\n## Resultado esperado\n\n{d['resultado_esperado']}\n\n"
        f"## Restricciones conocidas\n\n{restr}\n", encoding="utf-8")
    (inp / "restricciones.json").write_text(json.dumps({"req_id": s["req_id"], "tipo": s["tipo"], "origen": "Área de negocio", "campana": s["campana"],
        "puntos_historia": s["puntos"], "datos_personales_involucrados": s["datos_personales"],
        "reglas_negocio_referenciadas": [f"{r['id']} {r['texto'][:40]}" for r in s["reglas"]], "preguntas_abiertas": d["preguntas_abiertas"]},
        ensure_ascii=False), encoding="utf-8")
    (inp / "historia_original.md").write_text(f"# Historia de usuario — registro original\n\n{d['historia_original']}\n", encoding="utf-8")
    br10 = load_business_request(ROOT / "data/requerimientos" / s["req_id"], version="1.0")
    crit = json.loads(m.complete(g4.prompt_criterios(br10), g4.TEXTO_SCHEMA).text)["texto"] if documentado else None
    (inp / "criterios_aceptacion.md").write_text(f"# Criterios de aceptación\n\n{crit or g4.NO_DOC}\n", encoding="utf-8")
    (inp / "notas_refinamiento.md").write_text(f"# Notas de refinamiento\n\n{g4.notas_refinamiento(br10, documentado)}\n", encoding="utf-8")
    load_business_request(ROOT / "data/requerimientos" / s["req_id"])        # valida v1.1
    return s["req_id"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=30); ap.add_argument("--start", type=int, default=0)
    ap.add_argument("--url", default="http://localhost:8001/v1"); ap.add_argument("--modelo", default="Qwen/Qwen3-32B-AWQ")
    a = ap.parse_args()
    subprocess.run([sys.executable, str(ROOT / "scripts/gen_seeds.py"), "--n", str(a.n), "--start", str(a.start), "--seed", "2027",
                    "--prefijo", "SIM-E0", "--out", "/tmp/seeds_eval.jsonl"], check=True, stdout=subprocess.DEVNULL)
    seeds = [json.loads(l) for l in open("/tmp/seeds_eval.jsonl", encoding="utf-8")]
    docs = g4.documentados([s["req_id"] for s in seeds])
    m = OpenAICompatAdapter({"model": a.modelo, "url": a.url, "max_new_tokens": 2048, "temperature": 0.7, "chat_template_kwargs": {"enable_thinking": False}})
    with ThreadPoolExecutor(max_workers=8) as ex:
        ids = list(ex.map(lambda s: _seguro(m, s, s["req_id"] in docs), seeds))
    for r in ids:
        if r:
            print(r)


def _seguro(m, s, doc):
    for _ in range(3):
        try:
            return redactar(m, s, doc)
        except Exception as e:  # noqa: BLE001
            print("reintento", s["req_id"], str(e)[:120], file=sys.stderr)
    return None


if __name__ == "__main__":
    main()
