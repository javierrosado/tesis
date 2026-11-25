# eval_n3 · Conjunto de evaluación de los agentes N3 (v2)

Base: `Seleccion_Modelos_por_Nivel_Razonamiento` v1.0 (§3 CMA y §4 usos 3 y 4) y plan de implementación v1 (N1). Sirve para el
benchmark N3 (GLM-5.3 vs DeepSeek V4-Pro/Flash, con Claude como techo de referencia) y para decidir la escalera E0–E4.

## 1. Qué se mide

| Agente N3 | Entrada congelada | Métrica (CMA) |
|---|---|---|
| solution-architect | historias + dominio + UX aprobados | aprobación de governance en la ronda 0 (≥ 80 %) y rúbrica del juez (1–5) |
| data-model | arquitectura + dominio aprobados | aprobación en la ronda 0 (≥ 80 %) y rúbrica |
| security-compliance | arquitectura + historias | aprobación en la ronda 0 (≥ 80 %) y rúbrica del juez (trabaja sobre la arquitectura, no sobre el código) |
| backend-developer | diseño de API + modelo de datos aprobados | **pass@1** de las pruebas de aceptación del caso (≥ 70 %) |
| code-review | servicio con un defecto sembrado (lógica o seguridad), con el análisis estático y el reporte de las pruebas del pipeline v1, igual que en el pipeline | **recall de defectos sembrados** (≥ 70 %), con falsos positivos sobre el servicio limpio |

Pares de modelos sobre los mismos casos → McNemar exacto (condición C3 de E4).

**Ajuste tras los humos del 25/11/2026 (decisión de Javier, opción recomendada).** Con 2 casos, governance aprobó al 100 % a los
4 modelos en SA, data-model y security (no discrimina), pass@1 del backend fue 0 % en todos (las pruebas de referencia fijan
valores que la entrada no especifica, p. ej. `'ENVIADO'`) y code-review detectó el 100 % en todos (los mutantes de lógica
aparecen en el reporte de pruebas y bandit señala los patrones de seguridad). Métricas principales desde entonces:

| Agente | Principal | Secundarias |
|---|---|---|
| solution-architect, data-model, security | puntaje del juez 1–5 (Qwen3.6-35B-A3B, no candidato) · Wilcoxon pareado | aprobación en ronda 0 |
| backend-developer | % de pruebas de aceptación que pasan por caso · Wilcoxon pareado | pass@1 |
| code-review | falsos positivos sobre el servicio limpio y precisión de localización (hallazgos graves dentro del handler del defecto) | recall total y por tipo · McNemar |

El juez no califica los artefactos de Claude (techo); su acuerdo con la revisión humana del 20 % se mide con kappa ponderado.

**Segundo ajuste (humo 6b073c94, 5 casos, USD 8,49).** El juez 1–5 puso casi todo en 5 (sin diferencias), el backend
pasó solo el 12–19 % de las pruebas en los 4 modelos y code-review dio 6–9 falsos positivos por servicio limpio. Cambios:

- **Pruebas depuradas** (`scripts/eval_n3/depurar_pruebas.py`): se quitan los asserts que exigen ids del catálogo de errores
  (`ERR-nnn`, convención del generador de referencias que el prompt del backend no pide) y los que comparan contra
  literales que la entrada no fija. 313 asserts quitados en 28 casos; los 28 servicios limpios siguen pasando todas sus
  pruebas; 1 mutante de lógica deja de morir (`muerto_por_pruebas: false`). Las originales quedan en `pruebas_aceptacion.v0.json`.
- **Juez por pares**, ciego y con orden al azar: para cada caso y agente, cada par de modelos abiertos; prueba de signo
  (empates fuera). La escala 1–5 queda opcional (`JUEZ_ABSOLUTO=1`).
- **Falsos positivos**: se guardan los hallazgos graves sobre el servicio limpio para una muestra humana de 10.
- **Ahorro**: Claude solo en 10 casos estratificados por autor (`CLAUDE_CASOS`), por la Batch API (50 %), y code-review con
  limpio + 1 mutante de lógica + 2 de seguridad (`CR_LOGICA=1`).

## 2. Estructura

```
eval_n3/
  README.md
  casos/<SIM-E0x-Rnnn>/
    caso.json                 # metadatos: área, reglas, autor del servicio limpio (claude | glm53 | dsv4pro), hashes
    entradas/<agente>.json    # payload exacto que recibe cada agente N3 (reconstruido con Orchestrator._payload)
    servicio_limpio.json      # backend_code de referencia (formato del contrato: handlers + semillas), sin defectos
    pruebas_aceptacion.json   # qa_suite de referencia (formato del contrato); todas pasan contra el servicio limpio
    defectos/
      D01.json …              # una variante por defecto: {tipo, origen (mutmut | bandit | owasp), handler, linea, descripcion, severidad, parche}
  revision_humana.md          # 20 % de los casos (6) revisados por el autor: servicio, pruebas y defectos
```

Los requerimientos y sus artefactos se guardan en el dataset privado (`tesis-runs/runs/eval_n3/`), no en GitHub; en el repo
solo queda el código que los genera y este README.

## 3. Cómo se construye

1. **Requerimientos** (`scripts/eval_n3/preparar_brs.py`, dentro de `jobs/run_pipeline_job.py` con `PREPARAR_EVAL=30`): 30
   BusinessRequest v1.1 de proyectos SIM-E01..E05 (semilla 2027, distintos del piloto y del entrenamiento), redactados por el
   maestro open-weight.
2. **Entradas congeladas**: el pipeline v1 corre en modo automático; de cada caso se toman los artefactos aprobados aguas
   arriba de cada agente N3 y se reconstruye su payload exacto (`scripts/eval_n3/congelar.py`).
3. **Servicio limpio y pruebas de aceptación**: para cada caso, a partir de su diseño de API y modelo de datos congelados.
   Autoría (uso 3 del documento de selección): 15 casos Claude, 15 casos modelo de frontera. Como la Frontera A sale del
   propio benchmark, los 15 se reparten entre los dos candidatos (8 GLM-5.3 y 7 DeepSeek V4-Pro) para no favorecer a ninguno.
   Un caso entra solo si todas sus pruebas pasan contra su servicio limpio.
4. **Defectos sembrados** (`scripts/eval_n3/sembrar.py`): sobre el servicio limpio,
   - lógica: mutantes de mutmut que las pruebas de aceptación detectan (mutante "muerto"), 2–3 por caso;
   - seguridad: patrones OWASP/bandit insertados en un handler (secreto en el código, comparación insegura, SQL o comando
     armado con texto del usuario, `eval`, hash débil, verificación de autorización omitida), 1–2 por caso, y bandit debe
     detectar el patrón en el código sembrado.
   Cada variante tiene un solo defecto, con su ubicación (handler y línea) y la severidad esperada.
5. **Revisión humana del 20 %** (6 casos, el autor): servicio, pruebas y defectos; se anotan en `revision_humana.md`.

### 3.1 Resultado de la construcción (25/11/2026)

| Paso | Resultado |
|---|---|
| Entradas congeladas | 30 casos; con entrada de backend 28 (2 sin backend en el pipeline v1) |
| Referencias | **28/28** tras 4 corridas (MANIFEST): Claude **19**, DeepSeek V4-Pro **6**, GLM-5.3 **3** |
| Reasignados | 5 casos que su autor no logró en 6 intentos pasaron a Claude (`reasignado: true` en `autoria.json`): SIM-E01-R026 (DeepSeek), SIM-E03-R003, SIM-E03-R008, SIM-E04-R014, SIM-E05-R010 (GLM) |
| Defectos | 140 (3 de lógica + 2 de seguridad por caso), cada uno con su variante completa |
| Costo | Claude USD 2,94 (medido); HF Inference Providers ≈ USD 7 en las 4 corridas |

**Desviación del diseño (§3.3):** el reparto previsto era 15/15 (Claude/frontera); quedó 19/9 por las reasignaciones.
Como Claude también es la referencia de techo del benchmark, existe riesgo de sesgo de autoría a su favor en
backend-developer y code-review. Mitigación: el benchmark reporta esas métricas estratificadas por autor de la referencia,
y la conclusión de N4 se toma sobre los casos con autor de frontera cuando la diferencia dependa del estrato.

## 4. Juez semántico (uso 4)

Rúbrica 1–5 para solution-architect, data-model y security-compliance; kappa ponderado contra la revisión humana del 20 %
(≥ 0,6 para extenderlo al resto). El juez **no** califica artefactos producidos por Claude (los de la referencia de techo):
esos van solo a revisión humana.

## 5. Reglas

- Claude solo participa como autor de la mitad de los servicios limpios (fuente declarada) y como referencia de techo en el
  benchmark; entra al pipeline reportado únicamente en E4 con C1–C4 cumplidas.
- Ningún caso de eval_n3 entra al piloto ni al entrenamiento (prefijo SIM-E0, verificación de fuga con `scripts/verificar_fuga.py`).
