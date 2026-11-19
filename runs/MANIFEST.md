# Registro de corridas

| Fecha | Fase | Commit | Job ID | Flavor | Duración | Costo USD | Modelo / adaptador | Dataset | Semilla | Métricas | Estado |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 2026-11-18 | F0 | — | local | VM local | — | 0 | mock | SIM-P05-R001 | 2026 | pytest 7/7; dry-run OK | ✅ |
| 2026-11-18 | F1 | 949df90 | 6afe5f16e41aae15936d14e6 | l4x1 | 0 s (cancelado en cola) | 0 | — | — | 2026 | sin hardware disponible | ⛔ cancelado |
| 2026-11-18 | F1 | 949df90 | 6afe634b545f95df1c06edaa | l40sx1 | 169 s | ~0,08 | Qwen/Qwen3-8B int4 | SIM-P05-R001 | 2026 | falta dependencia `datasets` | ❌ |
| 2026-11-18 | F1 | 6ffdfc3 | 6afe64aee41aae15936d1764 | l40sx1 | 699 s | ~0,35 | Qwen/Qwen3-8B int4 | SIM-P05-R001 | 2026 | schema válido 100 % (3/3 agentes, 9 salidas); product-analyst pasa F5 (GWT 1,0); governance-LLM inconsistente (1→8→10 hallazgos, falso hallazgo de schema); domain-modeling ubiquitous_coverage 0→0,6; 2 escalamientos max_rounds | ⚠️ pipeline E2E real OK, falla por governance |
