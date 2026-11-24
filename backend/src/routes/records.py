from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response
from sqlalchemy import func, select
from starlette.concurrency import run_in_threadpool

from src.config.project import SPEC
from src.constants.enums import Role
from src.controllers.views import observation_view
from src.models.base import Session
from src.models.workflow import Observation
from src.services.auth import current_user, roles
from src.services.errors import BusinessError
from src.services.observations import add_observations, clean_observation, parse_csv
from src.services.broker import wake_worker
from src.services.queues import request_recompute_if_stale
from src.utils.formatting import csv_text

router = APIRouter(prefix='/api')
editor = roles(Role.ANALYST, Role.SUPERVISOR)


@router.get('/spec')
def spec():
    return SPEC


@router.get('/observations')
def index(offset: int = Query(0, ge=0), limit: int = Query(20, ge=1, le=100), user=Depends(current_user)):
    with Session() as db:
        total = db.scalar(select(func.count(Observation.id)))
        items = db.scalars(select(Observation).order_by(Observation.id.desc()).offset(offset).limit(limit))
        return {'total': total, 'offset': offset, 'items': [observation_view(item) for item in items]}


@router.post('/observations', status_code=201)
def create(payload: dict, user=Depends(editor)):
    row = clean_observation(payload)
    with Session.begin() as db:
        items = add_observations(db, [row], user['sub'], 'observation.created')
        if not items:
            raise BusinessError('相同观测已存在，请核对记录', 409)
        request_recompute_if_stale(db, reason='新观测影响队列', actor=user['sub'])
        view = observation_view(items[0])
    wake_worker()
    return view


@router.get('/observations/template')
def template(user=Depends(current_user)):
    fields = SPEC['fields']
    payload = csv_text([{'key': field['key'], 'label': field['key']} for field in fields],
                       [{field['key']: field.get('example') for field in fields}])
    return Response(payload, media_type='text/csv', headers={'Content-Disposition': f'attachment; filename={SPEC["slug"]}-template.csv'})


def import_payload(payload, actor):
    rows = parse_csv(payload)
    with Session.begin() as db:
        items = add_observations(db, rows, actor, 'observation.imported')
        request_recompute_if_stale(db, reason='导入观测影响队列', actor=actor)
        return {'added': len(items), 'skipped': len(rows) - len(items)}


@router.post('/observations/import')
async def import_csv(request: Request, user=Depends(editor)):
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > 512 * 1024:
            raise BusinessError('CSV 文件上限 512 KB', 413)
        raw.extend(chunk)
    report = await run_in_threadpool(import_payload, bytes(raw), user['sub'])
    wake_worker()
    return report
