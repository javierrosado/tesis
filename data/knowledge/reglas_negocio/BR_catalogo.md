# Catálogo de reglas de negocio (BR-XXX) — vigentes y aprobadas

| ID | Regla | Dueño | Observaciones |
|---|---|---|---|
| BR-001 | El calendario de campañas se define por país; cada campaña dura 4 semanas y se identifica como C{año}-{nn}. | Planeamiento | Fechas inamovibles |
| BR-002 | Niveles de consultora: Inicial 20 %, Plata 25 %, Oro 30 %, Diamante 35 % de descuento sobre el precio de campaña. El nivel se recalcula cada 3 campañas. | Comercial | — |
| BR-003 | Pedido mínimo por nivel (moneda local equivalente): Inicial 40, Plata 80, Oro 150, Diamante 250 USD. No alcanzarlo 2 campañas seguidas baja un nivel. | Comercial | Se evalúa al cierre |
| BR-005 | El precio aplicable a un pedido es el precio de campaña del país vigente al momento de **confirmar** el pedido, no al agregar al carrito. | Planeamiento | Fuente de reclamos cuando se muestra otro precio |
| BR-006 | Una oferta o promoción es válida solo dentro de su vigencia (fecha-hora inicio/fin) y país; vencida, no se aplica aunque esté en el carrito. | Planeamiento | — |
| BR-007 | Taxonomía de categorías: Fragancias, Maquillaje, Cuidado personal, Cuidado facial, Bisutería, Hogar. Un producto tiene una categoría principal. | Catálogo | — |
| BR-008 | El impuesto se calcula sobre el subtotal del pedido después del descuento de consultora y se redondea a 2 decimales **por total**, no por línea. | Finanzas | Misma regla que facturación |
| BR-010 | Estados del pedido: registrado → aprobado → en preparación → despachado → entregado; anulado es terminal desde registrado o aprobado. No hay retrocesos. | Pedidos | — |
| BR-011 | La fecha estimada de entrega = fecha de despacho + días de tránsito de la zona (tabla de Logística). | Logística | — |
| BR-012 | El historial consultable de pedidos y notas de pedido cubre las últimas 6 campañas. | Servicio | — |
| BR-020 | Sustitución: solo productos de la misma categoría y precio igual o menor; máximo 3 sustitutos; la consultora debe aceptar explícitamente. | Planeamiento | Tabla de sustitutos por campaña |
| BR-021 | El stock se reserva al confirmar el pedido, por centro de distribución de la zona; el carrito no reserva. | Logística | — |
| BR-030 | Ventana de cierre de campaña: últimas 72 horas; la hora de cierre es por zona en el huso horario del país. | Planeamiento | Pico de carga |
| BR-031 | Después de la hora de cierre de la zona no se aceptan pedidos de la campaña; el pedido pasa automáticamente a la siguiente. | Planeamiento | — |
| BR-040 | Todo contenido comercial del home (banner, destacados) debe tener vigencia y aprobación de Planeamiento antes de publicarse. | Planeamiento | — |
| BR-050 | El registro de una consultora requiere consentimiento explícito de tratamiento de datos personales con el texto vigente del país. | Legal | Normativa de protección de datos |
| BR-051 | La evidencia del consentimiento guarda: identificador, fecha-hora, versión del texto, país, canal e IP. Inmutable. | Legal | — |
| BR-052 | Los registros de acceso a datos personales se conservan 24 meses y no pueden modificarse. | Cumplimiento | — |
| BR-060 | Puntos: 1 punto por cada USD equivalente de pedido confirmado; productos foco de campaña suman doble. Se acreditan al facturar. | Comercial | — |
| BR-061 | Los puntos caducan 3 campañas después de acreditados. La anulación del pedido revierte los puntos. | Comercial | — |
| BR-062 | El catálogo de premios es por campaña y país; un canje descuenta puntos al confirmar. | Comercial | — |
| BR-070 | Kit de inicio: disponible solo en la primera campaña de la consultora, un kit por consultora, precio de incorporación fijo por país. | Comercial | — |
| BR-071 | Recomendaciones de productos para nuevas consultoras: 6 productos de mayor rotación de la zona en las últimas 3 campañas. | Planeamiento | — |
| BR-080 | Contraseña mínima 10 caracteres; bloqueo tras 5 intentos fallidos por 15 minutos. | Seguridad | — |
| BR-081 | Segundo factor opcional por SMS o correo; obligatorio para líderes de zona. | Seguridad | — |
| BR-090 | La consultora elige canal de notificación (push, correo, ambos) y puede desactivar los no obligatorios; las notificaciones de pedido confirmado son obligatorias. | Servicio | — |
| BR-100 | Línea de crédito: Inicial 0, Plata 1×, Oro 2×, Diamante 3× el pedido mínimo del nivel; requiere 3 campañas de antigüedad. | Finanzas | — |
| BR-101 | Mora: deuda vencida > 7 días bloquea nuevos pedidos hasta regularizar; el bloqueo se informa antes de confirmar. | Finanzas | — |
| BR-102 | Cuotas: disponibles solo en países habilitados; máximo 3 cuotas sin interés. | Finanzas | Lista por país |
| BR-110 | Plazo para reclamar o devolver: hasta el cierre de la segunda campaña posterior a la entrega. | Servicio | — |
| BR-111 | Estados del reclamo: recibido → en evaluación → aprobado / rechazado → reposición enviada. SLA de evaluación: 5 días hábiles. | Servicio | — |
| BR-120 | Prioridad de promociones: 1) regalo por monto, 2) descuento por combo, 3) 2x1; no acumulables salvo indicación explícita. | Planeamiento | Motor de promociones |
| BR-130 | Preventa: el catálogo de la siguiente campaña es visible 7 días antes; la lista de deseos no reserva stock salvo lanzamientos con cupo por zona. | Planeamiento | — |
| BR-140 | El comprobante electrónico se emite en el formato del país y queda disponible en el historial del pedido. | Finanzas | — |
| BR-150 | Toda promoción visible debe enlazar sus términos y condiciones aprobados por Legal para el país, con vigencia. | Legal | — |
| BR-160 | Motivos de devolución: defecto, error de despacho, producto distinto, arrepentimiento (solo sellado). Reposición o nota de crédito según motivo. | Servicio | — |
