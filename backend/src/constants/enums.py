from enum import StrEnum


class Role(StrEnum):
    VIEWER = 'viewer'
    ANALYST = 'analyst'
    SUPERVISOR = 'supervisor'


class RunStatus(StrEnum):
    QUEUED = 'queued'
    SUCCEEDED = 'succeeded'
    FAILED = 'failed'


class Decision(StrEnum):
    APPROVED = 'approved'
    RETURNED = 'returned'


class SignoffOutcome(StrEnum):
    """返染签认的取值。撤回是显式记录，生效后色卡回到「待判」。"""

    POSITIVE = '返染'
    NEGATIVE = '留样'
    WITHDRAWN = '撤回'


class QueueStatus(StrEnum):
    QUEUED = 'queued'
    COMPUTING = 'computing'
    READY = 'ready'
    ACTIVE = 'active'
    FAILED = 'failed'
    SUPERSEDED = 'superseded'


class ScheduleMode(StrEnum):
    RUN = 'run'
    QUEUE = 'queue'
