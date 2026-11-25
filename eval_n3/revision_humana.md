# eval_n3 · Revisión humana del 20 % (6 casos)

**Revisor:** Javier Rosado · **Fecha:** ____ · **Datos:** `jrosado1974/tesis-runs`, `runs/eval_n3/casos/<caso>/`
(`business_request.json`, `servicio_limpio.json`, `pruebas_aceptacion.json`, `defectos/D01..D05.json`).

Muestra por hash (`sha256("revision:<caso>")`), estratificada por autor de la referencia (4 Claude, 1 DeepSeek, 1 GLM):

| Caso | Autor | Pruebas | Título |
|---|---|---|---|
| SIM-E01-R021 | Claude | 11 | Gestión de cuotas para productos por catálogo |
| SIM-E04-R029 | Claude | 11 | Gestión de puntos y canjes de premios por campaña |
| SIM-E01-R026 | Claude (reasignado de DeepSeek) | 10 | Cierre de campaña en zona con huso horario local |
| SIM-E02-R007 | Claude | 12 | Control de seguridad de acceso para la app móvil |
| SIM-E05-R005 | DeepSeek V4-Pro | 12 | Gestión de puntos y premios para consultoras |
| SIM-E04-R019 | GLM-5.3 | 13 | Control de acceso seguro para la app móvil |

## Criterios (marcar ✅ / ⚠️ / ❌ y anotar)

1. **Servicio limpio:** implementa lo que pide el BusinessRequest y respeta el catálogo de errores del diseño de API.
2. **Pruebas de aceptación:** verifican comportamiento real (no son tautológicas), cubren casos felices, errores y reglas de negocio.
3. **Defectos de lógica (D01–D03):** cada uno cambia un comportamiento que un revisor de código debería señalar; no hay dos iguales.
4. **Defectos de seguridad (D04–D05):** el patrón es realista y la severidad/CWE asignada es correcta.
5. **Severidad esperada:** la que trae cada `Dnn.json` es razonable para el criterio "crítico o mayor" del recall.

## Registro

| Caso | 1 Servicio | 2 Pruebas | 3 Lógica | 4 Seguridad | 5 Severidad | Notas |
|---|---|---|---|---|---|---|
| SIM-E01-R021 | | | | | | |
| SIM-E04-R029 | | | | | | Revisar D01 y D02: misma descripción (posible duplicado) |
| SIM-E01-R026 | | | | | | |
| SIM-E02-R007 | | | | | | |
| SIM-E05-R005 | | | | | | |
| SIM-E04-R019 | | | | | | |

**Decisión:** un caso con ❌ en 1 o 2 sale del conjunto; un defecto con ❌ en 3–5 se descarta. Los resultados de esta tabla
son además la referencia humana del juez semántico (§4, kappa ≥ 0,6).
