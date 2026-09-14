from __future__ import annotations

import hashlib, json, os, secrets
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

app = FastAPI(title="Навигатор продаж", docs_url=None, redoc_url=None)
DEFAULT_SCENARIO = {
 "start":{"client":"Первый холодный контакт","manager":"Здравствуйте. Меня зовут [Имя], я из команды MetricHit. Мы занимаемся продвижением сайтов в Яндексе. С кем можно поговорить по вопросу продвижения вашего сайта?","hint":"Сначала найдите человека, который отвечает за сайт и продвижение.","choices":[{"label":"Я отвечаю за сайт","next":"qualification"},{"label":"Это другой коллега","next":"contact"},{"label":"Сейчас неудобно говорить","next":"time"}]},
 "qualification":{"client":"Да, я отвечаю за сайт.","manager":"Отлично, тогда коротко уточню: вы уже продвигаете сайт в Яндексе или это пока в планах?","hint":"Дайте собеседнику выбрать статус без давления.","choices":[{"label":"Уже продвигаем","next":"current_provider"},{"label":"Пока в планах","next":"planning"}]},
 "contact":{"client":"Этим занимается другой коллега.","manager":"Спасибо. Подскажите, пожалуйста, как к нему обратиться и когда будет удобно коротко созвониться?","hint":"Зафиксируйте имя, роль и время контакта.","choices":[]},
 "planning":{"client":"Пока это только в планах.","manager":"Понял. Что должно произойти, чтобы вы вернулись к вопросу продвижения: новый сайт, сезон или конкретная бизнес-цель?","hint":"Выясните триггер следующего контакта.","choices":[]},
 "current_provider":{"client":"Мы уже работаем с другим подрядчиком.","manager":"Понимаю. Не предлагаю менять всё прямо сейчас — хочу понять, что для вас важнее всего в текущем результате.","hint":"Не спорьте с выбором клиента.","choices":[{"label":"Нас не устраивает цена","next":"price"},{"label":"Нам важна предсказуемость результата","next":"proof"},{"label":"Сейчас нет времени разбираться","next":"time"}]},
 "price":{"client":"Нас прежде всего не устраивает цена.","manager":"Давайте сравним не только сумму, а стоимость результата. Какая задача должна окупиться в первую очередь?","hint":"Переводите разговор от скидки к экономике.","choices":[]},
 "proof":{"client":"Нам важна предсказуемость результата.","manager":"Покажу, как мы фиксируем стартовую точку, контрольные метрики и формат отчёта.","hint":"Предлагайте прозрачный процесс.","choices":[]},
 "time":{"client":"Сейчас нет времени разбираться.","manager":"Тогда не будем перегружать вас. Я подготовлю вариант, который можно оценить за пять минут.","hint":"Снижайте усилие клиента.","choices":[]}}
SESSIONS:set[str]=set()

def store_path(): return Path(os.getenv("SALES_NAVIGATOR_DATA_PATH", Path(__file__).resolve().parents[2]/"data"/"sales_navigator"/"scenario.json"))
def revision(s): return hashlib.sha256(json.dumps(s,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def validate(s):
 if not isinstance(s,dict) or "start" not in s: raise ValueError("Нужна стартовая ветка.")
 for key,node in s.items():
  if not isinstance(key,str) or not key or not isinstance(node,dict): raise ValueError("Некорректная ветка.")
  if any(not isinstance(node.get(x),str) or not node[x].strip() for x in ("client","manager","hint")): raise ValueError("Заполните все поля ветки.")
  if not isinstance(node.get("choices"),list): raise ValueError("Варианты ответа должны быть списком.")
  for choice in node["choices"]:
   if not isinstance(choice,dict) or not choice.get("label") or choice.get("next") not in s: raise ValueError("Укажите текст и существующую следующую ветку.")
 return s
def load():
 p=store_path()
 if not p.exists(): return deepcopy(DEFAULT_SCENARIO)
 try: return validate(json.loads(p.read_text(encoding="utf-8")))
 except Exception as error: raise HTTPException(500,"Сохранённый сценарий повреждён; он не был перезаписан.") from error
def save(s,old):
 validate(s)
 if old!=revision(load()): raise HTTPException(409,"Сценарий изменён в другой вкладке. Обновите редактор.")
 p=store_path();p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(".new")
 with t.open("w",encoding="utf-8") as f: json.dump(s,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
 os.replace(t,p);return {"scenario":s,"revision":revision(s)}
def auth(r):
 if r.cookies.get("sales_session") not in SESSIONS: raise HTTPException(401,"Требуется вход")
def layout(title,body):
 body = body.replace("{{", "{").replace("}}", "}")
 return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>body{{margin:0;background:#111827;color:#f8fafc;font:16px system-ui}}main{{max-width:960px;margin:auto;padding:28px 20px}}header{{display:flex;justify-content:space-between;gap:12px;margin-bottom:24px}}a,button{{background:#1e293b;color:white;border:1px solid #475569;border-radius:8px;padding:10px;text-decoration:none;font:inherit;cursor:pointer}}button.primary{{background:#22d3ee;color:#083344;font-weight:700}}.card{{background:#0f172a;border:1px solid #334155;border-radius:16px;padding:22px}}.label{{color:#94a3b8;font-size:12px;text-transform:uppercase}}.answer{{background:#172554;border-left:3px solid #22d3ee;padding:12px;margin:8px 0}}.choices{{display:grid;gap:8px;margin-top:18px}}.editor{{display:grid;grid-template-columns:210px 1fr;gap:16px}}textarea,input,select{{box-sizing:border-box;width:100%;margin:5px 0 13px;padding:9px;background:#111827;color:white;border:1px solid #475569;border-radius:7px;font:inherit}}textarea{{min-height:72px}}.choice{{display:grid;grid-template-columns:1fr 150px auto;gap:7px}}.status{{color:#67e8f9}}@media(max-width:650px){{.editor,.choice{{grid-template-columns:1fr}}header{{flex-direction:column}}}}</style><main><header><h1>{title}</h1><div><a href="/">Сценарий</a> <a href="/editor">Редактор</a> <form style="display:inline" method="post" action="/logout"><button>Выйти</button></form></div></header>{body}</main></html>'''
def app_page():
 s=load();return layout("Навигатор продаж",f'''<section class="card"><div class="label">Клиент говорит</div><h2 id="client"></h2><div class="label">Ответ менеджера</div><div id="manager" class="answer"></div><p id="hint"></p><div id="choices" class="choices"></div><p><button id="back">← Назад</button> <button id="restart">Начать заново</button></p></section><script>const n={json.dumps(s,ensure_ascii=False)};let c='start',h=[];function r(){{let x=n[c];client.textContent=x.client;manager.textContent=x.manager;hint.textContent='Подсказка: '+x.hint;choices.innerHTML='';x.choices.forEach(y=>{{let b=document.createElement('button');b.textContent=y.label;b.onclick=()=>{{h.push(c);c=y.next;r()}};choices.append(b)}});back.disabled=!h.length}}back.onclick=()=>{{c=h.pop();r()}};restart.onclick=()=>{{c='start';h=[];r()}};r()</script>''')
def editor_page(): return layout("Редактор сценария",'''<div class="editor"><aside class="card"><div id="nodes"></div><button id="new">+ Новая ветка</button></aside><section class="card"><label>Что говорит клиент<textarea id="client"></textarea></label><label>Ответ менеджера<textarea id="manager"></textarea></label><label>Подсказка<textarea id="hint"></textarea></label><div id="choices"></div><button id="add">+ Вариант ответа</button><p><button class="primary" id="save">Сохранить</button> <button id="cancel">Отменить</button> <span id="status" class="status"></span></p></section></div><script>let d,id='start';const $=x=>document.querySelector(x);async function load(){{d=await (await fetch('/api/scenario')).json();draw()}}function collect(){{let n=d.scenario[id];n.client=$('#client').value;n.manager=$('#manager').value;n.hint=$('#hint').value;document.querySelectorAll('[data-l]').forEach(x=>n.choices[x.dataset.l].label=x.value);document.querySelectorAll('[data-n]').forEach(x=>n.choices[x.dataset.n].next=x.value)}function draw(){{let n=d.scenario[id],ids=Object.keys(d.scenario);$('#nodes').innerHTML=ids.map(x=>`<button data-id="${{x}}">${{x===id?'● ':''}}${{x}}</button>`).join('<br>');document.querySelectorAll('[data-id]').forEach(b=>b.onclick=()=>{{collect();id=b.dataset.id;draw()}});$('#client').value=n.client;$('#manager').value=n.manager;$('#hint').value=n.hint;$('#choices').innerHTML=n.choices.map((x,i)=>`<div class="choice"><input data-l="${{i}}" value="${{x.label}}"><select data-n="${{i}}">${{ids.map(k=>`<option ${{k===x.next?'selected':''}}>${{k}}</option>`).join('')}}</select><button data-x="${{i}}">×</button></div>`).join('');document.querySelectorAll('[data-x]').forEach(b=>b.onclick=()=>{{collect();n.choices.splice(b.dataset.x,1);draw()}})}$('#add').onclick=()=>{{collect();d.scenario[id].choices.push({{label:'Новый вариант',next:'start'}});draw()}};$('#new').onclick=()=>{{collect();let i=1,k;while(d.scenario[k='new-node-'+i++]);d.scenario[k]={{client:'Ответ клиента',manager:'Новая реплика',hint:'Подсказка',choices:[]}};id=k;draw()}};$('#cancel').onclick=load;$('#save').onclick=async()=>{{collect();let r=await fetch('/api/scenario',{{method:'PUT',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}}),x=await r.json();if(r.ok){{d=x;status.textContent='Сохранено'}}else status.textContent=x.detail}};load()</script>''')
LOGIN='''<!doctype html><html lang="ru"><meta charset="utf-8"><body style="background:#111827;color:white;font:16px system-ui;padding:30px"><form method="post" action="/login"><h1>Навигатор продаж</h1><p>Демо-пароль: <code>demo</code></p><input name="password" type="password"><button>Войти</button></form></body></html>'''
@app.get("/",response_class=HTMLResponse)
def home(r:Request): return HTMLResponse(app_page() if r.cookies.get("sales_session") in SESSIONS else LOGIN)
@app.get("/editor",response_class=HTMLResponse)
def editor(r:Request):
 auth(r)
 additions = '''<style>
.editor-intro{margin:0 0 18px;padding:14px 16px;border:1px solid #334155;border-radius:12px;background:#172554;color:#dbeafe;line-height:1.45}.editor-intro strong{color:#67e8f9}.nodes{padding:14px!important}.nodes button{border:0!important;background:transparent!important;text-align:left;width:100%;margin:2px 0;padding:10px!important}.nodes button:hover{background:#1e293b!important}.nodes button:first-child{background:#164e63!important}.editor .card{box-shadow:0 18px 45px rgba(0,0,0,.2)}.editor label{display:block;font-weight:600}.editor label:before{content:'Редактируйте текст так, как его увидит менеджер';display:block;color:#94a3b8;font-size:12px;font-weight:400;margin-top:3px}.editor label:nth-of-type(2):before{content:'Эта реплика показывается менеджеру';}.editor label:nth-of-type(3):before{content:'Короткая подсказка, не для клиента';}.choice{padding:8px;border:1px solid #334155;border-radius:10px;margin:8px 0}.choice:before{content:'Если клиент отвечает:';color:#94a3b8;font-size:12px;grid-column:1/-1}</style><script>
const russianNames={start:'Первый звонок',qualification:'Уточнение ситуации',contact:'Передать контакт',planning:'Пока в планах',current_provider:'Уже есть подрядчик',price:'Возражение по цене',proof:'Нужны доказательства',time:'Нет времени',calculation:'Запрос расчёта',pilot:'Пилотный запуск',report:'Пример отчёта'};
function russianName(id){return russianNames[id]||'Новая ветка';}
function localizeEditor(){document.querySelectorAll('[data-id]').forEach(button=>{const active=button.textContent.includes('●');button.textContent=(active?'● ':'')+russianName(button.dataset.id)});document.querySelectorAll('[data-n] option').forEach(option=>option.textContent=russianName(option.value));}
const editorObserver=new MutationObserver(localizeEditor);editorObserver.observe(document.body,{childList:true,subtree:true});localizeEditor();
</script>'''
 page = editor_page().replace('<div class="editor">', '<div class="editor-intro"><strong>Как работать с редактором.</strong> Слева выберите этап разговора. Справа измените текст и варианты ответов. Нажмите «Сохранить», когда закончите.</div><div class="editor">')
 return HTMLResponse(page.replace('</main></html>', additions + '</main></html>'))
@app.post("/login")
async def login(r:Request):
 f=parse_qs((await r.body()).decode());
 if f.get("password",[""])[0]!=os.getenv("SALES_NAVIGATOR_PASSWORD","demo"): return RedirectResponse("/",303)
 t=secrets.token_urlsafe();SESSIONS.add(t);x=RedirectResponse("/",303);x.set_cookie("sales_session",t,httponly=True,samesite="lax");return x
@app.post("/logout")
def logout(r:Request): SESSIONS.discard(r.cookies.get("sales_session",""));x=RedirectResponse("/",303);x.delete_cookie("sales_session");return x
@app.get("/api/scenario")
def get_scenario(r:Request): auth(r);s=load();return {"scenario":s,"revision":revision(s)}
@app.put("/api/scenario")
async def put_scenario(r:Request):
 auth(r);p=await r.json()
 try:return save(p.get("scenario"),p.get("revision"))
 except ValueError as e:raise HTTPException(422,str(e))
@app.get("/api/scenario/{node_id}")
def node(node_id:str,r:Request):
 auth(r)
 n=load().get(node_id)
 if not n: raise HTTPException(404,"Ветка не найдена")
 return n
