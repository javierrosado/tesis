# Nomenclatura de base de datos

- Tablas en snake_case singular (`pedido`, `pedido_detalle`); claves primarias `id` (uuid); foráneas `<tabla>_id`.
- Toda tabla comercial lleva `pais` (char 2) y política de seguridad a nivel de fila por país (ADR-005).
- Columnas de auditoría obligatorias: `creado_en`, `creado_por`, `actualizado_en`, `actualizado_por`.
- Montos `numeric(14,2)`; porcentajes `numeric(5,2)`; fechas `timestamptz`.
- Migraciones versionadas `V{nnn}__descripcion.sql` con script de reversión `U{nnn}__descripcion.sql`.
- Datos personales marcados en el diccionario con clasificación (`restringido`) y enmascaramiento dinámico en ambientes no productivos.
