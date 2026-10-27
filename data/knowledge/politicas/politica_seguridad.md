# Política de seguridad aplicable al portal (resumen para agentes)

## Clasificación de datos
| Clase | Ejemplos | Controles mínimos |
|---|---|---|
| Público | catálogo, precios de campaña | — |
| Interno | métricas de ventas agregadas | autenticación |
| Confidencial | pedidos, puntos, línea de crédito | autenticación + autorización por consultora + registro de acceso |
| Restringido | datos personales de la consultora, documento de identidad, consentimientos | lo anterior + cifrado en reposo + enmascaramiento fuera de producción + retención 24 meses de accesos (BR-052) |

## Controles base (CTRL-001 … CTRL-010) que todo diseño debe cubrir
CTRL-001 autenticación de todas las APIs · CTRL-002 autorización por recurso (una consultora solo ve lo suyo) · CTRL-003 validación de entrada y límites · CTRL-004 cifrado en tránsito · CTRL-005 cifrado en reposo de datos restringidos · CTRL-006 registro de acceso a datos personales · CTRL-007 gestión de secretos fuera del código · CTRL-008 limitación de tasa en endpoints públicos · CTRL-009 dependencias sin vulnerabilidades críticas conocidas · CTRL-010 política de contraseñas y bloqueo (BR-080).

## Puertas de seguridad del pipeline (GATE)
GATE-SEC-1 análisis estático sin hallazgos críticos · GATE-SEC-2 dependencias sin críticas · GATE-SEC-3 secretos no detectados · GATE-SEC-4 pruebas de autorización por consultora superadas.
