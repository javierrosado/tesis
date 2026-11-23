# Checklist de aprobación por tipo de gate (protocolo F5 v2, criterio C7)

- **Estado:** borrador v0.9, pendiente de aprobación del autor. Al aprobarse pasa a v1.0, se registra el commit y **no cambia durante el piloto** (30/11 – 11/12/2026).
- **Quién lo aplica:** el autor, único aprobador humano de los gates de riesgo alto.
- **Para qué:** fijar el criterio antes de ver los artefactos y así acotar el sesgo del aprobador único (limitación 4 del Plan V2.7).

## Reglas comunes

1. **Governance ya aprobó el artefacto.** Contrato, criterios F5 y procedencia están verificados por reglas deterministas; el humano no los vuelve a revisar. El checklist cubre lo que una regla no puede juzgar: si el contenido es correcto y útil para el negocio.
2. **Se aprueba solo si todos los ítems son «Sí».** Si uno es «No», el artefacto se devuelve con un motivo que cita el ítem (por ejemplo: `PO-3: falta el caso de pedido anulado`).
3. **El dictamen de IA es una opinión, no el criterio.** Se registra aparte y no reemplaza la revisión de los ítems.
4. **Riesgo bajo:** los artefactos de riesgo bajo que governance aprueba se aprueban por política, sin checklist (`config/gates.yaml`).
5. **Sin información suficiente para decidir un ítem:** se devuelve con la pregunta concreta. No se aprueba «por si acaso».

## PO · Historias de usuario (`user_story_set`, Product Owner)

| Ítem | Criterio | Sí / No |
|---|---|---|
| PO-1 | Las historias cubren la necesidad del brief, sin agregar alcance que el brief no pide | |
| PO-2 | Cada regla de negocio citada (BR-xxx) se aplica como dice el corpus, no solo se menciona | |
| PO-3 | Hay criterios para los casos negativos y de error relevantes (dato inexistente, permiso denegado, estado no válido) | |
| PO-4 | No hay historias duplicadas ni escenarios que se contradigan | |
| PO-5 | Las preguntas abiertas que el brief no resuelve están en pendientes, no resueltas por supuesto | |

## TL-A · Arquitectura de solución (`solution_architecture`, Tech Lead)

| Ítem | Criterio | Sí / No |
|---|---|---|
| TL-A1 | Los componentes alcanzan para el requerimiento y no sobran componentes sin función | |
| TL-A2 | Cada ADR elige una opción con una razón vinculada al contexto del requerimiento | |
| TL-A3 | Las integraciones con sistemas existentes son coherentes con las ADR del corpus | |
| TL-A4 | Los requisitos no funcionales del brief (rendimiento, disponibilidad, canal) tienen respuesta en el diseño | |

## SA · Seguridad y cumplimiento (`security_compliance`, Security Architect)

| Ítem | Criterio | Sí / No |
|---|---|---|
| SA-1 | Los datos personales que maneja el requerimiento están identificados y tienen control | |
| SA-2 | Autenticación y autorización cubren a cada rol que usa la funcionalidad | |
| SA-3 | La severidad de cada hallazgo es razonable: un riesgo real de exposición de datos no aparece como «menor» | |
| SA-4 | Cada hallazgo mayor o menor tiene una remediación concreta para el backlog | |

## DA · Modelo de datos con datos personales (`data_model`, Data Architect; solo si hay columnas PII)

| Ítem | Criterio | Sí / No |
|---|---|---|
| DA-1 | Las columnas marcadas como PII son las que corresponden (ni faltan ni sobran) | |
| DA-2 | El enmascaramiento elegido permite el uso que el requerimiento necesita | |
| DA-3 | No se guardan datos personales que el requerimiento no usa | |

## TL-C · Revisión de código (`code_review`, Tech Lead)

| Ítem | Criterio | Sí / No |
|---|---|---|
| TL-C1 | Los hallazgos críticos están corregidos o justificados, y las pruebas pasan | |
| TL-C2 | Los handlers implementan las reglas de negocio de las historias (revisión de lectura, no solo de pruebas) | |
| TL-C3 | No hay credenciales, datos reales ni rutas de depuración en el código | |
| TL-C4 | Los mensajes de error no exponen detalles internos al usuario | |

## RM · Plan de release (`release_plan`, Release Manager)

| Ítem | Criterio | Sí / No |
|---|---|---|
| RM-1 | La decisión go/no-go es coherente con el checklist y la evidencia del propio plan | |
| RM-2 | La ventana es un día de release del calendario del piloto (01/12, 03/12, 09/12 o 10/12) | |
| RM-3 | El rollback tiene pasos ejecutables en staging | |
| RM-4 | Los hallazgos de seguridad mayores o menores están en el backlog con su remediación (no bloquean; solo bloquea un crítico abierto) | |

## Registro

Cada decisión se registra con `scripts/pilot_control.py lote`: hora real, hash del artefacto, decisión, motivo con el ítem citado y, aparte, el dictamen de IA. La concordancia humano–IA y cada desacuerdo con su motivo se reportan en la tesis.

| Versión | Fecha | Cambio | Commit |
|---|---|---|---|
| 0.9 | 23/11/2026 | Borrador para aprobación del autor | (este PR) |
| 1.0 | | Aprobado por el autor; queda fijo para el piloto | |
