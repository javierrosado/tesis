# Convenciones de código

- Arquitectura hexagonal por módulo: `dominio/`, `aplicacion/`, `infraestructura/`, `api/`.
- Nombres del dominio en español siguiendo el glosario (`Consultora`, `Pedido`, `Campana`); nombres técnicos en inglés (`repository`, `handler`).
- Cobertura mínima de pruebas unitarias en `dominio/` y `aplicacion/`: 80 %.
- Prohibido secretos en código o configuración versionada; se inyectan por el gestor de secretos del entorno.
- Eventos de dominio en pasado (`PedidoConfirmado`), inmutables, con `correlation_id` y `occurred_at`.
- Cada cambio llega por pull request con revisión; hallazgos críticos de seguridad bloquean la integración.
