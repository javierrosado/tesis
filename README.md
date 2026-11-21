# Pipeline multiagente de IA para el ciclo de vida del requerimiento de software

Implementación de la tesis de **Maestría en Inteligencia Artificial (Universidad Nacional de Ingeniería, Perú)** 

Un requerimiento de negocio entra al pipeline y **16 agentes** lo transforman, dominio por dominio, en historias de usuario, arquitectura, API, modelo de datos, código, pruebas, pipeline de CI/CD y un plan de release. Cada artefacto pasa por un revisor automático (**governance**). Los de riesgo alto esperan la aprobación de una persona. Si el release sale *go*, el servicio se despliega en un repositorio de staging con GitHub Actions.

Todo funciona con **modelos de lenguaje de pesos abiertos** (sin APIs comerciales). Cinco agentes tienen un **adaptador QLoRA propio**, entrenado para esta tesis.

> **Estado al 20/11/2026:** pipeline de 16 agentes implementado y probado de punta a punta; 5 adaptadores entrenados y evaluados; comparación de modelos base ejecutada; despliegue real validado. **Piloto real con 30 requerimientos: del 23/11 al 04/12/2026.**

---

## Índice

1. [Objetivos de la tesis y dónde está la evidencia](#1-objetivos-de-la-tesis-y-dónde-está-la-evidencia)
2. [Arquitectura](#2-arquitectura)
3. [Estructura del repositorio](#3-estructura-del-repositorio)
4. [Hardware utilizado](#4-hardware-utilizado)
5. [Software y versiones](#5-software-y-versiones)
6. [Datos y datasets](#6-datos-y-datasets)
7. [Cómo reproducir cada experimento](#7-cómo-reproducir-cada-experimento)
8. [Resultados obtenidos](#8-resultados-obtenidos)
9. [Errores encontrados y soluciones](#9-errores-encontrados-y-soluciones)
10. [Trazabilidad, bitácora y control de versiones](#10-trazabilidad-bitácora-y-control-de-versiones)
11. [Costos](#11-costos)
12. [Limitaciones conocidas](#12-limitaciones-conocidas)

---

## 1. Objetivos de la tesis y dónde está la evidencia

| Objetivo específico | Qué se hizo | Evidencia en este repositorio |
|---|---|---|
| **OE1** · Diagnosticar el proceso actual | EDA de 150 requerimientos de 6 proyectos: seis indicadores (H1–H6) | [`notebooks/eda_linea_base.ipynb`](notebooks/eda_linea_base.ipynb) · datos en [`data/linea_base/`](data/linea_base/) |
| **OE2/OE3** · Diseñar el pipeline multiagente | 16 agentes con contrato (JSON Schema), criterios de verificación F5, DAG y matriz RACI | [`agents/`](agents/) · [`config/`](config/) · [`contracts/`](contracts/) |
| **OE3** · Implementar y entrenar | Orquestador propio, governance determinista, 5 adaptadores QLoRA, despliegue | [`core/`](core/) · [`jobs/`](jobs/) · [`notebooks/eda_datasets_entrenamiento.ipynb`](notebooks/eda_datasets_entrenamiento.ipynb) |
| **OE4** · Verificar en un piloto | Pruebas de humo, gates manuales y despliegue real hechos; piloto con 30 requerimientos programado | [`runs/MANIFEST.md`](runs/MANIFEST.md) · [`scripts/indicadores.py`](scripts/indicadores.py) |

## 2. Arquitectura

```
 Requerimiento (brief + restricciones)
        │
        ▼
 ┌──────────────── skill-orchestrator (orquestador propio: DAG, estado, reintentos, gates) ────────────────┐
 │                                                                                                          │
 │  DISCOVERY            ARQUITECTURA           INGENIERÍA              CALIDAD               DEVOPS          │
 │  product-analyst ─┬─► solution-architect ─►  api-designer ─────┐    test-case-generator   cicd-pipeline   │
 │  domain-modeling ─┤   security-compliance    data-model         ├─►  qa-automation   ─►   release-manager │
 │  ux-ui-copilot ───┘                          backend-developer ─┘    code-review           ─► despliegue  │
 │                                                                                                          │
 │  Cada artefacto ─► governance (contrato + criterios F5 + procedencia) ─► gate RACI (humano si riesgo alto) │
 │  Consulta de conocimiento: knowledge-rag (BM25 sobre data/knowledge)                                      │
 └──────────────────────────────────────────────────────────────────────────────────────────────────────────┘
        │
        ▼
 Rama req/<id> en javierrosado/tesis-sandbox ─► GitHub Actions (test + deploy)
```

**Modelos por agente** (definidos en [`config/providers.yaml`](config/providers.yaml)):

| Grupo | Agentes | Modelo |
|---|---|---|
| Entrenados (uno por dominio) | product-analyst, solution-architect, api-designer, test-case-generator, cicd-pipeline | `Qwen/Qwen3-8B` + adaptador QLoRA propio |
| Escriben y revisan código | backend-developer, qa-automation, code-review | `Qwen/Qwen3-32B-AWQ` (sin ajuste) |
| Funcionales restantes | domain-modeling, ux-ui-copilot, security-compliance, data-model, release-manager | `Qwen/Qwen3-8B` base |
| Transversales | governance, skill-orchestrator, knowledge-rag | Sin modelo de lenguaje (reglas, orquestador, BM25) |

Los modelos se sirven con **vLLM** (multi-LoRA y salida restringida por JSON Schema). El modelo es un recurso inyectado por configuración: cambiar de proveedor es editar `config/providers.yaml`.

## 3. Estructura del repositorio

```
tesis/
├── agents/<agente>/            Ficha de cada agente: agent.yaml (propósito, entradas, criterios F5, gate),
│                               prompt.md y output.schema.json (contrato de salida)
├── config/
│   ├── dag.yaml                Orden de ejecución de los 16 agentes (con etapas en paralelo)
│   ├── gates.yaml              Matriz RACI y nivel de riesgo por artefacto (modo manual/auto)
│   └── providers.yaml          Qué modelo atiende a cada agente (mock, vLLM, adaptadores, maestro)
├── contracts/                  Esquemas comunes (solicitud de negocio, procedencia)
├── core/
│   ├── orchestrator.py         Orquestador: DAG, reintentos, gates reanudables, bucle de calidad
│   ├── governance.py           Revisor determinista: contrato + F5 + procedencia, con hallazgos accionables
│   ├── verify.py               Cálculo de las métricas F5 de cada agente
│   ├── render.py               Generación determinista de OpenAPI 3.1 y workflows de GitHub Actions
│   ├── deploy.py               Empaquetado y despliegue a staging (GitHub API + Actions)
│   ├── tools/sandbox.py        DDL en SQLite, servicio FastAPI generado, pytest, ruff, bandit
│   ├── tools/rag.py            knowledge-rag (BM25)
│   ├── adapters/               Proveedores de modelo (mock, OpenAI-compatible/vLLM, HF local, Ollama)
│   ├── envinfo.py              Registro de hardware y versiones en cada job
│   └── telemetry.py            Eventos JSONL de cada ejecución (insumo de los indicadores)
├── data/
│   ├── linea_base/             Linea_BaseV2.xlsx: datos operativos de la Empresa (OE1)
│   ├── requerimientos/         SIM-P05-R001…R030: los 30 requerimientos del piloto
│   └── knowledge/              Corpus: reglas de negocio, ADRs, políticas, glosario, especificaciones
├── jobs/                       Scripts que se ejecutan en GPU con Hugging Face Jobs (uv, dependencias fijadas)
│   ├── f2a_distill.py          Destilación con el modelo maestro → datos de entrenamiento
│   ├── f3_train_qlora.py       Entrenamiento QLoRA de los adaptadores
│   ├── f3_eval.py              Evaluación base vs. adaptador
│   ├── compare_models.py       Comparación de modelos base (Qwen3-8B, Llama-3.1-8B, Mistral-7B)
│   └── run_pipeline_job.py     Ejecución del pipeline de 16 agentes (pruebas de humo y piloto)
├── notebooks/
│   ├── eda_linea_base.ipynb            EDA de la línea base (OE1), ejecutado
│   ├── eda_datasets_entrenamiento.ipynb EDA del dataset de entrenamiento, ejecutado
│   └── run_pilot.ipynb, finetune_qlora.ipynb   Históricos (etapa con Qwen2.5); no se usan
├── scripts/                    gen_seeds.py (requerimientos sintéticos), refilter_dataset.py, indicadores.py,
│                               pilot_control.py (aprobaciones humanas), run_pipeline.py (local)
├── tests/                      38 pruebas (contratos, governance, DAG, sandbox, gates, despliegue)
├── runs/MANIFEST.md            Registro de todas las corridas (fecha, commit, job, GPU, costo, resultado)
├── docs/BITACORA.md            Bitácora: fechas, decisiones y dificultades
└── CLAUDE.md                   Reglas de gobierno del desarrollo (secretos, PR obligatorio, presupuesto)
```

## 4. Hardware utilizado

| Uso | Hardware | Dónde |
|---|---|---|
| Entrenamiento QLoRA, evaluación, comparación de modelos, pipeline con modelos de 8B | **NVIDIA L40S, 48 GB** (`l40sx1`) | Hugging Face Jobs |
| Modelo maestro Qwen3-32B-AWQ (destilación) y pipeline con 8B + maestro a la vez | **NVIDIA A100, 80 GB** (`a100-large`) | Hugging Face Jobs |
| Orquestación, pruebas automáticas, EDA, notebooks | PC Windows x64 sin GPU (entorno Linux con Python 3.10) | Local |
| Despliegue a staging | Runner `ubuntu-latest` de GitHub Actions | GitHub |

Ejemplo de entorno registrado en un job (`core/envinfo.py`, 20/11/2026): `NVIDIA L40S, 46068 MiB, driver 620.70.06`, Python 3.12.12.

## 5. Software y versiones

**En GPU (jobs, versiones fijadas en la cabecera de cada script de `jobs/`):**

| Componente | Versión | Uso |
|---|---|---|
| Python | 3.12 | Entorno de los jobs (uv) |
| vLLM | 0.34.0 | Servidor de inferencia, multi-LoRA, salida restringida |
| xgrammar | 0.2.8 | Gramática de JSON Schema en vLLM |
| PyTorch | 2.14.0 (instalado por vLLM) | Inferencia |
| transformers | 4.56.2 (entrenamiento) · 5.22.2 (instalado por vLLM en inferencia) | Modelos |
| PEFT · TRL · bitsandbytes | PEFT ≥ 0.13 · TRL 0.19–0.23 · bitsandbytes (4 bits) | QLoRA |
| huggingface_hub | 2.4.0 | Datos, modelos y jobs |
| jsonschema · openapi-spec-validator | 4.26.0 · 0.9.0 | Contratos y validación de OpenAPI |

**Modelos:** `Qwen/Qwen3-8B` (Apache 2.0), `Qwen/Qwen3-32B-AWQ` (Apache 2.0), y para la comparación `meta-llama/Llama-3.1-8B-Instruct` (licencia Llama 3.1) y `mistralai/Mistral-7B-Instruct-v0.3` (Apache 2.0).

**Local** (`requirements.txt`): Python 3.10, jsonschema 4.26.0, PyYAML 6.0.3, pytest 9.2.0, openapi-spec-validator 0.9.0, FastAPI 0.162.5, httpx 0.28.1, ruff 0.17.6, bandit 1.9.4, huggingface_hub 2.4.0. Notebooks: pandas, matplotlib, scipy, tokenizers, jsonschema.

**Configuración del entrenamiento:** QLoRA en 4 bits (NF4), rango 16, α 32, 2 épocas, tasa de aprendizaje 2e-4 con coseno, pérdida solo sobre la respuesta, longitud máxima de 8 192 tokens (12 288 en DevOps), **semilla 2026**. Inferencia de evaluación: temperatura 0, una generación por caso, salida restringida por JSON Schema, `enable_thinking=false` en Qwen3.

## 6. Datos y datasets

| Dataset | Contenido | Uso | Acceso |
|---|---|---|---|
| [`data/linea_base/Linea_BaseV2.xlsx`](data/linea_base/) | 6 proyectos, 150 requerimientos, 83 defectos, 40 despliegues, 666 handoffs | Línea base OE1 | Público |
| [`data/requerimientos/`](data/requerimientos/) | 30 requerimientos del Squad Fuerza de Ventas (SIM-P05) | Piloto y pruebas de humo (nunca se usaron para entrenar) | Público |
| [`data/knowledge/`](data/knowledge/) | Reglas de negocio, ADRs, políticas, glosario, especificaciones | Corpus de knowledge-rag | Público |
| [jrosado1974/tesis-sft-v2](https://huggingface.co/datasets/jrosado1974/tesis-sft-v2) | **1 013 ejemplos** (train 810 · val 116 · test 87) de 5 agentes | Entrenamiento y evaluación | Público |
| [jrosado1974/tesis-runs](https://huggingface.co/datasets/jrosado1974/tesis-runs) | Resultados de evaluación, comparación, telemetría y estado de corridas | Evidencia de resultados | Público |
| tesis-sft-pilot, tesis-sft, tesis-sft-r2, tesis-sft-final | Etapas intermedias de la destilación | Linaje de tesis-sft-v2 | Privado |

**Cómo se generaron los datos de entrenamiento (linaje):** `scripts/gen_seeds.py` crea requerimientos sintéticos → el modelo maestro `Qwen3-32B-AWQ` ejecuta el pipeline (`jobs/f2a_distill.py`) → governance acepta o rechaza cada salida → 1 165 ejemplos aprobados (`tesis-sft-final`) → re-filtrado con governance v2 (852) + 161 ejemplos de DevOps regenerados (`jobs/f2a_regen_agent.py`) = **1 013** (`tesis-sft-v2`). Las particiones son por requerimiento: no hay fuga entre train/val/test ni con el piloto (verificado en el notebook de EDA).

### 6.1 Datos sintéticos y datos reales

**Los datos sintéticos se usan solo para entrenar; todo lo que mide el impacto usa datos reales.** Detalle, justificación y referencias en [`docs/DATOS.md`](docs/DATOS.md).

| Uso | Datos | Naturaleza |
|---|---|---|
| Entrenar y evaluar los adaptadores (F3) | `tesis-sft-v2` (semillas SIM-T01…T05 destiladas por el maestro) | Sintético, validado con JSON Schema y governance |
| Línea base AS-IS (OE1) | `Linea_BaseV2.xlsx` | Real, anonimizado |
| Piloto (OE4) | `data/requerimientos/SIM-P05-*` | Real (caso del Squad Fuerza de Ventas) |

Por qué: no existe un corpus etiquetado con los contratos de estos agentes y los requerimientos de la Empresa son confidenciales; generar, filtrar y ajustar es el esquema de Self-Instruct (Wang et al., 2023) y de la destilación (Hsieh et al., 2023).

Verificación de que el piloto no está en el entrenamiento (`python scripts/verificar_fuga.py`, ~5 s, sin GPU): 0 identificadores y 0 títulos en común; el requerimiento del piloto más parecido a uno de entrenamiento tiene similitud 0,655, menor que la que hay entre requerimientos de entrenamiento distintos (mediana 0,67). Resultado: **sin fuga**.

**Adaptadores entrenados (públicos):** [qwen3-8b-product-analyst-lora](https://huggingface.co/jrosado1974/qwen3-8b-product-analyst-lora) · [qwen3-8b-solution-architect-lora](https://huggingface.co/jrosado1974/qwen3-8b-solution-architect-lora) · [qwen3-8b-api-designer-lora](https://huggingface.co/jrosado1974/qwen3-8b-api-designer-lora) · [qwen3-8b-test-case-generator-lora](https://huggingface.co/jrosado1974/qwen3-8b-test-case-generator-lora) · [qwen3-8b-cicd-pipeline-lora](https://huggingface.co/jrosado1974/qwen3-8b-cicd-pipeline-lora)

## 7. Cómo reproducir cada experimento

### 7.1 Requisitos

| Para | Necesitas |
|---|---|
| Pruebas locales y EDA | Python 3.10+ y git. Sin GPU ni cuentas |
| Experimentos en GPU | Cuenta de Hugging Face con saldo para [Jobs](https://huggingface.co/docs/huggingface_hub/guides/jobs) (o plan PRO), token con permiso de escritura y la CLI `hf` |
| Llama-3.1-8B en la comparación | Aceptar su licencia en su página de Hugging Face |
| Despliegue a staging | Un repositorio de GitHub propio y un token con permisos Contents, Actions y Workflows |

### 7.2 Instalación y pruebas locales (sin GPU, ~2 min)

```bash
git clone https://github.com/javierrosado/tesis.git && cd tesis
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pytest -q                                               # resultado esperado: 38 passed
PIPELINE_PROVIDER=mock python scripts/run_pipeline.py --req SIM-P05-R001   # pipeline completo con respuestas grabadas
```

### 7.3 EDA (sin GPU, en Colab o local)

| Notebook | Abrir en Colab | Resultado esperado |
|---|---|---|
| Línea base (OE1) | [eda_linea_base.ipynb](https://colab.research.google.com/github/javierrosado/tesis/blob/main/notebooks/eda_linea_base.ipynb) | 66,5 días · 45 % · 34 % · 1,0 · 0 % · 0 % / 30,9 % |
| Dataset de entrenamiento | [eda_datasets_entrenamiento.ipynb](https://colab.research.google.com/github/javierrosado/tesis/blob/main/notebooks/eda_datasets_entrenamiento.ipynb) | 1 013 ejemplos · 100 % válidos · 0 requerimientos en común entre particiones |
| Separación piloto / entrenamiento | `python scripts/verificar_fuga.py` (local, sin GPU) | 0 ids · 0 títulos · similitud máx. 0,655 · SIN FUGA |

### 7.4 Experimentos en GPU (Hugging Face Jobs)

Prepara tu entorno (una vez):

```bash
pip install -U huggingface_hub && hf auth login
export U=<tu_usuario_hf>
hf repo create $U/tesis-runs --repo-type dataset     # aquí se guardan tus resultados
```

**a) Evaluación base vs. adaptador** (usa los adaptadores públicos; L40S, ~10 min por agente, ~USD 0,3):

```bash
hf jobs uv run --flavor l40sx1 --timeout 1h --secrets HF_TOKEN \
  -e BRANCH=main -e SFT_REPO=jrosado1974/tesis-sft-v2 -e RUNS_REPO=$U/tesis-runs \
  -e "ADAPTERS=cicd-pipeline-agent=jrosado1974/qwen3-8b-cicd-pipeline-lora" \
  jobs/f3_eval.py
# para los 5 agentes, añade los otros pares agente=repo separados por espacio en ADAPTERS
```

Resultado esperado (DevOps): adaptador **9/9 aprobados (100 %)**, ~1 800 tokens, ~95 s por respuesta; base entre 2/9 y 3/9.

**b) Comparación de modelos base** (L40S, ~30 min, ~USD 0,9):

```bash
hf jobs uv run --flavor l40sx1 --timeout 2h --secrets HF_TOKEN \
  -e BRANCH=main -e SFT_REPO=jrosado1974/tesis-sft-v2 -e RUNS_REPO=$U/tesis-runs \
  jobs/compare_models.py
```

Resultado esperado: aprobación en ronda 0 de Qwen3-8B ≈ 83 %, Llama-3.1-8B ≈ 61 %, Mistral-7B ≈ 72 %.

**c) Entrenamiento QLoRA** (publica los adaptadores en tu cuenta; L40S, 15–35 min por agente):

```bash
hf jobs uv run --flavor l40sx1 --timeout 3h --secrets HF_TOKEN \
  -e SFT_REPO=jrosado1974/tesis-sft-v2 -e AGENTS=product-analyst-agent \
  jobs/f3_train_qlora.py
# DevOps: -e AGENTS=cicd-pipeline-agent -e MAX_LEN=12288
```

Resultado esperado: pérdida de validación cercana a la de la tabla de la sección 8 (p. ej., product-analyst ≈ 0,18).

**d) Pipeline de 16 agentes** (A100: Qwen3-8B + adaptadores + maestro; ~15 min para 3 requerimientos):

```bash
AD="product-analyst-agent=jrosado1974/qwen3-8b-product-analyst-lora solution-architect-agent=jrosado1974/qwen3-8b-solution-architect-lora api-designer-agent=jrosado1974/qwen3-8b-api-designer-lora test-case-generator-agent=jrosado1974/qwen3-8b-test-case-generator-lora cicd-pipeline-agent=jrosado1974/qwen3-8b-cicd-pipeline-lora"
hf jobs uv run --flavor a100-large --timeout 1h --secrets HF_TOKEN \
  -e BRANCH=main -e PILOT=prueba1 -e REQS=SIM-P05-R001,SIM-P05-R002,SIM-P05-R003 \
  -e RUNS_REPO=$U/tesis-runs -e "ADAPTERS=$AD" -e GATES_MODE=auto -e TEACHER_MODE=always \
  jobs/run_pipeline_job.py
# Gates humanos: GATES_MODE=manual y luego
#   python scripts/pilot_control.py pendientes --pilot prueba1
#   python scripts/pilot_control.py decidir --pilot prueba1 --req SIM-P05-R001 --artefacto user_story_set --decision approved
# Despliegue real: añade --secrets GITHUB_TOKEN -e DEPLOY_REPO=<tu_usuario>/<tu_repo_staging>
```

**e) Indicadores desde la telemetría:**

```bash
python scripts/indicadores.py <carpeta>/telemetria/*.jsonl --md indicadores.md
```

### 7.5 ¿Qué tan comparables serán los resultados?

- **Deterministas (idénticos):** EDA de la línea base, EDA del dataset, governance, pruebas locales.
- **Entrenamiento:** semilla fija (2026); se esperan pérdidas muy cercanas, no idénticas bit a bit.
- **Inferencia con vLLM a temperatura 0:** el procesamiento por lotes puede cambiar **1–2 casos** entre corridas. Reproducción verificada el 20/11/2026 (job `6b00e7664fdc5ab3c55c332b`): adaptador de DevOps **9/9, idéntico a F3** (1 805 vs. 1 810 tokens; 94,7 vs. 94,4 s); el modelo base pasó de 2/9 a 3/9.
- Cada job imprime y guarda su entorno (`ENTORNO …` en el log y `entorno.json` con los resultados): GPU, driver y versiones.

## 8. Resultados obtenidos

**Entrenamiento y evaluación (partición de prueba, 87 casos):**

| Agente (dominio) | Ejemplos entren./val./prueba usados | Pérdida de validación | Aprobación en ronda 0: base → LoRA | McNemar p | Tokens de salida |
|---|---|---|---|---|---|
| product-analyst (Discovery) | 211 / 29 / 24 | 0,178 | 91,7 % → 95,8 % | 1,000 | 609 → 602 |
| solution-architect (Arquitectura) | 143 / 20 / 18 | 0,211 | 100 % → 94,4 % | 1,000 | 1 247 → 901 |
| api-designer (Ingeniería) | 177 / 26 / 22 | 0,069 | 90,9 % → 100 % | 0,500 | 1 688 → 1 109 |
| test-case-generator (Calidad) | 129 / 22 / 14 | 0,115 | 92,9 % → 92,9 % | 1,000 | 1 770 → 1 240 |
| cicd-pipeline (DevOps) | 136 / 16 / 9 | 0,028 | **22,2 % → 100 %** | **0,016** | 2 431 → 1 810 |

**Comparación de modelos base (mismos 87 casos, sin ajuste):**

| Indicador | Qwen3-8B | Llama-3.1-8B | Mistral-7B |
|---|---|---|---|
| Contrato válido | **100 %** | 98,9 % | 93,1 % |
| Aprobación en ronda 0 | **82,8 %** | 60,9 % | 72,4 % |
| McNemar (Qwen vs. otro) | — | p = 0,0002 | p = 0,039 |
| Tokens / latencia | 1 427 / 64 s | **1 070 / 44 s** | 1 833 / 80 s |

**Pipeline:** dos requerimientos recorrieron los 16 agentes hasta un release *no-go* justificado por pruebas fallidas; despliegue real en staging con GitHub Actions ([run 44764311596](https://github.com/javierrosado/tesis-sandbox/actions/runs/44764311596): test ✔ y deploy ✔); flujo de aprobación humana probado en GPU (pausa → dictamen → devolución → reproceso).

**Definiciones:** *contrato válido* = la salida cumple el JSON Schema del agente; *aprobación en ronda 0* = la primera respuesta, sin correcciones, cumple contrato + criterios F5 + procedencia (equivale a la *accuracy* de un agente generativo); *McNemar exacto* compara dos modelos sobre los mismos casos usando solo los casos donde discrepan.

## 9. Errores encontrados y soluciones

| # | Fase | Error | Solución | Resultado |
|---|---|---|---|---|
| 1 | F1 | Governance con LLM inconsistente (1 → 8 → 10 hallazgos) | Governance determinista | 3/3 artefactos aprobados |
| 2 | F2-A | Salidas truncadas a 2 048 tokens | Límite de 4 096–6 144; JSON inválido = rechazo | Sin truncamientos |
| 3 | F2-A | YAML dentro de JSON degeneraba | Diseño estructurado + render determinista (`core/render.py`) | 7/7 aprobados |
| 4 | F2-A | vLLM rechazaba el esquema (HTTP 400) | Esquema adaptado a la gramática + reintento | Salida estable |
| 5 | F3 | Regeneración perdida por timeout | Script reanudable con publicación incremental | 161 ejemplos de DevOps |
| 6 | F3 | Entrenamiento sin gradiente (4 bits) | `prepare_model_for_kbit_training` + checkpointing no reentrante | Entrenamiento correcto |
| 7 | F3 | 128/150 ejemplos de DevOps descartados por longitud | Límite de 12 288 tokens | Pérdida de validación 0,028 |
| 8 | F4 | Código del backend inválido (comillas, DB) | DB con `json.loads`, comillas simples, firmas y tablas en la entrada | Servicio importable |
| 9 | F4 | El 8B base no producía código que pasara pruebas | Maestro Qwen3-32B para backend, QA y code-review | Aprobación en ronda 0 |
| 10 | F4 | Job de despliegue sin checkout | Adaptación determinista registrada en el empaquetado | test ✔ y deploy ✔ |

## 10. Trazabilidad, bitácora y control de versiones

- **Bitácora** con fechas, decisiones y dificultades: [`docs/BITACORA.md`](docs/BITACORA.md).
- **Registro de corridas:** [`runs/MANIFEST.md`](runs/MANIFEST.md) — 44 corridas con fecha, fase, commit/rama, id del job, GPU, duración, costo, modelo, dataset, semilla, métricas y estado. Los logs de cada job se consultan con `hf jobs logs <id>`.
- **Control de versiones:** una rama por fase y merge a `main` solo por pull request revisado por el autor: [PR #1–#8](https://github.com/javierrosado/tesis/pulls?q=is%3Apr).
- **Versión que produjo cada resultado:** la columna *Commit* del MANIFEST indica la rama o el commit; los jobs descargan exactamente esa rama de GitHub al iniciar.
- **Telemetría por requerimiento:** cada ejecución de agente, veredicto de governance, gate humano y despliegue queda en `tesis-runs/piloto/<piloto>/telemetria/*.jsonl`.

## 11. Costos

| Fase | GPU (USD) |
|---|---|
| F1 Vertical Discovery | 0,63 |
| F2-A Destilación | 9,68 |
| F3 Entrenamiento y evaluación | 11,42 |
| F4 Pipeline de 16 agentes | 4,27 |
| Comparación de modelos + verificación de reproducibilidad | 1,13 |
| **Total** | **≈ 27,13** |

## 12. Limitaciones conocidas

- Los datos de entrenamiento son sintéticos (la línea base y el piloto son reales; ver [`docs/DATOS.md`](docs/DATOS.md)) y sus respuestas de referencia vienen del maestro: el techo del adaptador es el maestro filtrado por governance.
- La partición de prueba de F3 también es sintética: F3 mide el efecto controlado del entrenamiento; la evidencia en contexto real la aporta el piloto.
- Particiones de prueba pequeñas (9–24 casos por agente).
- Qwen3-8B es de la misma familia que el maestro, lo que le da ventaja en el ajuste fino.
- Los tres agentes de código usan el maestro sin ajustar; ahí no se mide el efecto del entrenamiento.
- Las aprobaciones humanas del piloto las ejerce una sola persona en todos los roles.
- El entorno de despliegue es staging; no hay incidentes de producción.

---

Licencia del código: uso académico. Modelos y datos de terceros bajo sus propias licencias (Qwen: Apache 2.0; Llama 3.1: Llama Community License; Mistral: Apache 2.0).
