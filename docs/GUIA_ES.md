# DocuguIA · Guía en español

Consulta manuales, informes, apuntes, procedimientos y registros tabulares con fuentes. El tema es libre: cada archivo pertenece a una categoría que tú escribes, por ejemplo Investigación, Operaciones o Estudios. La categoría `general` se comparte con las consultas de cualquier categoría.

## Empezar

1. Clona [el repositorio](https://github.com/Andres-Vallejo/docuguia) e instala Python 3.12 o superior.
2. Desde PowerShell ejecuta `./start.ps1`. En Linux/macOS ejecuta `sh start.sh`. Los comandos manuales están en el [README](../README.md).
3. Abre [la aplicación](http://127.0.0.1:8765) y pulsa **Cargar ejemplo**. Incluye seis documentos ficticios sobre operaciones, inventario e infraestructura.
4. Pregunta «¿Cuántos microscopios tiene el laboratorio?» o «¿Cuánto tiempo se conservan las copias de seguridad de Atlas?».
5. En **Búsqueda local** se muestran fragmentos sin usar IA ni enviar datos. Revisa la fila, los encabezados y la ubicación de cada coincidencia.

## Cargar documentos propios

En **Documentos**, elige el archivo y asigna título, categoría, familia, versión, fecha y estado. La familia agrupa versiones del mismo documento. Los archivos nuevos se guardan como borradores; el filtro inicial incluye actuales y borradores. Los históricos requieren seleccionarlos.

Formatos: PDF con texto, DOCX, TXT, Markdown, CSV, TSV y HTML/HTM. Los archivos de texto deben estar en UTF-8. CSV/TSV usan la primera fila como encabezados. HTML se procesa como archivo local sin ejecutar scripts ni descargar recursos. No se aceptan directamente DOC antiguo, XLSX, PPTX ni audio/vídeo. Los escaneos necesitan OCR previo.

Límites: 10 MB por archivo, 200 páginas PDF y un millón de caracteres extraídos. No es necesario dividir manualmente el archivo en mil partes.

## Responder con Gemini

Crea una clave en [Google AI Studio](https://aistudio.google.com/api-keys) y verifica el nivel Free de su proyecto. Guárdala en **Conectar Gemini**, directamente en tu equipo. No pegues claves en chats ni issues.

Activa el permiso de envío solo en documentos que puedas compartir con Google y selecciona **Respuesta con Gemini**. Se envía la pregunta y hasta seis fragmentos recuperados. El nivel gratuito puede utilizar el contenido para mejorar productos de Google; consulta sus [condiciones y precios actuales](https://ai.google.dev/gemini-api/docs/pricing). La aplicación no puede comprobar tu facturación ni garantizar gratuidad en una cuenta con cobro activo.

La respuesta breve aparece primero; debajo puedes desplegar la evidencia y abrir la página disponible. Si falta un desglose, un total general no debe presentarse como el de una sede o grupo específico. Una cita literal comprobada no garantiza que la interpretación sea correcta.

## Páginas, secciones y tablas

Los PDF conservan la posición de página dentro del archivo. Para Word, instala LibreOffice: se genera un PDF de referencia local y la página citada corresponde a esa copia. Puede diferir de Word. Si una coincidencia no es inequívoca, se conserva sección, párrafo o fila sin inventar página.

Las tablas mantienen los encabezados junto a los valores de cada fila. Las tablas PDF con bordes se detectan automáticamente. Comprueba las celdas combinadas, tablas complejas y datos numéricos en el original antes de utilizarlos.

## Archivos y privacidad

La clave está en `.env`. Los originales, PDF de referencia, base de datos y caché están en `data/`. Ambas ubicaciones quedan fuera de Git. El repositorio incluye únicamente código, documentación y ejemplos ficticios. Las búsquedas locales no usan Gemini.

Eliminar un documento borra sus archivos guardados y fragmentos actuales y vacía la caché; no elimina copias de seguridad separadas ni información ya enviada a Google. Ejecuta el prototipo en `127.0.0.1`; no dispone de autenticación multiusuario.

## Aprender y comprobar

Consulta el [recorrido desde cero](APRENDER.md), la [arquitectura](ARCHITECTURE.md), la [API](API.md) y el [plan de evaluación](EVALUACION.md). Las pruebas y la evaluación de recuperación usan documentos ficticios y no consumen API.
