from __future__ import annotations

import json
import secrets
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .knowledge_store import KnowledgeError, KnowledgeStore


LOCAL_HOST = "127.0.0.1"
TOKEN_HEADER = "X-Operator-Token"


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": "operator_panel_error", "message": message}, status_code=status_code)


def _page(token: str) -> str:
    return """<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>MetricHit — знания</title><style>
body{font:16px system-ui,sans-serif;max-width:920px;margin:32px auto;padding:0 16px;color:#17212b}button,input,textarea{font:inherit;padding:8px}textarea{width:100%;min-height:110px;box-sizing:border-box}.tabs{display:flex;gap:8px;margin:16px 0}.tabs button.active{font-weight:700}.entry{border-top:1px solid #ddd;padding:14px 0}.meta{color:#667;font-size:13px}.entry p{white-space:pre-wrap}.row{display:flex;gap:8px;margin:12px 0}.row input{flex:1}.error{color:#a22}.result{color:#176b32}</style></head>
<body><h1>Знания MetricHit</h1><div class="tabs"><button data-kind="artem" class="active">Рекомендации Артёма</button><button data-kind="idea">Мои идеи</button></div>
<form id="add"><label>Тема<br><input name="topic" required></label><br><label>Текст<br><textarea name="text" required></textarea></label><br><label>Теги через запятую<br><input name="tags"></label><br><button>Добавить</button></form>
<div class="row"><input id="search" placeholder="Поиск по текущему разделу"><button id="find">Искать</button></div><div id="message" role="status"></div><section id="entries"></section>
<script>const token=""" + json.dumps(token) + """;let kind='artem';const message=document.querySelector('#message'),entries=document.querySelector('#entries');
async function api(path,options={}){const headers=Object.assign({},options.headers||{});if(options.method==='POST')headers['X-Operator-Token']=token;const r=await fetch(path,Object.assign({},options,{headers}));const body=await r.json();if(!r.ok)throw new Error(body.message);return body}
function render(items){entries.replaceChildren();for(const item of items){const box=document.createElement('article');box.className='entry';const title=document.createElement('strong');title.textContent=item.topic;const meta=document.createElement('div');meta.className='meta';meta.textContent=`${item.created_at} · ${item.id}`;const text=document.createElement('p');text.textContent=item.text;const tags=document.createElement('div');tags.className='meta';tags.textContent=item.tags.join(', ');const task=document.createElement('button');task.textContent='Создать задачу';task.onclick=async()=>{try{const result=await api('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:item.id})});show(`Задача: ${result.id}`)}catch(e){show(e.message,true)}};box.append(title,meta,text,tags,task);entries.append(box)}}
function show(text,error=false){message.className=error?'error':'result';message.textContent=text}async function load(){try{const q=document.querySelector('#search').value;render(await api(`/api/entries?kind=${encodeURIComponent(kind)}&query=${encodeURIComponent(q)}`))}catch(e){show(e.message,true)}}
document.querySelectorAll('[data-kind]').forEach(button=>button.onclick=()=>{kind=button.dataset.kind;document.querySelectorAll('[data-kind]').forEach(x=>x.classList.toggle('active',x===button));document.querySelector('#search').value='';load()});document.querySelector('#find').onclick=load;
document.querySelector('#add').onsubmit=async event=>{event.preventDefault();const form=new FormData(event.target);try{await api('/api/entries',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind,topic:form.get('topic'),text:form.get('text'),tags:form.get('tags')})});event.target.reset();show('Запись добавлена');load()}catch(e){show(e.message,true)}};load();</script></body></html>"""


def create_operator_app(database_path: Path) -> FastAPI:
    store = KnowledgeStore(database_path)
    token = secrets.token_urlsafe(32)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/", response_class=HTMLResponse)
    def page() -> str:
        return _page(token)

    @app.get("/api/entries")
    def entries(kind: str, query: str = "") -> JSONResponse:
        try:
            items = store.search(kind=kind, query=query) if query else store.list(kind=kind)
            return JSONResponse(items)
        except KnowledgeError as error:
            return _error(str(error), 400)

    @app.post("/api/entries")
    async def add_entry(request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token:
            return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json()
            item = store.add(
                kind=_text(payload, "kind"), topic=_text(payload, "topic"), text=_text(payload, "text"),
                tags=_optional_text(payload, "tags"),
            )
            return JSONResponse(item, status_code=201)
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error:
            return _error(str(error), 400)

    @app.post("/api/tasks")
    async def add_task(request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token:
            return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json()
            item = store.to_task(entry_id=_text(payload, "id"), title=_optional_text(payload, "title"))
            return JSONResponse(item)
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error:
            return _error(str(error), 400)

    return app


def _text(payload: object, key: str) -> str:
    if not isinstance(payload, dict) or not isinstance(payload.get(key), str):
        raise KnowledgeError(f"{key} must be a string")
    return payload[key]


def _optional_text(payload: object, key: str) -> str | None:
    if not isinstance(payload, dict) or payload.get(key) is None:
        return None
    if not isinstance(payload[key], str):
        raise KnowledgeError(f"{key} must be a string")
    return payload[key]


def run_operator_panel(database_path: Path, *, port: int, host: str = LOCAL_HOST) -> None:
    if host != LOCAL_HOST:
        raise ValueError("operator panel may only listen on 127.0.0.1")
    if not 1 <= port <= 65535:
        raise ValueError("port must be between 1 and 65535")
    uvicorn.run(create_operator_app(database_path), host=host, port=port)
