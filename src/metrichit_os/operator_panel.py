from __future__ import annotations

import json
import re
import secrets
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .config import CURRENT_CONTEXT
from .database import read_only_database
from .knowledge_store import KnowledgeError, KnowledgeStore


LOCAL_HOST = "127.0.0.1"
TOKEN_HEADER = "X-Operator-Token"


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": "operator_panel_error", "message": message}, status_code=status_code)


def _entries(store: KnowledgeStore, kind: str, query: str) -> list[dict[str, object]]:
    normalized = "idea" if kind in {"idea", "owner_idea"} else "artem"
    return store.search(kind=normalized, query=query) if query else store.list(kind=normalized)


def _summary(items: list[dict[str, object]]) -> dict[str, object]:
    topics: dict[str, int] = {}
    theses: list[str] = []
    seen: set[str] = set()
    for item in items:
        topic = str(item["topic"])
        topics[topic] = topics.get(topic, 0) + 1
        thesis = _short_text(str(item["text"])) or topic
        key = thesis.casefold()
        if key not in seen and len(theses) < 10:
            seen.add(key)
            theses.append(thesis)
    lines = ["# Выжимка", f"Записей: {len(items)}", "", "## Ключевые тезисы"]
    lines.extend(f"- {thesis}" for thesis in theses) or lines.append("- Нет")
    lines.extend(("", "## Основные темы"))
    lines.extend(f"- {topic} — {count}" for topic, count in sorted(topics.items(), key=lambda pair: (-pair[1], pair[0]))) or lines.append("- Нет")
    return {"count": len(items), "markdown": "\n".join(lines), "topics": topics, "theses": theses}


def _short_text(text: str, limit: int = 220) -> str:
    normalized = " ".join(text.split())
    sentence = re.split(r"(?<=[.!?])\s+", normalized, maxsplit=1)[0]
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"


def _action_plan(items: list[dict[str, object]], tasks: list[dict[str, object]]) -> dict[str, object]:
    entry_ids = {str(item["id"]) for item in items}
    related = [task for task in tasks if task["knowledge_entry_id"] in entry_ids]
    task_ids = {str(task["knowledge_entry_id"]) for task in related}
    groups = {status: [task for task in related if task["status"] == status] for status in ("open", "completed", "cancelled")}
    without_task = [item for item in items if item["id"] not in task_ids]
    labels = {"open": "Открытые связанные задачи", "completed": "Выполненные связанные задачи", "cancelled": "Отменённые связанные задачи"}
    lines = ["# План действий", "", "## Сделать сейчас"]
    if groups["open"]:
        for number, task in enumerate(groups["open"], 1):
            lines.extend((f"{number}. {task['title']}", f"   {_short_text(str(task['description']))}"))
    else:
        lines.append("- Нет открытых задач")
    lines.extend(("", "## Уже в работе"))
    if groups["open"]:
        lines.extend(f"- {task['title']} — {_short_text(str(task['description']))}" for task in groups["open"])
    else:
        lines.append("- Нет")
    lines.extend(("", "## Можно превратить в задачи"))
    if without_task:
        lines.extend(f"- {item['topic']} — {_short_text(str(item['text']))}" for item in without_task)
    else:
        lines.append("- Нет")
    lines.extend(("", "## Завершено", f"- {len(groups['completed'])} задач", "", "## Отменено", f"- {len(groups['cancelled'])} задач"))
    return {**groups, "markdown": "\n".join(lines), "without_task": without_task}


def _memory_items(database_path: Path, query: str) -> list[dict[str, object]]:
    pattern = f"%{query.strip()}%"
    with read_only_database(database_path) as database:
        rows = database.execute(
            """
            SELECT semantic_key, title, content, updated_at, version FROM memory_items
            WHERE status='active' AND (?='' OR semantic_key LIKE ? OR title LIKE ? OR content LIKE ?)
            ORDER BY updated_at DESC, semantic_key ASC
            """,
            (query.strip(), pattern, pattern, pattern),
        ).fetchall()
    return [dict(row) for row in rows]


def _decisions(database_path: Path, query: str) -> list[dict[str, object]]:
    pattern = f"%{query.strip()}%"
    with read_only_database(database_path) as database:
        rows = database.execute(
            """
            SELECT title, content, updated_at, version FROM decisions
            WHERE status='active' AND (?='' OR title LIKE ? OR content LIKE ?)
            ORDER BY updated_at DESC, title ASC
            """,
            (query.strip(), pattern, pattern),
        ).fetchall()
    return [dict(row) for row in rows]


def _current_context() -> dict[str, object]:
    content = CURRENT_CONTEXT.read_text(encoding="utf-8")
    return {"content": content}


def _page(token: str, focus_task: str | None = None) -> str:
    return """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>MetricHit</title><style>
 :root{color-scheme:dark}body{font:16px system-ui,sans-serif;max-width:960px;margin:28px auto;padding:0 18px;background:#101722;color:#e7edf6}button,input,textarea{font:inherit;padding:9px;border:1px solid #40516a;border-radius:6px;background:#182334;color:#e7edf6}button{cursor:pointer;background:#2266b3;border-color:#3c83d2}button:hover,button:focus{background:#2875ca;outline:2px solid #73aaf0;outline-offset:2px}textarea{width:100%;min-height:110px;box-sizing:border-box}input{box-sizing:border-box}input:focus,textarea:focus{outline:2px solid #73aaf0;border-color:#73aaf0}.tabs,.row,.actions{display:flex;gap:9px;margin:16px 0;flex-wrap:wrap}.tabs button.active{background:#4388d4}.tabs button{background:#23344b}.row input{flex:1;min-width:180px}.entry{border-top:1px solid #40516a;padding:16px 0}.meta{color:#a8b6c9;font-size:13px}.entry p,pre{white-space:pre-wrap;overflow-wrap:anywhere}.complete{background:#257553;border-color:#3b9b75}.cancel{background:#8d3e4b;border-color:#bb6070}.error{color:#ff9ca9}.result{color:#8ee0b9}.hidden{display:none}@media(max-width:600px){body{margin:16px auto;padding:0 12px}.tabs button,.row button,.row input{width:100%}}</style></head>
<style>.entry:target,.entry.task-focused{border:3px solid #38c7d4;background:#123745;box-shadow:0 0 0 4px #1a6474}.focus-label{color:#8ee0ff}.modal-card{background:#182334;border:2px solid #4388d4;border-radius:10px;width:min(760px,92vw);max-height:85vh;overflow:auto;padding:20px;position:relative}.modal-card #modal-close{position:absolute;right:12px;top:10px;font-size:24px}.modal-card pre{overflow-wrap:anywhere;white-space:pre-wrap}#output{position:fixed;inset:0;background:#000a;display:grid;place-items:center;z-index:10;padding:16px}#output.hidden{display:none}</style><script>window.addEventListener('load',()=>focusCard())</script><body><h1>MetricHit</h1><div class="tabs"><button data-view="artem" class="active">Рекомендации Артёма</button><button data-view="idea">Мои идеи</button><button data-view="tasks">Задачи</button><button data-view="memory">Память</button></div>
<div id="knowledge"><form id="add"><label>Тема<br><input name="topic" required></label><br><label>Текст<br><textarea name="text" required></textarea></label><br><label>Теги через запятую<br><input name="tags"></label><br><button>Добавить</button></form><div class="row"><input id="search" placeholder="Поиск по текущему разделу"><button id="find">Искать</button><button id="summary">Выжимка</button><button id="plan">План действий</button></div></div><section id="memory" class="hidden"><div class="tabs"><button data-memory="context" class="active">Текущий контекст</button><button data-memory="facts">Факты</button><button data-memory="decisions">Решения</button></div><div class="row" id="memory-search-row"><input id="memory-search" placeholder="Поиск"><button id="memory-find">Искать</button></div><div class="actions"><button id="memory-copy">Скопировать Markdown</button></div><pre id="memory-context"></pre><section id="memory-items"></section></section><div id="message" role="status"></div><section id="entries"></section><section id="output" class="hidden" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-card"><button id="modal-close" aria-label="Закрыть">×</button><h2 id="modal-title"></h2><div class="actions"><button id="copy">Копировать</button></div><pre id="markdown"></pre><div id="plan-items"></div></div></section>
<script>const requestedFocus=new URLSearchParams(location.search).get('focus_task');let focusAttempts=0;function focusCard(){const card=requestedFocus&&document.querySelector(`#task-${requestedFocus}`);if(card){card.classList.add('task-focused');if(!card.querySelector('.focus-label')){const label=document.createElement('div');label.className='focus-label';label.textContent='Открытая задача';card.prepend(label)}card.scrollIntoView({behavior:'smooth',block:'center'});return}if(requestedFocus&&focusAttempts++<30)setTimeout(focusCard,100)}setTimeout(()=>{const modal=document.querySelector('#output'),close=document.querySelector('#modal-close'),title=document.querySelector('#modal-title');let trigger;const hide=()=>{modal.classList.add('hidden');document.body.style.overflow='';trigger?.focus()};close.onclick=hide;modal.onclick=e=>{if(e.target===modal)hide()};document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!modal.classList.contains('hidden'))hide()});const original=report;report=async type=>{trigger=document.activeElement;await original(type);title.textContent=type==='summary'?'Выжимка':'План действий';document.body.style.overflow='hidden';close.focus()};},0)</script><script>const token=""" + json.dumps(token) + """;const focusTask=""" + json.dumps(focus_task) + """;let view=focusTask?'tasks':'artem';const message=document.querySelector('#message'),entries=document.querySelector('#entries'),knowledge=document.querySelector('#knowledge');
async function api(path,options={}){const headers=Object.assign({},options.headers||{});if(options.method==='POST')headers['X-Operator-Token']=token;const r=await fetch(path,Object.assign({},options,{headers}));const body=await r.json();if(!r.ok)throw new Error(body.message);return body}function show(text,error=false){message.className=error?'error':'result';message.textContent=text}
function createTask(id){return api('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})})}function openTask(id){location.href=`/?view=tasks&focus_task=${encodeURIComponent(id)}#task-${id}`}function taskFeedback(holder,result){holder.replaceChildren();const text=document.createElement('span');text.className='result';text.textContent=result.created?'Задача создана':'Задача уже создана';const open=document.createElement('a');open.href=`/?view=tasks&focus_task=${encodeURIComponent(result.id)}#task-${result.id}`;open.textContent='Открыть задачу';holder.append(text,open)}function renderKnowledge(items){entries.replaceChildren();for(const item of items){const box=document.createElement('article');box.className='entry';const title=document.createElement('strong');title.textContent=item.topic;const meta=document.createElement('div');meta.className='meta';meta.textContent=`${item.created_at} · ${item.id}`;const text=document.createElement('p');text.textContent=item.text;const tags=document.createElement('div');tags.className='meta';tags.textContent=item.tags.join(', ');const holder=document.createElement('div');holder.className='actions';if(item.task){taskFeedback(holder,{...item.task,created:false})}else{const task=document.createElement('button');task.textContent='Создать задачу';task.onclick=async()=>{task.disabled=true;try{taskFeedback(holder,await createTask(item.id))}catch(e){task.disabled=false;const error=document.createElement('span');error.className='error';error.textContent=e.message;holder.append(error)}};holder.append(task)}box.append(title,meta,text,tags,holder);entries.append(box)}}
async function changeTask(id,status){try{await api(`/api/tasks/${encodeURIComponent(id)}/status`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});load()}catch(e){show(e.message,true)}}function renderTasks(items){entries.replaceChildren();for(const item of items){const box=document.createElement('article');box.id=`task-${item.id}`;box.className='entry';const title=document.createElement('strong');title.textContent=item.display_title;const meta=document.createElement('div');meta.className='meta';meta.textContent=`${item.status} · ${item.created_at}`;const description=document.createElement('p');description.textContent=item.description.slice(0,160)+(item.description.length>160?'…':'');const source=document.createElement('div');source.textContent=item.source;const details=document.createElement('div');details.className='hidden';const full=document.createElement('p');full.textContent=item.description;const origin=document.createElement('div');origin.textContent=`${item.source}: ${item.knowledge_topic}`;const uuid=document.createElement('div');uuid.className='meta';uuid.textContent=item.id;details.append(full,origin,uuid);const toggle=document.createElement('button');toggle.textContent='Подробнее';toggle.onclick=()=>details.classList.toggle('hidden');box.append(title,meta,description,source,toggle,details);if(item.status==='open'){const actions=document.createElement('div');actions.className='actions';for(const [label,status,className] of [['Выполнено','completed','complete'],['Отменить','cancelled','cancel']]){const button=document.createElement('button');button.textContent=label;button.className=className;button.onclick=()=>changeTask(item.id,status);actions.append(button)}details.append(actions)}entries.append(box)}}
const output=document.querySelector('#output'),markdown=document.querySelector('#markdown'),planItems=document.querySelector('#plan-items'),memory=document.querySelector('#memory'),memoryContext=document.querySelector('#memory-context'),memoryItems=document.querySelector('#memory-items'),memorySearch=document.querySelector('#memory-search'),memorySearchRow=document.querySelector('#memory-search-row');let memoryView='context';async function report(type){try{const q=document.querySelector('#search').value;const result=await api(`/api/${type}?kind=${encodeURIComponent(view)}&query=${encodeURIComponent(q)}`);markdown.textContent=result.markdown;planItems.replaceChildren();if(type==='action-plan'){for(const item of result.without_task){const button=document.createElement('button');button.textContent=`Создать задачу: ${item.topic}`;button.onclick=async()=>{try{const task=await createTask(item.id);button.disabled=true;button.textContent=task.created?'Задача создана':'Задача уже существует';const open=document.createElement('button');open.textContent='Открыть задачу';open.onclick=()=>openTask(task.id);button.after(open)}catch(e){const error=document.createElement('span');error.className='error';error.textContent=e.message;button.after(error)}};planItems.append(button)}}output.classList.remove('hidden')}catch(e){show(e.message,true)}}function renderMemory(items){memoryItems.replaceChildren();for(const item of items){const box=document.createElement('article');box.className='entry';const title=document.createElement('strong');title.textContent=item.title;const meta=document.createElement('div');meta.className='meta';meta.textContent=`${item.updated_at} · версия ${item.version}`;const content=document.createElement('p');content.textContent=item.content;box.append(title,meta,content);if(item.semantic_key){const key=document.createElement('div');key.className='meta';key.textContent=item.semantic_key;box.prepend(key)}memoryItems.append(box)}}async function loadMemory(){try{memoryContext.classList.toggle('hidden',memoryView!=='context');memoryItems.replaceChildren();memorySearchRow.classList.toggle('hidden',memoryView==='context');if(memoryView==='context'){const result=await api('/api/memory/context');memoryContext.textContent=result.content;return}const result=await api(`/api/memory/${memoryView}?query=${encodeURIComponent(memorySearch.value)}`);renderMemory(result)}catch(e){show(e.message,true)}}async function load(){try{if(view==='memory'){await loadMemory();return}if(view==='tasks'){renderTasks(await api('/api/tasks'));return}const q=document.querySelector('#search').value;renderKnowledge(await api(`/api/entries?kind=${encodeURIComponent(view)}&query=${encodeURIComponent(q)}`))}catch(e){show(e.message,true)}}document.querySelectorAll('[data-view]').forEach(button=>button.onclick=()=>{view=button.dataset.view;knowledge.classList.toggle('hidden',view==='tasks'||view==='memory');memory.classList.toggle('hidden',view!=='memory');entries.classList.toggle('hidden',view==='memory');output.classList.add('hidden');document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('active',x===button));document.querySelector('#search').value='';load()});document.querySelectorAll('[data-memory]').forEach(button=>button.onclick=()=>{memoryView=button.dataset.memory;document.querySelectorAll('[data-memory]').forEach(x=>x.classList.toggle('active',x===button));memorySearch.value='';loadMemory()});document.querySelector('#find').onclick=load;document.querySelector('#memory-find').onclick=loadMemory;document.querySelector('#summary').onclick=()=>report('summary');document.querySelector('#plan').onclick=()=>report('action-plan');document.querySelector('#copy').onclick=async()=>{try{await navigator.clipboard.writeText(markdown.textContent);show('Скопировано')}catch(e){show('Не удалось скопировать',true)}};document.querySelector('#memory-copy').onclick=async()=>{try{await navigator.clipboard.writeText(memoryContext.textContent);show('Скопировано')}catch(e){show('Не удалось скопировать',true)}};document.querySelector('#add').onsubmit=async event=>{event.preventDefault();const form=new FormData(event.target);try{await api('/api/entries',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:view,topic:form.get('topic'),text:form.get('text'),tags:form.get('tags')})});event.target.reset();show('Запись добавлена');load()}catch(e){show(e.message,true)}};load();</script></body></html>"""


def create_operator_app(database_path: Path) -> FastAPI:
    store = KnowledgeStore(database_path)
    token = secrets.token_urlsafe(32)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/", response_class=HTMLResponse)
    def page(request: Request, focus_task: str | None = None) -> str:
        focused = focus_task if focus_task and any(task["id"] == focus_task for task in store.list_tasks()) else None
        return _page(token, focused)

    @app.get("/api/entries")
    def entries(kind: str, query: str = "") -> JSONResponse:
        try:
            tasks = {task["knowledge_entry_id"]: task for task in store.list_tasks()}
            items = _entries(store, kind, query)
            return JSONResponse([{**item, "task": tasks.get(item["id"])} for item in items])
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

    @app.get("/api/memory/context")
    def memory_context() -> JSONResponse:
        return JSONResponse(_current_context())

    @app.get("/api/memory/facts")
    def memory_facts(query: str = "") -> JSONResponse:
        return JSONResponse(_memory_items(database_path, query))

    @app.get("/api/memory/decisions")
    def memory_decisions(query: str = "") -> JSONResponse:
        return JSONResponse(_decisions(database_path, query))

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
            entry_id = _text(payload, "id")
            existing = store.task_for_entry(entry_id)
            item = existing or store.to_task(entry_id=entry_id, title=_optional_text(payload, "title"))
            item["created"] = existing is None
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
