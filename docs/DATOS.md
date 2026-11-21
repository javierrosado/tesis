# Datos del estudio: qué es sintético y qué es real

En esta tesis **los datos sintéticos se usan solo para entrenar** los adaptadores. **Todo lo que mide el impacto del pipeline usa datos reales**: la línea base AS-IS proviene de registros anonimizados de la Empresa, y el piloto se ejecuta sobre requerimientos de un caso real. Este documento explica cada fuente, por qué se eligió y cómo se verifica que no se mezclan.

## 1. Mapa de datos

```
 ENTRENAMIENTO (sintético)                       MEDICIÓN DEL IMPACTO (real)
 ─────────────────────────                       ──────────────────────────────────────
 scripts/gen_seeds.py                            Línea base AS-IS (OE1)
   requerimientos creados para el estudio        data/linea_base/Linea_BaseV2.xlsx
   proyectos SIM-T01 … SIM-T05                   registros reales anonimizados (SIM-P0x)
        │                                        66,5 días · 45 % · 34 % · 1,0 · 0 % · 0 %
        ▼                                                     │
 Maestro Qwen3-32B-AWQ (jobs/f2a_distill.py)                  │ comparación (H1–H6)
        │                                                     ▼
        ▼                                        Piloto F5 (OE4)
 governance + JSON Schema                        data/requerimientos/SIM-P05-*
   1 165 aprobados → re-filtro v2 → 1 013        30 requerimientos del caso real
        │                                        (Squad Fuerza de Ventas)
        ▼                                                     ▲
 jrosado1974/tesis-sft-v2 ──► 5 adaptadores LoRA ─────────────┘
                              los agentes entrenados trabajan sobre el caso real
```

## 2. Fuentes de datos

| Fuente | Naturaleza | Para qué se usa | Ubicación |
|---|---|---|---|
| Línea base AS-IS | **Real**, anonimizada (proyectos SIM-P01…P06) | Medir el estado actual (OE1) y comparar con el piloto | [`data/linea_base/Linea_BaseV2.xlsx`](../data/linea_base/) |
| Requerimientos del piloto | **Real** (caso del Squad Fuerza de Ventas, proyecto SIM-P05) | Ejecutar el pipeline y medir indicadores (OE4) | [`data/requerimientos/`](../data/requerimientos/) |
| Corpus de conocimiento | Documentación del dominio (reglas BR, ADRs, políticas) | Contexto de knowledge-rag | [`data/knowledge/`](../data/knowledge/) |
| Requerimientos semilla | **Sintéticos** (proyectos SIM-T01…T05) | Entradas para generar ejemplos de entrenamiento | [`scripts/gen_seeds.py`](../scripts/gen_seeds.py) |
| Ejemplos de entrenamiento | **Sintéticos** (destilados por el maestro y filtrados) | Entrenar y evaluar los 5 adaptadores (F3) | [jrosado1974/tesis-sft-v2](https://huggingface.co/datasets/jrosado1974/tesis-sft-v2) |

## 3. Por qué el entrenamiento usa datos sintéticos

1. **No existe un corpus etiquetado.** No hay un conjunto público, en español, de requerimientos con las salidas que esperan los contratos de estos agentes (historias con criterios Given/When/Then, OpenAPI, workflows de GitHub Actions…). Etiquetar a mano unos 1 000 ejemplos no era viable en el plazo de la tesis.
2. **Confidencialidad.** Entrenar con requerimientos de la Empresa dejaría información de negocio dentro de un modelo y un dataset públicos. Los datos reales se reservaron para la medición, donde se publican anonimizados.
3. **Es una técnica establecida.** Generar ejemplos con un modelo, filtrar los inválidos y ajustar con ellos es el esquema de Self-Instruct (Wang et al., 2023). Entrenar un modelo menor con salidas de uno mayor es destilación (Hsieh et al., 2023). Long et al. (2024) revisan la generación, curación y evaluación de datos sintéticos con LLM.

## 4. Controles de calidad aplicados

| Control | Resultado | Dónde se verifica |
|---|---|---|
| Validación contra el JSON Schema de cada agente | 100 % de los 1 013 ejemplos válidos | [`notebooks/eda_datasets_entrenamiento.ipynb`](../notebooks/eda_datasets_entrenamiento.ipynb) |
| Filtro de governance (reglas deterministas F5) | 1 165 → 1 013 tras governance v2 (más 161 de DevOps regenerados) | [`scripts/refilter_dataset.py`](../scripts/refilter_dataset.py), [`runs/MANIFEST.md`](../runs/MANIFEST.md) |
| Particiones por requerimiento | 0 requerimientos en común entre train, val y test | Notebook de EDA |
| Separación del piloto | Ver la sección 5 | [`scripts/verificar_fuga.py`](../scripts/verificar_fuga.py) |
| Revisión humana de una muestra | Muestra preparada; la revisión del autor está pendiente y se reportará en la tesis | `F2A_Muestra_Revision.md` (documento del proyecto) |

## 5. Verificación de que el piloto no está en el entrenamiento

`scripts/verificar_fuga.py` descarga el dataset público y lo compara con los 30 requerimientos del piloto. Resultado del 20/11/2026:

```
python scripts/verificar_fuga.py

1. Identificadores del piloto presentes en el dataset: 0
   Proyectos del dataset: SIM-T01, SIM-T02, SIM-T03, SIM-T04, SIM-T05 (el piloto es SIM-P05)
2. Títulos del piloto idénticos a uno de entrenamiento: 0
3. Similitud con el requerimiento más parecido (coseno de 5-gramas de caracteres)
   Piloto → entrenamiento:          mediana 0.411 · máximo 0.655
   Entrenamiento → entrenamiento:   mediana 0.67  · máximo 0.863  (referencia)
   Requerimientos del piloto con similitud ≥ 0.8: 0
Resultado: SIN FUGA
```

Cómo leerlo:

- **Identificadores y títulos:** ningún requerimiento del piloto aparece en el dataset.
- **Contenido:** el requerimiento del piloto más parecido a uno de entrenamiento tiene una similitud de 0,655. Eso es **menos** de lo que se parecen entre sí dos requerimientos de entrenamiento distintos (mediana 0,67). No hay indicio de copia.
- **Temas compartidos, no textos:** los pares más parecidos tratan el mismo tema de negocio, por ejemplo el consentimiento de datos personales (SIM-P05-R006 frente a SIM-T02-R292). Es esperable, porque las semillas se generaron sobre las mismas reglas de negocio del dominio; el texto no se repite.

## 6. Limitaciones

- La partición de prueba de F3 también es sintética. F3 mide el efecto **controlado** del entrenamiento (base frente a LoRA sobre el mismo test). La evidencia en contexto real la aporta el piloto.
- Las respuestas de referencia vienen del maestro: el techo del adaptador es el maestro filtrado por governance.
- Qwen3-8B es de la misma familia que el maestro, lo que puede favorecerlo en el ajuste fino.
- Las 4 etapas intermedias de la destilación (`tesis-sft-pilot`, `tesis-sft`, `tesis-sft-r2`, `tesis-sft-final`) son privadas. El entrenamiento y la evaluación se reproducen con `tesis-sft-v2`, que es público.

## Referencias

- Hsieh, C.-Y., Li, C.-L., Yeh, C.-K., Nakhost, H., Fujii, Y., Ratner, A., Krishna, R., Lee, C.-Y., & Pfister, T. (2023). Distilling step-by-step! Outperforming larger language models with less training data and smaller model sizes. En *Findings of the Association for Computational Linguistics: ACL 2023* (pp. 8003–8017). https://doi.org/10.18653/v1/2023.findings-acl.507
- Long, L., Wang, R., Xiao, R., Zhao, J., Ding, X., Chen, G., & Wang, H. (2024). On LLMs-driven synthetic data generation, curation, and evaluation: A survey. En *Findings of the Association for Computational Linguistics: ACL 2024* (pp. 11065–11082). https://doi.org/10.18653/v1/2024.findings-acl.658
- Wang, Y., Kordi, Y., Mishra, S., Liu, A., Smith, N. A., Khashabi, D., & Hajishirzi, H. (2023). Self-Instruct: Aligning language models with self-generated instructions. En *Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers)* (pp. 13484–13508). https://doi.org/10.18653/v1/2023.acl-long.754
