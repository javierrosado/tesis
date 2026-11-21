#!/usr/bin/env python3
"""Verifica que el dataset sintético de entrenamiento no contiene los requerimientos del piloto.

Tres pruebas, de la más simple a la más estricta:
  1. Identificadores: ningún req_id del piloto (data/requerimientos/SIM-P05-*) aparece en el dataset.
  2. Títulos: ningún título del piloto aparece igual (sin tildes ni mayúsculas) en el dataset.
  3. Contenido: similitud coseno de n-gramas de caracteres entre el texto de negocio de cada requerimiento
     del piloto (título + necesidad + resultado esperado) y el de cada requerimiento de entrenamiento.
     Como referencia se calcula la misma similitud entre requerimientos de entrenamiento distintos:
     si el piloto no se parece al entrenamiento más de lo que los requerimientos de entrenamiento se
     parecen entre sí, no hay indicio de copia.

Uso (desde la raíz del repo; descarga el dataset público de Hugging Face):
  python scripts/verificar_fuga.py
  python scripts/verificar_fuga.py --json resultados_fuga.json
"""
import argparse, collections, glob, json, math, re, statistics, unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATASET = "jrosado1974/tesis-sft-v2"
AGENTES = ["product-analyst-agent", "solution-architect-agent", "api-designer-agent",
           "test-case-generator-agent", "cicd-pipeline-agent"]
N = 5          # n-gramas de caracteres
UMBRAL = 0.80  # similitud a partir de la cual se considera casi-duplicado


def norm(t: str) -> str:
    t = unicodedata.normalize("NFKD", t.lower())
    t = "".join(c for c in t if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9 ]", " ", t)).strip()


def vec(t: str) -> collections.Counter:
    t = norm(t)
    return collections.Counter(t[i:i + N] for i in range(max(len(t) - N + 1, 0)))


def cos(a, b) -> float:
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(k, 0) for k, v in a.items())
    return dot / (math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values())))


def seccion(md: str, titulo: str) -> str:
    m = re.search(rf"^## {titulo}\s*\n(.*?)(?=^## |\Z)", md, re.S | re.M)
    return m.group(1).strip() if m else ""


def piloto():
    reqs = {}
    for brief in sorted(glob.glob(str(ROOT / "data/requerimientos/SIM-P05-*/input/brief.md"))):
        md = Path(brief).read_text(encoding="utf-8")
        rid = Path(brief).parts[-3]
        titulo = re.search(r"^# Brief\s*[—-]\s*(.+)$", md, re.M).group(1).strip()
        reqs[rid] = {"titulo": titulo,
                     "texto": " ".join([titulo, seccion(md, "Necesidad de negocio"), seccion(md, "Resultado esperado")])}
    return reqs


def entrenamiento():
    from huggingface_hub import snapshot_download
    ruta = snapshot_download(DATASET, repo_type="dataset")
    ids, reqs = set(), {}
    for ag in AGENTES:
        for split in ("train", "val", "test"):
            for linea in open(f"{ruta}/{ag}/{split}.jsonl", encoding="utf-8"):
                r = json.loads(linea)
                ids.add(r["req_id"])
                if ag != "product-analyst-agent" or r["req_id"] in reqs:
                    continue
                user = next(m["content"] for m in r["messages"] if m["role"] == "user")
                bloque = re.search(r"```json\s*(\{.*?\})\s*```", user, re.S)
                br = json.loads(bloque.group(1))
                reqs[r["req_id"]] = {"titulo": br.get("titulo", ""),
                                     "texto": " ".join([br.get("titulo", ""), br.get("necesidad", ""),
                                                        br.get("resultado_esperado", "")])}
    return ids, reqs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", help="guardar el resultado en este archivo")
    a = ap.parse_args()

    pil = piloto()
    ids_ent, ent = entrenamiento()
    print(f"Piloto: {len(pil)} requerimientos · Entrenamiento: {len(ids_ent)} requerimientos "
          f"({len(ent)} con texto de negocio en product-analyst)\n")

    # 1. identificadores
    comunes = sorted(set(pil) & ids_ent)
    print(f"1. Identificadores del piloto presentes en el dataset: {len(comunes)} {comunes if comunes else ''}")
    proyectos = sorted({i.rsplit('-R', 1)[0] for i in ids_ent})
    print(f"   Proyectos del dataset: {', '.join(proyectos)} (el piloto es SIM-P05)")

    # 2. títulos
    tit_ent = {norm(v["titulo"]) for v in ent.values()}
    iguales = sorted(k for k, v in pil.items() if norm(v["titulo"]) in tit_ent)
    print(f"2. Títulos del piloto idénticos a uno de entrenamiento: {len(iguales)} {iguales if iguales else ''}")

    # 3. contenido
    vp = {k: vec(v["texto"]) for k, v in pil.items()}
    ve = {k: vec(v["texto"]) for k, v in ent.items()}
    claves = list(ve)
    max_piloto = {}
    for k, v in vp.items():
        s, j = max((cos(v, ve[c]), c) for c in claves)
        max_piloto[k] = (round(s, 3), j)
    max_ent = []
    for i, c in enumerate(claves):
        max_ent.append(max(cos(ve[c], ve[d]) for d in claves if d != c))
    sp = [s for s, _ in max_piloto.values()]
    resumen = {
        "piloto_vs_entrenamiento": {"mediana": round(statistics.median(sp), 3), "maximo": round(max(sp), 3)},
        "entrenamiento_vs_entrenamiento": {"mediana": round(statistics.median(max_ent), 3), "maximo": round(max(max_ent), 3)},
        "casi_duplicados_piloto": sorted(k for k, (s, _) in max_piloto.items() if s >= UMBRAL),
    }
    print("3. Similitud con el requerimiento más parecido (coseno de 5-gramas de caracteres, 0 = nada, 1 = idéntico)")
    print(f"   Piloto → entrenamiento:          mediana {resumen['piloto_vs_entrenamiento']['mediana']} · "
          f"máximo {resumen['piloto_vs_entrenamiento']['maximo']}")
    print(f"   Entrenamiento → entrenamiento:   mediana {resumen['entrenamiento_vs_entrenamiento']['mediana']} · "
          f"máximo {resumen['entrenamiento_vs_entrenamiento']['maximo']}  (referencia)")
    print(f"   Requerimientos del piloto con similitud ≥ {UMBRAL}: {len(resumen['casi_duplicados_piloto'])}")
    print("\n   Los 5 requerimientos del piloto más parecidos al entrenamiento:")
    for k, (s, j) in sorted(max_piloto.items(), key=lambda x: -x[1][0])[:5]:
        print(f"   {s:.3f}  {k} «{pil[k]['titulo']}»  ↔  {j} «{ent[j]['titulo']}»")

    ok = not comunes and not iguales and not resumen["casi_duplicados_piloto"]
    print(f"\nResultado: {'SIN FUGA' if ok else 'REVISAR'}")
    if a.json:
        Path(a.json).write_text(json.dumps({"ids_comunes": comunes, "titulos_iguales": iguales, **resumen,
                                            "detalle_piloto": max_piloto, "sin_fuga": ok},
                                           ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
