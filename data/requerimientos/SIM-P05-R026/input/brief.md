# Brief — Integración con facturación electrónica para el comprobante al cierre del pedido

| Campo | Valor |
|---|---|
| Requerimiento | SIM-P05-R026 |
| Proyecto | SIM-P05 — Portal de autoservicio de la fuerza de ventas |
| Tipo | Integración |
| Origen | Mejora técnica (Chapter de Arquitectura) |
| Solicitante | Tech Lead del squad |
| Campaña objetivo | C2026-01 |
| Alcance geográfico | Guatemala, Ecuador, Colombia |
| Canal | App móvil y web |
| Fecha de registro | 2026-01-10 |
| Complejidad estimada | 8 puntos |
| Aprobación formal del brief | No — aprobación verbal |

## Necesidad de negocio

El comprobante electrónico se genera horas después del cierre en el sistema de facturación; la consultora no lo ve en el portal y lo pide por correo.

## Resultado esperado

Integrar con el sistema de facturación electrónica del Squad Finanzas para que, cuando se emita el comprobante, aparezca en el historial del pedido para descargar.

## Restricciones conocidas

- Fecha de salida ligada al calendario de campaña (inamovible).
- Debe respetar las reglas de negocio: BR-140 Comprobante electrónico por país.
- Integra con el sistema del proyecto SIM-P06.
