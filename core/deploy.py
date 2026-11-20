"""Despliegue real a staging (F4.5): publica el servicio generado, las suites de pruebas y el workflow de
staging de cicd-pipeline en una rama del repositorio sandbox y espera la ejecución de GitHub Actions.

Reglas:
- Solo despliega si el release (release-manager) es go y su gate fue aprobado.
- Respeta la ventana: si hoy < ventana, el requerimiento queda programado (Scheduled) y se reanuda luego.
- Un despliegue cuenta para H4 cuando llega al job de despliegue; es fallido (H2) si ese job falla.
- Sin acceso al sandbox (DEPLOY_REPO/GITHUB_TOKEN), queda en modo validación y se marca como tal (no se reporta como despliegue)."""
import base64, json, os, time, urllib.error, urllib.request
from datetime import date, datetime, timezone

from . import render, verify


def _gh(method: str, path: str, body=None):
    req = urllib.request.Request(f"https://api.github.com{path}", method=method, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Authorization": "Bearer " + os.environ["GITHUB_TOKEN"], "Accept": "application/vnd.github+json",
                                          "X-GitHub-Api-Version": "2022-11-28"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            txt = r.read()
            return json.loads(txt) if txt else {}
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitHub {method} {path}: {e.code} {e.read()[:200]!r}") from e


def package(ctx: dict) -> dict[str, str]:
    from .tools.sandbox import _CONFTEST
    files = dict(verify.app_files(ctx))
    for s in ctx.get("qa_suite", {}).get("suites", []):
        files[f"tests/test_{s['id'].replace('-', '_').lower()}.py"] = "\n".join(s["lineas"]) + "\n"
    files["tests/conftest.py"] = _CONFTEST; files["tests/__init__.py"] = ""
    files["requirements.txt"] = "fastapi\nuvicorn\nhttpx\npytest\n"
    files["deploy.sh"] = ("#!/usr/bin/env bash\nset -euo pipefail\n# Despliegue efímero a staging: levanta el servicio y verifica que responda (smoke test)\n"
                          "pip install -q -r requirements.txt\npython -m uvicorn app.main:app --port 8000 &\nsleep 5\n"
                          "curl -fsS http://localhost:8000/openapi.json > /dev/null\necho \"desplegado en ${1:-staging}\"\n")
    pipes = ctx.get("cicd_pipeline", {}).get("pipelines", [])
    stg = next((p for p in pipes if p["ambiente"] == "staging"), pipes[0] if pipes else None)
    if stg:
        wf = render.workflow_from_pipeline(stg)
        wf["on"] = {"push": {"branches": [f"req/{ctx['req_id']}"]}}     # adaptación determinista: dispara con la rama del requerimiento
        adapt = []
        for jid, job in (wf.get("jobs") or {}).items():                   # adaptación determinista: checkout en jobs que usan el repo
            if verify.needs_checkout(job):
                job["steps"] = [{"name": "checkout", "uses": "actions/checkout@v4"}] + list(job["steps"]); adapt.append(jid)
        ctx["_adaptaciones_deploy"] = {"trigger": f"req/{ctx['req_id']}", "checkout_añadido": adapt}
        import yaml
        files[".github/workflows/staging.yml"] = yaml.safe_dump(wf, sort_keys=False, allow_unicode=True)
    return files


def _push(repo: str, branch: str, files: dict[str, str], msg: str) -> str:
    main = _gh("GET", f"/repos/{repo}/git/ref/heads/main")["object"]["sha"]
    base_tree = _gh("GET", f"/repos/{repo}/git/commits/{main}")["tree"]["sha"]
    tree = [{"path": p, "mode": "100755" if p.endswith(".sh") else "100644", "type": "blob",
             "sha": _gh("POST", f"/repos/{repo}/git/blobs", {"content": base64.b64encode(t.encode()).decode(), "encoding": "base64"})["sha"]}
            for p, t in files.items()]
    t = _gh("POST", f"/repos/{repo}/git/trees", {"base_tree": base_tree, "tree": tree})["sha"]
    c = _gh("POST", f"/repos/{repo}/git/commits", {"message": msg, "tree": t, "parents": [main]})["sha"]
    try:
        _gh("POST", f"/repos/{repo}/git/refs", {"ref": f"refs/heads/{branch}", "sha": c})
    except RuntimeError:
        _gh("PATCH", f"/repos/{repo}/git/refs/heads/{branch}", {"sha": c, "force": True})
    return c


def _wait_run(repo: str, sha: str, timeout_s: int = 900) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        runs = _gh("GET", f"/repos/{repo}/actions/runs?head_sha={sha}").get("workflow_runs", [])
        if runs and runs[0]["status"] == "completed":
            jobs = _gh("GET", f"/repos/{repo}/actions/runs/{runs[0]['id']}/jobs").get("jobs", [])
            return {"run_id": runs[0]["id"], "url": runs[0]["html_url"], "conclusion": runs[0]["conclusion"],
                    "jobs": [{"nombre": j["name"], "conclusion": j["conclusion"]} for j in jobs]}
        time.sleep(15)
    return {"conclusion": "timeout"}


def run(orch, ctx: dict) -> None:
    from .orchestrator import Scheduled, _now
    req_id = ctx["req_id"]
    rel = ctx.get("release_plan", {}).get("release", {})
    if rel.get("decision") != "go":
        orch.tel.emit(event="deploy_skipped", req_id=req_id, reason="no-go")
        orch._estado(req_id, estado="no_go")
        return
    if date.fromisoformat(orch.today) < date.fromisoformat(rel["ventana"]):
        orch.tel.emit(event="deploy_scheduled", req_id=req_id, ventana=rel["ventana"])
        raise Scheduled(rel["ventana"])
    repo = os.environ.get("DEPLOY_REPO"); files = package(ctx)
    out = orch._out_dir(req_id)
    if not repo or not os.environ.get("GITHUB_TOKEN"):
        orch.tel.emit(event="deploy_validation_only", req_id=req_id, archivos=len(files))
        orch._estado(req_id, estado="validado_sin_despliegue")
        return
    sha = _push(repo, f"req/{req_id}", files, f"{req_id} {rel['id']} v{rel['version']}")
    res = _wait_run(repo, sha)
    deploy_jobs = [j for j in res.get("jobs", []) if "deploy" in j["nombre"].lower()]
    reached = bool(deploy_jobs) and all(j["conclusion"] not in ("skipped", None) for j in deploy_jobs)
    failed = reached and any(j["conclusion"] != "success" for j in deploy_jobs)
    ev = {"event": "deployment", "req_id": req_id, "release": rel["id"], "version": rel["version"], "sha": sha, "run": res.get("url"),
          "conclusion": res.get("conclusion"), "alcanzo_deploy": reached, "fallido": failed, "jobs": res.get("jobs"),
          "adaptaciones": ctx.get("_adaptaciones_deploy", {})}
    orch.tel.emit(**{k: v for k, v in ev.items() if k != "event"}, event="deployment")
    (out / "deployment.json").write_text(json.dumps({**ev, "ts": _now()}, ensure_ascii=False, indent=1), encoding="utf-8")
    if reached and not failed:
        orch._estado(req_id, estado="desplegado", fin=_now())
    else:
        orch._estado(req_id, estado="despliegue_fallido" if reached else "pipeline_fallido", ultimo_intento=_now())
