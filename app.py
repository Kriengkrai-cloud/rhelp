# app.py
from typing import List, Optional
import json, os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from sqlalchemy import create_engine, Column, String, Text, func
from sqlalchemy.orm import sessionmaker, declarative_base

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from pathlib import Path
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"


# -------------------- DB setup --------------------
# Prefer setting DATABASE_URL via environment variable.
# For NEON with psycopg v3, use:
#   postgresql+psycopg://USER:PASS@HOST:5432/DBNAME?sslmode=require
DB_URL = os.getenv("DATABASE_URL", "sqlite:///./kb.db").strip()

# Only pass check_same_thread for SQLite
connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}

engine = create_engine(DB_URL, pool_pre_ping=True, connect_args=connect_args)

# ✅ define SessionLocal and Base BEFORE models/endpoints
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# -------------------- SQLAlchemy model --------------------
class ItemModel(Base):
    __tablename__ = "items"
    id = Column(String(128), primary_key=True)
    name = Column(String(255), nullable=False)
    desc = Column(Text, nullable=True)
    tags_json = Column(Text, nullable=True)  # JSON-encoded list of strings

# Create tables (idempotent)
Base.metadata.create_all(bind=engine)

# -------------------- Pydantic schemas --------------------
class ItemIn(BaseModel):
    id: str
    name: str
    desc: Optional[str] = ""
    tags: List[str] = []

class ItemUpdate(BaseModel):
    name: Optional[str] = None
    desc: Optional[str] = None
    tags: Optional[List[str]] = None

class SearchResult(BaseModel):
    total: int
    items: List[ItemIn]

# -------------------- FastAPI app --------------------
app = FastAPI(title="Product KB API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

@app.get("/healthz")
def healthz():
    return {"ok": True}

def to_dict(m: ItemModel) -> ItemIn:
    try:
        tags = json.loads(m.tags_json) if m.tags_json else []
    except Exception:
        tags = []
    return ItemIn(id=m.id, name=m.name, desc=m.desc or "", tags=tags)

# -------------------- Endpoints --------------------

@app.get("/")
def root_page():
    app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public")
    return FileResponse("public/index.html")

@app.get("/api/search", response_model=SearchResult)
def search(q: Optional[str] = "", limit: int = 20, offset: int = 0):
    db = SessionLocal()
    try:
        query = db.query(ItemModel)
        if q:
            pattern = f"%{q.lower()}%"
            query = query.filter(
                func.lower(ItemModel.id).like(pattern) |
                func.lower(ItemModel.name).like(pattern) |
                func.lower(func.coalesce(ItemModel.desc, "")).like(pattern) |
                func.lower(func.coalesce(ItemModel.tags_json, "")).like(pattern)
            )
        total = query.count()
        rows = query.order_by(ItemModel.id).offset(offset).limit(limit).all()
        return SearchResult(total=total, items=[to_dict(r) for r in rows])
    finally:
        db.close()

@app.post("/api/items", status_code=201)
def create_item(item: ItemIn):
    db = SessionLocal()
    try:
        if db.get(ItemModel, item.id):
            raise HTTPException(status_code=409, detail="ID already exists")
        row = ItemModel(
            id=item.id,
            name=item.name,
            desc=item.desc or "",
            tags_json=json.dumps(item.tags or []),
        )
        db.add(row)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.get("/api/items/{item_id}", response_model=ItemIn)
def get_item(item_id: str):
    db = SessionLocal()
    try:
        row = db.get(ItemModel, item_id)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return to_dict(row)
    finally:
        db.close()

@app.put("/api/items/{item_id}")
def update_item(item_id: str, patch: ItemUpdate):
    db = SessionLocal()
    try:
        row = db.get(ItemModel, item_id)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        if patch.name is not None:
            row.name = patch.name
        if patch.desc is not None:
            row.desc = patch.desc
        if patch.tags is not None:
            row.tags_json = json.dumps(patch.tags)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.delete("/api/items/{item_id}")
def delete_item(item_id: str):
    db = SessionLocal()
    try:
        row = db.get(ItemModel, item_id)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        db.delete(row)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.get("/")
def root():
    return {"ok": True, "message": "Product KB API. See /docs for Swagger UI."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
