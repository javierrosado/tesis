# Convenciones de API (aprobadas por el chapter de Arquitectura)

- Especificación OpenAPI 3.1 obligatoria por servicio, en `api/openapi.yaml`, versionada con la aplicación.
- Rutas en minúsculas y plural (`/pedidos`, `/consultoras`); versionado por ruta `/v{n}`; cabecera `Sunset` al deprecar.
- Identificadores opacos (`string`), nunca secuenciales expuestos.
- Errores en formato RFC 7807 (`application/problem+json`) con `correlation_id` obligatorio.
- Paginación por cursor (`cursor`, `limit` ≤ 100); nunca por `offset`.
- Fechas en ISO 8601 UTC; moneda con código ISO 4217 y montos decimales (nunca float binario).
- Autenticación por token portador (OAuth2 flujo cliente o usuario según caso); alcance mínimo por endpoint.
- Toda API pública tiene pruebas de contrato que se ejecutan en el pipeline de CI.
