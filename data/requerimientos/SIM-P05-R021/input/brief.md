# Brief — Integración con el motor de promociones para aplicar descuentos en el carrito

| Campo | Valor |
|---|---|
| Requerimiento | SIM-P05-R021 |
| Proyecto | SIM-P05 — Portal de autoservicio de la fuerza de ventas |
| Tipo | Integración |
| Origen | Planeamiento de campaña (Planeamiento de Campaña) |
| Solicitante | Analista de Planeamiento de Campaña |
| Campaña objetivo | C2025-13 |
| Alcance geográfico | Bolivia, Colombia, Guatemala |
| Canal | App móvil y web |
| Fecha de registro | 2025-12-24 |
| Complejidad estimada | 5 puntos |
| Aprobación formal del brief | No — aprobación verbal |

## Necesidad de negocio

Las promociones de campaña (2x1, regalo por monto, descuento por combo) se aplican manualmente en facturación; el carrito del portal no las conoce.

## Resultado esperado

Conectar el carrito con el motor de promociones del Squad Promociones para que las promos vigentes se apliquen automáticamente al armar el pedido y la consultora vea lo que se lleva de regalo.

## Restricciones conocidas

- Fecha de salida ligada al calendario de campaña (inamovible).
- Debe respetar las reglas de negocio: BR-006 Vigencia de ofertas, BR-120 Tipos de promoción y prioridad de aplicación.
- Integra con el sistema del proyecto SIM-P02.
