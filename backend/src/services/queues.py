from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from src.config.project import SPEC
from src.constants.enums import QueueStatus
from src.domain import analysis
from src.models.base import utc_now
from src.models.workflow import AuditEvent, QueueRow, SamplingQueue
from src.services.errors import BusinessError
from src.services.signoffs import build_dataset
from src.services.validation import validated


IN_FLIGHT = (QueueStatus.QUEUED, QueueStatus.COMPUTING, QueueStatus.READY)
DEFAULT_PARAMETERS = {'risk': 60, 'alpha': 1}


def _pending_scope(dataset):
    return {(row['ticket'], row['lot'], row.get('day', ''))
            for row in dataset if row.get('outcome') == analysis.PENDING}


def _snapshot(dataset):
    return {row['ticket']: row for row in dataset}


def latest_queue(db, *statuses):
    query = select(SamplingQueue)
    if statuses:
        query = query.where(SamplingQueue.status.in_(statuses))
    return db.scalar(query.order_by(SamplingQueue.revision.desc()).limit(1))


def active_queue(db):
    return db.scalar(select(SamplingQueue).where(SamplingQueue.status == QueueStatus.ACTIVE)
                     .order_by(SamplingQueue.revision.desc()).limit(1))


def changed_tickets(db, live=None):
    """自当前生效队列以来内容发生变化的色卡（改判、撤回、特征修订或新签认）。"""
    active = active_queue(db)
    if active is None:
        return set()
    live = live if live is not None else build_dataset(db)
    now, then = _snapshot(live), _snapshot(active.dataset or [])
    return {ticket for ticket in now.keys() | then.keys() if now.get(ticket) != then.get(ticket)}


def _ahead_of_active(db):
    """是否已有比生效队列更新的版本登记（无论其计算状态）。"""
    newest = latest_queue(db)
    active = active_queue(db)
    return newest is not None and (active is None or newest.revision > active.revision)


def held_tickets(db, live=None):
    """重算尚未切换期间需要暂停下发的色卡。

    只在存在比生效队列更新的版本时才暂停。判断粒度落在旧队列的每一行：
    色卡自身已变化就暂停；否则只要某个与它不同的染批里有色卡变化，它的
    训练样本就变了，暂停。与逐卡留一染批的训练口径一致，只暂停可能改变
    建议的色卡。
    """
    active = active_queue(db)
    if active is None or not active.result or not _ahead_of_active(db):
        return set()
    live = live if live is not None else build_dataset(db)
    changed = changed_tickets(db, live)
    if not changed:
        return set()
    changed_lots = {row['lot'] for row in live if row['ticket'] in changed}
    held = set()
    for row in active.result.get('rows', []):
        ticket, lot = row['ticket'], row['lot']
        if ticket in changed or any(lot != other for other in changed_lots):
            held.add(ticket)
    return held


def _affected(dataset, changed):
    """新队列里受影响的待判色卡：改判/撤回的、或被改染批进入其训练集的。"""
    changed_lots = {row['lot'] for row in dataset if row['ticket'] in changed}
    snapshot = _snapshot(dataset)
    tickets = {ticket for ticket in changed
               if snapshot.get(ticket, {}).get('outcome') == analysis.PENDING}
    if changed_lots:
        tickets |= {ticket for ticket, lot, _ in _pending_scope(dataset) if lot not in changed_lots}
    return tickets


def _next_revision(db):
    return (db.scalar(select(func.max(SamplingQueue.revision))) or 0) + 1


def request_recompute(db, changed, *, reason, parameters=None, actor='system'):
    """登记一次新的队列重算。修订号只增不减，较早版本无法顶替新版。

    条件不足时仍记录一版 FAILED，占住修订号并留下原因，不会回滚补录本身；
    期间按下发规则暂停受影响色卡。并发登记时用保存点重试占号。
    """
    dataset = build_dataset(db)
    parameters = validated(SPEC['parameters'], parameters or DEFAULT_PARAMETERS, defaults=True)
    for _ in range(5):
        try:
            with db.begin_nested():
                item = SamplingQueue(revision=_next_revision(db), parameters=parameters,
                                     dataset=dataset, changed_tickets=sorted(set(changed)),
                                     status=QueueStatus.QUEUED, total=0, computed=0,
                                     reason=reason[:200])
                db.add(item)
                db.flush()
            break
        except IntegrityError:
            continue
    else:
        raise BusinessError('抽查队列编号冲突，请稍后重试', 409)
    try:
        analysis.queue_preamble(dataset, parameters)
    except ValueError as exc:
        item.status = QueueStatus.FAILED
        item.reason = f'{reason[:120]}；{str(exc)[:80]}'
        item.ready_at = utc_now()
        db.add(AuditEvent(actor=actor, action='queue.failed',
                          detail=f'队列 r{item.revision} · {str(exc)[:120]}'))
        return item
    pending = sorted(_pending_scope(dataset), key=lambda row: (row[2], row[0]))
    item.total = len(pending)
    item.held_tickets = sorted(_affected(dataset, set(changed)))
    db.add_all([QueueRow(queue_id=item.id, ticket=ticket, lot=lot, day=day)
                for ticket, lot, day in pending])
    db.add(AuditEvent(actor=actor, action='queue.requested',
                      detail=f'队列 r{item.revision} · {len(pending)} 张待判 · {len(item.held_tickets)} 张暂停'))
    return item


def ensure_queue(db, parameters=None, actor='system'):
    """首次启动或尚无队列时建立的基线队列。"""
    if latest_queue(db) is not None:
        return None
    return request_recompute(db, [], reason='初始队列', parameters=parameters, actor=actor)


def dataset_stale(db, live=None):
    """当前有效数据与生效队列是否已不一致（任意色卡内容或待判范围变化）。"""
    active = active_queue(db)
    if active is None:
        return False
    live = live if live is not None else build_dataset(db)
    return _snapshot(live) != _snapshot(active.dataset or [])


def request_recompute_if_stale(db, *, reason, actor='system'):
    """数据与生效队列不一致时登记重算；没有变化则不动，避免空转多版本。"""
    live = build_dataset(db)
    if not dataset_stale(db, live):
        return None
    changed = changed_tickets(db, live)
    return request_recompute(db, changed, reason=reason, actor=actor)


def queue_pending(db):
    """推进一版队列的计算。返回是否做了工作。"""
    item = db.scalar(select(SamplingQueue)
                     .where(SamplingQueue.status.in_((QueueStatus.QUEUED, QueueStatus.COMPUTING)))
                     .order_by(SamplingQueue.revision).limit(1)
                     .with_for_update(skip_locked=True))
    if item is None:
        return False
    newest = db.scalar(select(func.max(SamplingQueue.revision)))
    if newest is not None and newest > item.revision:
        # 已有更新的补录版本在排队，这一版不再计算，也不会被切换上线。
        item.status = QueueStatus.SUPERSEDED
        item.ready_at = utc_now()
        return True
    item.status = QueueStatus.COMPUTING
    rows = list(db.scalars(select(QueueRow).where(QueueRow.queue_id == item.id).order_by(QueueRow.id)))
    failures = 0
    for row in rows:
        if row.status == QueueStatus.READY:
            continue
        try:
            row.payload = analysis.queue_row(item.dataset, item.parameters, row.ticket)
            row.status = QueueStatus.READY
        except ValueError as exc:
            row.error = str(exc)[:600]
            row.status = QueueStatus.FAILED
            failures += 1
        item.computed = sum(1 for other in rows if other.status == QueueStatus.READY)
        db.flush()
    item.computed = sum(1 for other in rows if other.status == QueueStatus.READY)
    item.ready_at = utc_now()
    # 只有整版逐卡都算齐才进入可切换状态；任一张失败就保留旧队列继续服务。
    if failures or item.computed != item.total:
        item.status = QueueStatus.FAILED
        item.reason = f'{item.reason[:120]}；{failures} 张未能计算' if failures else item.reason
        return True
    item.status = QueueStatus.READY
    item.result = analysis.queue_output(
        [{"ticket": row.ticket, "lot": row.lot, "day": row.day, "payload": row.payload} for row in rows])
    return True


def activate_ready(db):
    """算齐的队列一次性切换为 active。只有最新版能切，且不覆盖更新的版本。"""
    ready = list(db.scalars(select(SamplingQueue).where(SamplingQueue.status == QueueStatus.READY)
                            .order_by(SamplingQueue.revision)))
    if not ready:
        return False
    newest = db.scalar(select(func.max(SamplingQueue.revision)))
    candidate = ready[-1]
    # 任何比最新登记版本更旧的待切换版本都不再有机会上线。
    for stale in ready[:-1]:
        stale.status = QueueStatus.SUPERSEDED
    if newest is not None and newest > candidate.revision:
        candidate.status = QueueStatus.SUPERSEDED
        return True
    current = active_queue(db)
    if current is not None and current.revision >= candidate.revision:
        candidate.status = QueueStatus.SUPERSEDED
        return True
    if current is not None:
        current.status = QueueStatus.SUPERSEDED
    candidate.status = QueueStatus.ACTIVE
    candidate.activated_at = utc_now()
    db.add(AuditEvent(actor='worker', action='queue.activated',
                      detail=f'队列 r{candidate.revision} · {candidate.computed} 张待判'))
    return True
