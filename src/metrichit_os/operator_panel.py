from __future__ import annotations

import json
import re
import secrets
import sqlite3
from datetime import date
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse

from .config import CURRENT_CONTEXT
from .activity import list_activity
from .database import read_only_database
from .global_search import search as global_search
from .knowledge_store import KnowledgeError, KnowledgeStore
from .project_store import ProjectStore


LOCAL_HOST = "127.0.0.1"
TOKEN_HEADER = "X-Operator-Token"


def _error(message: str, status_code: int) -> JSONResponse:
    return JSONResponse({"error": "operator_panel_error", "message": message}, status_code=status_code)


def _entries(store: KnowledgeStore, kind: str, query: str) -> list[dict[str, object]]:
    if kind not in {"artem", "idea"}:
        raise KnowledgeError("kind must be artem or idea")
    return store.search(kind=kind, query=query) if query else store.list(kind=kind)


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
            SELECT id, semantic_key, title, content, updated_at, version FROM memory_items
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
            SELECT id, title, content, updated_at, version FROM decisions
            WHERE status='active' AND (?='' OR title LIKE ? OR content LIKE ?)
            ORDER BY updated_at DESC, title ASC
            """,
            (query.strip(), pattern, pattern),
        ).fetchall()
    return [dict(row) for row in rows]


def _memory_documents(database_path: Path, query: str) -> list[dict[str, object]]:
    pattern = f"%{query.strip()}%"
    with read_only_database(database_path) as database:
        rows = database.execute(
            """
            SELECT id, title, content, updated_at, version FROM documents
            WHERE type!='knowledge_entry' AND status='active'
              AND (?='' OR title LIKE ? OR content LIKE ?)
            ORDER BY updated_at DESC, id ASC
            """,
            (query.strip(), pattern, pattern),
        ).fetchall()
    return [dict(row) for row in rows]


def _current_context() -> dict[str, object]:
    content = CURRENT_CONTEXT.read_text(encoding="utf-8")
    return {"content": content}


def _dashboard(store: KnowledgeStore, database_path: Path) -> dict[str, object]:
    """Build independent, read-only dashboard blocks without exposing raw tables."""
    result: dict[str, object] = {}
    try:
        open_tasks = store.list_tasks(status="open", sort="recommended")
        with read_only_database(database_path) as connection:
            project_names = {str(row["id"]): str(row["title"]) for row in connection.execute("SELECT id,title FROM documents WHERE type='project'")}
        for task in open_tasks:
            project_id = task.get("project_id")
            task["project_name"] = project_names.get(str(project_id)) if project_id else None
        today = date.today().isoformat()
        important = open_tasks[:5]
        result["tasks"] = {
            "open": len(open_tasks),
            "overdue": sum(1 for task in open_tasks if task["due_date"] and task["due_date"] < today),
            "today": sum(1 for task in open_tasks if task["due_date"] == today),
            "high": sum(1 for task in open_tasks if task["priority"] == "high"),
            "items": important,
            "overdue_items": [task for task in important if task["due_date"] and task["due_date"] < today],
            "today_items": [task for task in important if task["due_date"] == today],
            "high_items": [
                task for task in important
                if task["priority"] == "high" and (not task["due_date"] or task["due_date"] > today)
            ],
        }
    except (KnowledgeError, sqlite3.Error, ValueError):
        result["tasks"] = {"error": "Задачи временно недоступны."}
    for kind in ("artem", "idea"):
        try:
            result[kind] = {"items": store.list(kind=kind, limit=3)}
        except (KnowledgeError, sqlite3.Error):
            result[kind] = {"error": "Записи временно недоступны."}

    def count(sql: str) -> int | None:
        try:
            with read_only_database(database_path) as connection:
                return int(connection.execute(sql).fetchone()[0])
        except sqlite3.Error:
            return None

    memory = {
        "approved": count("SELECT count(*) FROM memory_items WHERE status='active'"),
        "pending": count("SELECT count(*) FROM memory_candidates WHERE status='pending'"),
        "conflicts": count("SELECT count(*) FROM memory_conflicts WHERE status='open'"),
        "sources": count("SELECT count(*) FROM sources"),
    }
    result["memory"] = memory if all(value is not None for value in memory.values()) else {
        "approved": "недоступно", "pending": "недоступно", "conflicts": "недоступно", "sources": "недоступно",
    }
    return result


def _page_raw(token: str, focus_task: str | None = None) -> str:
    return """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>MetricHit</title><style>
 :root{color-scheme:dark}body{font:16px system-ui,sans-serif;max-width:960px;margin:28px auto;padding:0 18px;background:#000;color:#e7edf6}h1{text-align:center;color:#8ee0b9}button,input,textarea{font:inherit;padding:9px;border:1px solid #40516a;border-radius:6px;background:#182334;color:#e7edf6}button{cursor:pointer;background:#2266b3;border-color:#3c83d2}button:hover,button:focus{background:#2875ca;outline:2px solid #73aaf0;outline-offset:2px}textarea{width:100%;min-height:110px;box-sizing:border-box}input{box-sizing:border-box}input:focus,textarea:focus{outline:2px solid #73aaf0;border-color:#73aaf0}.tabs,.row,.actions{display:flex;gap:9px;margin:16px 0;flex-wrap:wrap}.tabs button.active{background:#4388d4}.tabs button{background:#23344b}.row input{flex:1;min-width:180px}.entry{border-top:1px solid #40516a;padding:16px 0}.meta{color:#a8b6c9;font-size:13px}.entry p,pre{white-space:pre-wrap;overflow-wrap:anywhere}.complete{background:#257553;border-color:#3b9b75}.cancel{background:#8d3e4b;border-color:#bb6070}.error{color:#ff9ca9}.result{color:#8ee0b9}.hidden{display:none}.overview-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:14px}.overview-card{min-width:0;border:1px solid #40516a;border-radius:9px;padding:14px;background:#142031}.overview-card h2{font-size:18px;margin:0 0 8px}.overview-counts{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:8px}.overview-count{padding:8px;background:#182334;border-radius:6px}.overview-task{display:flex;gap:8px;justify-content:space-between;align-items:center;padding:8px 0;border-top:1px solid #40516a;min-width:0}.overview-task span{overflow-wrap:anywhere}.overview-task a{white-space:nowrap}.overview-empty{color:#a8b6c9}@media(max-width:600px){body{margin:16px auto;padding:0 12px}.tabs button,.row button,.row input{width:100%}.overview-grid{grid-template-columns:1fr}.overview-task{align-items:flex-start;flex-wrap:wrap}}</style></head>
<style>.entry:target,.entry.task-focused{border:3px solid #38c7d4;background:#123745;box-shadow:0 0 0 4px #1a6474}.focus-label{color:#8ee0ff}.modal-card{background:#182334;border:2px solid #4388d4;border-radius:10px;width:min(760px,92vw);max-height:85vh;overflow:auto;padding:20px;position:relative}.modal-card #modal-close{position:absolute;right:12px;top:10px;font-size:24px}.modal-card pre{overflow-wrap:anywhere;white-space:pre-wrap}#output{position:fixed;inset:0;background:#000a;display:grid;place-items:center;z-index:10;padding:16px}#output.hidden{display:none}</style><script>window.addEventListener('load',()=>focusCard())</script><body><h1>Yadro</h1><div class="tabs"><button data-view="overview" data-testid="tab-overview" class="active">Обзор</button><button data-view="artem" data-testid="tab-artem">Рекомендации Артёма</button><button data-view="idea" data-testid="tab-idea">Мои идеи</button><button data-view="tasks" data-testid="tab-tasks">Задачи</button><button data-view="memory" data-testid="tab-memory">Память</button></div><section id="overview" data-testid="overview-screen"></section>
<div id="knowledge" data-testid="knowledge-screen"><form id="add"><label>Тема<br><input name="topic" required></label><br><label>Текст<br><textarea name="text" required></textarea></label><br><label>Теги через запятую<br><input name="tags"></label><br><button data-testid="add-entry">Добавить</button></form><div class="row"><input id="search" data-testid="knowledge-search" placeholder="Поиск по текущему разделу"><button id="find" data-testid="knowledge-find">Искать</button><button id="summary" data-testid="summary">Выжимка</button><button id="plan" data-testid="action-plan">План действий</button></div></div><section id="memory" data-testid="memory-screen" class="hidden"><div class="tabs"><button data-memory="context" class="active">Текущий контекст</button><button data-memory="facts">Факты</button><button data-memory="decisions">Решения</button></div><div class="row" id="memory-search-row"><input id="memory-search" placeholder="Поиск"><button id="memory-find">Искать</button></div><div class="actions"><button id="memory-copy">Скопировать Markdown</button></div><pre id="memory-context"></pre><section id="memory-items"></section></section><div id="message" role="status"></div><section id="entries" data-testid="entries"></section><section id="output" data-testid="modal-overlay" class="hidden" role="dialog" aria-modal="true" aria-labelledby="modal-title"><div class="modal-card"><button id="modal-close" data-testid="modal-close" aria-label="Закрыть">×</button><h2 id="modal-title"></h2><div class="actions"><button id="copy" data-testid="modal-copy">Копировать</button></div><pre id="markdown" data-testid="modal-markdown"></pre><div id="plan-items"></div></div></section>
<script>const requestedFocus=new URLSearchParams(location.search).get('focus_task');let focusAttempts=0;function focusCard(){const card=requestedFocus&&document.querySelector(`#task-${requestedFocus}`);if(card){card.classList.add('task-focused');if(!card.querySelector('.focus-label')){const label=document.createElement('div');label.className='focus-label';label.textContent='Открытая задача';card.prepend(label)}card.scrollIntoView({behavior:'smooth',block:'center'});return}if(requestedFocus&&focusAttempts++<30)setTimeout(focusCard,100)}setTimeout(()=>{const modal=document.querySelector('#output'),close=document.querySelector('#modal-close'),title=document.querySelector('#modal-title');let trigger;const hide=()=>{modal.classList.add('hidden');document.body.style.overflow='';trigger?.focus()};close.onclick=hide;modal.onclick=e=>{if(e.target===modal)hide()};document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!modal.classList.contains('hidden'))hide()});const original=report;report=async type=>{trigger=document.activeElement;await original(type);title.textContent=type==='summary'?'Выжимка':'План действий';document.body.style.overflow='hidden';close.focus()};},0)</script><script>const token=""" + json.dumps(token) + """;const focusTask=""" + json.dumps(focus_task) + """;let view=focusTask?'tasks':'artem';const message=document.querySelector('#message'),entries=document.querySelector('#entries'),knowledge=document.querySelector('#knowledge');
async function api(path,options={}){const headers=Object.assign({},options.headers||{});if(options.method==='POST')headers['X-Operator-Token']=token;const r=await fetch(path,Object.assign({},options,{headers}));const body=await r.json();if(!r.ok)throw new Error(body.message);return body}function show(text,error=false){message.className=error?'error':'result';message.textContent=text}
function createTask(id){return api('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id})})}function openTask(id){location.href=`/?view=tasks&focus_task=${encodeURIComponent(id)}#task-${id}`}function taskFeedback(holder,result){holder.replaceChildren();const text=document.createElement('span');text.className='result';text.textContent=result.created?'Задача создана':'Задача уже создана';const open=document.createElement('a');open.href=`/?view=tasks&focus_task=${encodeURIComponent(result.id)}#task-${result.id}`;open.textContent='Открыть задачу';holder.append(text,open)}function renderKnowledge(items){entries.replaceChildren();for(const item of items){const box=document.createElement('article');box.className='entry';const title=document.createElement('strong');title.textContent=item.topic;const meta=document.createElement('div');meta.className='meta';meta.textContent=`${item.created_at} · ${item.id}`;const text=document.createElement('p');text.textContent=item.text;const tags=document.createElement('div');tags.className='meta';tags.textContent=item.tags.join(', ');const holder=document.createElement('div');holder.className='actions';if(item.task){taskFeedback(holder,{...item.task,created:false})}else{const task=document.createElement('button');task.textContent='Создать задачу';task.onclick=async()=>{task.disabled=true;try{taskFeedback(holder,await createTask(item.id))}catch(e){task.disabled=false;const error=document.createElement('span');error.className='error';error.textContent=e.message;holder.append(error)}};holder.append(task)}box.append(title,meta,text,tags,holder);entries.append(box)}}
async function changeTask(id,status){try{await api(`/api/tasks/${encodeURIComponent(id)}/status`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});load()}catch(e){show(e.message,true)}}function renderTasks(items){entries.replaceChildren();for(const item of items){const box=document.createElement('article');box.id=`task-${item.id}`;box.className='entry';if(item.id===focusTask)box.classList.add('task-focused');const title=document.createElement('strong');title.textContent=item.display_title;const meta=document.createElement('div');meta.className='meta';meta.textContent=`${item.status} · ${item.created_at}`;const details=document.createElement('div');details.className='hidden';const full=document.createElement('p');full.textContent=item.description;const origin=document.createElement('div');origin.textContent=`${item.source}: ${item.knowledge_topic}`;const date=document.createElement('div');date.className='meta';date.textContent=item.created_at;const uuid=document.createElement('div');uuid.className='meta';uuid.textContent=item.id;details.append(full,origin,date,uuid);const actions=document.createElement('div');actions.className='actions';const toggle=document.createElement('button');toggle.textContent='Подробнее';toggle.onclick=()=>{details.classList.toggle('hidden');toggle.textContent=details.classList.contains('hidden')?'Подробнее':'Скрыть'};actions.append(toggle);if(item.status==='open'){for(const [label,status,className] of [['Выполнено','completed','complete'],['Отменить','cancelled','cancel']]){const button=document.createElement('button');button.textContent=label;button.className=className;button.onclick=()=>changeTask(item.id,status);actions.append(button)}}if(item.id===focusTask){const label=document.createElement('div');label.className='focus-label';label.textContent='Открытая задача';box.append(label)}box.append(title,meta,actions,details);entries.append(box)}if(focusTask)setTimeout(focusCard,0)}
const output=document.querySelector('#output'),markdown=document.querySelector('#markdown'),planItems=document.querySelector('#plan-items'),memory=document.querySelector('#memory'),memoryContext=document.querySelector('#memory-context'),memoryItems=document.querySelector('#memory-items'),memorySearch=document.querySelector('#memory-search'),memorySearchRow=document.querySelector('#memory-search-row');let memoryView='context';async function report(type){try{const q=document.querySelector('#search').value;const result=await api(`/api/${type}?kind=${encodeURIComponent(view)}&query=${encodeURIComponent(q)}`);markdown.textContent=result.markdown;planItems.replaceChildren();if(type==='action-plan'){for(const item of result.without_task){const button=document.createElement('button');button.textContent=`Создать задачу: ${item.topic}`;button.onclick=async()=>{try{const task=await createTask(item.id);button.disabled=true;button.textContent=task.created?'Задача создана':'Задача уже существует';const open=document.createElement('button');open.textContent='Открыть задачу';open.onclick=()=>openTask(task.id);button.after(open)}catch(e){const error=document.createElement('span');error.className='error';error.textContent=e.message;button.after(error)}};planItems.append(button)}}output.classList.remove('hidden')}catch(e){show(e.message,true)}}function renderMemory(items){memoryItems.replaceChildren();for(const item of items){const box=document.createElement('article');box.className='entry';const title=document.createElement('strong');title.textContent=item.title;const meta=document.createElement('div');meta.className='meta';meta.textContent=`${item.updated_at} · версия ${item.version}`;const content=document.createElement('p');content.textContent=item.content;box.append(title,meta,content);if(item.semantic_key){const key=document.createElement('div');key.className='meta';key.textContent=item.semantic_key;box.prepend(key)}memoryItems.append(box)}}async function loadMemory(){try{memoryContext.classList.toggle('hidden',memoryView!=='context');memoryItems.replaceChildren();memorySearchRow.classList.toggle('hidden',memoryView==='context');if(memoryView==='context'){const result=await api('/api/memory/context');memoryContext.textContent=result.content;return}const result=await api(`/api/memory/${memoryView}?query=${encodeURIComponent(memorySearch.value)}`);renderMemory(result)}catch(e){show(e.message,true)}}async function load(){try{if(view==='memory'){await loadMemory();return}if(view==='tasks'){renderTasks(await api('/api/tasks'));return}const q=document.querySelector('#search').value;renderKnowledge(await api(`/api/entries?kind=${encodeURIComponent(view)}&query=${encodeURIComponent(q)}`))}catch(e){show(e.message,true)}}document.querySelectorAll('[data-view]').forEach(button=>button.onclick=()=>{view=button.dataset.view;knowledge.classList.toggle('hidden',view==='tasks'||view==='memory');memory.classList.toggle('hidden',view!=='memory');entries.classList.toggle('hidden',view==='memory');output.classList.add('hidden');document.querySelectorAll('[data-view]').forEach(x=>x.classList.toggle('active',x===button));document.querySelector('#search').value='';load()});document.querySelectorAll('[data-memory]').forEach(button=>button.onclick=()=>{memoryView=button.dataset.memory;document.querySelectorAll('[data-memory]').forEach(x=>x.classList.toggle('active',x===button));memorySearch.value='';loadMemory()});document.querySelector('#find').onclick=load;document.querySelector('#memory-find').onclick=loadMemory;document.querySelector('#summary').onclick=()=>report('summary');document.querySelector('#plan').onclick=()=>report('action-plan');document.querySelector('#copy').onclick=async()=>{try{await navigator.clipboard.writeText(markdown.textContent);show('Скопировано')}catch(e){show('Не удалось скопировать',true)}};document.querySelector('#memory-copy').onclick=async()=>{try{await navigator.clipboard.writeText(memoryContext.textContent);show('Скопировано')}catch(e){show('Не удалось скопировать',true)}};document.querySelector('#add').onsubmit=async event=>{event.preventDefault();const form=new FormData(event.target);try{await api('/api/entries',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:view,topic:form.get('topic'),text:form.get('text'),tags:form.get('tags')})});event.target.reset();show('Запись добавлена');load()}catch(e){show(e.message,true)}};load();</script></body></html>"""


def _page(token: str, focus_task: str | None, view: str) -> str:
    selected = view if view in {"overview", "search", "activity", "projects", "artem", "idea", "tasks", "memory"} else "overview"
    page = _page_raw(token, focus_task)
    page = page.replace(
        '<form id="add">',
        '<form id="add"><fieldset data-testid="intake" style="border:0;padding:0;margin:0 0 12px"><legend>Новый вход</legend><div class="actions"><button type="button" data-testid="intake-text" aria-pressed="true">Текст</button><button type="button" data-testid="intake-url" aria-pressed="false">Ссылка</button><button type="button" data-testid="intake-file" aria-pressed="false">Файл</button></div><label data-testid="intake-url-row" class="hidden">Ссылка<br><input id="intake-url" type="text" inputmode="url" placeholder="https://example.com"></label><label data-testid="intake-file-row" class="hidden">Текстовый файл<br><input id="intake-file" type="file" accept=".txt,.md,.csv,.json,text/plain,text/markdown,text/csv,application/json"></label></fieldset>',
        1,
    )
    page = page.replace(
        ';load();</script></body></html>',
        r''' ;const intakeForm=document.querySelector('#add'),intakeText=intakeForm.querySelector('textarea').closest('label'),intakeUrlRow=document.querySelector('[data-testid="intake-url-row"]'),intakeFileRow=document.querySelector('[data-testid="intake-file-row"]'),intakeUrl=document.querySelector('#intake-url'),intakeFile=document.querySelector('#intake-file');let intakeMode='text';intakeForm.elements.topic.required=false;function setIntakeMode(mode){intakeMode=mode;intakeForm.elements.text.required=mode==='text';intakeText.classList.toggle('hidden',mode!=='text');intakeUrlRow.classList.toggle('hidden',mode!=='url');intakeFileRow.classList.toggle('hidden',mode!=='file');for(const button of document.querySelectorAll('[data-testid^="intake-"]'))if(button.tagName==='BUTTON')button.setAttribute('aria-pressed',String(button.dataset.testid===`intake-${mode}`))}for(const mode of ['text','url','file'])document.querySelector(`[data-testid="intake-${mode}"]`).onclick=()=>setIntakeMode(mode);function intakeTopic(value){return value.trim()||'Входящий материал'}async function intakePayload(form){const topic=String(form.elements.topic.value||'');if(intakeMode==='text'){const text=String(form.elements.text.value||'');if(!text.trim())throw new Error('Введите текст.');return {topic:intakeTopic(topic),text}}if(intakeMode==='url'){let parsed;try{parsed=new URL(intakeUrl.value.trim())}catch(error){throw new Error('Введите корректную ссылку с http:// или https://.')}if(!['http:','https:'].includes(parsed.protocol)||!parsed.hostname)throw new Error('Введите корректную ссылку с http:// или https://.');return {topic:topic.trim()||parsed.hostname,text:parsed.href}}const files=intakeFile.files;if(!files||files.length!==1)throw new Error('Выберите один текстовый файл.');const file=files[0],extension=(file.name.split('.').pop()||'').toLowerCase();if(!['txt','md','csv','json'].includes(extension))throw new Error('Поддерживаются только файлы TXT, MD, CSV или JSON.');if(file.size===0)throw new Error('Выбранный файл пуст.');if(file.size>1048576)throw new Error('Файл должен быть не больше 1 МБ.');let text;try{text=await file.text()}catch(error){throw new Error('Не удалось прочитать выбранный файл.')}if(!text.trim())throw new Error('Выбранный файл не содержит текста.');return {topic:topic.trim()||file.name.replace(/\.[^.]+$/,''),text}}intakeForm.onsubmit=async event=>{event.preventDefault();try{const payload=await intakePayload(event.target);await api('/api/entries',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:view,topic:payload.topic,text:payload.text,tags:event.target.elements.tags.value,project_id:event.target.elements.project_id?.value||null})});event.target.reset();setIntakeMode('text');show('Входящий материал добавлен. Ниже можно создать задачу.');load()}catch(error){show(error.message,true)}};load();</script></body></html>''',
        1,
    )
    page = page.replace(
        "due_date:form.elements.due_date.value||null};try{",
        "due_date:form.elements.due_date.value||null,project_id:form.elements.project_id?.value||null};try{",
    )
    page = page.replace(
        "form.elements.due_date.value=item?.due_date||'';taskModal",
        "form.elements.due_date.value=item?.due_date||'';form.elements.project_id.dataset.current=item?.project_id||entry?.project_id||'';taskModal",
    )
    page = page.replace(
        "sort:p.get('sort')||'recommended'}",
        "sort:p.get('sort')||'recommended',project:p.get('project')||'all'}",
    )
    page = page.replace('<button data-view="artem"', '<button data-view="projects" data-testid="tab-projects">Проекты</button><button data-view="artem"', 1)
    page = page.replace('<section id="overview" data-testid="overview-screen">', '<section id="projects" data-testid="projects-screen" class="hidden"></section><section id="overview" data-testid="overview-screen">', 1)
    page = page.replace(
        '<button data-view="artem"',
        '<button data-view="activity" data-testid="tab-activity">Активность</button><button data-view="artem"',
        1,
    ).replace(
        '<section id="overview" data-testid="overview-screen">',
        '<section id="activity" data-testid="activity-screen" class="hidden"></section><section id="overview" data-testid="overview-screen">',
        1,
    )
    page = page.replace(
        '<button data-view="overview" data-testid="tab-overview" class="active">Обзор</button>',
        '<button data-view="overview" data-testid="tab-overview" class="active">Обзор</button>'
        '<button data-view="search" data-testid="tab-search">Поиск</button>',
    ).replace(
        '<section id="overview" data-testid="overview-screen">',
        '<section id="search" data-testid="search-screen" class="hidden"></section>'
        '<section id="overview" data-testid="overview-screen">',
    )
    page = re.sub(
        r'(<button data-view="(?:overview|search|activity|projects|artem|idea|tasks|memory)"[^>]*) class="active"(?: aria-current="page")?',
        r'\1',
        page,
    )
    page = re.sub(
        rf'(<button data-view="{selected}"[^>]*)>',
        r'\1 class="active" aria-current="page">',
        page,
        count=1,
    )
    page = page.replace("let view=focusTask?'tasks':'artem'", f"let view={json.dumps(selected)}")
    page = page.replace("async function load(){try{", "async function load(){try{if(view==='overview'||view==='search'||view==='activity'||view==='projects')return;")
    page = page.replace(
        "knowledge.classList.toggle('hidden',view==='tasks'||view==='memory')",
        "knowledge.classList.toggle('hidden',view==='tasks'||view==='memory'||view==='overview'||view==='search')",
    )
    page = page.replace("entries.classList.toggle('hidden',view==='memory')", "entries.classList.toggle('hidden',view==='memory'||view==='overview'||view==='search')")
    # The base script eagerly loads tasks before the task UI can replace its renderer.
    # Task mode is loaded once by the guarded MVP layer below.
    if selected in {"tasks", "activity", "projects"}:
        page = page.replace(";load();</script></body>", ";if(view!=='tasks'&&view!=='activity'&&view!=='projects')load();</script></body>")
    if selected in {"tasks", "memory", "overview", "search", "activity", "projects"}:
        page = page.replace(
            '<div id="knowledge" data-testid="knowledge-screen">',
            '<div id="knowledge" data-testid="knowledge-screen" class="hidden">',
        )
    if selected == "memory":
        page = page.replace(
            '<section id="memory" data-testid="memory-screen" class="hidden">',
            '<section id="memory" data-testid="memory-screen">',
        )
    if selected in {"overview", "search", "activity", "projects"}:
        page = page.replace('<section id="entries" data-testid="entries">', '<section id="entries" data-testid="entries" class="hidden">')
    if selected != "overview":
        page = page.replace('<section id="overview" data-testid="overview-screen">', '<section id="overview" data-testid="overview-screen" class="hidden">')
    task_blocks = """for(const [key,label] of [['overdue','Просроченные'],['today','На сегодня'],['high','Высокий приоритет']]){const compact=node('section',undefined,'overview-compact');compact.dataset.testid=`overview-${key}-tasks`;compact.append(node('strong',label));const items=data[`${key}_items`]||[];if(!items.length)compact.append(node('p','Нет задач.','overview-empty'));else for(const item of items)compact.append(taskRow(item));box.append(compact)}"""
    dashboard_ui = _dashboard_ui().replace("function memory(data)", "function memoryState(data)").replace(
        ",memory(data.memory),", ",memoryState(data.memory),"
    ).replace(
        "${task.display_title} · ${task.priority}",
        "${task.display_title}${task.project_name?` · ${task.project_name}`:''} · ${task.priority}",
    ).replace("box.append(counts);if(!data.items.length)", f"box.append(counts);{task_blocks}if(!data.items.length)").replace(
        "for(const item of data.items)box.append(taskRow(item));return box", "return box"
    )
    focus_ui = _focus_navigation_ui().replace(
        "oldKnowledge(items);if(entryId)",
        "oldKnowledge(items);for(const [index,item] of items.entries()){const card=document.querySelectorAll('#entries>.entry')[index];if(card)card.id=`knowledge-${item.id}`}if(entryId)",
    )
    task_ui = _task_mvp_ui().replace("due_date:form.elements.due_date.value||null};try{", "due_date:form.elements.due_date.value||null,project_id:form.elements.project_id.value||null};try{").replace("form.elements.due_date.value=item?.due_date||'';taskModal", "form.elements.due_date.value=item?.due_date||'';form.elements.project_id.dataset.current=item?.project_id||entry?.project_id||'';window.metricHitRefreshProjects?.(form,item?.project_id||entry?.project_id||'');taskModal").replace("sort:p.get('sort')||'recommended'}", "sort:p.get('sort')||'recommended',project:p.get('project')||'all'}").replace("sort:sort.value});load()", "sort:sort.value,project:new URLSearchParams(location.search).get('project')||'all'});load()")
    search_ui = _search_ui().replace("${item.date} · ${item.status}", "${item.date} · ${item.status}${item.project_name?` · ${item.project_name}`:''}")
    activity_ui = _activity_ui().replace(":item.object_type==='memory'?", ":item.object_type==='project'?`/?view=projects&project_id=${encodeURIComponent(item.target_id)}#project-${item.target_id}`:item.object_type==='memory'?")
    return page.replace("</body>", task_ui + dashboard_ui + search_ui + activity_ui + _projects_ui() + _project_assignment_ui() + _project_modal_refresh() + _project_experience_ui() + _project_assignment_controls() + _project_task_filter_ui() + focus_ui + _focus_navigation_reload_ui() + _dashboard_quick_action_guard() + "</body>")


def _e2e_markers() -> str:
    """Attach stable test selectors without changing panel behaviour."""
    return """<script>(()=>{const mark=()=>{for(const button of document.querySelectorAll('[data-view]'))button.dataset.testid=`tab-${button.dataset.view}`;const knowledge=document.querySelector('#knowledge'),memory=document.querySelector('#memory'),entries=document.querySelector('#entries'),modal=document.querySelector('#output');if(knowledge)knowledge.dataset.testid='knowledge-screen';if(memory)memory.dataset.testid='memory-screen';if(entries)entries.dataset.testid='entries';if(modal)modal.dataset.testid='modal-overlay';for(const name of ['topic','text','tags'])document.querySelector(`#add [name="${name}"]`)?.setAttribute('data-testid',`add-${name}`);document.querySelector('#add button')?.setAttribute('data-testid','add-entry');document.querySelector('#summary')?.setAttribute('data-testid','summary');document.querySelector('#plan')?.setAttribute('data-testid','action-plan');document.querySelector('#modal-close')?.setAttribute('data-testid','modal-close');document.querySelector('#copy')?.setAttribute('data-testid','modal-copy');for(const [index,card] of [...document.querySelectorAll('#entries>.entry')].entries()){if(card.id.startsWith('task-')){const id=card.id.slice(5);card.dataset.testid=`task-card-${id}`;const actions=card.querySelector('.actions');if(actions){actions.dataset.testid=`task-actions-${id}`;const [details,complete,cancel]=actions.querySelectorAll('button');if(details)details.dataset.testid=`task-details-toggle-${id}`;if(complete)complete.dataset.testid=`task-completed-${id}`;if(cancel)cancel.dataset.testid=`task-cancelled-${id}`;}const details=card.querySelector('.hidden');if(details)details.dataset.testid=`task-details-${id}`;}else{card.dataset.testid=`knowledge-entry-${index}`;const action=card.querySelector('.actions');const button=action?.querySelector('button'),link=action?.querySelector('a'),feedback=action?.querySelector('.result');if(button)button.dataset.testid=`create-task-${index}`;if(link)link.dataset.testid=`open-task-${index}`;if(feedback)feedback.dataset.testid=`task-feedback-${index}`;}}};for(const button of document.querySelectorAll('[data-view]'))button.addEventListener('click',()=>{for(const tab of document.querySelectorAll('[data-view]'))tab.toggleAttribute('aria-current',tab===button)});new MutationObserver(mark).observe(document.body,{childList:true,subtree:true});mark()})()</script>"""


def _tab_accessibility() -> str:
    return """<script>document.addEventListener('click',event=>{const active=event.target.closest('[data-view]');if(!active)return;for(const tab of document.querySelectorAll('[data-view]')){if(tab===active)tab.setAttribute('aria-current','page');else tab.removeAttribute('aria-current')}})</script>"""


def _task_ui() -> str:
    return """<script>(()=>{const originalLoad=load,originalRender=renderTasks;let taskQuery=new URLSearchParams(location.search);const params=()=>Object.fromEntries(['query','status','priority','due','sort'].map(k=>[k,taskQuery.get(k)||({status:'all',priority:'all',due:'all',sort:'recommended'}[k]||'')]));const updateUrl=()=>history.replaceState(null,'',`/?view=tasks&${new URLSearchParams({...params(),focus_task:focusTask||''}).toString()}`);const label=(text,value,testid)=>{const l=document.createElement('label');l.textContent=text;const s=document.createElement('select');s.dataset.testid=testid;for(const [v,n] of value)s.append(new Option(n,v));l.append(s);return [l,s]};function controls(items){let bar=document.querySelector('#task-controls');if(!bar){bar=document.createElement('div');bar.id='task-controls';bar.className='row';bar.dataset.testid='task-controls';entries.before(bar)}bar.replaceChildren();const q=document.createElement('input');q.placeholder='Поиск задач';q.value=params().query;q.dataset.testid='task-search';const [sl,st]=label('Статус',[['all','Все'],['open','Открытые'],['completed','Выполненные'],['cancelled','Отменённые']],'task-status-filter');const [pl,pr]=label('Приоритет',[['all','Все'],['high','Высокий'],['normal','Обычный'],['low','Низкий']],'task-priority-filter');const [dl,du]=label('Срок',[['all','Все'],['overdue','Просроченные'],['today','Сегодня'],['week','7 дней'],['none','Без срока']],'task-due-filter');const [ol,so]=label('Сортировка',[['recommended','Рекомендуемая'],['due','По сроку'],['priority','По приоритету'],['newest','Новые'],['oldest','Старые']],'task-sort');for(const s of [st,pr,du,so])s.value=params()[s===st?'status':s===pr?'priority':s===du?'due':'sort'];const reset=document.createElement('button');reset.textContent='Сбросить';reset.dataset.testid='task-reset';const count=document.createElement('span');count.dataset.testid='task-count';count.textContent=`Найдено: ${items.length}`;bar.append(q,sl,pl,dl,ol,reset,count);const change=()=>{taskQuery.set('query',q.value);taskQuery.set('status',st.value);taskQuery.set('priority',pr.value);taskQuery.set('due',du.value);taskQuery.set('sort',so.value);updateUrl();load()};q.oninput=change;[st,pr,du,so].forEach(x=>x.onchange=change);reset.onclick=()=>{taskQuery=new URLSearchParams();updateUrl();load()}}
async function today(){let box=document.querySelector('#today-tasks');if(!box){box=document.createElement('section');box.id='today-tasks';box.dataset.testid='today-tasks';entries.before(box)}const items=await api('/api/tasks/today');box.replaceChildren();const h=document.createElement('h2');h.textContent='Сегодня';box.append(h);if(!items.length){const empty=document.createElement('p');empty.textContent='На сегодня срочных задач нет.';box.append(empty);return}for(const item of items){const line=document.createElement('div');line.className='actions';line.textContent=`${item.title} · ${item.priority}${item.due_date?' · '+item.due_date:''}`;const open=document.createElement('a');open.dataset.testid=`today-open-${item.id}`;open.href=`/?view=tasks&focus_task=${item.id}#task-${item.id}`;open.textContent='Открыть';line.append(open);box.append(line)}}
renderTasks=items=>{originalRender(items);if(view!=='tasks')return;controls(items);today();for(const item of items){const card=document.getElementById(`task-${item.id}`);if(!card)continue;const meta=card.querySelector('.meta');meta.textContent=`${item.status} · ${item.created_at} · ${item.priority}${item.due_date?' · '+item.due_date:''}`;if(item.due_date){const due=document.createElement('span');due.className=item.due_date<new Date().toISOString().slice(0,10)?'due-overdue':item.due_date===new Date().toISOString().slice(0,10)?'due-today':'';due.textContent=item.due_date;meta.append(' ',due)}const details=card.querySelector('[data-testid^="task-details-"]');const edit=document.createElement('button');edit.textContent='Редактировать';edit.dataset.testid=`task-edit-${item.id}`;edit.onclick=()=>{const form=document.createElement('form');form.dataset.testid=`task-edit-form-${item.id}`;form.innerHTML=`<input data-testid="task-edit-title-${item.id}" value=""><textarea data-testid="task-edit-description-${item.id}"></textarea><select data-testid="task-edit-priority-${item.id}"><option value="high">high</option><option value="normal">normal</option><option value="low">low</option></select><input type="date" data-testid="task-edit-due-date-${item.id}"><button data-testid="task-edit-save-${item.id}">Сохранить</button><button type="button" data-testid="task-edit-cancel-${item.id}">Отмена</button><span data-testid="task-edit-feedback-${item.id}"></span>`;form.querySelector(`[data-testid="task-edit-title-${item.id}"]`).value=item.title;form.querySelector(`[data-testid="task-edit-description-${item.id}"]`).value=item.description;form.querySelector(`[data-testid="task-edit-priority-${item.id}"]`).value=item.priority;form.querySelector(`[data-testid="task-edit-due-date-${item.id}"]`).value=item.due_date||'';form.onsubmit=async e=>{e.preventDefault();const feedback=form.querySelector('span');try{await api(`/api/tasks/${item.id}/edit`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:form.querySelector('input').value,description:form.querySelector('textarea').value,priority:form.querySelector('select').value,due_date:form.querySelector('input[type=date]').value||null})});feedback.textContent='Изменения сохранены';card.classList.add('task-focused');load()}catch(err){feedback.className='error';feedback.textContent=err.message}};form.querySelector(`[data-testid="task-edit-cancel-${item.id}"]`).onclick=()=>form.remove();details.append(form)};details.append(edit)}};
load=async()=>{if(view!=='tasks')return originalLoad();try{const p=new URLSearchParams(params());renderTasks(await api(`/api/tasks?${p}`))}catch(e){show(e.message,true)}};if(view==='tasks')load()})()</script>"""


def _task_edit_feedback() -> str:
    return """<script>(()=>{new MutationObserver(()=>{for(const form of document.querySelectorAll('[data-testid^="task-edit-form-"]')){if(form.dataset.enhanced)continue;form.dataset.enhanced='1';const id=form.dataset.testid.slice('task-edit-form-'.length);form.onsubmit=async event=>{event.preventDefault();const feedback=form.querySelector(`[data-testid="task-edit-feedback-${id}"]`);try{await api(`/api/tasks/${id}/edit`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({title:form.querySelector('input').value,description:form.querySelector('textarea').value,priority:form.querySelector('select').value,due_date:form.querySelector('input[type=date]').value||null})});feedback.className='result';feedback.textContent='Изменения сохранены';form.closest('.entry').classList.add('task-focused')}catch(error){feedback.className='error';feedback.textContent=error.message}}}}).observe(document.body,{childList:true,subtree:true})})()</script>"""


def _task_edit_controls() -> str:
    return """<script>(()=>{const add=async()=>{const items=await api('/api/tasks');for(const card of document.querySelectorAll('article[id^="task-"]')){const id=card.id.slice(5),details=card.querySelector('.hidden');if(!details||details.querySelector(`[data-testid="task-edit-${id}"]`))continue;const item=items.find(x=>x.id===id);if(!item)continue;const button=document.createElement('button');button.textContent='Редактировать';button.dataset.testid=`task-edit-${id}`;button.onclick=()=>{const form=document.createElement('form');form.dataset.testid=`task-edit-form-${id}`;form.innerHTML=`<input data-testid="task-edit-title-${id}"><textarea data-testid="task-edit-description-${id}"></textarea><select data-testid="task-edit-priority-${id}"><option>high</option><option>normal</option><option>low</option></select><input type="date" data-testid="task-edit-due-date-${id}"><button data-testid="task-edit-save-${id}">Сохранить</button><button type="button" data-testid="task-edit-cancel-${id}">Отмена</button><span data-testid="task-edit-feedback-${id}"></span>`;form.querySelector('input').value=item.title;form.querySelector('textarea').value=item.description;form.querySelector('select').value=item.priority;form.querySelector('input[type=date]').value=item.due_date||'';form.querySelector(`[data-testid="task-edit-cancel-${id}"]`).onclick=()=>form.remove();details.append(form)};details.append(button)}};new MutationObserver(()=>add().catch(()=>{})).observe(entries,{childList:true,subtree:true});add().catch(()=>{})})()</script>"""


def _task_safe_render() -> str:
    return """<script>(()=>{const previous=renderTasks;renderTasks=items=>{try{previous(items)}catch(error){return}for(const item of items){const card=document.getElementById(`task-${item.id}`);const details=card?.querySelector('.hidden');if(!details)return;}}})()</script>"""


def _stable_test_ids() -> str:
    return """<script>(()=>{const mark=()=>{for(const card of document.querySelectorAll('#entries>.entry:not([id^="task-"])')){const entryId=card.textContent.match(/\\b[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\\b/i)?.[0];if(!entryId)continue;card.dataset.testid=`knowledge-entry-${entryId}`;const action=card.querySelector('.actions'),button=action?.querySelector('button'),link=action?.querySelector('a[href*="focus_task="]');if(button)button.dataset.testid=`create-task-${entryId}`;if(link){const taskId=new URL(link.href).searchParams.get('focus_task');link.dataset.testid=`open-task-${taskId}`;action.querySelector('.result').dataset.testid=`task-feedback-${taskId}`;}}};new MutationObserver(mark).observe(document.body,{childList:true,subtree:true});mark()})()</script>"""


def _task_mvp_ui() -> str:
    """Single guarded task UI layer; it deliberately does not depend on async test-id decoration."""
    return r"""<style>
.task-modal{position:fixed;inset:0;background:#000a;display:grid;place-items:center;z-index:20;padding:16px}.task-modal.hidden{display:none}.task-modal form{background:#182334;border:2px solid #4388d4;border-radius:10px;width:min(620px,92vw);max-height:85vh;overflow:auto;padding:20px}.task-modal label{display:block;margin:10px 0}.task-modal input,.task-modal select{width:100%;box-sizing:border-box}.priority-high{color:#ff9ca9}.priority-normal{color:#8ee0ff}.priority-low{color:#a8b6c9}.due-overdue{color:#ff9ca9}.due-today{color:#ffc36b}.task-actions{display:flex;gap:9px;flex-wrap:wrap;margin:12px 0}.task-actions button{width:auto}@media(max-width:600px){.task-actions button{width:auto}}</style>
<script>(()=>{
const originalLoad=load;
for(const [name,testid] of [['topic','add-topic'],['text','add-text'],['tags','add-tags']]){const field=document.querySelector(`#add [name="${name}"]`);if(field)field.dataset.testid=testid}
const taskModal=document.createElement('section');
taskModal.className='task-modal hidden'; taskModal.dataset.testid='task-modal'; taskModal.setAttribute('role','dialog'); taskModal.setAttribute('aria-modal','true');
taskModal.innerHTML='<form data-testid="task-form"><h2 data-testid="task-modal-title"></h2><label>Название<input name="title" required data-testid="task-title"></label><label>Описание<textarea name="description" required data-testid="task-description"></textarea></label><label>Приоритет<select name="priority" data-testid="task-priority"><option value="high">Высокий</option><option value="normal">Обычный</option><option value="low">Низкий</option></select></label><label>Срок<input name="due_date" type="date" data-testid="task-due-date"></label><label>Проект<select name="project_id" data-testid="task-project"><option value="">Без проекта</option></select></label><div class="task-actions"><button data-testid="task-save">Сохранить</button><button type="button" data-testid="task-cancel">Отмена</button></div><div class="error" data-testid="task-form-error"></div></form>';
document.body.append(taskModal);
const form=taskModal.querySelector('form'), formError=taskModal.querySelector('[data-testid="task-form-error"]'); let modalState=null;
const closeModal=()=>{taskModal.classList.add('hidden');modalState=null;}; taskModal.querySelector('[data-testid="task-cancel"]').onclick=closeModal; taskModal.onclick=e=>{if(e.target===taskModal)closeModal};
document.addEventListener('keydown',e=>{if(e.key==='Escape'&&!taskModal.classList.contains('hidden'))closeModal()});
const focusUrl=id=>`/?view=tasks&focus_task=${encodeURIComponent(id)}#task-${id}`;
function openModal(mode,{entry=null,item=null,holder=null}={}){modalState={mode,entry,item,holder};const suffix=item?.id;formError.textContent='';form.dataset.testid=suffix?`task-edit-form-${suffix}`:'task-form';for(const [name,base] of [['title','task-edit-title'],['description','task-edit-description'],['priority','task-edit-priority'],['due_date','task-edit-due-date']])form.elements[name].dataset.testid=suffix?`${base}-${suffix}`:`task-${name==='due_date'?'due-date':name}`;taskModal.querySelector('[data-testid="task-modal-title"]').textContent=mode==='edit'?'Редактировать задачу':'Новая задача';form.elements.title.value=item?.title||entry?.topic||'';form.elements.description.value=item?.description||entry?.text||'';form.elements.priority.value=item?.priority||'normal';form.elements.due_date.value=item?.due_date||'';taskModal.classList.remove('hidden');form.elements.title.focus()}
function feedback(holder,item,created){holder.replaceChildren();const text=document.createElement('span');text.className='result';text.dataset.testid=`task-feedback-${item.id}`;text.textContent=created?'Задача создана':'Задача уже создана';const priority=document.createElement('span');priority.textContent=` · ${item.priority}`;holder.append(text,priority);if(item.due_date){const due=document.createElement('span');due.textContent=` · ${item.due_date}`;holder.append(due)}const open=document.createElement('a');open.href=focusUrl(item.id);open.dataset.testid=`open-task-${item.id}`;open.textContent='Открыть задачу';holder.append(open)}
form.onsubmit=async e=>{e.preventDefault();if(!modalState)return;const state=modalState;const payload={title:form.elements.title.value,description:form.elements.description.value,priority:form.elements.priority.value,due_date:form.elements.due_date.value||null};try{let result;if(state.mode==='edit'){result=await api(`/api/tasks/${encodeURIComponent(state.item.id)}/edit`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});closeModal();await load();const card=document.getElementById(`task-${result.id}`);if(card){card.classList.add('task-focused');const note=document.createElement('div');note.className='result';note.dataset.testid=`task-edit-feedback-${result.id}`;note.textContent='Изменения сохранены';card.prepend(note);card.scrollIntoView({behavior:'smooth',block:'center'})}}else{if(state.entry)payload.id=state.entry.id;result=await api('/api/tasks',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});closeModal();if(state.holder)feedback(state.holder,result,result.created);else window.location.href=focusUrl(result.id)}}catch(error){formError.textContent=error.message}};
function removeTaskUi(){document.querySelector('#task-controls')?.remove();document.querySelector('#today-tasks')?.remove();}
function taskParams(){const p=new URLSearchParams(location.search);return {query:p.get('query')||'',status:p.get('status')||'all',priority:p.get('priority')||'all',due:p.get('due')||'all',sort:p.get('sort')||'recommended'}}
function updateTaskUrl(values){const p=new URLSearchParams(values);p.set('view','tasks');history.replaceState(null,'',`/?${p.toString()}`)}
function makeSelect(label,values,testid,current){const wrap=document.createElement('label');wrap.textContent=label;const select=document.createElement('select');select.dataset.testid=testid;for(const [value,text] of values)select.append(new Option(text,value));select.value=current;wrap.append(select);return [wrap,select]}
function controls(items){if(view!=='tasks')return;let bar=document.querySelector('#task-controls');if(!bar){bar=document.createElement('div');bar.id='task-controls';bar.className='row';entries.before(bar)}bar.replaceChildren();const values=taskParams(),query=document.createElement('input');query.value=values.query;query.placeholder='Поиск задач';query.dataset.testid='task-search';const [statusWrap,status]=makeSelect('Статус',[['all','Все'],['open','Открытые'],['completed','Выполненные'],['cancelled','Отменённые']],'task-status-filter',values.status);const [priorityWrap,priority]=makeSelect('Приоритет',[['all','Все'],['high','Высокий'],['normal','Обычный'],['low','Низкий']],'task-priority-filter',values.priority);const [dueWrap,due]=makeSelect('Срок',[['all','Все'],['overdue','Просроченные'],['today','Сегодня'],['week','7 дней'],['none','Без срока']],'task-due-filter',values.due);const [sortWrap,sort]=makeSelect('Сортировка',[['recommended','Рекомендуемая'],['due','По сроку'],['priority','По приоритету'],['newest','Новые'],['oldest','Старые']],'task-sort',values.sort);const reset=document.createElement('button');reset.textContent='Сбросить';reset.dataset.testid='task-reset';const create=document.createElement('button');create.textContent='Новая задача';create.dataset.testid='new-task';create.onclick=()=>openModal('create');const count=document.createElement('span');count.dataset.testid='task-count';count.textContent=`Найдено: ${items.length}`;bar.append(query,statusWrap,priorityWrap,dueWrap,sortWrap,reset,create,count);const change=()=>{updateTaskUrl({query:query.value,status:status.value,priority:priority.value,due:due.value,sort:sort.value});load()};query.oninput=change;[status,priority,due,sort].forEach(x=>x.onchange=change);reset.onclick=()=>{updateTaskUrl({query:'',status:'all',priority:'all',due:'all',sort:'recommended'});load()}}
async function today(){if(view!=='tasks')return;let box=document.querySelector('#today-tasks');if(!box){box=document.createElement('section');box.id='today-tasks';box.dataset.testid='today-tasks';entries.before(box)}const items=await api('/api/tasks/today');box.replaceChildren();const heading=document.createElement('h2');heading.textContent='Сегодня';box.append(heading);if(!items.length){const empty=document.createElement('p');empty.textContent='На сегодня срочных задач нет.';box.append(empty);return}for(const item of items){const line=document.createElement('div'), open=document.createElement('a');line.className='task-actions';line.textContent=`${item.title} · ${item.priority}${item.due_date?' · '+item.due_date:''}`;open.href=focusUrl(item.id);open.dataset.testid=`today-open-${item.id}`;open.textContent='Открыть';line.append(open);box.append(line)}}
async function change(id,status){try{await api(`/api/tasks/${encodeURIComponent(id)}/status`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({status})});load()}catch(error){show(error.message,true)}}
renderTasks=items=>{if(view!=='tasks')return;removeTaskUi();controls(items);entries.replaceChildren();for(const item of items){const card=document.createElement('article');card.id=`task-${item.id}`;card.className='entry';card.dataset.testid=`task-card-${item.id}`;if(item.id===focusTask)card.classList.add('task-focused');const title=document.createElement('strong');title.textContent=item.display_title;const meta=document.createElement('div');meta.className='meta';meta.textContent=`${item.status} · ${item.created_at} · ${item.priority}${item.due_date?' · '+item.due_date:''}`;const actions=document.createElement('div');actions.className='task-actions';actions.dataset.testid=`task-actions-${item.id}`;const details=document.createElement('div');details.className='hidden';details.dataset.testid=`task-details-${item.id}`;const toggle=document.createElement('button');toggle.textContent='Подробнее';toggle.dataset.testid=`task-details-toggle-${item.id}`;toggle.onclick=()=>{details.classList.toggle('hidden');toggle.textContent=details.classList.contains('hidden')?'Подробнее':'Скрыть'};const edit=document.createElement('button');edit.textContent='Редактировать';edit.dataset.testid=`task-edit-${item.id}`;edit.onclick=()=>openModal('edit',{item});actions.append(toggle,edit);if(item.status==='open'){for(const [text,status,testid] of [['Выполнено','completed','task-completed'],['Отменить','cancelled','task-cancelled']]){const button=document.createElement('button');button.textContent=text;button.dataset.testid=`${testid}-${item.id}`;button.onclick=()=>change(item.id,status);actions.append(button)}}const description=document.createElement('p');description.textContent=item.description;const source=document.createElement('div');source.textContent=item.source;const topic=document.createElement('div');topic.textContent=item.knowledge_topic||'Без источника';const uuid=document.createElement('div');uuid.className='meta';uuid.textContent=item.id;details.append(description,source,topic,uuid);if(item.id===focusTask){const label=document.createElement('div');label.className='focus-label';label.textContent='Открытая задача';card.append(label)}card.append(title,meta,actions,details);entries.append(card)}today().catch(error=>show(error.message,true));if(focusTask)setTimeout(focusCard,0)};
renderKnowledge=items=>{if(view!=='artem'&&view!=='idea')return;removeTaskUi();entries.replaceChildren();for(const item of items){const card=document.createElement('article');card.className='entry';card.dataset.testid=`knowledge-entry-${item.id}`;const title=document.createElement('strong');title.textContent=item.topic;const text=document.createElement('p');text.textContent=item.text;const actions=document.createElement('div');actions.className='task-actions';if(item.task)feedback(actions,item.task,false);else{const button=document.createElement('button');button.textContent='Создать задачу';button.dataset.testid=`create-task-${item.id}`;button.onclick=()=>openModal('create',{entry:item,holder:actions});actions.append(button)}card.append(title,text,actions);entries.append(card)}};
load=async()=>{try{if(view==='tasks'){const p=new URLSearchParams(taskParams());renderTasks(await api(`/api/tasks?${p}`));return}if(view==='artem'||view==='idea'){const search=document.querySelector('#search');renderKnowledge(await api(`/api/entries?kind=${encodeURIComponent(view)}&query=${encodeURIComponent(search?search.value:'')}`));return}removeTaskUi();return originalLoad()}catch(error){show(error.message,true)}};
for(const tab of document.querySelectorAll('[data-view]'))tab.addEventListener('click',()=>{for(const candidate of document.querySelectorAll('[data-view]')){if(candidate===tab)candidate.setAttribute('aria-current','page');else candidate.removeAttribute('aria-current')}if(tab.dataset.view!=='tasks')removeTaskUi()});
window.metricHitOpenTaskModal=()=>openModal('create');
setTimeout(load,0);
})();</script>"""


def _dashboard_ui() -> str:
    return """<script>(()=>{const overview=document.querySelector('#overview');const tab=viewName=>document.querySelector(`[data-view="${viewName}"]`);const short=(text,limit=120)=>text.length<=limit?text:`${text.slice(0,limit-1).trimEnd()}…`;const openTask=id=>`/?view=tasks&focus_task=${encodeURIComponent(id)}#task-${id}`;function node(tag,text,cls){const value=document.createElement(tag);if(text!==undefined)value.textContent=text;if(cls)value.className=cls;return value}function section(title,testid){const box=node('section',undefined,'overview-card');box.dataset.testid=testid;box.append(node('h2',title));return box}function taskRow(task){const line=node('div',undefined,'overview-task');line.dataset.testid=`overview-task-${task.id}`;const text=node('span',`${task.display_title} · ${task.priority}${task.due_date?` · ${task.due_date}`:''}`);const open=node('a','Открыть');open.href=openTask(task.id);open.dataset.testid=`overview-open-${task.id}`;line.append(text,open);return line}function empty(box,text,testid){const value=node('p',text,'overview-empty');if(testid)value.dataset.testid=testid;box.append(value)}function recent(title,kind,data){const box=section(title,`overview-${kind}-list`);if(data.error){empty(box,data.error);return box}if(!data.items.length){empty(box,'Записей пока нет.');return box}for(const item of data.items){const line=node('div',undefined,'overview-task');line.dataset.testid=`overview-${kind}-${item.id}`;line.append(node('span',`${item.topic} — ${short(item.text)}`));box.append(line)}const open=node('button',kind==='artem'?'Открыть рекомендации':'Открыть идеи');open.dataset.testid=`overview-open-${kind}`;open.onclick=()=>{tab(kind).click();setTimeout(()=>document.querySelector('#add [name="topic"]')?.focus(),0)};box.append(open);return box}function memory(data){const box=section('Состояние памяти','overview-memory');for(const [key,label] of [['approved','Утверждено'],['pending','Ожидает'],['conflicts','Открытые конфликты'],['sources','Источники']]){const value=node('div',`${label}: ${data[key]}`, 'overview-count');value.dataset.testid=`overview-memory-${key}`;box.append(value)}return box}function tasks(data){const box=section('Задачи','overview-task-list');if(data.error){empty(box,data.error);return box}const counts=node('div',undefined,'overview-counts');for(const [key,label] of [['open','Открытых'],['overdue','Просрочено'],['today','На сегодня'],['high','Высокий приоритет']]){const value=node('div',`${label}: ${data[key]}`, 'overview-count');value.dataset.testid=`overview-${key}-count`;counts.append(value)}box.append(counts);if(!data.items.length){empty(box,'Открытых задач нет.', 'overview-empty-tasks');return box}for(const item of data.items)box.append(taskRow(item));return box}function quick(){const box=section('Быстрые действия','overview-quick-actions');const task=node('button','Новая задача');task.dataset.testid='overview-new-task';task.onclick=()=>{tab('tasks').click();setTimeout(()=>document.querySelector('#new-task')?.click(),0)};const artem=node('button','Добавить рекомендацию');artem.dataset.testid='overview-add-artem';artem.onclick=()=>tab('artem').click();const idea=node('button','Добавить идею');idea.dataset.testid='overview-add-idea';idea.onclick=()=>tab('idea').click();box.append(task,artem,idea);return box}async function render(){if(view!=='overview')return;overview.classList.remove('hidden');overview.replaceChildren();knowledge.classList.add('hidden');memory.classList.add('hidden');entries.classList.add('hidden');document.querySelector('#task-controls')?.remove();document.querySelector('#today-tasks')?.remove();try{const data=await api('/api/dashboard');const grid=node('div',undefined,'overview-grid');grid.append(tasks(data.tasks),recent('Последние рекомендации','artem',data.artem),recent('Последние идеи','idea',data.idea),memory(data.memory),quick());overview.append(grid)}catch(error){empty(overview,'Обзор временно недоступен.')}}const previousLoad=load;load=async()=>{if(view==='overview'){await render();return}overview.classList.add('hidden');await previousLoad()};for(const button of document.querySelectorAll('[data-view]'))button.addEventListener('click',()=>{if(button.dataset.view==='overview'){setTimeout(load,0)}else overview.classList.add('hidden')});setTimeout(()=>{if(view==='overview')load()},0)})();</script>"""


def _dashboard_quick_action_guard() -> str:
    return """<script>document.addEventListener('click',event=>{const button=event.target.closest('[data-testid="overview-new-task"]');if(!button)return;event.preventDefault();event.stopImmediatePropagation();document.querySelector('[data-view="tasks"]').click();window.metricHitOpenTaskModal?.()},true)</script>"""


def _search_ui() -> str:
    return """<script>(()=>{const screen=document.querySelector('#search');const types=[['all','Все'],['artem','Рекомендации Артёма'],['idea','Мои идеи'],['task','Задачи'],['fact','Факты'],['decision','Решения'],['document','Документы']];const statuses=[['all','Все статусы'],['open','Открытые'],['completed','Выполненные'],['cancelled','Отменённые'],['active','Активные']];const params=()=>new URLSearchParams(location.search);const make=(tag,text,testid)=>{const el=document.createElement(tag);el.textContent=text;el.dataset.testid=testid;return el};const target=item=>{const state=params();const query=new URLSearchParams({view:'search',q:state.get('q')||'',type:state.get('type')||'all',status:state.get('status')||'all'}).toString();if(item.type==='task')return `/?view=tasks&focus_task=${encodeURIComponent(item.id)}#task-${item.id}`;if(item.type==='artem'||item.type==='idea')return `/?view=${item.type}&focus_entry=${encodeURIComponent(item.id)}#knowledge-${item.id}`;const tab=item.type==='fact'?'facts':item.type==='decision'?'decisions':'documents';return `/?view=memory&memory_tab=${tab}&focus_memory=${encodeURIComponent(item.id)}#memory-${item.type}-${item.id}`};async function render(){if(view!=='search')return;screen.classList.remove('hidden');screen.replaceChildren();knowledge.classList.add('hidden');memory.classList.add('hidden');entries.classList.add('hidden');document.querySelector('#task-controls')?.remove();document.querySelector('#today-tasks')?.remove();const row=document.createElement('div');row.className='row';const input=document.createElement('input');input.placeholder='Поиск по данным MetricHit';input.value=params().get('q')||'';input.dataset.testid='global-search-query';const type=document.createElement('select');type.dataset.testid='global-search-type';for(const [value,label] of types)type.append(new Option(label,value));type.value=params().get('type')||'all';const status=document.createElement('select');status.dataset.testid='global-search-status';for(const [value,label] of statuses)status.append(new Option(label,value));status.value=params().get('status')||'all';const submit=make('button','Найти','global-search-submit');row.append(input,type,status,submit);const count=make('div','Введите запрос для поиска.','global-search-count');screen.append(row,count);const execute=async(push)=>{const q=input.value.trim();const next=new URLSearchParams({view:'search',q,type:type.value,status:status.value});if(push)history.pushState(null,'',`/?${next}`);if(!q){count.textContent='Введите запрос для поиска.';return}const result=await api(`/api/search?query=${encodeURIComponent(q)}&item_type=${encodeURIComponent(type.value)}&status=${encodeURIComponent(status.value)}`);count.textContent=`Найдено: ${result.results.length}`;const list=document.createElement('section');list.dataset.testid='global-search-results';if(!result.results.length){const empty=make('p','Ничего не найдено.','search-empty');list.append(empty)}for(const item of result.results){const card=document.createElement('article');card.className='entry';card.dataset.testid=`search-result-${item.type}-${item.id}`;const title=make('strong',`${item.type}: ${item.title}`);const snippet=make('p',item.snippet);const meta=make('div',`${item.date} · ${item.status}`,'meta');const open=make('a','Открыть',`search-open-${item.type}-${item.id}`);open.href=target(item);card.append(title,snippet,meta,open);list.append(card)}screen.querySelector('[data-testid="global-search-results"]')?.remove();screen.append(list)};submit.onclick=()=>execute(true);input.onkeydown=event=>{if(event.key==='Enter'){event.preventDefault();execute(true)}};if(input.value)execute(false)}const previousLoad=load;load=async()=>{if(view==='search'){await render();return}screen.classList.add('hidden');await previousLoad()};for(const tab of document.querySelectorAll('[data-view]'))tab.addEventListener('click',()=>{if(tab.dataset.view==='search')setTimeout(load,0);else screen.classList.add('hidden')});window.addEventListener('popstate',()=>{if(new URLSearchParams(location.search).get('view')==='search'){view='search';document.querySelectorAll('[data-view]').forEach(tab=>{const active=tab.dataset.view==='search';tab.classList.toggle('active',active);tab.toggleAttribute('aria-current',active)});load()}});setTimeout(()=>{if(view==='search')load()},0)})();</script>"""


def _activity_ui() -> str:
    return r"""<script>(()=>{const screen=document.querySelector('#activity'),params=()=>new URLSearchParams(location.search),node=(tag,text,id)=>{const el=document.createElement(tag);el.textContent=text;if(id)el.dataset.testid=id;return el};const target=item=>item.object_type==='task'?`/?view=tasks&focus_task=${encodeURIComponent(item.target_id)}#task-${item.target_id}`:item.object_type==='artem'||item.object_type==='idea'?`/?view=${item.object_type}&focus_entry=${encodeURIComponent(item.target_id)}#knowledge-${item.target_id}`:item.object_type==='memory'?`/?view=memory&memory_tab=facts&focus_memory=${encodeURIComponent(item.target_id)}#memory-fact-${item.target_id}`:null;async function render(){if(view!=='activity')return;screen.classList.remove('hidden');screen.replaceChildren();knowledge.classList.add('hidden');memory.classList.add('hidden');entries.classList.add('hidden');const row=document.createElement('div');row.className='row';const controls=[['period',[['today','Сегодня'],['7','7 дней'],['30','30 дней'],['all','Всё']]],['type',[['all','Все'],['task','Задачи'],['artem','Рекомендации'],['idea','Идеи'],['memory','Память']]],['action',[['all','Все действия'],['create','Создание'],['update','Изменение'],['completed','Выполнение'],['cancelled','Отмена']]]];const selects={};for(const [name,options] of controls){const select=document.createElement('select');select.dataset.testid=`activity-${name}`;for(const [value,label] of options)select.append(new Option(label,value));select.value=params().get(name)||'all';selects[name]=select;row.append(select)}const apply=node('button','Применить','activity-apply');row.append(apply);screen.append(row);const list=document.createElement('section');list.dataset.testid='activity-list';screen.append(list);const load=async(offset=0,push=false)=>{if(push)history.pushState(null,'',`/?${new URLSearchParams({view:'activity',period:selects.period.value,type:selects.type.value,action:selects.action.value})}`);const data=await api(`/api/activity?period=${selects.period.value}&item_type=${selects.type.value}&action=${selects.action.value}&offset=${offset}`);if(!offset)list.replaceChildren();if(!data.items.length&&!offset){list.append(node('p','Событий пока нет.','activity-empty'));return}for(const item of data.items){const card=node('article',undefined,`activity-event-${item.id}`);card.className='entry';card.append(node('strong',item.label),node('div',`${item.title} · ${item.date}`,'meta'));const brief=node('p',item.changes.length?item.changes.map(x=>x.field).join(', '):'Без дополнительных деталей');card.append(brief);const actions=node('div');actions.className='actions';if(item.available&&target(item)){const open=node('a','Открыть',`activity-open-${item.id}`);open.href=target(item);actions.append(open)}else actions.append(node('span','Запись недоступна'));const detail=node('button','Подробнее',`activity-details-${item.id}`);detail.onclick=()=>{markdown.textContent=item.changes.length?item.changes.map(x=>`${x.field}\nБыло: ${x.old}\nСтало: ${x.new}`).join('\n\n'):'Подробные изменения не зафиксированы.';document.querySelector('#modal-title').textContent=item.label;output.classList.remove('hidden');document.body.style.overflow='hidden'};actions.append(detail);card.append(actions);list.append(card)}if(data.has_more){const more=node('button','Показать ещё','activity-more');more.onclick=()=>load(data.next_offset);list.append(more)}};apply.onclick=()=>load(0,true);load(0)}const oldLoad=load;load=async()=>{if(view==='activity'){await render();return}screen.classList.add('hidden');await oldLoad()};for(const tab of document.querySelectorAll('[data-view]'))tab.addEventListener('click',()=>{if(tab.dataset.view==='activity')setTimeout(load,0);else screen.classList.add('hidden')});window.addEventListener('popstate',()=>{if(params().get('view')==='activity'){view='activity';document.querySelectorAll('[data-view]').forEach(tab=>{const active=tab.dataset.view==='activity';tab.classList.toggle('active',active);tab.toggleAttribute('aria-current',active)});render()}});setTimeout(()=>{if(view==='activity')load()},0)})();</script>"""


def _focus_navigation_ui() -> str:
    return """<style>.entry-focused{border:3px solid #38c7d4!important;background:#123745!important;box-shadow:0 0 0 4px #1a6474}.entry-focused .focus-label{color:#8ee0ff}</style><script>(()=>{const p=new URLSearchParams(location.search),entryId=p.get('focus_entry'),memoryId=p.get('focus_memory'),memoryTab=p.get('memory_tab');const focus=card=>{if(!card)return;card.classList.add('entry-focused');if(!card.querySelector('.focus-label')){const label=document.createElement('div');label.className='focus-label';label.textContent='Открытая запись';card.prepend(label)}card.scrollIntoView({behavior:'smooth',block:'center'})};const oldKnowledge=renderKnowledge;renderKnowledge=items=>{oldKnowledge(items);if(entryId)focus(document.getElementById(`knowledge-${entryId}`)||document.querySelector(`[data-testid="knowledge-entry-${entryId}"]`))};const oldMemory=renderMemory;renderMemory=items=>{oldMemory(items);for(const [index,item] of items.entries()){const card=document.querySelectorAll('#memory-items>.entry')[index];if(!card)continue;const itemType=memoryView==='facts'?'fact':memoryView==='decisions'?'decision':'document';card.id=`memory-${itemType}-${item.id}`;card.dataset.testid=`memory-${itemType}-${item.id}`}if(memoryId){const itemType=memoryView==='facts'?'fact':memoryView==='decisions'?'decision':'document';focus(document.getElementById(`memory-${itemType}-${memoryId}`))}};const tabs=document.querySelector('#memory .tabs');if(tabs&&!tabs.querySelector('[data-memory="documents"]')){const docs=document.createElement('button');docs.dataset.memory='documents';docs.textContent='Документы';docs.onclick=()=>{memoryView='documents';document.querySelectorAll('[data-memory]').forEach(tab=>tab.classList.toggle('active',tab===docs));loadMemory()};tabs.append(docs)}if(view==='memory'&&memoryTab&&['facts','decisions','documents'].includes(memoryTab)){memoryView=memoryTab;setTimeout(loadMemory,0)}})();</script>"""


def _focus_navigation_reload_ui() -> str:
    return """<script>const focusParams=new URLSearchParams(location.search),focusView=focusParams.get('view');if(['artem','idea'].includes(focusView)){view=focusView;setTimeout(()=>api(`/api/entries?kind=${focusView}&query=`).then(renderKnowledge).catch(error=>show(error.message,true)),50)}if(focusView==='memory'){memoryView=focusParams.get('memory_tab')||'context';if(memoryView!=='context')setTimeout(()=>api(`/api/memory/${memoryView}?query=`).then(renderMemory).catch(error=>show(error.message,true)),50)}</script>"""


def _projects_ui() -> str:
    return r"""<script>(()=>{const screen=document.querySelector('#projects'),node=(tag,text,id)=>{const el=document.createElement(tag);el.textContent=text;if(id)el.dataset.testid=id;return el};let modal;function form(item){modal?.remove();modal=document.createElement('div');modal.className='task-modal';modal.dataset.testid='project-modal';const box=document.createElement('form'),name=document.createElement('input'),description=document.createElement('textarea'),save=node('button','Сохранить','project-save'),cancel=node('button','Отмена','project-cancel'),error=node('div','project-feedback');name.dataset.testid='project-title';description.dataset.testid='project-description';name.value=item?.name||'';description.value=item?.description||'';box.append(node('h2',item?'Редактировать проект':'Новый проект'),name,description,save,cancel,error);modal.append(box);document.body.append(modal);name.focus();cancel.onclick=()=>modal.remove();box.onsubmit=async e=>{e.preventDefault();try{const url=item?`/api/projects/${item.id}/edit`:'/api/projects';await api(url,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:name.value,description:description.value})});modal.remove();load()}catch(x){error.className='error';error.textContent=x.message}}}async function render(){if(view!=='projects')return;screen.classList.remove('hidden');screen.replaceChildren();knowledge.classList.add('hidden');memory.classList.add('hidden');entries.classList.add('hidden');const add=node('button','Новый проект','projects-new');add.onclick=()=>form();screen.append(add);const items=await api('/api/projects');for(const item of items){const card=node('article',undefined,`project-card-${item.id}`);card.className='entry';card.append(node('strong',item.name),node('p',item.description),node('div',`${item.status} · открытых задач: ${item.open_tasks} · рекомендаций: ${item.artem} · идей: ${item.ideas}`,'meta'));if(item.id!=='unassigned'){const actions=node('div');actions.className='actions';const edit=node('button','Редактировать',`project-edit-${item.id}`);edit.onclick=()=>form(item);actions.append(edit);if(item.status==='active'){const archive=node('button','Архивировать',`project-archive-${item.id}`);archive.onclick=async()=>{archive.disabled=true;try{await api(`/api/projects/${item.id}/archive`,{method:'POST'});load()}catch(x){archive.disabled=false;show(x.message,true)}};actions.append(archive)}card.append(actions)}card.id=`project-${item.id}`;screen.append(card)}}const oldLoad=load;load=async()=>{if(view==='projects'){await render();return}screen.classList.add('hidden');await oldLoad()};for(const tab of document.querySelectorAll('[data-view]'))tab.addEventListener('click',()=>{if(tab.dataset.view==='projects')setTimeout(load,0);else screen.classList.add('hidden')});setTimeout(()=>{if(view==='projects')load()},0)})();</script>"""


def _project_assignment_ui() -> str:
    return r"""<script>(()=>{async function active(){return (await api('/api/projects')).filter(x=>x.status==='active')}async function selectFor(form,current=''){let select=form.querySelector('[name="project_id"]');if(!select){const label=document.createElement('label');label.textContent='Проект';select=document.createElement('select');select.name='project_id';select.dataset.testid='knowledge-project';label.append(select);form.insertBefore(label,form.querySelector('button'))}select.replaceChildren(new Option('Без проекта',''));for(const p of await active())select.append(new Option(p.name,p.id));select.value=current||select.dataset.current||''}const add=document.querySelector('#add');if(add){selectFor(add).catch(()=>{});if(!add.querySelector('[data-testid="intake"]'))add.onsubmit=async event=>{event.preventDefault();const form=new FormData(add);try{await api('/api/entries',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({kind:view,topic:form.get('topic'),text:form.get('text'),tags:form.get('tags'),project_id:form.get('project_id')||null})});add.reset();await selectFor(add);show('Запись добавлена');load()}catch(error){show(error.message,true)}}}const seed=()=>{const form=document.querySelector('[data-testid="task-form"]');if(form&&form.dataset.projects!=='1'){form.dataset.projects='1';selectFor(form).catch(()=>{})}};seed();new MutationObserver(seed).observe(document.body,{childList:true,subtree:true});})();</script>"""


def _project_experience_ui() -> str:
    return r"""<script>(()=>{const projectUrl=id=>`/?view=projects&project_id=${encodeURIComponent(id)}#project-${id}`;const objectUrl=(kind,id)=>kind==='task'?`/?view=tasks&focus_task=${encodeURIComponent(id)}#task-${id}`:`/?view=${kind}&focus_entry=${encodeURIComponent(id)}#knowledge-${id}`;const text=(tag,value)=>{const el=document.createElement(tag);el.textContent=value;return el};async function names(){return Object.fromEntries((await api('/api/projects')).filter(x=>x.id!=='unassigned').map(x=>[x.id,x.name]))}function link(card,id,name){if(!id||card.querySelector('[data-testid^="project-link-"]'))return;const a=document.createElement('a');a.href=projectUrl(id);a.dataset.testid=`project-link-${id}`;a.textContent=`Проект: ${name||'Архивный проект'}`;card.append(a)}const oldTasks=renderTasks;renderTasks=items=>{oldTasks(items);names().then(map=>items.forEach(item=>link(document.getElementById(`task-${item.id}`),item.project_id,map[item.project_id]))).catch(()=>{})};const oldKnowledge=renderKnowledge;renderKnowledge=items=>{oldKnowledge(items);names().then(map=>items.forEach(item=>{const card=document.getElementById(`knowledge-${item.id}`)||document.querySelector(`[data-testid="knowledge-entry-${item.id}"]`);link(card,item.project_id,map[item.project_id]);if(!card||card.querySelector('[data-testid^="assign-project-"]'))return;const button=text('button','Назначить проект');button.dataset.testid=`assign-project-${item.id}`;button.onclick=async()=>{const value=prompt('ID проекта (пусто — снять назначение)',item.project_id||'');try{await api('/api/projects/assign',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({object_id:item.id,project_id:value||null})});load()}catch(error){show(error.message,true)}};card.append(button)})).catch(()=>{})};const prior=load;load=async()=>{const p=new URLSearchParams(location.search);if(view==='projects'&&p.get('project_id')){const screen=document.querySelector('#projects');screen.classList.remove('hidden');screen.replaceChildren();try{const data=await api(`/api/projects/${encodeURIComponent(p.get('project_id'))}`),project=data.project;const card=text('section','');card.id=`project-${project.id}`;card.className='entry';card.append(text('h2',project.name),text('p',project.description||'Без описания'),text('div',project.status==='archived'?'Архивный':'Активный'));for(const [key,label,kind] of [['tasks','Открытые задачи','task'],['artem','Рекомендации Артёма','artem'],['ideas','Мои идеи','idea']]){const section=document.createElement('section');section.append(text('h3',label));if(!data[key].length)section.append(text('p','Записей нет.'));for(const item of data[key]){const line=document.createElement('a');line.href=objectUrl(kind,item.id);line.textContent=item.title;line.dataset.testid=`project-open-${kind}-${item.id}`;section.append(line)}card.append(section)}screen.append(card)}catch(error){screen.append(text('p',error.message))}return}await prior()};new MutationObserver(()=>{for(const card of document.querySelectorAll('[data-testid^="project-card-"]')){if(card.querySelector('[data-testid^="project-open-"]'))continue;const id=card.dataset.testid.slice('project-card-'.length);const open=text('a','Открыть');open.href=projectUrl(id);open.dataset.testid=`project-open-${id}`;card.querySelector('.actions')?.prepend(open)}}).observe(document.body,{childList:true,subtree:true});})();</script>"""


def _project_assignment_controls() -> str:
    return r"""<script>(()=>{async function enhance(){const projects=(await api('/api/projects')).filter(x=>x.status==='active');for(const button of document.querySelectorAll('[data-testid^="assign-project-"]')){if(button.dataset.ready)continue;button.dataset.ready='1';const id=button.dataset.testid.slice('assign-project-'.length),select=document.createElement('select'),save=document.createElement('button');select.dataset.testid=`project-select-${id}`;select.append(new Option('Без проекта',''));for(const p of projects)select.append(new Option(p.name,p.id));save.textContent='Сохранить проект';save.onclick=async()=>{try{await api('/api/projects/assign',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({object_id:id,project_id:select.value||null})});load()}catch(error){show(error.message,true)}};button.replaceWith(select,save)}}enhance().catch(()=>{});new MutationObserver(()=>enhance().catch(()=>{})).observe(document.body,{childList:true,subtree:true});})();</script>"""


def _project_modal_refresh() -> str:
    return r"""<script>window.metricHitRefreshProjects=async(form,current)=>{const select=form?.elements?.project_id;if(!select)return;try{const projects=await api('/api/projects');select.replaceChildren(new Option('Без проекта',''));for(const p of projects)if(p.status==='active')select.append(new Option(p.name,p.id));select.value=current||''}catch(error){show(error.message,true)}}</script>"""


def _project_task_filter_ui() -> str:
    return r"""<script>(()=>{async function add(){if(view!=='tasks')return;const bar=document.querySelector('#task-controls');if(!bar||bar.querySelector('[data-testid="task-project-filter"]'))return;const select=document.createElement('select');select.dataset.testid='task-project-filter';select.append(new Option('Все проекты','all'),new Option('Без проекта','none'));for(const p of await api('/api/projects'))if(p.id!=='unassigned')select.append(new Option(p.name,p.id));const params=new URLSearchParams(location.search);select.value=params.get('project')||'all';select.onchange=()=>{params.set('view','tasks');params.set('project',select.value);history.replaceState(null,'',`/?${params}`);load()};bar.append(select)}new MutationObserver(()=>add().catch(()=>{})).observe(document.body,{childList:true,subtree:true});add().catch(()=>{})})();</script>"""


def create_operator_app(database_path: Path) -> FastAPI:
    store = KnowledgeStore(database_path)
    projects = ProjectStore(database_path)
    token = secrets.token_urlsafe(32)
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.get("/favicon.ico", status_code=204)
    def favicon() -> None:
        return None

    @app.get("/", response_class=HTMLResponse)
    def page(request: Request, view: str = "overview", focus_task: str | None = None) -> str:
        focused = focus_task if focus_task and any(task["id"] == focus_task for task in store.list_tasks()) else None
        return _page(token, focused, view)

    @app.get("/api/entries")
    def entries(kind: str, query: str = "") -> JSONResponse:
        try:
            tasks = {task["knowledge_entry_id"]: task for task in store.list_tasks()}
            items = _entries(store, kind, query)
            return JSONResponse([{**item, "task": tasks.get(item["id"])} for item in items])
        except KnowledgeError as error:
            return _error(str(error), 400)

    @app.get("/api/dashboard")
    def dashboard() -> JSONResponse:
        return JSONResponse(_dashboard(store, database_path))

    @app.get("/api/projects")
    def project_list() -> JSONResponse:
        return JSONResponse(projects.list())

    @app.get("/api/projects/{project_id}")
    def project_detail(project_id: str) -> JSONResponse:
        try:
            return JSONResponse(projects.detail(project_id))
        except KnowledgeError as error:
            return _error(str(error), 404)

    @app.post("/api/projects")
    async def project_create(request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token: return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json(); item, created = projects.create(name=_text(payload, "name"), description=_optional_text(payload, "description") or ""); item["created"] = created
            return JSONResponse(item)
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error: return _error(str(error), 400)

    @app.post("/api/projects/{project_id}/edit")
    async def project_edit(project_id: str, request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token: return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json(); return JSONResponse(projects.edit(project_id=project_id, name=_text(payload, "name"), description=_optional_text(payload, "description") or ""))
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error: return _error(str(error), 400)

    @app.post("/api/projects/{project_id}/archive")
    async def project_archive(project_id: str, request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token: return _error("missing or invalid startup token", 403)
        try: return JSONResponse(projects.archive(project_id))
        except KnowledgeError as error: return _error(str(error), 400)

    @app.post("/api/projects/assign")
    async def project_assign(request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token: return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json(); projects.assign(object_id=_text(payload, "object_id"), project_id=_optional_text(payload, "project_id")); return JSONResponse({"ok": True})
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error: return _error(str(error), 400)

    @app.get("/api/search")
    def search(query: str = "", item_type: str = "all", status: str = "all") -> JSONResponse:
        try:
            return JSONResponse({"query": query, "results": global_search(database_path, query=query, item_type=item_type, status=status)})
        except ValueError as error:
            return _error(str(error), 400)

    @app.get("/api/activity")
    def activity(period: str = "all", item_type: str = "all", action: str = "all", offset: int = 0) -> JSONResponse:
        try:
            return JSONResponse(list_activity(database_path, period=period, item_type=item_type, action=action, offset=offset))
        except ValueError as error:
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

    @app.get("/api/memory/documents")
    def memory_documents(query: str = "") -> JSONResponse:
        return JSONResponse(_memory_documents(database_path, query))

    @app.post("/api/entries")
    async def add_entry(request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token:
            return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json()
            projects.validate_assignment(_optional_text(payload, "project_id"))
            item = store.add(
                kind=_text(payload, "kind"), topic=_text(payload, "topic"), text=_text(payload, "text"),
                tags=_optional_text(payload, "tags"),
            )
            projects.assign(object_id=str(item["id"]), project_id=_optional_text(payload, "project_id"))
            return JSONResponse(item, status_code=201)
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error:
            return _error(str(error), 400)

    @app.post("/api/tasks")
    async def add_task(request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token:
            return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json()
            projects.validate_assignment(_optional_text(payload, "project_id"))
            entry_id = _optional_text(payload, "id")
            if entry_id:
                item, created = store.to_task_with_created(
                    entry_id=entry_id, title=_optional_text(payload, "title"),
                    description=_optional_text(payload, "description"),
                    priority=_optional_text(payload, "priority") or "normal",
                    due_date=_optional_text(payload, "due_date"),
                )
                item["created"] = created
            else:
                item = store.create_task(
                    title=_text(payload, "title"), description=_text(payload, "description"),
                    priority=_optional_text(payload, "priority") or "normal", due_date=_optional_text(payload, "due_date"),
                )
                item["created"] = True
            projects.assign(object_id=str(item["id"]), project_id=_optional_text(payload, "project_id"))
            return JSONResponse(item)
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error:
            return _error(str(error), 400)

    @app.get("/api/tasks")
    def tasks(query: str = "", status: str = "all", priority: str = "all", due: str = "all", sort: str = "recommended", project: str = "all") -> JSONResponse:
        try:
            return JSONResponse(store.list_tasks(query=query, status=status, priority=priority, due=due, sort=sort, project=project))
        except KnowledgeError as error:
            return _error(str(error), 400)

    @app.get("/api/tasks/today")
    def today_tasks() -> JSONResponse:
        return JSONResponse(store.today_tasks())

    @app.post("/api/tasks/{task_id}/edit")
    async def edit_task(task_id: str, request: Request) -> JSONResponse:
        if request.headers.get(TOKEN_HEADER) != token:
            return _error("missing or invalid startup token", 403)
        try:
            payload = await request.json()
            projects.validate_assignment(_optional_text(payload, "project_id"))
            item = store.edit_task(
                task_id=task_id, title=_text(payload, "title"), description=_text(payload, "description"),
                priority=_text(payload, "priority"), due_date=_optional_text(payload, "due_date"),
            )
            projects.assign(object_id=task_id, project_id=_optional_text(payload, "project_id"))
            return JSONResponse(item)
        except (KnowledgeError, ValueError, TypeError, json.JSONDecodeError) as error:
            return _error(str(error), 400)

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
