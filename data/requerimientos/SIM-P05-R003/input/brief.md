# Brief — Carrito de pedido con validación de stock y productos sustitutos

| Campo | Valor |
|---|---|
| Requerimiento | SIM-P05-R003 |
| Proyecto | SIM-P05 — Portal de autoservicio de la fuerza de ventas |
| Tipo | Funcional |
| Origen | Área de negocio (Gerencia Comercial (Fuerza de Ventas)) |
| Solicitante | Jefe de Servicio a la Consultora |
| Campaña objetivo | C2025-11 |
| Alcance geográfico | todos los países de operación |
| Canal | App móvil y web |
| Fecha de registro | 2025-10-12 |
| Complejidad estimada | 13 puntos |
| Aprobación formal del brief | Sí (acta de refinamiento) |

## Necesidad de negocio

El pedido se arma en el portal pero el stock se valida recién en el cierre; cuando falta un producto, el pedido llega incompleto o se retrasa. Se requiere validar stock al agregar al carrito y proponer sustitutos equivalentes definidos por Planeamiento.

## Resultado esperado

Como consultora, quiero saber al momento de agregar un producto si hay stock en mi zona y que me ofrezcan un sustituto si no lo hay, para no recibir pedidos incompletos ni perder la venta.

## Restricciones conocidas

- Fecha de salida ligada al calendario de campaña (inamovible).
- Debe respetar las reglas de negocio: BR-020 Reglas de sustitución de productos, BR-021 Reserva de stock al confirmar (no al agregar), BR-005 Precio de campaña.
