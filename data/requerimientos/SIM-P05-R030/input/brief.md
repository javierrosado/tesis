# Brief — Trazas de extremo a extremo por pedido

| Campo | Valor |
|---|---|
| Requerimiento | SIM-P05-R030 |
| Proyecto | SIM-P05 — Portal de autoservicio de la fuerza de ventas |
| Tipo | No funcional |
| Origen | Mejora técnica (Chapter de Arquitectura) |
| Solicitante | Tech Lead del squad |
| Campaña objetivo | C2026-07 |
| Alcance geográfico | Perú, Bolivia, Colombia |
| Canal | Plataforma |
| Fecha de registro | 2026-07-01 |
| Complejidad estimada | 3 puntos |
| Aprobación formal del brief | No — aprobación verbal |

## Necesidad de negocio

Cuando un pedido falla no se puede reconstruir el recorrido entre portal, promociones, pedidos y facturación.

## Resultado esperado

Como Tech Lead del squad, quiero que cada pedido lleve un identificador de correlación que atraviese todas las integraciones, para diagnosticar fallos en minutos en lugar de días.

## Restricciones conocidas

- Fecha de salida ligada al calendario de campaña (inamovible).
- Debe respetar las reglas de negocio: por identificar en refinamiento.
- Requerimiento no funcional: definir métrica objetivo y forma de medición.
