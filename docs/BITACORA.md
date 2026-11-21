# Bitácora de la implementación

Registro cronológico de actividades, decisiones y dificultades de la implementación de la tesis. Las decisiones con código **D-xx** las tomó el autor (Javier Rosado); el detalle de cada corrida está en [`runs/MANIFEST.md`](../runs/MANIFEST.md) y cada cambio de código en su pull request.

## Línea de tiempo

| Fecha | Fase | Actividad | Decisión o resultado | Dificultad y cómo se resolvió |
|---|---|---|---|---|
| 23/10/2026 | OE1 | EDA de la línea base AS-IS (`Linea_BaseV2.xlsx`, 150 requerimientos) | 5 de 6 indicadores reproducen exactamente el plan; H4 = 1,0 solo con todos los despliegues | Denominador de H4 ambiguo → se documenta la alternativa (0,69 con solo releases) |
| 27/10/2026 | Diseño | Restricción del asesor: entrenar modelos y no usar API keys comerciales | Modelos de pesos abiertos en Hugging Face | — |
| 06/11/2026 | Diseño | Orquestador propio, sin licencia de plataforma | Capa de proveedor intercambiable (`config/providers.yaml`) | — |
| 18/11/2026 | F0 | Repositorio, reglas de gobierno (`CLAUDE.md`), CI con proveedor `mock` | **D-IMP-1:** piloto con ejecución real (se abandona la simulación) · **D-IMP-3:** Qwen3-8B + un adaptador QLoRA por dominio | — |
| 18/11/2026 | F1 | Vertical Discovery (3 agentes) en GPU | Esquema válido 100 % | La governance con LLM era inconsistente (1 → 8 → 10 hallazgos) → **governance determinista (F1.1)**: 3/3 artefactos aprobados |
| 19/11/2026 | F2-A | Agentes de los 5 dominios + destilación con Qwen3-32B-AWQ | 7/7 artefactos aprobados; 1 165 ejemplos (`tesis-sft-final`) | Salidas truncadas a 2 048 tokens · YAML dentro de JSON · HTTP 400 de vLLM por regex → límite de tokens, diseño estructurado + render determinista, esquema adaptado a la gramática |
| 19/11/2026 | F2-A | Corrida larga de destilación (R001–R200) | Cancelada por decisión del autor (opción B) con 253 ejemplos conservados | Se relanzó sobre R201–R400: 178/194 pipelines completos (92 %) |
| 19/11/2026 | F3 | Governance v2 (6 correcciones semánticas) y re-filtrado | `tesis-sft-v2`: 852 válidos + 161 de DevOps regenerados = 1 013 | Regeneración perdida por timeout → script reanudable con publicación incremental |
| 19–20/11/2026 | F3 | QLoRA de 5 adaptadores (rango 16, 2 épocas, semilla 2026) | Pérdida de validación ≤ entrenamiento en los 5 (sin sobreajuste) | Entrenamiento sin gradiente → `prepare_model_for_kbit_training` + checkpointing no reentrante · 128/150 ejemplos de DevOps descartados por longitud → límite de 12 288 tokens |
| 20/11/2026 | F3 | Evaluación base vs. adaptador (87 casos de prueba) | DevOps 22,2 % → 100 % (McNemar p = 0,016); 26–34 % menos tokens | Variación de ±1 caso del modelo base entre corridas (inferencia por lotes) → se declara |
| 20/11/2026 | F4 | Pipeline de 16 agentes, gates por riesgo, despliegue a staging | **D-P1–D-P5** aprobadas; tope USD 5 | 13 fallas corregidas en la prueba de humo (ver tabla de errores del README) |
| 20/11/2026 | F4 | Agentes que escriben código | **D-F4-1 opción C:** backend, QA y code-review con Qwen3-32B-AWQ | Con Qwen3-8B base el código no pasaba las pruebas tras 5 rondas |
| 20/11/2026 | F4 | Despliegue real a `javierrosado/tesis-sandbox` | GitHub Actions: test ✔ y deploy ✔ | El job de despliegue no hacía checkout → adaptación determinista registrada |
| 20/11/2026 | F4 | Flujo de gates manuales en GPU | **Opción A:** el autor decide los gates en lote; el dictamen de IA se registra aparte | Se descartó que la IA apruebe en nombre del autor (integridad de los datos) |
| 20/11/2026 | Selección | Comparación de modelos base | Qwen3-8B 82,8 % vs. Llama-3.1-8B 60,9 % vs. Mistral-7B 72,4 % (McNemar p = 0,0002 y 0,039) | — |
| 20/11/2026 | Semana 10 | Reproducibilidad | Versiones fijadas, registro de entorno en cada job, notebooks de EDA, README detallado | Reproducción del adaptador de DevOps: 9/9 (idéntico a F3) |
| 23/11–04/12/2026 | F5 | Piloto real con los 30 requerimientos del squad | Pendiente | — |

## Decisiones metodológicas (resumen)

| Código | Decisión | Motivo |
|---|---|---|
| D-IMP-1 | Piloto con ejecución real del pipeline (no simulación) | El asesor pide entrenar modelos; los resultados deben salir de lo ejecutado |
| D-IMP-3 | Qwen3-8B como base, 5 adaptadores QLoRA (uno por dominio) | Pesos abiertos, cabe en una GPU, misma familia que el maestro; confirmado por la comparación de modelos |
| F1.1 | Governance determinista (sin LLM) | La revisión con LLM no era reproducible |
| F2-A | Datos de entrenamiento por destilación + filtro de governance | No hay datos etiquetados; el filtro garantiza calidad verificable |
| D-P4 | Aprobación humana por riesgo (5–6 gates por requerimiento) | 13 gates por requerimiento eran inviables |
| D-F4-1 | Modelo maestro para los agentes de código | El 8B base no producía código que pasara las pruebas |
| Opción A | Decisión humana en lote con dictamen de IA registrado aparte | Reduce la carga sin falsear el dato humano; permite medir la concordancia humano–IA |
| Release | Solo un hallazgo de seguridad crítico bloquea; mayor y menor van al backlog | Alineado con la política escrita ("puertas de seguridad definidas") |
