from src.utils.formatting import timestamp


def review_view(item):
    return {'decision': item.decision, 'note': item.note, 'reviewer': item.reviewer,
            'at': timestamp(item.created_at)} if item else None


def run_view(item, review=None, *, include_result=False):
    view = {'id': item.id, 'title': item.title, 'owner': item.owner, 'status': item.status,
            'parameters': item.parameters, 'sample_size': item.sample_size,
            'snapshot_id': item.last_observation_id, 'created_at': timestamp(item.created_at),
            'finished_at': timestamp(item.finished_at), 'review': review_view(review), 'error': item.error}
    if include_result:
        view['result'] = item.result
    return view


def observation_view(item):
    return {'id': item.id, 'data': item.payload, 'created_at': timestamp(item.created_at)}


def signoff_view(item):
    return {'id': item.id, 'ticket': item.ticket, 'version': item.version, 'outcome': item.outcome,
            'note': item.note, 'actor': item.actor, 'received_at': timestamp(item.received_at)}


def queue_row_view(item):
    return {'ticket': item.ticket, 'lot': item.lot, 'day': item.day, 'status': item.status,
            'error': item.error, 'result': item.payload}


def queue_view(item, *, include_result=False):
    view = {'id': item.id, 'revision': item.revision, 'status': item.status,
            'parameters': item.parameters, 'total': item.total, 'computed': item.computed,
            'changed_tickets': item.changed_tickets, 'held_tickets': item.held_tickets,
            'reason': item.reason, 'created_at': timestamp(item.created_at),
            'ready_at': timestamp(item.ready_at), 'activated_at': timestamp(item.activated_at)}
    if item.status in ('queued', 'computing'):
        view['progress'] = item.computed / item.total if item.total else 0
    if include_result:
        view['result'] = item.result
    return view


def schedule_view(item):
    return {'id': item.id, 'mode': item.mode, 'run_id': item.run_id, 'recipient': item.recipient,
            'interval_minutes': item.interval_minutes, 'next_at': timestamp(item.next_at),
            'active': item.active}


def delivery_view(delivery, schedule, queue=None):
    return {'id': delivery.id, 'schedule_id': schedule.id, 'recipient': schedule.recipient,
            'mode': schedule.mode, 'run_id': schedule.run_id, 'queue_id': delivery.queue_id,
            'revision': queue.revision if queue else None,
            'at': timestamp(delivery.delivered_at), 'scheduled_at': timestamp(delivery.scheduled_at)}
