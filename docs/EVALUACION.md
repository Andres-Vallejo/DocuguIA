# Evaluación: recuperación, citas y respuestas

## Comprobaciones actuales

`tests/test_app.py` verifica el comportamiento del software con fuentes ficticias y respuestas simuladas. `evaluation/cases.json` contiene diez comprobaciones de desarrollo: ocho preguntas con evidencia esperada, una sin coincidencias léxicas y una con exclusión de categoría. También reserva tres preguntas sin respuesta documental para una evaluación posterior con Gemini real; quedan pendientes, sin contarlas como aprobadas. No se deben presentar las comprobaciones locales como rendimiento general de RAG ni como evaluación de Gemini.

`python -m evaluation.run` genera `evaluation/baseline.json` sin utilizar la clave ni los archivos de la biblioteca del usuario. Los resultados de una ejecución real de Gemini deben registrarse por separado, indicando modelo, fecha, filtros y número de llamadas. No se han inventado respuestas reales para llenar una tabla.

## Conjunto siguiente, antes de ajustar el sistema

Reserva al menos 20 preguntas nuevas: cinco directas, cinco con paráfrasis, cinco sin respuesta documental y cinco con versiones o conflictos. Define primero qué documentos y fragmentos permitirían contestar. Sepáralas de las preguntas usadas para ajustar prompts, tamaños o recuperación.

Para cada pregunta registra:

| Campo | Qué comprobar |
|---|---|
| Recuperación | Si aparece el fragmento necesario entre los primeros seis; para preguntas sin respuesta no basta con que haya coincidencias. |
| Corrección | Si la respuesta coincide con el contenido documental y no añade detalles sin respaldo. |
| Citas | Si existen y si realmente respaldan toda la afirmación; son dos comprobaciones distintas. |
| Suficiencia | Si responde lo preguntado o reconoce lo que falta. |
| Versiones | Si evita usar una versión histórica al pedir la actual y si presenta los conflictos. |
| Operación | Latencia, tokens devueltos, uso de caché y límites; indicar siempre si hubo llamada real. |

El validador literal automático no demuestra corrección semántica. Una cita verdadera puede acompañar una afirmación falsa. La evaluación inicial debe tener una revisión humana con rúbrica explícita, especialmente para requisitos y números.

## Comparaciones útiles

Mantén el corpus y las preguntas de prueba fijos al comparar BM25 con embeddings o distintos tamaños de fragmento. Informa los cambios, los fallos y la incertidumbre por el pequeño tamaño de muestra. Una métrica global no reemplaza revisar errores de versión o afirmaciones sin soporte.

## Uso del nivel gratuito

Consulta una pregunta cada vez y usa documentos ficticios o públicos autorizados. El programa limita llamadas por día UTC y no reintenta automáticamente. Verifica las cuotas del proyecto en Google AI Studio; no presupongas que coinciden con el límite local. Si se acaba la cuota, conserva lo observado y continúa la evaluación en otra sesión, sin crear cuentas adicionales para eludir límites.
