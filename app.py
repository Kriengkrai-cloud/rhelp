# app.py
from typing import List, Optional
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, Column, String, Text, Integer, func
from sqlalchemy.orm import sessionmaker, declarative_base
import json
import os

DB_URL = os.getenv("DATABASE_URL", "sqlite:///./kb.db")
engine = create_engine(
    DB_URL,
    connect_args={"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# --- SQLAlchemy model ---
class ItemModel(Base):
    __tablename__ = "items"
    id = Column(String(128), primary_key=True)       # product ID (string)
    name = Column(String(255), nullable=False)
    desc = Column(Text, nullable=True)
    tags_json = Column(Text, nullable=True)          # JSON-encoded list

# --- create tables ---
Base.metadata.create_all(bind=engine)

# --- Pydantic schemas ---
class ItemIn(BaseModel):
    id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    desc: Optional[str] = ""
    tags: List[str] = []

class ItemUpdate(BaseModel):
    name: Optional[str]
    desc: Optional[str]
    tags: Optional[List[str]]

class SearchResult(BaseModel):
    total: int
    items: List[ItemIn]

# --- app ---
app = FastAPI(title="Product KB API")

# CORS (open for demo; tighten in production)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

@app.get("/healthz")
def healthz():
    return {"ok": True}

def to_dict(m: ItemModel) -> ItemIn:
    tags = []
    if m.tags_json:
        try:
            tags = json.loads(m.tags_json)
        except Exception:
            tags = []
    return ItemIn(id=m.id, name=m.name, desc=m.desc or "", tags=tags)

# --- Endpoints ---

@app.get("/api/search", response_model=SearchResult)
def search(q: Optional[str] = "", limit: int = 20, offset: int = 0):
    session = SessionLocal()
    try:
        query = session.query(ItemModel)
        if q:
            pattern = f"%{q.lower()}%"
            # naive case-insensitive search across id/name/desc/tags
            query = query.filter(
                func.lower(ItemModel.id).like(pattern) |
                func.lower(ItemModel.name).like(pattern) |
                func.lower(func.coalesce(ItemModel.desc, "")).like(pattern) |
                func.lower(func.coalesce(ItemModel.tags_json, "")).like(pattern)
            )

        total = query.count()
        rows = (query.order_by(ItemModel.id)
                    .offset(offset)
                    .limit(limit)
                    .all())
        return SearchResult(total=total, items=[to_dict(r) for r in rows])
    finally:
        session.close()

@app.post("/api/items", status_code=201)
def create_item(item: ItemIn):
    session = SessionLocal()
    try:
        exists = session.get(ItemModel, item.id)
        if exists:
            raise HTTPException(status_code=409, detail="ID already exists")
        row = ItemModel(
            id=item.id,
            name=item.name,
            desc=item.desc or "",
            tags_json=json.dumps(item.tags or []),
        )
        session.add(row)
        session.commit()
        return {"ok": True}
    finally:
        session.close()

@app.get("/api/items/{item_id}", response_model=ItemIn)
def get_item(item_id: str):
    session = SessionLocal()
    try:
        row = session.get(ItemModel, item_id)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        return to_dict(row)
    finally:
        session.close()

@app.put("/api/items/{item_id}")
def update_item(item_id: str, patch: ItemUpdate):
    session = SessionLocal()
    try:
        row = session.get(ItemModel, item_id)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")

        if patch.name is not None:
            row.name = patch.name
        if patch.desc is not None:
            row.desc = patch.desc
        if patch.tags is not None:
            row.tags_json = json.dumps(patch.tags)

        session.commit()
        return {"ok": True}
    finally:
        session.close()

@app.delete("/api/items/{item_id}")
def delete_item(item_id: str):
    session = SessionLocal()
    try:
        row = session.get(ItemModel, item_id)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        session.delete(row)
        session.commit()
        return {"ok": True}
    finally:
        session.close()

if __name__ == "__main__":
    import uvicorn, os
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
