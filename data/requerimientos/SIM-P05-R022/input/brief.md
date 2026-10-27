# Brief — Integración con gestión de pedidos para el estado de despacho

| Campo | Valor |
|---|---|
| Requerimiento | SIM-P05-R022 |
| Proyecto | SIM-P05 — Portal de autoservicio de la fuerza de ventas |
| Tipo | Integración |
| Origen | Área de negocio (Gerencia Comercial (Fuerza de Ventas)) |
| Solicitante | Jefe de Servicio a la Consultora |
| Campaña objetivo | C2025-13 |
| Alcance geográfico | todos los países de operación |
| Canal | App móvil y web |
| Fecha de registro | 2025-12-27 |
| Complejidad estimada | 8 puntos |
| Aprobación formal del brief | Sí (acta de refinamiento) |

## Necesidad de negocio

El estado de despacho del pedido vive en el sistema de gestión de pedidos multicanal; el portal necesita consumirlo para mostrarlo a la consultora (complementa R001).

## Resultado esperado

Integrar con el sistema de pedidos del Squad Pedidos para traer el estado de despacho y el número de guía, por evento o por consulta, y mostrarlo en el historial.

## Restricciones conocidas

- Fecha de salida ligada al calendario de campaña (inamovible).
- Debe respetar las reglas de negocio: BR-010 Estados del pedido.
- Integra con el sistema del proyecto SIM-P03.
