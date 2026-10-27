# Brief — Pedido con crédito: línea disponible, bloqueo por mora y cuotas

| Campo | Valor |
|---|---|
| Requerimiento | SIM-P05-R016 |
| Proyecto | SIM-P05 — Portal de autoservicio de la fuerza de ventas |
| Tipo | Funcional |
| Origen | Planeamiento de campaña (Planeamiento de Campaña) |
| Solicitante | Analista de Planeamiento de Campaña |
| Campaña objetivo | C2025-13 |
| Alcance geográfico | todos los países de operación |
| Canal | App móvil y web |
| Fecha de registro | 2025-12-09 |
| Complejidad estimada | 8 puntos |
| Aprobación formal del brief | No — aprobación verbal |

## Necesidad de negocio

Las consultoras con línea de crédito no ven su saldo disponible al hacer el pedido y el bloqueo por mora se aplica recién en facturación, generando pedidos rechazados.

## Resultado esperado

Que al armar el pedido se vea la línea de crédito disponible, se avise si el pedido la excede, y si la consultora está en mora el portal lo diga antes de confirmar. Opción de pagar en cuotas según el país.

## Restricciones conocidas

- Fecha de salida ligada al calendario de campaña (inamovible).
- Debe respetar las reglas de negocio: BR-100 Línea de crédito por nivel y antigüedad, BR-101 Bloqueo por mora, BR-102 Cuotas por país.
