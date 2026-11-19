# Reglas de ejecución del repo (gobierno de la implementación)

Este repo implementa el pipeline multiagente de la tesis de maestría (UNI). El gobierno de la
implementación se hace desde el Proyecto "Tesis 2" en Claude; este archivo fija las reglas que
cualquier agente que ejecute código en el repo debe cumplir.

## Secretos
- Los tokens viven FUERA del repo, en `../secrets/.env` (HF_TOKEN, GITHUB_TOKEN, HF_USERNAME, GITHUB_USER).
- Nunca imprimir, registrar ni commitear un token. Cargar con `source scripts/load_env.sh`.
- Ningún proveedor comercial por API key en el piloto reportado (restricción del asesor).
  El adaptador `anthropic` es solo para pruebas internas que no entran en la tesis.

## Ramas y cambios
- `main` solo se actualiza por Pull Request aprobado por Javier.
- Una rama por fase: `f0-setup`, `f1-discovery`, `f2-dataset`, `f3-finetune`, `f4-agentes`, `f5-piloto`, `f6-contraste`.
- Cada PR debe pasar el CI (pytest + dry-run con proveedor `mock`).

## Cómputo y costo
- GPU solo vía Hugging Face Jobs, con `configs/<corrida>.yaml` que declare flavor, timeout y tope de costo.
- Ningún job sin aprobación explícita de Javier en el chat del proyecto.
- Toda corrida se registra en `runs/MANIFEST.md` (fecha, commit, job id, flavor, costo, modelo, dataset, semilla, métricas).

## Reproducibilidad
- Semilla por defecto: 2026. Modelo base: `Qwen/Qwen3-8B` (revisión fijada en cada config).
- Un adaptador QLoRA por dominio: product-analyst (Discovery), solution-architect (Arquitectura),
  api-designer (Ingeniería), test-case-generator (Calidad), cicd-pipeline (DevOps). Gobernanza sin modelo.
- Modelos y datasets en el Hub, privados, bajo el usuario de `HF_USERNAME`.
- No modificar `data/knowledge/` ni `data/requerimientos/*/input/` sin decisión registrada.

## Aprobaciones humanas (RACI)
- Las ejerce el investigador en nombre de cada rol; cada aprobación registra rol, decisión y timestamp real
  en el decision_log. Su tiempo de respuesta forma parte del lead time (H1).
