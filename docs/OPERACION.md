# Operación del piloto `piloto1` (14/12–23/12/2026)

> Borrador para validar por Javier (§8.7). Versión congelada: `v1.0-piloto`. Cualquier cambio de código durante el piloto
> es una desviación: se registra en `docs/BITACORA.md`, se etiqueta `v1.0.x-piloto` y se republica la consola con ese tag.

## 1. Qué hay y dónde

| Pieza | Ubicación | Notas |
|---|---|---|
| Consola | https://jrosado1974-consola-piloto.hf.space | Space privado; entra con la cuenta de Hugging Face |
| Código congelado | `javierrosado/tesis`, tag `v1.0-piloto` | El job lo toma de `CONSOLA_TAG` |
| Entradas y estado del piloto | dataset privado `jrosado1974/tesis-piloto`, carpeta `piloto/piloto1/` | Nunca en GitHub |
| Despliegues | `javierrosado/tesis-sandbox` | GitHub Actions valida cada despliegue |
| Cómputo | HF Jobs, `a100-large` | Qwen3-8B + 5 QLoRA y maestro Qwen3-32B-AWQ |
| Modelos de frontera | HF Inference Providers | GLM-5.3 (`:together`) y DeepSeek V4-Flash (`:deepinfra`), asignados por N4 |

Claude no participa en el piloto. No se usa GPT.

## 2. Roles

La consola reconoce tres roles, asignados en la variable `CONSOLA_USUARIOS`. Hoy la cuenta `jrosado1974` tiene los tres.

- **Registrador:** da de alta requerimientos. El input queda inmutable desde el alta (sha256 en `alta.json`).
- **Aprobador:** decide los gates humanos (aprobar o devolver con comentario).
- **Operador:** reanuda, programa, suspende y cancela jobs; registra defectos y despliegues.

## 3. Rutina diaria

El pipeline avanza solo hasta el siguiente gate humano y se pausa. Las decisiones del día se aplican en dos cierres de ventana, a las **10:00** y a las **18:00** (hora de Lima). En cada cierre, un Scheduled Job reanuda todos los requerimientos del piloto con las decisiones tomadas hasta ese momento.

1. **Antes de cada cierre**, revisa **Gates** y decide lo pendiente. Una devolución necesita un comentario concreto: qué falta o qué está mal, no solo "corregir".
2. **Si no quieres esperar al cierre**, entra al requerimiento y pulsa **Reanudar este requerimiento**. **Reanudar ahora** reanuda todos los requerimientos del piloto (solo los del piloto, no los del repositorio).
3. **Después de cada cierre**, revisa en **Jobs** que el job terminó y en el tablero que cada requerimiento avanzó o quedó esperando un gate.

Un requerimiento termina en uno de tres estados: **desplegado** (go en release y despliegue correcto), **no-go** (release rechazado con motivo) o **escalado** (un agente agotó rondas y rescate; la decisión pasa al humano y cuenta como decisión de release, D-8.1).

## 4. Alta de un requerimiento

Desde **Alta**, sube el ZIP del requerimiento o llena el formulario. Primero se valida (modo `validar`) y, si está bien, se confirma. Un `req_id` que ya existe se rechaza: el input no se reemplaza.

## 5. Registro de defectos y despliegues

- **Defecto escapado** (aparece después del despliegue): regístralo en **Defectos** con el requerimiento, la descripción y la fecha en que se detectó. Alimenta H3.
- **Despliegue manual o fallido** que no haya quedado registrado por el job: regístralo en **Despliegues**. Alimenta H1, H2 y H4.

## 6. Programación (T19)

Los dos Scheduled Jobs se crean suspendidos y con el tag congelado. El **14/12 antes de las 10:00** se activan desde **Jobs → Activar**. Para pausar el piloto (por ejemplo, ante un problema de proveedor) se usa **Suspender**, y se reactiva igual.

## 7. Contingencias

| Situación | Qué hacer |
|---|---|
| Un job falla (estado `ERROR`) | Revisar el log en **Jobs**. Si fue la infraestructura, reanudar el requerimiento. Si fue el código, es desviación (ver arriba). |
| Un proveedor no responde (GLM o DeepSeek) | El job reintenta solo. Si la caída persiste, el operador fija `PROVIDERS_DOWN` en `CONSOLA_JOB_ENV` y el router N4 usa el modelo base del agente. Se anota en la bitácora. |
| Un requerimiento queda escalado | Revisar los hallazgos en el gate y decidir. La decisión se registra como humana; el dictamen de la IA queda aparte. |
| La consola no carga | El Space puede estar dormido: abrir https://huggingface.co/spaces/jrosado1974/consola-piloto y esperar que arranque. |
| Un job queda colgado | **Cancelar** desde **Jobs** y reanudar el requerimiento. |

## 8. Costos

Cada tramo de job (hasta el siguiente gate) cuesta del orden de USD 0,2 a 0,5 de a100 más las llamadas a GLM y DeepSeek. El costo real se toma de la facturación de Hugging Face (`core/costos.py`), no del `usage.cost` del router, que lo subestima. Un requerimiento completo cuesta del orden de USD 1,5 a 2,5.

## 9. Cierre y evidencia

- **Indicadores:** **Indicadores** en la consola, o `scripts/indicadores.py` sobre `telemetria/` y `registros/`.
- **Contraste con la línea base:** `scripts/contraste.py --piloto <csv> --linea-base data/linea_base/Linea_BaseV2.xlsx`.
- **Evidencia completa:** **Auditoría → evidencia.zip** (telemetría, registros, decisiones y accesos).

Al cerrar el piloto (23/12) se suspenden los Scheduled Jobs y se descarga la evidencia.

## Por validar con Javier

- Horarios de los cierres de ventana (10:00 y 18:00).
- Si se agregan usuarios con un solo rol (por ejemplo, un aprobador distinto del operador).
- Umbral de costo diario a partir del cual se suspende el piloto.
