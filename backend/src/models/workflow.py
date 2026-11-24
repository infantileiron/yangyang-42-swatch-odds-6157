from datetime import datetime

from sqlalchemy import (JSON, Boolean, DateTime, ForeignKey, Integer, String, Text,
                        UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column

from src.constants.enums import QueueStatus, RunStatus, ScheduleMode
from src.models.base import Base, utc_now


class Observation(Base):
    __tablename__ = 'observations'
    id: Mapped[int] = mapped_column(primary_key=True)
    source_key: Mapped[str] = mapped_column(String(96), unique=True)
    payload: Mapped[dict] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class Signoff(Base):
    """返染签认补录。同张色卡以最高 version 为准，乱序到达也不影响生效值。"""

    __tablename__ = 'signoffs'
    __table_args__ = (UniqueConstraint('ticket', 'version'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    ticket: Mapped[str] = mapped_column(String(120), index=True)
    version: Mapped[int] = mapped_column(Integer)
    outcome: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text, default='')
    actor: Mapped[str] = mapped_column(String(60))
    received_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class AnalysisRun(Base):
    __tablename__ = 'analysis_runs'
    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(120))
    owner: Mapped[str] = mapped_column(String(60))
    parameters: Mapped[dict] = mapped_column(JSON)
    last_observation_id: Mapped[int] = mapped_column(Integer)
    sample_size: Mapped[int] = mapped_column(Integer)
    observation_ids: Mapped[list] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(16), default=RunStatus.QUEUED, index=True)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class Review(Base):
    __tablename__ = 'reviews'
    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[int] = mapped_column(ForeignKey('analysis_runs.id'), unique=True)
    decision: Mapped[str] = mapped_column(String(16))
    note: Mapped[str] = mapped_column(Text)
    reviewer: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class SamplingQueue(Base):
    """抽查队列的一次完整重算。新版本算齐后一次性切换为 active。"""

    __tablename__ = 'sampling_queues'
    id: Mapped[int] = mapped_column(primary_key=True)
    revision: Mapped[int] = mapped_column(Integer, unique=True, index=True)
    signoff_watermark: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(16), default=QueueStatus.QUEUED, index=True)
    parameters: Mapped[dict] = mapped_column(JSON)
    dataset: Mapped[list] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    changed_tickets: Mapped[list] = mapped_column(JSON, default=list)
    held_tickets: Mapped[list] = mapped_column(JSON, default=list)
    total: Mapped[int] = mapped_column(Integer, default=0)
    computed: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str] = mapped_column(String(200), default='')
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
    ready_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class QueueRow(Base):
    __tablename__ = 'queue_rows'
    __table_args__ = (UniqueConstraint('queue_id', 'ticket'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    queue_id: Mapped[int] = mapped_column(ForeignKey('sampling_queues.id'), index=True)
    ticket: Mapped[str] = mapped_column(String(120))
    lot: Mapped[str] = mapped_column(String(120))
    day: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(16), default=QueueStatus.QUEUED)
    payload: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class Schedule(Base):
    __tablename__ = 'schedules'
    id: Mapped[int] = mapped_column(primary_key=True)
    mode: Mapped[str] = mapped_column(String(16), default=ScheduleMode.RUN)
    run_id: Mapped[int | None] = mapped_column(ForeignKey('analysis_runs.id'), nullable=True, index=True)
    recipient: Mapped[str] = mapped_column(String(100))
    interval_minutes: Mapped[int] = mapped_column(Integer)
    next_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Delivery(Base):
    __tablename__ = 'deliveries'
    __table_args__ = (UniqueConstraint('schedule_id', 'scheduled_at'),)
    id: Mapped[int] = mapped_column(primary_key=True)
    schedule_id: Mapped[int] = mapped_column(ForeignKey('schedules.id'))
    queue_id: Mapped[int | None] = mapped_column(ForeignKey('sampling_queues.id'), nullable=True)
    scheduled_at: Mapped[datetime] = mapped_column(DateTime)
    filename: Mapped[str] = mapped_column(String(120))
    delivered_at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)


class AuditEvent(Base):
    __tablename__ = 'audit_events'
    id: Mapped[int] = mapped_column(primary_key=True)
    actor: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(60))
    detail: Mapped[str] = mapped_column(String(200))
    at: Mapped[datetime] = mapped_column(DateTime, default=utc_now)
