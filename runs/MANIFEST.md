# Registro de corridas

| Fecha | Fase | Commit | Job ID | Flavor | Duración | Costo USD | Modelo / adaptador | Dataset | Semilla | Métricas | Estado |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-18 | F0 | — | local | VM local | — | 0 | mock | SIM-P05-R001 | 2026 | pytest 7/7; dry-run OK | ✅ |
| 2026-11-18 | F1 | 949df90 | 6afe5f16e41aae15936d14e6 | l4x1 | 0 s (cancelado en cola) | 0 | — | — | 2026 | sin hardware disponible | ⛔ cancelado |
| 2026-11-18 | F1 | 949df90 | 6afe634b545f95df1c06edaa | l40sx1 | 169 s | ~0,08 | Qwen/Qwen3-8B int4 | SIM-P05-R001 | 2026 | falta dependencia `datasets` | ❌ |
| 2026-11-18 | F1 | 6ffdfc3 | 6afe64aee41aae15936d1764 | l40sx1 | 699 s | ~0,35 | Qwen/Qwen3-8B int4 | SIM-P05-R001 | 2026 | schema válido 100 % (3/3 agentes, 9 salidas); product-analyst pasa F5 (GWT 1,0); governance-LLM inconsistente (1→8→10 hallazgos, falso hallazgo de schema); domain-modeling ubiquitous_coverage 0→0,6; 2 escalamientos max_rounds | ⚠️ pipeline E2E real OK, falla por governance |
| 2026-11-18 | F1.1 | 463a1b0 | 6afe6899545f95df1c06f037 | l40sx1 | 406 s | ~0,20 | Qwen/Qwen3-8B int4 + governance determinista | SIM-P05-R001 | 2026 | pipeline completo: 3/3 artefactos aprobados; schema 100 %; F5 100 % al cierre (GWT 1,0, BR 1,0, story_coverage 1,0, ubiquitous_coverage 0→1,0 tras 1 reintento); 2 rechazos corregidos con feedback; 0 escalamientos; gates RACI en modo auto | ✅ |
| 2026-11-19 | F2-A | f2a-agentes | 6afef6ffefaf5e14f4b15a44 | l40sx1 | 502 s | ~0,25 | Qwen/Qwen3-8B int4 (hf_local) | SIM-P05-R001 | 2026 | Discovery OK; solution-architect truncado a 2048 tokens (JSON sin cerrar) | ❌ |
| 2026-11-19 | F2-A | f2a-agentes | 6afef98b4fdc5ab3c559af8d | l40sx1 | 832 s | ~0,42 | Qwen/Qwen3-8B (vLLM) | SIM-P05-R001 | 2026 | 4/7 agentes aprobados (Discovery + Arquitectura); api-designer degenera al escribir YAML dentro de JSON | ❌ |
| 2026-11-19 | F2-A | f2a-agentes | 6afef7f4efaf5e14f4b15c58 | l40sx1 | 1208 s | ~0,60 | maestro Qwen/Qwen3-32B-AWQ (vLLM) | 6 semillas SIM-T0x | 2026 | 11 ejemplos (product-analyst 6, solution-architect 5); api-designer 0/6 (openapi_valid) → rediseño a diseño estructurado + render determinista | ⚠️ piloto de destilación |
| 2026-11-19 | F2-A | f2a-agentes | 6aff00924fdc5ab3c559be8a / 6aff0099efaf5e14f4b16e47 | l40sx1 | 0 s | 0 | — | — | — | CANCELED antes de ejecutar (no cancelado desde el chat) | ⛔ |
| 2026-11-19 | F2-A | f2a-agentes | 6aff07f04fdc5ab3c559c9a4 | l40sx1 | 259 s | ~0,13 | Qwen/Qwen3-8B (vLLM) | SIM-P05-R001 | 2026 | HTTP 400 de vLLM: regex + maxLength no soportado por la gramática | ❌ |
| 2026-11-19 | F2-A | f2a-agentes | 6aff0d114fdc5ab3c559d0bc | l40sx1 | 441 s | ~0,22 | Qwen/Qwen3-8B (vLLM) | SIM-P05-R001 | 2026 | reintento sin límites perdió cardinalidades (errores dentro de respuestas) | ❌ |
| 2026-11-19 | F2-A | f2a-agentes | 6aff0d174fdc5ab3c559d0c6 | l40sx1 | 641 s | ~0,32 | maestro Qwen3-32B-AWQ | 6 semillas SIM-T0x | 2026 | 2/6 pipelines completos; ejemplos en los 5 agentes (PA 6, SA 5, API 3, TC 2, CICD 2) | ⚠️ piloto destilación |
| 2026-11-19 | F2-A | f2a-agentes | 6aff10d04fdc5ab3c559d528 | l40sx1 | 481 s | ~0,24 | Qwen/Qwen3-8B (vLLM) | SIM-P05-R001 | 2026 | **7/7 artefactos aprobados**; OpenAPI 3.1 y 3 workflows válidos; 3 rechazos corregidos en 1 reintento; 0 escalamientos; 12 955 tokens de salida | ✅ |
