#!/usr/bin/env python3
"""Re-filtra el dataset destilado con la versión vigente de governance (determinista, sin GPU).

Para cada ejemplo: reconstruye el contexto desde el payload de entrada, re-evalúa la salida aprobada
con governance (contrato + F5 + procedencia) y la conserva solo si sigue aprobada. Además alinea el
prompt con el de inferencia: system prompt y JSON Schema vigentes del agente y corpus sin la mención
del proyecto piloto. Excluye salidas que mencionen el piloto (SIM-P05).

  python scripts/refilter_dataset.py --src jrosado1974/tesis-sft-final --dst jrosado1974/tesis-sft-v2
"""
import argparse, collections, json, re, sys
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from core.registry import Registry   # noqa: E402
from core import governance          # noqa: E402

AGENTS = ["product-analyst-agent", "solution-architect-agent", "api-designer-agent", "test-case-generator-agent", "cicd-pipeline-agent"]
BLOCK = re.compile(r"```json\n(.*?)\n```", re.S)


def rebuild(agent, msgs):
    user = msgs[1]["content"]
    payload = json.loads(BLOCK.search(user).group(1))
    ctx = {"business_request": payload} if agent == "product-analyst-agent" else dict(payload)
    return payload, ctx


def align_prompt(reg_agent, msgs):
    user = msgs[1]["content"].replace(" (SIM-P05)", "")
    head, _, _ = user.rpartition("## Esquema de salida (JSON Schema)")
    user = head + "## Esquema de salida (JSON Schema)\n```json\n" + json.dumps(reg_agent.output_schema, ensure_ascii=False) + "\n```"
    return [{"role": "system", "content": reg_agent.prompt}, {"role": "user", "content": user}]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument("--src", required=True); ap.add_argument("--dst", required=True)
    ap.add_argument("--out", default="/tmp/sft_v2"); a = ap.parse_args()
    from huggingface_hub import snapshot_download, HfApi
    src = Path(snapshot_download(a.src, repo_type="dataset", allow_patterns=["*/*.jsonl"]))
    reg = Registry(ROOT); out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    stats = collections.defaultdict(collections.Counter); counts = {}
    for agent in AGENTS:
        ag = reg.agents[agent]; (out / agent).mkdir(exist_ok=True)
        for sp in ("train", "val", "test"):
            keep = []
            for line in (src / agent / f"{sp}.jsonl").read_text(encoding="utf-8").splitlines():
                e = json.loads(line); msgs = e["messages"]
                try:
                    output = json.loads(msgs[-1]["content"])
                    payload, ctx = rebuild(agent, msgs)
                except Exception:  # noqa: BLE001
                    stats[agent]["payload_ilegible"] += 1; continue
                ctx["req_id"] = e["req_id"]
                if "SIM-P05" in msgs[-1]["content"]:
                    stats[agent]["menciona_piloto"] += 1; continue
                v, ok, f5 = governance.review(ag, output, ctx, 0)
                if v["veredicto"] != "aprobado":
                    for h in v["hallazgos"]:
                        stats[agent][h["regla"]] += 1
                    stats[agent]["_descartados"] += 1; continue
                e["messages"] = align_prompt(ag, msgs) + [msgs[-1]]
                e["f5"] = {k: r["value"] for k, r in f5.items()}
                keep.append(e)
            (out / agent / f"{sp}.jsonl").write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in keep), encoding="utf-8")
            counts[f"{agent}/{sp}"] = len(keep)
    summary = {"src": a.src, "counts": counts, "total": sum(counts.values()), "descartes": {k: dict(v) for k, v in stats.items()}}
    (out / "resumen.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    rows = "".join(f"| {ag} | {counts[ag+'/train']} | {counts[ag+'/val']} | {counts[ag+'/test']} |\n" for ag in AGENTS)
    (out / "README.md").write_text(f"""---\nlicense: other\nlanguage: [es]\npretty_name: tesis-sft-v2\n---\n# Dataset SFT v2 (F2-A re-filtrado)\n\nDerivado de `{a.src}` re-evaluando cada salida con governance v2 (6 correcciones de calidad: job de pruebas autónomo,
lista blanca de acciones, integraciones entre componentes distintos, 204 sin esquema, corpus sin mención del piloto,
código pytest como lista de líneas). Prompt alineado con el de inferencia (system prompt y JSON Schema vigentes).\n\n| Agente | train | val | test |\n|---|---|---|---|\n{rows}""", encoding="utf-8")
    api = HfApi(); api.create_repo(a.dst, repo_type="dataset", private=True, exist_ok=True)
    api.upload_folder(folder_path=str(out), repo_id=a.dst, repo_type="dataset", commit_message="governance v2")
    print(json.dumps(summary, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
