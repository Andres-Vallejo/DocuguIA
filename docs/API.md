# Local API

Run the app and open [interactive API documentation](http://127.0.0.1:8765/docs) for the request schemas. These endpoints are intended for local use.

| Method | Route | Purpose |
| --- | --- | --- |
| GET | `/api/status` | Model/configuration flags and local daily usage; never returns the key |
| GET | `/api/documents` | Library metadata, categories and version warnings |
| POST | `/api/documents` | Multipart upload and metadata |
| PATCH | `/api/documents/{id}` | Set status and cloud permission |
| DELETE | `/api/documents/{id}` | Remove local document entries, saved files and answer caches |
| GET | `/api/documents/{id}/preview` | Local reference PDF if available |
| POST | `/api/demo` | Import only the bundled invented examples |
| POST | `/api/ask` | Retrieve evidence or generate a cited response |
| POST | `/api/settings` | Save a key locally and confirm the project's Free tier |

Example search (no external provider request):

```sh
curl http://127.0.0.1:8765/api/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"Microscopio Laboratorio Cantidad","block":"Inventario","status":"active","mode":"local"}'
```

The UI calls categories «Categoría». The JSON/multipart field remains `block`. `all` is reserved for no category filter; `general` is shared across categories. Valid document states are `draft`, `current` and `historical`; the default query state `active` includes current and draft documents.

Generated answer states are `answered`, `partial`, `insufficient`, `conflict` and `unverified`. Retrieval and permission states distinguish `matches`, `empty_library`, `filtered` and `cloud_permission_required`. `api_called`, `cached` and `stage` identify whether the result came from local search, cache, provider or validation. A claim's `source_id` maps to the trusted source metadata supplied separately by the API.

Use invented samples when integrating or testing. Keep API keys out of command lines, URLs, issues and screenshots; configure the real key through the local password field.
