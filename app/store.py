from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import re
import sqlite3
import time
import unicodedata
from uuid import uuid4

STOP = set("a al algo ante como con cual cuales cuando de del desde donde el ella en entre es esa ese esta este esto fue ha hay la las le lo los me mi para por que qué quien se si sin sobre su sus te tiene un una uno unos unas y o u documento documentos favor segun según dice decir necesito saber dime muestra mostrar".split())


def normalize(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c))


def query_terms(text):
    return list(dict.fromkeys(t for t in re.findall(r"[a-z0-9]+", normalize(text))
                             if t not in STOP and len(t) > 1))[:24]


def now():
    return datetime.now(timezone.utc).isoformat()


class Store:
    def __init__(self, path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
            CREATE TABLE IF NOT EXISTS documents (
              id TEXT PRIMARY KEY, filename TEXT, title TEXT, family TEXT, version TEXT,
              document_date TEXT, block TEXT, status TEXT, allow_cloud INTEGER,
              sha TEXT, warnings TEXT, created_at TEXT);
            CREATE TABLE IF NOT EXISTS chunks (
              id INTEGER PRIMARY KEY, document_id TEXT REFERENCES documents(id) ON DELETE CASCADE,
              location TEXT, text TEXT);
            CREATE VIRTUAL TABLE IF NOT EXISTS search USING fts5(title, body, tokenize='unicode61 remove_diacritics 2');
            CREATE TABLE IF NOT EXISTS cache (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, timestamp REAL, day TEXT);
            """)
            columns = {row['name'] for row in db.execute('PRAGMA table_info(chunks)')}
            for name, definition in [('section', "TEXT NOT NULL DEFAULT ''"), ('page', 'INTEGER'),
                                     ('page_end', 'INTEGER'), ('kind', "TEXT NOT NULL DEFAULT 'text'")]:
                if name not in columns:
                    db.execute(f'ALTER TABLE chunks ADD COLUMN {name} {definition}')

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def add(self, filename, content, meta, chunks, warnings):
        sha = hashlib.sha256(content).hexdigest()
        with self.connect() as db:
            duplicate = db.execute("SELECT id FROM documents WHERE sha=? AND block=? AND version=?",
                                   (sha, meta["block"], meta["version"])).fetchone()
            if duplicate:
                # Refresh extraction after parser improvements, preserving the user's metadata.
                old = [(r['location'], r['text'], r['section'], r['page'], r['page_end'], r['kind']) for r in db.execute(
                    "SELECT * FROM chunks WHERE document_id=? ORDER BY id", (duplicate["id"],))]
                new = [(c['location'], c['text'], c.get('section', ''), c.get('page'), c.get('page_end'), c.get('kind', 'text')) for c in chunks]
                if old != new:
                    db.execute("DELETE FROM search WHERE rowid IN (SELECT id FROM chunks WHERE document_id=?)", (duplicate["id"],))
                    db.execute("DELETE FROM chunks WHERE document_id=?", (duplicate["id"],))
                    for chunk in chunks:
                        row = db.execute("INSERT INTO chunks(document_id,location,text,section,page,page_end,kind) VALUES (?,?,?,?,?,?,?)",
                                         (duplicate['id'], chunk['location'], chunk['text'], chunk.get('section', ''), chunk.get('page'), chunk.get('page_end'), chunk.get('kind', 'text')))
                        db.execute("INSERT INTO search(rowid,title,body) VALUES (?,?,?)",
                                   (row.lastrowid, meta["title"], chunk["text"]))
                    db.execute("DELETE FROM cache")
                db.execute('UPDATE documents SET warnings=? WHERE id=?', (json.dumps(warnings, ensure_ascii=False), duplicate['id']))
                return duplicate["id"], False
            docid = uuid4().hex
            db.execute("INSERT INTO documents VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (
                docid, filename, meta["title"], meta["family"], meta["version"],
                meta["document_date"], meta["block"], meta["status"], int(meta["allow_cloud"]),
                sha, json.dumps(warnings, ensure_ascii=False), now()))
            for chunk in chunks:
                cur = db.execute("INSERT INTO chunks(document_id,location,text,section,page,page_end,kind) VALUES (?,?,?,?,?,?,?)",
                                 (docid, chunk['location'], chunk['text'], chunk.get('section', ''), chunk.get('page'), chunk.get('page_end'), chunk.get('kind', 'text')))
                db.execute("INSERT INTO search(rowid,title,body) VALUES(?,?,?)",
                           (cur.lastrowid, meta["title"], chunk["text"]))
            db.execute("DELETE FROM cache")
            return docid, True

    def documents(self):
        with self.connect() as db:
            rows = db.execute("""SELECT d.*,count(c.id) chunk_count FROM documents d
                LEFT JOIN chunks c ON d.id=c.document_id GROUP BY d.id ORDER BY d.created_at DESC""").fetchall()
            result = []
            for row in rows:
                item = dict(row)
                item["warnings"] = json.loads(item["warnings"])
                item["allow_cloud"] = bool(item["allow_cloud"])
                result.append(item)
            return result

    def delete(self, docid):
        with self.connect() as db:
            db.execute("DELETE FROM search WHERE rowid IN (SELECT id FROM chunks WHERE document_id=?)", (docid,))
            changed = db.execute("DELETE FROM documents WHERE id=?", (docid,)).rowcount
            db.execute("DELETE FROM cache")
            return bool(changed)

    def update(self, docid, status, allow_cloud):
        with self.connect() as db:
            changed = db.execute("UPDATE documents SET status=?,allow_cloud=? WHERE id=?",
                                 (status, int(allow_cloud), docid)).rowcount
            db.execute("DELETE FROM cache")
            return bool(changed)

    def retrieve(self, question, block="all", status="active", cloud=False, limit=6):
        terms = query_terms(question)
        if not terms:
            return []
        match = " OR ".join('"' + term + '"' for term in terms)
        where, params = ["search MATCH ?"], [match]
        if block != "all":
            where.append("d.block IN (?, 'general')")
            params.append(block)
        if status == "active":
            where.append("d.status IN ('current', 'draft')")
        elif status != "all":
            where.append("d.status=?")
            params.append(status)
        if cloud:
            where.append("d.allow_cloud=1")
        sql = """SELECT c.id chunk_id,c.text,c.location,c.section,c.page,c.page_end,c.kind,d.id document_id,d.title,d.filename,
                 d.block,d.version,d.document_date,d.status,d.family,d.allow_cloud,
                 bm25(search,2.0,1.0) rank FROM search
                 JOIN chunks c ON c.id=search.rowid JOIN documents d ON d.id=c.document_id
                 WHERE """ + " AND ".join(where) + " ORDER BY rank,c.id LIMIT ?"
        with self.connect() as db:
            rows = db.execute(sql, [*params, limit]).fetchall()
            result = []
            for i, row in enumerate(rows, 1):
                item = dict(row)
                item["source_id"] = f"S{i}"
                preview = self.path.parent / 'previews' / (item['document_id'] + '.pdf')
                item['preview_url'] = f"/api/documents/{item['document_id']}/preview" if preview.is_file() else None
                item['page_origin'] = 'generated_pdf' if item['page'] and item['filename'].lower().endswith('.docx') else 'original_pdf' if item['page'] else None
                result.append(item)
            return result

    def fingerprint(self):
        docs = [(d["id"], d["status"], d["allow_cloud"]) for d in self.documents()]
        return hashlib.sha256(json.dumps(docs).encode()).hexdigest()

    def cached(self, key):
        with self.connect() as db:
            row = db.execute("SELECT value FROM cache WHERE key=?", (key,)).fetchone()
            return json.loads(row[0]) if row else None

    def cache(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO cache VALUES (?,?)", (key, json.dumps(value, ensure_ascii=False)))

    def reserve_call(self, limit, interval):
        # Reserve before network I/O; failures also consume the local budget.
        stamp = time.time()
        day = datetime.now(timezone.utc).date().isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            count = db.execute("SELECT count(*) FROM calls WHERE day=?", (day,)).fetchone()[0]
            last = db.execute("SELECT max(timestamp) FROM calls").fetchone()[0]
            if count >= limit:
                raise ValueError("Se alcanzó el límite local diario. Continúa con búsqueda local.")
            if last and stamp - last < interval:
                raise ValueError(f"Espera {int(interval - (stamp - last)) + 1} segundos entre consultas a Gemini.")
            db.execute("INSERT INTO calls(timestamp,day) VALUES(?,?)", (stamp, day))

    def usage(self):
        day = datetime.now(timezone.utc).date().isoformat()
        with self.connect() as db:
            return db.execute("SELECT count(*) FROM calls WHERE day=?", (day,)).fetchone()[0]
