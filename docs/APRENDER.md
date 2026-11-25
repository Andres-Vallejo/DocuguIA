# Construir y entender DocuguIA desde cero

El problema: una respuesta útil debe permitir encontrar el documento que la respalda. En procesos de infraestructura también importa saber qué categoría y qué versión se consultaron. Aquí puedes recorrer toda la implementación sin entrenar un modelo ni pagar una base de datos.

## 1. Ejecuta una consulta sin IA

Carga el ejemplo y busca las pruebas de aceptación. En `app/main.py`, sigue `POST /api/ask` hasta `answer()` en `app/qa.py`. En modo local, el flujo termina en los fragmentos recuperados. El modelo todavía no interviene.

Ejercicio: explica por qué un resultado de búsqueda no equivale a una respuesta correcta. Encuentra una pregunta que recupere un fragmento relacionado pero insuficiente.

## 2. Comprende la extracción

En `app/structure.py`, cada formato se convierte en unidades con sección y ubicación: página de PDF, párrafo o fila de tabla. Los encabezados de las tablas acompañan a los valores de cada fila. En `app/ingest.py`, las unidades largas se dividen con solapamiento sin agrupar secciones diferentes. `app/rendering.py` genera una copia PDF de Word con LibreOffice local y asigna página solo cuando el texto permite localizarla sin ambigüedad.

Ejercicio: crea un TXT con tres párrafos, impórtalo y comprueba sus referencias. Después usa un PDF escaneado y observa el mensaje de OCR. No confundas que un archivo se haya abierto con que todo su contenido se haya leído bien.

## 3. Revisa la base de datos y los filtros

En `app/store.py`, `documents` guarda metadatos, `chunks` el texto y `search` el índice FTS5. `retrieve()` aplica categoría, estado y permiso de nube antes de devolver resultados.

Ejercicio SQL, usando una copia de la base:

```sql
SELECT block, status, COUNT(*) AS documentos
FROM documents GROUP BY block, status;

SELECT d.title, COUNT(c.id) AS fragmentos
FROM documents d LEFT JOIN chunks c ON c.document_id=d.id
GROUP BY d.id ORDER BY fragmentos DESC;
```

Prueba la misma pregunta con «Actuales», «Históricos» y «Todas las versiones». Explica por qué el nombre del archivo o su fecha no bastan para decidir vigencia.

## 4. Entiende la petición a Gemini

En `app/qa.py`, `call_gemini()` crea una solicitud REST con instrucciones, pregunta, fuentes y un esquema de salida. La clave viaja en una cabecera, nunca en la URL. No se suben los archivos completos: se envían los fragmentos recuperados que hayas autorizado, junto con la pregunta.

Ejercicio: describe los campos `status`, `text`, `source_id` y `quote`. Comprueba en la interfaz que una pregunta repetida puede responderse desde caché. No imprimas la clave al depurar.

## 5. Intenta romper la validación

`validate_answer()` rechaza identificadores desconocidos, citas ausentes y conflictos con una sola fuente. Las pruebas del repositorio permiten probarlo sin llamar a Google.

Ejercicio: escribe una prueba donde la cita existe pero la afirmación es incorrecta. El validador literal puede aceptarla: documenta por qué necesitamos evaluación semántica y revisión humana. No añadas una supuesta garantía de veracidad al README.

## 6. Construye tu propia mejora

Elige una mejora pequeña y publica evidencia de su efecto:

- Añadir un filtro por familia documental y una prueba que demuestre que excluye otras familias.
- Comparar BM25 con una recuperación que use embeddings locales, con preguntas de prueba reservadas antes de ajustar.
- Añadir una tabla de evaluación manual con respuesta esperada, documentos válidos y casos sin respuesta.
- Probar Docker realmente y documentar el procedimiento reproducible.

## Primer piloto con documentos de tu trabajo

Selecciona entre tres y cinco documentos que tengas permiso de procesar. Revisa su contenido y carga primero con Gemini desactivado. Asigna familia, versión, categoría y estado; comprueba la extracción y formula diez preguntas con respuestas conocidas. Usa el modo Gemini solo cuando hayas autorizado compartir esos fragmentos con Google.

Mantén los documentos de trabajo, sus preguntas y sus respuestas fuera del repositorio público. Para el portafolio publica el código, ejemplos ficticios y resultados de evaluación que no revelen contenido interno.

## Cómo explicarlo en una entrevista

Explica el problema concreto, qué datos usaste, por qué elegiste recuperación local, cómo separaste versiones, qué sale de tu computador y qué garantiza exactamente el validador. Enseña un fallo y cómo lo mediste. Describe con honestidad tu contribución y el uso de Codex; practica modificar y depurar el código por tu cuenta.
