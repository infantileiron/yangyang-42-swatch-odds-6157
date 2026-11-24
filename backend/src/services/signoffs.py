from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.constants.enums import SignoffOutcome
from src.domain.analysis import PENDING
from src.models.workflow import AuditEvent, Observation, Signoff
from src.services.errors import BusinessError


WITHDRAWN = SignoffOutcome.WITHDRAWN.value


def effective_signoffs(db):
    """每张色卡取最高 version 的签认。乱序补齐后结果仍然确定。"""
    latest = {}
    for row in db.scalars(select(Signoff).order_by(Signoff.ticket, Signoff.version)):
        latest[row.ticket] = row
    return latest


def resolve_outcome(payload, signoff):
    if signoff is None:
        return payload['outcome']
    return PENDING if signoff.outcome == WITHDRAWN else signoff.outcome


def build_dataset(db):
    """把观测与有效签认合并成队列计算快照。同号色卡以最后一条观测为准。"""
    by_ticket = {}
    for observation in db.scalars(select(Observation).order_by(Observation.id)):
        by_ticket[observation.payload['ticket']] = dict(observation.payload)
    latest = effective_signoffs(db)
    for ticket, row in by_ticket.items():
        if ticket in latest:
            row['outcome'] = resolve_outcome(row, latest[ticket])
    return list(by_ticket.values())


def submit_signoffs(db, items, actor):
    """补录签认记录。低版本照常归档但不改变有效值；同版本冲突直接拒收。"""
    before = effective_signoffs(db)
    observations = {row.payload['ticket']: row.payload
                    for row in db.scalars(select(Observation))}
    unknown = sorted({item['ticket'] for item in items if item['ticket'] not in observations})
    if unknown:
        raise BusinessError(f'色卡 {", ".join(unknown[:5])} 不在台账中，请先登记观测', 409)
    accepted = ignored = 0
    seen = {}
    for item in items:
        ticket, version, outcome = item['ticket'], item['version'], item['outcome']
        if seen.get((ticket, version), outcome) != outcome:
            raise BusinessError(f'同一批补录中色卡 {ticket} 的版本 {version} 结论冲突', 409)
        seen[(ticket, version)] = outcome
        existing = db.scalar(select(Signoff).where(Signoff.ticket == ticket, Signoff.version == version))
        if existing is not None:
            if existing.outcome == outcome and existing.note == item.get('note', ''):
                ignored += 1
                continue
            raise BusinessError(f'色卡 {ticket} 的版本 {version} 已有不同签认，请使用更高版本补录', 409)
        db.add(Signoff(ticket=ticket, version=version, outcome=outcome,
                       note=item.get('note', ''), actor=actor))
        accepted += 1
    try:
        db.flush()
    except IntegrityError as exc:
        raise BusinessError('有相同版本的签认刚刚写入，请刷新后重试', 409) from exc
    after = effective_signoffs(db)
    changes = []
    for ticket in {item['ticket'] for item in items}:
        payload = observations.get(ticket)
        if payload is None:
            continue
        old = resolve_outcome(payload, before.get(ticket))
        new = resolve_outcome(payload, after.get(ticket))
        if old != new:
            changes.append({'ticket': ticket, 'from': old, 'to': new})
    if accepted:
        db.add(AuditEvent(actor=actor, action='signoff.recorded',
                          detail=f'补录 {accepted} 条签认，有效变更 {len(changes)} 张色卡'))
    return {'accepted': accepted, 'ignored': ignored, 'changes': changes}
