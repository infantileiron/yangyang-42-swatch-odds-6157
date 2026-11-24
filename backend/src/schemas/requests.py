from datetime import datetime

from pydantic import BaseModel, Field, field_validator, model_validator

from src.constants.enums import Decision, SignoffOutcome


class Credentials(BaseModel):
    email: str = Field(min_length=1, max_length=60)
    password: str = Field(min_length=1, max_length=128)


class CreateRun(BaseModel):
    title: str = Field(max_length=120)
    parameters: dict = Field(default_factory=dict)

    @field_validator('title')
    @classmethod
    def meaningful_title(cls, value):
        if not value.strip():
            raise ValueError('请填写分析名称')
        return value.strip()


class ReviewInput(BaseModel):
    decision: Decision
    note: str = Field(min_length=2, max_length=1000)

    @field_validator('note')
    @classmethod
    def meaningful_note(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('请填写复核依据')
        return value.strip()


class ScheduleInput(BaseModel):
    run_id: int | None = Field(default=None, gt=0)
    queue: bool = False
    recipient: str = Field(min_length=2, max_length=100)
    interval_minutes: int = Field(ge=1, le=10080)
    start_at: datetime | None = None

    @field_validator('recipient')
    @classmethod
    def meaningful_recipient(cls, value):
        if len(value.strip()) < 2:
            raise ValueError('请填写收件组')
        return value.strip()

    @field_validator('start_at')
    @classmethod
    def absolute_time(cls, value):
        if value is not None and value.utcoffset() is None:
            raise ValueError('首次分发时间必须包含时区')
        return value

    @model_validator(mode='after')
    def target(self):
        if not self.queue and not self.run_id:
            raise ValueError('请选择签核报告或抽查队列')
        if self.queue:
            self.run_id = None
        return self


class SignoffInput(BaseModel):
    ticket: str = Field(min_length=1, max_length=120)
    version: int = Field(ge=1)
    outcome: SignoffOutcome
    note: str = Field(default='', max_length=500)

    @field_validator('ticket')
    @classmethod
    def meaningful_ticket(cls, value):
        if not value.strip():
            raise ValueError('请填写色样号')
        return value.strip()


class SignoffBatch(BaseModel):
    items: list[SignoffInput] = Field(min_length=1, max_length=500)


class RecomputeInput(BaseModel):
    parameters: dict = Field(default_factory=dict)
    reason: str = Field(default='签认变更后重算', max_length=200)
