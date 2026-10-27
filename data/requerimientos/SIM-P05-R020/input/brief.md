# Brief — Corrección del redondeo de precios con impuesto en el resumen del pedido

| Campo | Valor |
|---|---|
| Requerimiento | SIM-P05-R020 |
| Proyecto | SIM-P05 — Portal de autoservicio de la fuerza de ventas |
| Tipo | Funcional |
| Origen | Mejora técnica (Chapter de Arquitectura) |
| Solicitante | Tech Lead del squad |
| Campaña objetivo | C2025-13 |
| Alcance geográfico | Bolivia |
| Canal | App móvil y web |
| Fecha de registro | 2025-12-18 |
| Complejidad estimada | 2 puntos |
| Aprobación formal del brief | No — aprobación verbal |

## Necesidad de negocio

El total del resumen del pedido difiere en centavos del total facturado por redondear el impuesto por línea en vez de por total, lo que genera reclamos y ajustes manuales.

## Resultado esperado

Arreglar el redondeo: el impuesto se calcula sobre el total y se redondea a 2 decimales, igual que en facturación. Revisar también el descuento de consultora que se aplica antes del impuesto.

## Restricciones conocidas

- Fecha de salida ligada al calendario de campaña (inamovible).
- Debe respetar las reglas de negocio: BR-008 Cálculo de impuestos y redondeo, BR-002 Descuento de consultora.
