from pydantic import BaseModel,Field,model_validator
from typing import Literal
class BatchInput(BaseModel):
 name:str=Field(min_length=1,max_length=100)
 kind:Literal['reference','candidate']
 filename:str=Field(default='',max_length=160)
 description:str=Field(default='',max_length=500)
 content:str|None=None
 lines:list[str]|None=None
 @model_validator(mode='after')
 def validate_source(self):
  if self.lines is None and self.content is None:raise ValueError('请提供批次原文')
  if self.lines is not None and self.content is not None:raise ValueError('content 与 lines 只能提供一种')
  if self.lines is not None and any(not isinstance(x,str) for x in self.lines):raise ValueError('每行原文必须为字符串')
  return self
class RowCorrectionInput(BaseModel):
 raw_text:str=Field(max_length=20000)
