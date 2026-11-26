"""Gasto real en HF Inference Providers según la facturación de la cuenta (T24, 25/11/2026).

El benchmark 6b076df2 reportó USD 13,21 por `usage.cost` y la facturación marcó USD 27,90: hay llamadas que se cobran y
no devuelven costo (reintentos, cortes). Los jobs leen el gasto acumulado al empezar y al terminar y guardan la diferencia.
Si otro job usa la misma cuenta a la vez, la diferencia lo incluye: por eso se guarda junto con la ventana de tiempo."""
import json, os, time, urllib.request


def gasto_ip_usd(dias: int = 2) -> dict | None:
    tok = os.environ.get("HF_TOKEN")
    if not tok:
        return None
    fin = int(time.time()); ini = fin - dias * 86400
    req = urllib.request.Request(f"https://huggingface.co/api/settings/billing/usage-v2?startDate={ini}&endDate={fin}",
                                 headers={"Authorization": f"Bearer {tok}"})
    try:
        u = json.load(urllib.request.urlopen(req, timeout=30))["usage"]
        ip = u.get("inferenceProviders") or {}
        return {"ts": fin, "usd": round(ip.get("usedNanoUsd", 0) / 1e9, 4), "llamadas": ip.get("numRequests", 0)}
    except Exception:  # noqa: BLE001 — la facturación no debe tumbar el job
        return None


def diferencia(a: dict | None, b: dict | None) -> dict | None:
    if not a or not b:
        return None
    return {"usd": round(b["usd"] - a["usd"], 4), "llamadas": b["llamadas"] - a["llamadas"], "desde": a["ts"], "hasta": b["ts"]}
