from fastapi import APIRouter,Depends
from sqlalchemy.orm import Session
from src.config.database import get_db
from src.controllers.dependencies import current_user,writers
from src.schemas.import_batch import BatchInput,RowCorrectionInput
from src.services import import_batches
router=APIRouter()
@router.get('/import-batches')
def index(db:Session=Depends(get_db),user=Depends(current_user)):return import_batches.list_batches(db)
@router.post('/import-batches',status_code=201)
def create(data:BatchInput,db:Session=Depends(get_db),user=Depends(writers)):return import_batches.create_batch(db,data,user)
@router.get('/import-batches/{id}')
def detail(id:int,db:Session=Depends(get_db),user=Depends(current_user)):return import_batches.detail(db,id)
@router.patch('/import-batches/{id}/rows/{row_id}')
def correct(id:int,row_id:int,data:RowCorrectionInput,db:Session=Depends(get_db),user=Depends(writers)):return import_batches.correct_row(db,id,row_id,data.raw_text,user)
@router.post('/import-batches/{id}/publish')
def publish(id:int,db:Session=Depends(get_db),user=Depends(writers)):return import_batches.publish_batch(db,id,user)
