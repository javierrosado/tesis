# Brief — Migración del inicio de sesión a autenticación con token y segundo factor opcional

| Campo | Valor |
|---|---|
| Requerimiento | SIM-P05-R011 |
| Proyecto | SIM-P05 — Portal de autoservicio de la fuerza de ventas |
| Tipo | Funcional |
| Origen | Mejora técnica (Chapter de Arquitectura) |
| Solicitante | Tech Lead del squad |
| Campaña objetivo | C2025-12 |
| Alcance geográfico | todos los países de operación |
| Canal | App móvil y web |
| Fecha de registro | 2025-11-15 |
| Complejidad estimada | 5 puntos |
| Aprobación formal del brief | No — aprobación verbal |

## Necesidad de negocio

El portal mantiene sesión por cookie de servidor y contraseñas sin política; el chapter de arquitectura pide migrar a autenticación basada en tokens con expiración y ofrecer segundo factor por SMS/correo.

## Resultado esperado

Como chapter de arquitectura, quiero que el portal autentique con tokens de corta duración y renovación, con segundo factor opcional, para reducir el riesgo de suplantación de cuentas de consultoras.

## Restricciones conocidas

- Fecha de salida ligada al calendario de campaña (inamovible).
- Debe respetar las reglas de negocio: BR-080 Política de contraseñas y bloqueo, BR-081 Segundo factor opcional.
