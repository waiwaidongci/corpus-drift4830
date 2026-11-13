from sqlalchemy.orm import Mapped,mapped_column
from sqlalchemy import String,Text,JSON,ForeignKey,UniqueConstraint,DateTime
from sqlalchemy.dialects.mysql import MEDIUMTEXT
from datetime import datetime,timezone
from src.config.database import Base
# 单行原文可含中文与转义，utf8mb4 下必须用 MEDIUMTEXT，避免 TEXT 的 64KB 上限。
RawText=Text().with_variant(MEDIUMTEXT(),'mysql')
class ImportBatch(Base):
 __tablename__='import_batches'
 id:Mapped[int]=mapped_column(primary_key=True)
 name:Mapped[str]=mapped_column(String(100),unique=True)
 kind:Mapped[str]=mapped_column(String(20))
 filename:Mapped[str]=mapped_column(String(160))
 description:Mapped[str]=mapped_column(String(500),default='')
 status:Mapped[str]=mapped_column(String(20),default='pending')
 created_by:Mapped[int]=mapped_column(ForeignKey('users.id'))
 created_at:Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
 publisher_id:Mapped[int|None]=mapped_column(ForeignKey('users.id'),nullable=True)
 published_snapshot_id:Mapped[int|None]=mapped_column(nullable=True)
 published_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
class ImportBatchRow(Base):
 __tablename__='import_batch_rows'
 __table_args__=(UniqueConstraint('batch_id','line_no'),)
 id:Mapped[int]=mapped_column(primary_key=True)
 batch_id:Mapped[int]=mapped_column(ForeignKey('import_batches.id'))
 line_no:Mapped[int]=mapped_column()
 raw_text:Mapped[str]=mapped_column(RawText)
 reference:Mapped[str|None]=mapped_column(String(80),nullable=True)
 features:Mapped[dict|None]=mapped_column(JSON,nullable=True)
 error:Mapped[str|None]=mapped_column(String(500),nullable=True)
 status:Mapped[str]=mapped_column(String(20))
 corrected_at:Mapped[datetime|None]=mapped_column(DateTime,nullable=True)
 created_at:Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
class ImportRowRevision(Base):
 __tablename__='import_row_revisions'
 id:Mapped[int]=mapped_column(primary_key=True)
 row_id:Mapped[int]=mapped_column(ForeignKey('import_batch_rows.id'))
 previous_raw:Mapped[str]=mapped_column(RawText)
 previous_error:Mapped[str|None]=mapped_column(String(500),nullable=True)
 previous_status:Mapped[str]=mapped_column(String(20))
 new_raw:Mapped[str]=mapped_column(RawText)
 new_error:Mapped[str|None]=mapped_column(String(500),nullable=True)
 new_status:Mapped[str]=mapped_column(String(20))
 actor:Mapped[str]=mapped_column(String(120))
 created_at:Mapped[datetime]=mapped_column(DateTime,default=lambda:datetime.now(timezone.utc))
