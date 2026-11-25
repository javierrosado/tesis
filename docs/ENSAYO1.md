# Ensayo informal `ensayo1` (23–24/11/2026)

Ensayo previo al piloto, con los requerimientos SIM-P05-R001 a R003, puertas humanas en modo manual (`GATES_MODE=manual`) y el maestro Qwen3-32B-AWQ cargado (`TEACHER_MODE=auto`). Sirvió para ajustar el pipeline. **Sus resultados no se reportan como resultados del piloto**: los cambios que motivó (D-E1 a D-E6) forman parte de la versión que se congela como `v1.0-piloto`.

- 20 jobs en HF Jobs (19 en `a100-large`, uno cancelado en cola), 12 059 s de cómputo, ≈ USD 8,4. Detalle por job en `runs/MANIFEST.md`.
- Decisiones humanas registradas literalmente con `scripts/pilot_control.py lote`; el dictamen de apoyo se guardó aparte (`dictamen_ia`). En este ensayo el dictamen lo redactó Claude; en el piloto lo genera el propio job (G5).

## Resultado

| Requerimiento | Estado al cierre | Comentario |
|---|---|---|
| SIM-P05-R001 | **Desplegado** en `tesis-sandbox` (`DEP-SIM-P05-R001`, intento 1, resultado `ok`, 24/11 16:17) | Recorrió los 16 agentes y todas las puertas; 14/14 pruebas en verde antes del release |
| SIM-P05-R002 | En espera de `code_review` | BR-012 implementada correctamente; las semillas no coinciden con los índices que usan las pruebas |
| SIM-P05-R003 | En espera de `qa_suite` y `code_review` | IDs de las pruebas distintos a los de las semillas; BR-005 y BR-021 no implementables con el modelo de datos aprobado |

## Hallazgos y decisiones

| # | Hallazgo | Decisión |
|---|---|---|
| D-E1 | Los modelos 8B no aplican las devoluciones humanas (las ignoran o pierden correcciones previas) | La corrección tras una devolución humana la genera el maestro 32B; la primera versión sigue siendo del agente |
| D-E2 | Los ciclos automáticos del bucle de calidad deshacían la devolución del Tech Lead; `qa_suite` y `backend_code` se aprobaban por riesgo bajo con pruebas fallidas o tautológicas | Devoluciones vigentes en todos los ciclos; `qa_suite` solo se aprueba sola con todas las pruebas en verde y llamando al servicio; regla F5 `calls_service` |
| D-E3 | Los errores no podían responder en problem+json (el handler no puede importar módulos) | El marco del servicio genera problem+json con el catálogo de errores del diseño de API |
| D-E4 | El contrato limitaba las filas de ejemplo a 5 por tabla | Hasta 10 filas por tabla |
| D-E5 | La salida del maestro se cortaba a 6144 tokens | Hasta 10 240 tokens, con reintento a 4096 si la entrada es larga |
| D-E6 | Suites con `@pytest.mark.xfail` sin `import pytest`; JSON inválido sin diagnóstico | El sistema agrega el import; `contract_rejected` guarda el contexto del error |

## Hallazgos sin corrección (pasan a limitaciones o a trabajo futuro)

- No existe forma de reabrir un artefacto ya aprobado aguas arriba: en R003 el modelo de datos aprobado no tiene precio de campaña ni stock por zona, y BR-005 y BR-021 quedaron en backlog.
- El backend de R003 (9 tablas) roza el límite de salida del maestro cuando genera muchas filas de ejemplo (≈ 32 000 caracteres).
- Las pruebas generadas suelen fijar índices o IDs de los datos de ejemplo; varias devoluciones se dedicaron a alinear semillas y pruebas.
- El analista de producto omite casos negativos y los modelos 8B proponen patrones sin justificar e identifican mal los datos personales.
