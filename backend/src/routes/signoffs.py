from fastapi import APIRouter, Depends
from fastapi.responses import Response
from sqlalchemy import select

from src.config.project import SPEC
from src.constants.enums import QueueStatus, Role
from src.controllers.views import queue_row_view, queue_view, signoff_view
from src.models.base import Session
from src.models.workflow import QueueRow, SamplingQueue
from src.schemas.requests import RecomputeInput, SignoffBatch
from src.services.auth import current_user, roles
from src.services.broker import wake_worker
from src.services.errors import BusinessError
from src.services.queues import active_queue, latest_queue, request_recompute
from src.services.signoffs import effective_signoffs, submit_signoffs
from src.utils.formatting import csv_text

router = APIRouter(prefix='/api')


@router.get('/signoffs')
def list_signoffs(user=Depends(current_user)):
    with Session() as db:
        latest = effective_signoffs(db)
        return [signoff_view(item) for ticket, item in sorted(latest.items())]


@router.post('/signoffs', status_code=201)
def record_signoffs(payload: SignoffBatch, user=Depends(roles(Role.SUPERVISOR))):
    with Session.begin() as db:
        report = submit_signoffs(db, [item.model_dump() for item in payload.items], user['sub'])
        if report['changes']:
            item = request_recompute(db, [change['ticket'] for change in report['changes']],
                                     reason='签认变更后重算', actor=user['sub'])
            report['queue'] = queue_view(item)
    wake_worker()
    return report


@router.get('/queues')
def index(user=Depends(current_user)):
    with Session() as db:
        current = active_queue(db)
        pending = latest_queue(db, QueueStatus.QUEUED, QueueStatus.COMPUTING, QueueStatus.READY)
        return {'active': queue_view(current) if current else None,
                'incoming': queue_view(pending) if pending else None}


@router.post('/queues/rebuild', status_code=201)
def rebuild(payload: RecomputeInput, user=Depends(roles(Role.SUPERVISOR))):
    with Session.begin() as db:
        item = request_recompute(db, [], reason=payload.reason, parameters=payload.parameters,
                                 actor=user['sub'])
        view = queue_view(item)
    wake_worker()
    return view


@router.get('/queues/active/export')
def export_active(user=Depends(current_user)):
    with Session() as db:
        item = active_queue(db)
        if item is None or not item.result:
            raise BusinessError('当前没有可下载的抽查队列', 409)
        columns, rows = item.result['columns'], item.result['rows']
        file = f'{SPEC["slug"]}-queue-r{item.revision}.csv'
        return Response(csv_text(columns, rows), media_type='text/csv',
                        headers={'Content-Disposition': f'attachment; filename={file}'})


@router.get('/queues/{queue_id}')
def detail(queue_id: int, user=Depends(current_user)):
    with Session() as db:
        item = db.get(SamplingQueue, queue_id)
        if item is None:
            raise BusinessError('抽查队列不存在', 404)
        rows = db.scalars(select(QueueRow).where(QueueRow.queue_id == queue_id).order_by(QueueRow.id))
        return queue_view(item, include_result=True) | {'rows': [queue_row_view(row) for row in rows]}
