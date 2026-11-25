# Validación de la versión 0.2.0

Entorno local: Windows, Python 3.12.10, 25 de noviembre de 2026.

- Instalación editable mediante `pip install -e ".[dev]"`: completada en un entorno virtual nuevo; las 61 pruebas también pasan desde esa instalación limpia.
- Pruebas automatizadas: 61 aprobadas. Usan corpus temporal y proveedor simulado; cero llamadas a Gemini durante las pruebas. Cubren documentos extensos, claves actuales, filtros, borradores, permisos, citas, respuestas parciales, caché, filas y encabezados combinados, columnas omitidas de Word, tablas PDF, páginas ambiguas, categorías libres, CSV/TSV y HTML.
- Evaluación de recuperación sintética: 10 de 10 comprobaciones aprobadas; ver `evaluation/baseline.json`. Las tres preguntas reservadas para generación real se informan como pendientes.
- Interfaz: verificada en una biblioteca local separada con seis ejemplos ficticios, categorías libres y consulta de inventario CSV. Las capturas del README proceden de esa biblioteca, sin documentos ni claves del usuario.
- Conexión real con Gemini: comprobada con un texto completamente ficticio de Campus Aurora, sin enviar documentos de trabajo. El modelo devolvió una respuesta parcial con cita válida al preguntar por un desglose no incluido en el ejemplo. La clave nunca se imprimió ni se guardó en el repositorio.
- Preguntas sobre documentos de trabajo con Gemini real: requieren autorización explícita antes de enviar sus fragmentos; esta verificación no se hizo en la corrección de filtros.
- Corrección de filtros: se reprodujo localmente el caso de archivos cargados como borradores y excluidos por el filtro de actuales. El filtro inicial ahora incluye actuales y borradores, sin incluir históricos automáticamente ni cambiar permisos de nube.
- Referencias locales: dos documentos Word reindexados conservando sus permisos y versiones. Se generaron PDF locales con LibreOffice y se verificó visualmente una página contra su sección y texto. Los fragmentos sin coincidencia inequívoca mantienen la ubicación original sin inventar una página. No se usaron estos documentos como ejemplos públicos.
- Docker, CI remoto, despliegue público y evaluación de respuestas de Gemini con documentos de trabajo: no ejecutados.

Starlette emite una advertencia de migración futura del cliente de pruebas de `httpx` a `httpx2`; las pruebas con las dependencias fijadas pasan. El servicio de Gemini usa `httpx` directamente.

Este registro documenta lo observado, sin atribuir exactitud de respuestas a las comprobaciones locales.
