from datetime import timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.config.project import SPEC
from src.config.runtime import WORKDIR
from src.constants.enums import Decision, ScheduleMode
from src.models.base import utc_now
from src.models.workflow import AnalysisRun, AuditEvent, Delivery, Review, Schedule
from src.services.errors import BusinessError
from src.services.queues import active_queue, held_tickets
from src.utils.formatting import csv_text


QUEUE_COLUMNS = ({'key': 'ticket', 'label': '色样签'}, {'key': 'lot', 'label': '批号'},
                 {'key': 'risk', 'label': '返染概率（%）'}, {'key': 'decision', 'label': '抽查建议'},
                 {'key': 'signal', 'label': '主要风险信号'})


def create_schedule(db, request, actor):
    first_at = request.start_at.astimezone(timezone.utc).replace(tzinfo=None) if request.start_at else utc_now()
    if first_at < utc_now() - timedelta(minutes=1):
        raise BusinessError('首次分发时间已过去')
    if request.queue:
        item = active_queue(db)
        if item is None:
            raise BusinessError('当前没有可用的抽查队列', 409)
        schedule = Schedule(mode=ScheduleMode.QUEUE, run_id=None, recipient=request.recipient,
                            interval_minutes=request.interval_minutes, next_at=first_at)
    else:
        if not db.scalar(select(Review.id).where(Review.run_id == request.run_id,
                                                 Review.decision == Decision.APPROVED)):
            raise BusinessError('只有已签核分析可以定时分发', 409)
        schedule = Schedule(mode=ScheduleMode.RUN, run_id=request.run_id, recipient=request.recipient,
                            interval_minutes=request.interval_minutes, next_at=first_at)
    db.add(schedule)
    db.flush()
    db.add(AuditEvent(actor=actor, action='schedule.created',
                      detail=f'计划 #{schedule.id} · {schedule.recipient}'))
    return schedule


def stop_schedule(db, schedule_id, actor):
    schedule = db.get(Schedule, schedule_id, with_for_update=True)
    if schedule is None:
        raise BusinessError('计划不存在', 404)
    if schedule.active:
        schedule.active = False
        db.add(AuditEvent(actor=actor, action='schedule.stopped', detail=f'计划 #{schedule.id}'))
    return schedule


def _queue_report(db, schedule):
    """为队列计划生成当期报表。受影响色卡重算期间暂停，其余照常下发。"""
    queue = active_queue(db)
    if queue is None or not queue.result:
        return None
    held = held_tickets(db)
    rows = [row for row in queue.result['rows'] if row['ticket'] not in held]
    if not rows:
        return None
    return queue, csv_text(QUEUE_COLUMNS, rows)


def _run_report(db, schedule):
    run = db.get(AnalysisRun, schedule.run_id)
    if run is None or not run.result:
        return None
    return run, csv_text(run.result['columns'], run.result['rows'])


def dispatch_pending(db):
    """投递到期计划。跳过本期无内容（暂停）的计划，继续处理其它到期计划。"""
    now = utc_now()
    ids = list(db.scalars(select(Schedule.id).where(Schedule.active.is_(True), Schedule.next_at <= now)
                          .order_by(Schedule.next_at, Schedule.id).limit(20)))
    worked = False
    for schedule_id in ids:
        try:
            with db.begin_nested():
                schedule = db.get(Schedule, schedule_id, with_for_update=True)
                if schedule is None or not schedule.active or schedule.next_at > now:
                    continue
                worked = _dispatch_one(db, schedule, now) or worked
        except IntegrityError:
            # 并发的另一投递已写入同一到期时点，唯一约束兜底，跳过即可。
            worked = True
    return worked


def _dispatch_one(db, schedule, now):
    due_at = schedule.next_at
    report = _queue_report(db, schedule) if schedule.mode == ScheduleMode.QUEUE else _run_report(db, schedule)
    # 同一计划同一到期时点只发布一次；重试时唯一约束兜底。
    if db.scalar(select(Delivery.id).where(Delivery.schedule_id == schedule.id,
                                           Delivery.scheduled_at == due_at)):
        schedule.next_at = due_at + timedelta(minutes=schedule.interval_minutes)
        return True
    if report is None:
        # 本期无可用内容（如待判全部受影响暂停）。保留到期时点，等切换或解除暂停后再补送。
        return False
    baked, payload = report
    queue_id = baked.id if schedule.mode == ScheduleMode.QUEUE else None
    filename = f'{SPEC["slug"]}-plan{schedule.id}-{due_at:%Y%m%dT%H%M%S}.csv'
    WORKDIR.mkdir(parents=True, exist_ok=True)
    with NamedTemporaryFile(dir=WORKDIR, suffix='.tmp', delete=False) as temp:
        temp_name = Path(temp.name)
        temp.write(payload.encode('utf-8'))
    try:
        temp_name.replace(WORKDIR / filename)
    finally:
        temp_name.unlink(missing_ok=True)
    db.add(Delivery(schedule_id=schedule.id, queue_id=queue_id, scheduled_at=due_at, filename=filename))
    every = timedelta(minutes=schedule.interval_minutes)
    schedule.next_at = due_at + every * ((now - due_at) // every + 1)
    db.add(AuditEvent(actor='worker', action='report.delivered',
                      detail=f'计划 #{schedule.id} · {schedule.recipient}'))
    return True
