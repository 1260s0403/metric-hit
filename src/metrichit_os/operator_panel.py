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


def _entries(store: KnowledgeStore, kind: str, query: str) -> list[dict[str, object]]:
    return store.search(kind=kind, query=query) if query else store.list(kind=kind)


def _summary(items: list[dict[str, object]]) -> dict[str, object]:
    topics: dict[str, list[dict[str, object]]] = {}
    for item in items:
        topics.setdefault(str(item["topic"]), []).append(item)
    lines = ["# Выжимка", f"Найдено записей: {len(items)}"]
    for topic, topic_items in topics.items():
        lines.extend(("", f"## {topic}"))
        for item in topic_items:
            tags = ", ".join(item["tags"]) or "—"
            lines.extend((f"- {item['created_at']} — {item['topic']}", f"  - Теги: {tags}", "  - Текст:", f"    {item['text']}"))
    return {"count": len(items), "markdown": "\n".join(lines), "topics": topics}


def _action_plan(items: list[dict[str, object]], tasks: list[dict[str, object]]) -> dict[str, object]:
    entry_ids = {str(item["id"]) for item in items}
    related = [task for task in tasks if task["knowledge_entry_id"] in entry_ids]
    task_ids = {str(task["knowledge_entry_id"]) for task in related}
    groups = {status: [task for task in related if task["status"] == status] for status in ("open", "completed", "cancelled")}
    without_task = [item for item in items if item["id"] not in task_ids]
    labels = {"open": "Открытые связанные задачи", "completed": "Выполненные связанные задачи", "cancelled": "Отменённые связанные задачи"}
    lines = ["# План действий"]
    for status in ("open", "completed", "cancelled"):
        lines.extend(("", f"## {labels[status]}"))
        if groups[status]:
            lines.extend(f"- {task['created_at']} — {task['title']} ({task['id']})" for task in groups[status])
        else:
            lines.append("- Нет")
    lines.extend(("", "## Записи без задачи"))
    if without_task:
        lines.extend(f"- {item['created_at']} — {item['topic']} ({item['id']})" for item in without_task)
    else:
        lines.append("- Нет")
    return {**groups, "markdown": "\n".join(lines), "without_task": without_task}


def _page(token: str) -> str:
    return """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>MetricHit</title><style>
:root{color-scheme:dark}body{font:16px system-ui,sans-serif;max-width:960px;margin:28px auto;padding:0 18px;background:#101722;color:#e7edf6}button,input,textarea{font:inherit;padding:9px;border:1px solid #40516a;border-radius:6px;background:#182334;color:#e7edf6}button{cursor:pointer;background:#2266b3;border-color:#3c83d2}button:hover,button:focus{background:#2875ca;outline:2px solid #73aaf0;outline-offset:2px}textarea{width:100%;min-height:110px;box-sizing:border-box}input{box-sizing:border-box}input:focus,textarea:focus{outline:2px solid #73aaf0;border-color:#73aaf0}.tabs,.row,.actions{display:flex;gap:9px;margin:16px 0;flex-wrap:wrap}.tabs button.active{background:#4388d4}.tabs button{background:#23344b}.row input{flex:1;min-width:180px}.entry{border-top:1px solid #40516a;padding:16px 0}.meta{color:#a8b6c9;font-size:13px}.entry p{white-space:pre-wrap}.complete{background:#257553;border-color:#3b9b75}.cancel{background:#8d3e4b;border-color:#bb6070}.error{color:#ff9ca9}.result{color:#8ee0b9}.hidden{display:none}@media(max-width:600px){body{margin:16px auto;padding:0 12px}.tabs button,.row button,.row input{width:100%}}</style></head>
<body><h1>MetricHit</h1><div class="tabs"><button data-view="artem" class="active">Рекомендации Артёма</button><button data-view="idea">Мои идеи</button><button data-view="tasks">Задачи</button></div>
<div id="knowledge"><form id="add"><label>Тема<br><input name="topic" required></label><br><label>Текст<br><textarea name="text" required></textarea></label><br><label>Теги через запятую<br><input name="tags"></label><br><button>Добавить</button></form><div class="row"><input id="search" placeholder="Поиск по текущему разделу"><button id="find">Искать</button><button id="summary">Выжимка</button><button id="plan">План действий</button></div></div><div id="message" role="status"></div><section id="entries"></section><section id="output" class="hidden"><div class="actions"><button id="copy">Скопировать</button></div><pre id="markdown"></pre><div id="plan-items"></div></section>
<script>const token=""" + json.dumps(token) + """;let view='artem';const message=document.querySelector('#message'),entries=document.querySelector('#entries'),knowledge=document.querySelector('#knowledge');
async function api(path,options={}){const headers=Object.assign({},options.headers||{});if(options.method==='POST')headers['X-Operator-Token']=token;const r=await fetch(path,Object.assign({},options,{headers}));const body=await r.json();if(!r.ok)throw new Error(body.message);return body}function show(text,error=false){message.className=error?'error':'result';message.textContent=text}
function createTask(id){return api('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})})}function renderKnowledge(items){entries.replaceChildren();for(const item of items){const box=document.createElement('article');box.className='entry';const title=document.createElement('strong');title.textContent=item.topic;const meta=document.createElement('div');meta.className='meta';meta.textContent=`${item.created_at} · ${item.id}`;const text=document.createElement('p');text.textContent=item.text;const tags=document.createElement('div');tags.className='meta';tags.textContent=item.tags.join(', ');const task=document.createElement('button');task.textContent='Создать задачу';task.onclick=async()=>{try{const result=await createTask(item.id);show(`Задача: ${result.id}`)}catch(e){show(e.message,true)}};box.append(title,meta,text,tags,task);entries.append(box)}}
async function changeTask(id,status){try{await api(`/api/tasks/${encodeURIComponent(id)}/status`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});show('Статус задачи обновлён');load()}catch(e){show(e.message,true)}}function renderTasks(items){entries.replaceChildren();for(const item of items){const box=document.createElement('article');box.className='entry';const title=document.createElement('strong');title.textContent=item.title;const meta=document.createElement('div');meta.className='meta';meta.textContent=`${item.status} · ${item.created_at} · ${item.id}`;const source=document.createElement('div');source.textContent=`${item.source}: ${item.knowledge_topic}`;box.append(title,meta,source);if(item.status==='open'){const actions=document.createElement('div');actions.className='actions';for(const [label,status,className] of [['Выполнено','completed','complete'],['Отменить','cancelled','cancel']]){const button=document.createElement('button');button.textContent=label;button.className=className;button.onclick=()=>changeTask(item.id,status);actions.append(button)}box.append(actions)}entries.append(box)}}
const output=document.querySelector('#output'),markdown=document.querySelector('#markdown'),planItems=document.querySelector('#plan-items');async function report(type){try{const q=document.querySelector('#search').value;const result=await api(`/api/${type}?kind=${encodeURIComponent(view)}&query=${encodeURIComponent(q)}`);markdown.textContent=result.markdown;planItems.replaceChildren();if(type==='action-plan'){for(const item of result.without_task){const button=document.createElement('button');button.textContent=`Создать задачу: ${item.topic}`;button.onclick=async()=>{try{const task=await createTask(item.id);show(`Задача: ${task.id}`);report(type)}catch(e){show(e.message,true)}};planItems.append(button)}}output.classList.remove('hidden')}catch(e){show(e.message,true)}}async function load(){try{if(view==='tasks'){renderTasks(await api('/api/tasks'));return}const q=document.querySelector('#search').value;renderKnowledge(await api(`/api/entries?kind=${encodeURIComponent(view)}&query=${encodeURIComponent(q)}`))}catch(e){show(e.message,true)}}document.querySelectorAll('[data-view]').forEach(button=>button.onclick=()=>{view=button.dataset.view;knowledge.classList.toggle('hidden',view==='tasks');output.classList.add('hidden');document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('active',x===button));document.querySelector('#search').value='';load()});document.querySelector('#find').onclick=load;document.querySelector('#summary').onclick=()=>report('summary');document.querySelector('#plan').onclick=()=>report('action-plan');document.querySelector('#copy').onclick=async()=>{try{await navigator.clipboard.writeText(markdown.textContent);show('Скопировано')}catch(e){show('Не удалось скопировать',true)}};document.querySelector('#add').onsubmit=async event=>{event.preventDefault();const form=new FormData(event.target);try{await api('/api/entries',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:view,topic:form.get('topic'),text:form.get('text'),tags:form.get('tags')})});event.target.reset();show('Запись добавлена');load()}catch(e){show(e.message,true)}};load();</script></body></html>"""


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
            return JSONResponse(_entries(store, kind, query))
        except KnowledgeError as error:
            return _error(str(error), 400)

    @app.get("/api/summary")
    def summary(kind: str, query: str = "") -> JSONResponse:
        try:
            return JSONResponse(_summary(_entries(store, kind, query)))
        except KnowledgeError as error:
            return _error(str(error), 400)

    @app.get("/api/action-plan")
    def action_plan(kind: str, query: str = "") -> JSONResponse:
        try:
            return JSONResponse(_action_plan(_entries(store, kind, query), store.list_tasks()))
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

    @app.get("/api/tasks")
    def tasks() -> JSONResponse:
        return JSONResponse(store.list_tasks())

    @app.post("/api/tasks/{task_id}/status")
    async def change_task_status(task_id: str, request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token:
            return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json()
            return JSONResponse(store.set_task_status(task_id=task_id, status=_text(payload, "status")))
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
