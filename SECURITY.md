# Security and data handling

DocuguIA is a single-user local prototype. Bind it to `127.0.0.1`. It has no multi-user authentication or tenant isolation and is not designed for an Internet-facing deployment.

- `.env` stores the Gemini key locally; `data/` stores extracted text, originals, PDF previews and cached answers. Both are excluded from Git and Docker build contexts.
- Local search does not contact Gemini. Generated answers send the question and up to six retrieved fragments from documents whose cloud permission is enabled to Google's Gemini API. The app does not upload original files to Google.
- The free tier can use submitted content to improve Google's products. Review the current provider terms before enabling a document's cloud permission.
- DOCX page references use a local LibreOffice conversion. The original is preserved; only the temporary rendering copy has external relationships and VBA parts removed. Run with an updated converter and only open documents you are authorized to process.
- Citation validation checks source identity and literal quotation. It does not prove semantic support or prevent every prompt injection attempt.
- Deleting a document removes its current database entries and saved original/preview and clears answer caches. This is not secure disk erasure; separate backups and any content already transmitted are outside that operation.

For a vulnerability, use GitHub's private vulnerability reporting if enabled on the repository. If unavailable, contact the maintainer through the contact information on their GitHub profile before disclosing exploit details. Never include secrets or private documents in a public issue.
