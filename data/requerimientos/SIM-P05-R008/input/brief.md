# Brief — Simulador de ganancia de la consultora por pedido

| Campo | Valor |
|---|---|
| Requerimiento | SIM-P05-R008 |
| Proyecto | SIM-P05 — Portal de autoservicio de la fuerza de ventas |
| Tipo | Funcional |
| Origen | Área de negocio (Gerencia Comercial (Fuerza de Ventas)) |
| Solicitante | Jefe de Servicio a la Consultora |
| Campaña objetivo | C2025-11 |
| Alcance geográfico | Perú, México, Ecuador |
| Canal | App móvil y web |
| Fecha de registro | 2025-10-23 |
| Complejidad estimada | 5 puntos |
| Aprobación formal del brief | No — aprobación verbal |

## Necesidad de negocio

La consultora no sabe cuánto gana con el pedido que está armando (descuento por nivel, bonificaciones, puntos) y por eso pide menos de lo que podría.

## Resultado esperado

Queremos un simulador en el carrito que le diga a la consultora cuánto va a ganar con ese pedido: su descuento según nivel, si alcanza el pedido mínimo para subir de nivel y cuántos puntos suma. Que se actualice al agregar o quitar productos.

## Restricciones conocidas

- Fecha de salida ligada al calendario de campaña (inamovible).
- Debe respetar las reglas de negocio: BR-002 Niveles de consultora y porcentaje de descuento, BR-003 Pedido mínimo por nivel, BR-060 Acumulación de puntos.
