# Brief — Escalamiento automático de capacidad para los picos de campaña

| Campo | Valor |
|---|---|
| Requerimiento | SIM-P05-R012 |
| Proyecto | SIM-P05 — Portal de autoservicio de la fuerza de ventas |
| Tipo | No funcional |
| Origen | Planeamiento de campaña (Planeamiento de Campaña) |
| Solicitante | Analista de Planeamiento de Campaña |
| Campaña objetivo | C2025-12 |
| Alcance geográfico | Colombia, Perú |
| Canal | Plataforma |
| Fecha de registro | 2025-11-16 |
| Complejidad estimada | 13 puntos |
| Aprobación formal del brief | No — aprobación verbal |

## Necesidad de negocio

La infraestructura del portal se dimensiona fijo; en el cierre de campaña se satura y fuera de él está sobredimensionada. Se requiere escalamiento automático con alertas.

## Resultado esperado

Como squad Fuerza de Ventas, quiero que la capacidad del portal crezca y se reduzca automáticamente según la carga, para sostener el cierre de campaña sin intervención manual y sin sobrecosto el resto del mes.

## Restricciones conocidas

- Fecha de salida ligada al calendario de campaña (inamovible).
- Debe respetar las reglas de negocio: BR-030 Ventana de cierre de campaña.
- Requerimiento no funcional: definir métrica objetivo y forma de medición.
