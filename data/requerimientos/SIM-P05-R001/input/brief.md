# Brief — Consulta de estado del pedido en tiempo real

| Campo | Valor |
|---|---|
| Requerimiento | SIM-P05-R001 |
| Proyecto | SIM-P05 — Portal de autoservicio de la fuerza de ventas |
| Tipo | Funcional |
| Origen | Área de negocio (Gerencia Comercial (Fuerza de Ventas)) |
| Solicitante | Jefe de Servicio a la Consultora |
| Campaña objetivo | C2025-10 |
| Alcance geográfico | Ecuador |
| Canal | App móvil y web |
| Fecha de registro | 2025-10-07 |
| Complejidad estimada | 5 puntos |
| Aprobación formal del brief | No — aprobación verbal |

## Necesidad de negocio

Las consultoras llaman al centro de atención para saber dónde está su pedido. Hoy el portal muestra solo 'en proceso' hasta que el pedido se factura, y el estado real vive en el sistema de pedidos y en el de logística.

## Resultado esperado

Necesitamos que la consultora pueda ver en el portal en qué etapa está su pedido (registrado, aprobado, en preparación, despachado, entregado) sin tener que llamar. Que se vea también la fecha estimada de entrega. Lo pide Servicio a la Consultora porque el 30% de las llamadas son por esto.

## Restricciones conocidas

- Fecha de salida ligada al calendario de campaña (inamovible).
- Debe respetar las reglas de negocio: BR-010 Estados del pedido, BR-011 Fecha estimada de entrega por zona.
