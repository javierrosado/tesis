"""Serialización determinista de artefactos de diseño a formatos estándar (sin modelo de lenguaje).
El agente decide el contenido; el código produce el documento, de modo que el formato siempre es correcto
y F5 evalúa el diseño, no la sintaxis. Usado por F5 (verify) y por el orquestador al guardar artefactos."""
import re
import yaml

_T = {"string": {"type": "string"}, "integer": {"type": "integer"}, "number": {"type": "number"}, "boolean": {"type": "boolean"},
      "array": {"type": "array", "items": {}}, "object": {"type": "object"}}


def openapi_from_design(d: dict) -> dict:
    schemas = {s["nombre"]: {"type": "object", "properties": {p["nombre"]: dict(_T[p["tipo"]]) for p in s["propiedades"]},
                             **({"required": r} if (r := [p["nombre"] for p in s["propiedades"] if p["requerido"]]) else {})}
               for s in d.get("esquemas", [])}
    schemas["Problem"] = {"type": "object", "required": ["type", "title", "status", "correlation_id"],
                          "properties": {"type": {"type": "string"}, "title": {"type": "string"}, "status": {"type": "integer"},
                                         "detail": {"type": "string"}, "correlation_id": {"type": "string"}}}
    errs = {e["id"]: e for e in d.get("errores", [])}
    sec = {}
    for s in d.get("esquemas_seguridad", []):
        sec[s["id"]] = {"jwt_bearer": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"},
                        "oauth2": {"type": "oauth2", "flows": {"clientCredentials": {"tokenUrl": "https://auth.empresa/token", "scopes": {}}}},
                        "api_key": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
                        "mtls": {"type": "mutualTLS"}}[s["tipo"]]
    ref = lambda n: {"$ref": f"#/components/schemas/{n}"}
    paths = {}
    for ep in d.get("endpoints", []):
        op = {"operationId": ep["id"].replace("-", "_").lower(), "summary": ep["resumen"],
              "parameters": [{"name": p["nombre"], "in": p["en"], "required": True if p["en"] == "path" else p["requerido"], "schema": dict(_T[p["tipo"]])} for p in ep.get("parametros", [])],
              "responses": {}}
        for r in ep.get("respuestas", []):
            op["responses"][str(r["status"])] = {"description": r["descripcion"],
                **({"content": {"application/json": {"schema": ref(r["esquema"]) if r["esquema"] in schemas else {}}}} if r.get("esquema") else {})}
        for eid in ep.get("errores", []):
            e = errs.get(eid)
            if e:
                op["responses"][str(e["status"])] = {"description": e["title"], "content": {"application/problem+json": {"schema": ref("Problem")}}}
        if ep.get("cuerpo"):
            op["requestBody"] = {"required": True, "content": {"application/json": {"schema": ref(ep["cuerpo"]) if ep["cuerpo"] in schemas else {}}}}
        if ep.get("seguridad") in sec:
            op["security"] = [{ep["seguridad"]: []}]
        paths.setdefault(ep["ruta"], {})[ep["metodo"].lower()] = op
    return {"openapi": "3.1.0", "info": {"title": d.get("titulo_api", "API"), "version": d.get("version_api", "v1")},
            "paths": paths, "components": {"schemas": schemas, "securitySchemes": sec}}


def workflow_from_pipeline(p: dict) -> dict:
    trig = {"push": {"push": {"branches": ["main"]}}, "pull_request": {"pull_request": {"branches": ["main"]}},
            "workflow_dispatch": {"workflow_dispatch": {}}, "tag": {"push": {"tags": ["v*"]}}}[p["disparador"]]
    jobs = {}
    for j in p.get("jobs", []):
        job = {"runs-on": j["runs_on"]}
        if j.get("needs"):
            job["needs"] = j["needs"]
        if j.get("environment"):
            job["environment"] = j["environment"]
        job["steps"] = [{"name": s["nombre"], **({"uses": s["uses"]} if s.get("uses") else {}), **({"run": s["run"]} if s.get("run") else {})} for s in j["steps"]]
        jobs[j["id"]] = job
    return {"name": f"{p['id']} {p['ambiente']}", "on": trig, "jobs": jobs}


def workflow_yaml(p: dict) -> str:
    return yaml.safe_dump(workflow_from_pipeline(p), sort_keys=False, allow_unicode=True)


def openapi_yaml(d: dict) -> str:
    return yaml.safe_dump(openapi_from_design(d), sort_keys=False, allow_unicode=True)
