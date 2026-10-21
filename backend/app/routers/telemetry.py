# Telemetria para Painel Cyber Core IA
import json, asyncio, re
from datetime import datetime
from typing import Dict, Optional
from fastapi import APIRouter, Request, HTTPException, Body
from fastapi.responses import JSONResponse
try:
    from sse_starlette.sse import EventSourceResponse
except Exception:
    EventSourceResponse = None

router = APIRouter(prefix='/api/telemetry', tags=['telemetry'])
_event_buffer = []
_max_buffer = 100
_sse_clients: Dict[str, asyncio.Queue] = {}
_metric_key = re.compile(r'^[a-z][a-z0-9_]{0,23}$')


def _agora_iso():
    return datetime.utcnow().isoformat() + 'Z'


def _sanitize_metrics(metrics):
    if not isinstance(metrics, list):
        return []
    result = []
    for item in metrics[:6]:
        if not isinstance(item, dict):
            continue
        key = item.get('key')
        if not isinstance(key, str) or not _metric_key.match(key):
            continue
        label = item.get('label') if isinstance(item.get('label'), str) else key
        value = item.get('value')
        if isinstance(value, bool):
            value = 'Sim' if value else 'Não'
        elif isinstance(value, (int, float)):
            value = str(value)
        elif not isinstance(value, str):
            continue
        label = label.strip()[:32] or key
        value = value.strip()[:40]
        if value:
            result.append({'key': key, 'label': label, 'value': value})
    return result


def _enqueue_event(agent, state, monitoring=None, analysis=None, activity='', result='', evidence='', observed_at=None, metrics=None):
    event = {
        'agent': agent,
        'state': state,
        'observedAt': observed_at or _agora_iso(),
        'monitoring': monitoring or {'state': 'waiting', 'task': ''},
        'analysis': analysis or {'state': 'waiting', 'task': ''},
        'activity': activity or '',
        'result': result or '',
        'evidence': evidence or '',
        'metrics': _sanitize_metrics(metrics),
    }
    _event_buffer.insert(0, event)
    if len(_event_buffer) > _max_buffer:
        _event_buffer.pop()
    for q in list(_sse_clients.values()):
        try:
            q.put_nowait(event)
        except Exception:
            pass
    return event


@router.post('/agent-event')
async def registrar_evento_agente(
    agent: str = Body(..., embed=True),
    state: str = Body(..., embed=True),
    monitoring: Optional[dict] = Body(None, embed=True),
    analysis: Optional[dict] = Body(None, embed=True),
    activity: str = Body('', embed=True),
    result: str = Body('', embed=True),
    evidence: str = Body('', embed=True),
    metrics: Optional[list] = Body(None, embed=True),
):
    if agent not in ('financeiro', 'sentinel', 'auditor', 'fiscal'):
        raise HTTPException(400, 'Agente invalido')
    if state not in ('running', 'idle', 'error', 'offline'):
        raise HTTPException(400, 'Estado invalido')
    ev = _enqueue_event(agent, state, monitoring, analysis, activity, result, evidence, metrics=metrics)
    return JSONResponse({'status': 'ok', 'event': ev})


@router.get('/stream')
async def stream_telemetria(request: Request):
    if EventSourceResponse is None:
        raise HTTPException(500, 'sse-starlette nao instalado')
    cid = str(id(request))
    q: asyncio.Queue = asyncio.Queue()
    _sse_clients[cid] = q

    async def gen():
        try:
            for evt in list(_event_buffer)[:10]:
                yield {'event': 'telemetry', 'data': json.dumps(evt, ensure_ascii=False)}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), 30)
                    yield {'event': 'telemetry', 'data': json.dumps(ev, ensure_ascii=False)}
                except asyncio.TimeoutError:
                    yield {'event': 'heartbeat', 'data': '{}'}
        finally:
            _sse_clients.pop(cid, None)

    return EventSourceResponse(gen())


@router.get('/recentes')
async def eventos_recentes(limite: int = 20):
    limite = max(1, min(limite, _max_buffer))
    return JSONResponse({'eventos': _event_buffer[:limite], 'total': len(_event_buffer)})
