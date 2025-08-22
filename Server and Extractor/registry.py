import os
import uvicorn
from fastapi import FastAPI, HTTPException, Depends
from pydantic import BaseModel
from sqlalchemy import create_engine, Column, String, Integer
from sqlalchemy.orm import sessionmaker, Session
from sqlalchemy.ext.declarative import declarative_base

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://admin:secret@localhost/registry_db")
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class ExtractorModel(Base):
    __tablename__ = "extractors"
    id = Column(Integer, primary_key=True, index=True)
    extractor_id = Column(String, unique=True, index=True, nullable=False)
    extractor_url = Column(String, nullable=False)
    status = Column(String, default="available", nullable=False)

class ExtractorRegister(BaseModel):
    extractor_id: str
    extractor_url: str

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

app = FastAPI(title="Central Registry (PostgreSQL)")

@app.on_event("startup")
def on_startup():
    Base.metadata.create_all(bind=engine)

@app.post("/register")
def register_extractor(extractor: ExtractorRegister, db: Session = Depends(get_db)):
    db_extractor = db.query(ExtractorModel).filter(ExtractorModel.extractor_id == extractor.extractor_id).first()
    if db_extractor:
        db_extractor.extractor_url = extractor.extractor_url
        db_extractor.status = "available"
    else:
        db_extractor = ExtractorModel(**extractor.dict(), status="available")
        db.add(db_extractor)
    db.commit()
    db.refresh(db_extractor)
    return {"message": f"Extractor {db_extractor.extractor_id} registered."}

@app.post("/update_status")
def update_extractor_status(extractor_id: str, status: str, db: Session = Depends(get_db)):
    db_extractor = db.query(ExtractorModel).filter(ExtractorModel.extractor_id == extractor_id).first()
    if not db_extractor:
        raise HTTPException(status_code=404, detail="Extractor not found")
    db_extractor.status = status
    db.commit()
    return {"message": "Status updated"}

@app.get("/get_available_extractor")
def get_available_extractor(db: Session = Depends(get_db)):
    db.expire_on_commit = False
    available_extractor = db.query(ExtractorModel).filter(ExtractorModel.status == "available").first()
    if not available_extractor:
        raise HTTPException(status_code=503, detail="No available extractors")
    
    available_extractor.status = "busy"
    db.commit()
    
    return {
        "extractor_id": available_extractor.extractor_id,
        "extractor_url": available_extractor.extractor_url
    }

@app.get("/health")
def health_check():
    return {"status": "ok"}