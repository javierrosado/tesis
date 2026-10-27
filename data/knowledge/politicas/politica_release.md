# Política de release (Squad Fuerza de Ventas)

- Ventanas de despliegue: solo fuera de las 72 horas de cierre de campaña de cualquier zona del país (ADR-008). Ventana preferente: primeros 5 días de campaña.
- Criterios de go/no-go: pruebas automatizadas en verde; 0 hallazgos críticos de revisión; puertas de seguridad superadas; plan de rollback probado en staging; comunicación a Servicio a la Consultora enviada.
- Estrategia de rollback por defecto: despliegue azul/verde con conmutación; para cambios de esquema, migraciones expandir-contraer.
- Versionado semántico de la aplicación; etiqueta de release = versión.
- Hotfix: solo con aprobación del Release Manager y del Tech Lead; se registra como despliegue de tipo hotfix.
