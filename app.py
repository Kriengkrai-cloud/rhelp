# app.py  — FastAPI + SQLite CRUD + static UI at "/"
import os
import sqlite3
from typing import List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import threading



DB_LOCK = threading.Lock()

DB_PATH = "kb.db"

# ---------- DB helpers ----------
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
    CREATE TABLE IF NOT EXISTS products (
      id    TEXT PRIMARY KEY,
      name  TEXT NOT NULL,
      desc  TEXT,
      tags  TEXT            -- comma-separated tags
    );
    """)
    con.commit()
    con.close()

def get_conn():
    # timeout: wait up to 30s for locks
    con = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    cur = con.cursor()
    # Robust settings for concurrent readers/writers
    cur.execute("PRAGMA journal_mode=WAL;")
    cur.execute("PRAGMA synchronous=NORMAL;")
    cur.execute("PRAGMA busy_timeout=5000;")  # 5s retry on lock at sqlite level
    cur.close()
    return con

def _rowdicts(rows, cur):
    cols = [d[0] for d in cur.description]
    return [dict(zip(cols, r)) for r in rows]

def dbq(sql: str, params=(), one: bool = False):
    # Detect write vs read
    is_select = sql.lstrip().lower().startswith("select")

    # Serialize writes (INSERT/UPDATE/DELETE); allow parallel reads
    lock = DB_LOCK if not is_select else None
    if lock: lock.acquire()

    con = None
    try:
        con = get_conn()
        cur = con.cursor()
        cur.execute(sql, params)
        if is_select:
            cols = [d[0] for d in cur.description]
            rows = [dict(zip(cols, r)) for r in cur.fetchall()]
            return (rows[0] if (one and rows) else rows)
        else:
            con.commit()
            return []
    finally:
        try:
            if con: con.close()
        finally:
            if lock: lock.release()

init_db()

# ---------- Schemas ----------
class Product(BaseModel):
    id: str
    name: str
    desc: Optional[str] = ""
    tags: Optional[List[str]] = []

class ProductUpdate(BaseModel):
    name: Optional[str] = None
    desc: Optional[str] = None
    tags: Optional[List[str]] = None

# ---------- FastAPI app ----------
app = FastAPI(title="Product KB")

# CORS (allow from your phone/browser)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------- API ROUTES (mounted BEFORE static) ----------
@app.get("/api/search")
def search(
    q: str = "",
    qtext: str = "",
    limit: int = 20,
    offset: int = 0
):
    term = (qtext or q or "").strip().lower()
    like = f"%{term}%" if term else "%"
    # นับจำนวนทั้งหมดก่อน (สำหรับ pager)
    count_sql = """
      SELECT COUNT(*) AS c
      FROM products
      WHERE LOWER(name) LIKE ?
         OR LOWER(desc) LIKE ?
         OR LOWER(IFNULL(tags,'')) LIKE ?
    """
    total = dbq(count_sql, (like, like, like))[0]["c"]

    data_sql = f"""
      SELECT id, name, desc, tags
      FROM products
      WHERE LOWER(name) LIKE ?
         OR LOWER(desc) LIKE ?
         OR LOWER(IFNULL(tags,'')) LIKE ?
      ORDER BY name
      LIMIT ? OFFSET ?
    """
    items = dbq(data_sql, (like, like, like, max(1, limit), max(0, offset)))
    return {"total": total, "items": items}

@app.get("/api/items/{pid}")
def get_item(pid: str):
    row = dbq("SELECT id, name, desc, tags FROM products WHERE id=?", (pid,), one=True)

    if not row:
        raise HTTPException(404, "Not found")
    row["tags"] = [t for t in (row.get("tags") or "").split(",") if t]
    return row

@app.post("/api/items")
def create_item(p: Product):
    try:
        dbq("INSERT INTO products(id,name,desc,tags) VALUES(?,?,?,?)",
    (p.id, p.name, p.desc or "", ",".join(p.tags or [])))

    except sqlite3.IntegrityError:
        raise HTTPException(400, "ID already exists")
    return {"ok": True}

@app.put("/api/items/{pid}")
def update_item(pid: str, u: ProductUpdate):
    exists = dbq("SELECT 1 FROM products WHERE id=?", (pid,), one=True)
    if not exists:
        raise HTTPException(404, "Not found")

    fields, params = [], []
    if u.name is not None:
        fields.append("name=?"); params.append(u.name)
    if u.desc is not None:
        fields.append("desc=?"); params.append(u.desc)
    if u.tags is not None:
        fields.append("tags=?"); params.append(",".join(u.tags))

    if fields:
        params.append(pid)
        dbq(f"UPDATE products SET {', '.join(fields)} WHERE id=?", params)
    return {"ok": True}

@app.delete("/api/items/{pid}")
def delete_item(pid: str):
    dbq("DELETE FROM products WHERE id=?", (pid,))
    return {"ok": True}

# ---------- STATIC SITE (mount AFTER routes so /api/* wins) ----------
from fastapi.staticfiles import StaticFiles
os.makedirs("static", exist_ok=True)            # put index.html in ./static
app.mount("/", StaticFiles(directory="static", html=True), name="static")

# ---------- Dev entrypoint ----------
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
