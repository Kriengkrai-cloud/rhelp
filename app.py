# app.py
from typing import List, Optional
import json, os, time
from pathlib import Path

from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from sqlalchemy import create_engine, Column, String, Text, func, Integer, ForeignKey, LargeBinary, DateTime, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.sql import func as sqlfunc

BASE_DIR = Path(__file__).resolve().parent
PUBLIC_DIR = BASE_DIR / "public"

MAX_IMAGES = 15
MAX_BYTES = 4 * 1024 * 1024  # 4 MB/image

# -------------------- DB setup --------------------
DB_URL = os.getenv(
    "DATABASE_URL",
    # You can keep sqlite fallback for local: "sqlite:///./kb.db"
    "postgresql+psycopg://neondb_owner:npg_2SATnmYzbRH7@ep-wild-poetry-admjc084-pooler.c-2.us-east-1.aws.neon.tech/rhelp?sslmode=require"
).strip()

connect_args = {"check_same_thread": False} if DB_URL.startswith("sqlite") else {}
engine = create_engine(DB_URL, pool_pre_ping=True, connect_args=connect_args)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# -------------------- Models (define BEFORE create_all) --------------------
class ItemModel(Base):
    __tablename__ = "items"
    id = Column(String(128), primary_key=True)
    name = Column(String(255), nullable=False)
    desc = Column(Text, nullable=True)
    tags_json = Column(Text, nullable=True)
    images_json = Column(Text, nullable=True)  # optional URL list (legacy)

class ItemImage(Base):
    __tablename__ = "item_images"
    id = Column(Integer, primary_key=True, autoincrement=True)
    item_id = Column(String(128), ForeignKey("items.id", ondelete="CASCADE"), nullable=False, index=True)
    filename = Column(String(255), nullable=False)
    content_type = Column(String(128), nullable=False)
    data = Column(LargeBinary, nullable=False)
    created_at = Column(DateTime, server_default=sqlfunc.now())

# Create/upgrade tables (idempotent)
Base.metadata.create_all(bind=engine)
with engine.begin() as conn:
    conn.execute(text("ALTER TABLE items ADD COLUMN IF NOT EXISTS images_json TEXT"))
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS item_images (
            id SERIAL PRIMARY KEY,
            item_id VARCHAR(128) NOT NULL REFERENCES items(id) ON DELETE CASCADE,
            filename VARCHAR(255) NOT NULL,
            content_type VARCHAR(128) NOT NULL,
            data BYTEA NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        );
    """))
    conn.execute(text("CREATE INDEX IF NOT EXISTS idx_item_images_item_id ON item_images(item_id)"))

# -------------------- Schemas --------------------
from pydantic import BaseModel

class ItemIn(BaseModel):
    id: str
    name: str
    desc: Optional[str] = ""
    tags: List[str] = []
    images: List[str] = []

class ItemUpdate(BaseModel):
    name: Optional[str] = None
    desc: Optional[str] = None
    tags: Optional[List[str]] = None
    images: Optional[List[str]] = None

class SearchResult(BaseModel):
    total: int
    items: List[ItemIn]

# -------------------- App --------------------
app = FastAPI(title="Product KB API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], allow_credentials=True,
    allow_methods=["*"], allow_headers=["*"],
)

def _parse_tags(src: Optional[str]) -> list[str]:
    if not src:
        return []
    # Try JSON list first
    try:
        val = json.loads(src)
        if isinstance(val, list):
            return [str(v).strip() for v in val if str(v).strip()]
    except Exception:
        pass
    # Fallback: comma-separated string
    return [s.strip() for s in str(src).split(",") if s.strip()]


def to_dict(m: ItemModel) -> ItemIn:
    tags = _parse_tags(m.tags_json)

    # build image URLs from item_images
    db = SessionLocal()
    try:
        ids = [row[0] for row in db.query(ItemImage.id)
               .filter(ItemImage.item_id == m.id)
               .order_by(ItemImage.id)]
    finally:
        db.close()

    imgs = [f"/media/{img_id}" for img_id in ids]
    return ItemIn(id=m.id, name=m.name, desc=(m.desc or ""), tags=tags, images=imgs)


@app.get("/healthz")
def healthz():
    return {"ok": True}

# -------------------- API --------------------
from sqlalchemy import func as safunc

@app.get("/api/search", response_model=SearchResult)
def search(q: Optional[str] = "", limit: int = 20, offset: int = 0):
    db = SessionLocal()
    try:
        query = db.query(ItemModel)
        if q:
            pattern = f"%{q.lower()}%"
            query = query.filter(
                safunc.lower(ItemModel.id).like(pattern) |
                safunc.lower(ItemModel.name).like(pattern) |
                safunc.lower(safunc.coalesce(ItemModel.desc, "")).like(pattern) |
                safunc.lower(safunc.coalesce(ItemModel.tags_json, "")).like(pattern)
            )
        total = query.count()
        rows = query.order_by(ItemModel.id).offset(offset).limit(limit).all()
        return SearchResult(total=total, items=[to_dict(r) for r in rows])
    finally:
        db.close()

@app.post("/api/items", status_code=201)
def create_item(item: ItemIn):
    if len(item.images or []) > 15:
        raise HTTPException(status_code=400, detail="Max 15 images")
    db = SessionLocal()
    try:
        if db.get(ItemModel, item.id):
            raise HTTPException(status_code=409, detail="ID already exists")
        db.add(ItemModel(
            id=item.id,
            name=item.name,
            desc=item.desc or "",
            tags_json=json.dumps(item.tags or []),
            images_json=json.dumps((item.images or [])[:15])
        ))
        db.commit()
        return {"ok": True}
    finally:
        db.close()


@app.get("/api/items/{item_id}")
def get_item(item_id: str):
    db = SessionLocal()
    try:
        row = db.get(ItemModel, item_id)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")

        # normalize tags from tags_json (JSON array or "a,b")
        def _parse_tags(src):
            if not src:
                return []
            try:
                v = json.loads(src)
                if isinstance(v, list):
                    return [str(x).strip() for x in v if str(x).strip()]
            except Exception:
                pass
            return [s.strip() for s in str(src).split(",") if s.strip()]

        tags = _parse_tags(row.tags_json)

        # image URLs (may be empty)
        ids = [i for (i,) in db.query(ItemImage.id)
               .filter(ItemImage.item_id == item_id)
               .order_by(ItemImage.id).all()]
        images = [f"/media/{i}" for i in ids]

        desc = row.desc or ""                 # <- always a string
        return {
            "id": row.id,
            "name": row.name or "",
            "desc": desc,                      # preferred
            "description": desc,               # alias for safety
            "tags": tags,                      # normalized list
            "tags_json": row.tags_json or "",  # fallback
            "images": images
        }
    finally:
        db.close()


@app.put("/api/items/{item_id}")
def update_item(item_id: str, patch: ItemUpdate):
    db = SessionLocal()
    try:
        row = db.get(ItemModel, item_id)
        if not row:
            raise HTTPException(status_code=404, detail="Not found")
        if patch.name is not None: row.name = patch.name
        if patch.desc is not None: row.desc = patch.desc
        if patch.tags is not None: row.tags_json = json.dumps(patch.tags)
        if patch.images is not None:
            if len(patch.images) > 15:
                raise HTTPException(status_code=400, detail="Max 15 images")
            row.images_json = json.dumps(patch.images[:15])
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

# ---- Image upload/list/serve/delete ----
@app.post("/api/items/{item_id}/images", status_code=201)
async def upload_images(item_id: str, files: list[UploadFile] = File(...), name: Optional[str] = Form(None)):
    """
    Upload one or more images for an item.
    If the item doesn't exist, auto-create it with name (or item_id as fallback).
    """
    db = SessionLocal()
    try:
        item = db.get(ItemModel, item_id)
        if not item:
            # auto-create stub item so "Item not found" never blocks user
            item = ItemModel(
                id=item_id,
                name=(name or item_id),
                desc="",
                tags_json=json.dumps([]),
                images_json=json.dumps([])
            )
            db.add(item)
            db.commit()

        cur = db.query(ItemImage).filter(ItemImage.item_id == item_id).count()
        if cur >= MAX_IMAGES:
            raise HTTPException(status_code=400, detail=f"Already has {cur} images; max {MAX_IMAGES}")

        saved = 0
        for f in files:
            if cur + saved >= MAX_IMAGES:
                break
            if not (f.content_type or "").startswith("image/"):
                raise HTTPException(status_code=400, detail="Only image/* files allowed")

            data = await f.read()
            if not data:
                continue
            if len(data) > MAX_BYTES:
                raise HTTPException(status_code=400, detail="Image too large (max 4MB)")

            db.add(ItemImage(
                item_id=item_id,
                filename=f.filename or "image",
                content_type=f.content_type or "application/octet-stream",
                data=data
            ))
            saved += 1

        if saved == 0:
            raise HTTPException(status_code=400, detail="No images uploaded")
        db.commit()
        return {"ok": True, "added": saved}
    finally:
        db.close()

@app.get("/api/items/{item_id}/images")
def list_images(item_id: str):
    db = SessionLocal()
    try:
        rows = db.query(ItemImage.id, ItemImage.filename, ItemImage.content_type)\
                 .filter(ItemImage.item_id == item_id).order_by(ItemImage.id).all()
        return [{"id": i, "url": f"/media/{i}", "filename": fn, "content_type": ct} for (i, fn, ct) in rows]
    finally:
        db.close()

@app.get("/media/{image_id}")
def serve_image(image_id: int):
    db = SessionLocal()
    try:
        img = db.get(ItemImage, image_id)
        if not img:
            raise HTTPException(status_code=404, detail="Not found")
        return Response(content=img.data, media_type=img.content_type or "application/octet-stream")
    finally:
        db.close()

@app.delete("/api/images/{image_id}")
def delete_image(image_id: int):
    db = SessionLocal()
    try:
        img = db.get(ItemImage, image_id)
        if not img:
            raise HTTPException(status_code=404, detail="Not found")
        db.delete(img)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

@app.get("/item/{item_id}")
def item_page(item_id: str):
    return FileResponse(str(PUBLIC_DIR / "product.html"))

# -------------------- Static site (mount once) --------------------
app.mount("/", StaticFiles(directory=str(PUBLIC_DIR), html=True), name="public")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=int(os.getenv("PORT", "8000")), reload=True)
