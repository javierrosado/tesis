# Pipeline multiagente de IA para el ciclo de vida del requerimiento de software

Implementación de referencia de la tesis de maestría (UNI). Los agentes se definen una sola vez
(fichas F1–F5 como `agent.yaml` + `prompt.md` + JSON Schema) y el modelo de lenguaje es un recurso
inyectado por configuración: cambiar de proveedor es editar `config/providers.yaml`.

```
┌─────────────────────────────────────────────────────────────────────────┐
│ 4. ORQUESTACIÓN   config/dag.yaml · config/gates.yaml (RACI) · telemetría│
├─────────────────────────────────────────────────────────────────────────┤
│ 3. AGENTES        agents/<nombre>/agent.yaml · prompt.md · output.schema │
│                   → declaran capacidades requeridas, no un modelo        │
├─────────────────────────────────────────────────────────────────────────┤
│ 2. PUERTO         core/model_port.py: capacidades → llamada → validación │
│                   de contrato → reintento → telemetría                   │
├─────────────────────────────────────────────────────────────────────────┤
│ 1. ADAPTADORES    core/adapters/: mock · hf_local · hf_endpoint · ollama │
│                   · anthropic (solo desarrollo interno)                  │
└─────────────────────────────────────────────────────────────────────────┘
```

## Estado

| Vertical | Agentes | Estado |
|---|---|---|
| Discovery | product-analyst, domain-modeling, ux-ui-copilot + governance + knowledge-rag | funcional con `mock`; listo para `hf_local` |
| Arquitectura, Ingeniería, Calidad, DevOps | 10 agentes | pendiente (misma plantilla) |

## Ejecutar

```bash
pip install -r requirements.txt
pytest -q                                                     # contratos + DAG con mock
PIPELINE_PROVIDER=mock python scripts/run_pipeline.py --req SIM-P05-R001
```

Con modelo open-weight (GPU): abrir `notebooks/run_pilot.ipynb` en Google Colab.

## Fases del trabajo

| Fase | Proveedor | Propósito | ¿Entra en la tesis? |
|---|---|---|---|
| 1 | `anthropic` / `mock` | validar contratos, DAG, gates y telemetría | No |
| 2 | `hf_local` (Qwen2.5-7B-Instruct) | piloto de 30 requerimientos; cifras de 3.1.3 | Sí |
| 3 | `hf_local` + LoRA en `product-analyst-agent` | ablación sin/con fine-tuning | Sí |

Toda llamada a modelo queda registrada en `telemetry/*.jsonl` con `provider` y `model_id`; así se
filtra y demuestra qué proveedor produjo cada dato reportado.

## Estructura

```
agents/<agente>/agent.yaml      F1 propósito · F2 contrato · F3 handoffs · F4 lógica · F5 verificación · gate RACI
agents/<agente>/prompt.md       instrucciones portables (sin sintaxis propietaria)
agents/<agente>/output.schema.json
contracts/                      schemas compartidos (BusinessRequest, FieldProvenance)
core/                           puerto de modelo, adaptadores, orquestador, verificación F5, rag, telemetría
config/                         providers.yaml · dag.yaml · gates.yaml
data/knowledge/                 corpus de la Empresa (reglas BR, ADR, specs, políticas, glosario)
data/requerimientos/<id>/       input/ (brief, restricciones) · output/ (artefactos) · logs/
tests/fixtures/<agente>/        respuestas grabadas para el proveedor mock
notebooks/                      run_pilot.ipynb (Fase 2) · finetune_qlora.ipynb (Fase 3, pendiente)
```

## Añadir un agente

1. Copiar `agents/product-analyst/` y editar `agent.yaml`, `prompt.md`, `output.schema.json`.
2. Añadir sus métricas F5 en `core/verify.py` (`METRICS`).
3. Añadir el nodo en `config/dag.yaml` y su gate en `config/gates.yaml`.
4. Grabar un fixture en `tests/fixtures/<agente>/` para que CI lo cubra.
