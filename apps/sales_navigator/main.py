from __future__ import annotations

import hashlib, json, os, secrets, html
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
SESSIONS:dict[str,str]={}

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
def auth(r,required_role=None):
 role=SESSIONS.get(r.cookies.get("sales_session"))
 if not role: raise HTTPException(401,"Требуется вход")
 if required_role and role!=required_role: raise HTTPException(403,"Недостаточно прав")
 return role
def layout(title,body,role):
 editor_link=' <a href="/editor">Редактор</a>' if role=='admin' else ''
 return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title><style>body{{margin:0;background:#111827;color:#f8fafc;font:16px system-ui}}main{{max-width:960px;margin:auto;padding:28px 20px}}header{{display:flex;justify-content:space-between;gap:12px;margin-bottom:24px}}a,button{{background:#1e293b;color:white;border:1px solid #475569;border-radius:8px;padding:10px;text-decoration:none;font:inherit;cursor:pointer}}button.primary{{background:#22d3ee;color:#083344;font-weight:700}}.card{{background:#0f172a;border:1px solid #334155;border-radius:16px;padding:22px}}.label{{color:#94a3b8;font-size:12px;text-transform:uppercase}}.answer{{background:#172554;border-left:3px solid #22d3ee;padding:12px;margin:8px 0}}.choices{{display:grid;gap:8px;margin-top:18px}}.editor{{display:grid;grid-template-columns:210px 1fr;gap:16px}}textarea,input,select{{box-sizing:border-box;width:100%;margin:5px 0 13px;padding:9px;background:#111827;color:white;border:1px solid #475569;border-radius:7px;font:inherit}}textarea{{min-height:72px}}.choice{{display:grid;grid-template-columns:1fr 150px auto;gap:7px}}.status{{color:#67e8f9}}@media(max-width:650px){{.editor,.choice{{grid-template-columns:1fr}}header{{flex-direction:column}}}}</style><main><header><h1>{title}</h1><div><a href="/">Сценарий</a>{editor_link} <form style="display:inline" method="post" action="/logout"><button>Выйти</button></form></div></header>{body}</main></html>'''
def app_page(role):
 s=load();is_admin=role=='admin'
 edit_controls=''' <button id="edit">Редактировать этот шаг</button></p><section id="edit-panel" class="card" hidden style="margin-top:18px"><div class="label">Редактирование текущего шага</div><label>Клиент говорит<textarea id="edit-client"></textarea></label><label>Ответ менеджера<textarea id="edit-manager"></textarea></label><label>Подсказка для менеджера<textarea id="edit-hint"></textarea></label><div class="label">Варианты ответа клиента</div><div id="edit-choices" class="choices"></div><p><button id="add-choice">+ Добавить вариант ответа</button></p><p><button id="save-edit" class="primary">Сохранить изменения</button> <button id="cancel-edit">Отменить</button> <span id="edit-status" class="status"></span></p></section>''' if is_admin else '</p>'
 edit_script=f'''function fill(){{let x=n[c],ids=Object.keys(n);$('edit-client').value=x.client;$('edit-manager').value=x.manager;$('edit-hint').value=x.hint;$('edit-choices').innerHTML=x.choices.map((y,i)=>`<div class="choice" data-choice="${{i}}"><input aria-label="Вариант ответа клиента" value="${{y.label}}"><select aria-label="Следующий шаг">${{ids.map(k=>`<option value="${{k}}" ${{k===y.next?'selected':''}}>${{name(k)}}</option>`).join('')}}</select><button data-remove="${{i}}">Удалить</button></div>`).join('');document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{{pull();n[c].choices.splice(+b.dataset.remove,1);fill()}})}}function pull(){{let x=n[c];x.client=$('edit-client').value.trim();x.manager=$('edit-manager').value.trim();x.hint=$('edit-hint').value.trim();document.querySelectorAll('[data-choice]').forEach(row=>{{let i=+row.dataset.choice;x.choices[i].label=row.querySelector('input').value.trim();x.choices[i].next=row.querySelector('select').value}})}}function freshNode(){{let i=1,k;while(n[k='new-node-'+i++]);n[k]={{client:'Ответ клиента',manager:'Новая реплика менеджера',hint:'Подсказка для менеджера',choices:[]}};return k}}$('edit').onclick=()=>{{editing=!editing;$('edit-panel').hidden=!editing;$('edit').textContent=editing?'Закрыть редактирование':'Редактировать этот шаг';$('edit-status').textContent='';if(editing)fill()}};$('add-choice').onclick=()=>{{pull();let from=c,k=freshNode();n[from].choices.push({{label:'Новый вариант ответа',next:k}});h.push(from);c=k;r();fill();$('edit-client').focus()}};$('cancel-edit').onclick=()=>{{editing=false;$('edit-panel').hidden=true;$('edit').textContent='Редактировать этот шаг';$('edit-status').textContent='';r()}};$('save-edit').onclick=async()=>{{pull();let q=await fetch('/api/scenario',{{method:'PUT',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{scenario:n,revision:v}})}}),z=await q.json();if(!q.ok){{$('edit-status').textContent=z.detail;return}}v=z.revision;$('edit-status').textContent='Сохранено';editing=false;$('edit-panel').hidden=true;$('edit').textContent='Редактировать этот шаг';r()}};''' if is_admin else ''
 return layout("Навигатор продаж",f'''<section class="card"><div class="label">Клиент говорит</div><h2 id="client"></h2><div class="label">Ответ менеджера</div><div id="manager" class="answer"></div><p id="hint"></p><div id="choices" class="choices"></div><p><button id="back">← Назад</button> <button id="restart">Начать заново</button>{edit_controls}</section><script>const n={json.dumps(s,ensure_ascii=False)},names={{start:'Первый звонок',qualification:'Уточнение ситуации',contact:'Передать контакт',planning:'Пока в планах',current_provider:'Уже есть подрядчик',price:'Возражение по цене',proof:'Нужны доказательства',time:'Нет времени'}};let c='start',h=[],editing=false,v='{revision(s)}';const $=x=>document.getElementById(x),name=x=>names[x]||'Новая ветка';function r(){{let x=n[c];$('client').textContent=x.client;$('manager').textContent=x.manager;$('hint').textContent='Подсказка: '+x.hint;$('choices').innerHTML='';x.choices.forEach(y=>{{let b=document.createElement('button');b.textContent=y.label;b.onclick=()=>{{h.push(c);c=y.next;r()}};$('choices').append(b)}});$('back').disabled=!h.length}}{edit_script}$('back').onclick=()=>{{if(!editing){{c=h.pop();r()}}}};$('restart').onclick=()=>{{if(!editing){{c='start';h=[];r()}}}};r()</script>''',role)
def editor_page(): return layout("Редактор сценария",'''<div class="editor"><aside class="card"><div id="nodes"></div><button id="new">+ Новая ветка</button></aside><section class="card"><label>Что говорит клиент<textarea id="client"></textarea></label><label>Ответ менеджера<textarea id="manager"></textarea></label><label>Подсказка<textarea id="hint"></textarea></label><div id="choices"></div><button id="add">+ Вариант ответа</button><p><button class="primary" id="save">Сохранить</button> <button id="cancel">Отменить</button> <span id="status" class="status"></span></p></section></div><script>let d,id='start';const names={{start:'Первый звонок',qualification:'Уточнение ситуации',contact:'Передать контакт',planning:'Пока в планах',current_provider:'Уже есть подрядчик',price:'Возражение по цене',proof:'Нужны доказательства',time:'Нет времени'}};const name=x=>names[x]||'Новая ветка';const $=x=>document.querySelector(x);async function load(){{d=await (await fetch('/api/scenario')).json();id='start';draw()}}function collect(){{let n=d.scenario[id];n.client=$('#client').value;n.manager=$('#manager').value;n.hint=$('#hint').value;document.querySelectorAll('[data-l]').forEach(x=>n.choices[x.dataset.l].label=x.value);document.querySelectorAll('[data-n]').forEach(x=>n.choices[x.dataset.n].next=x.value)}function draw(){{let n=d.scenario[id],ids=Object.keys(d.scenario);$('#nodes').innerHTML=ids.map(x=>`<button data-id="${{x}}">${{x===id?'● ':''}}${{name(x)}}</button>`).join('<br>');document.querySelectorAll('[data-id]').forEach(b=>b.onclick=()=>{{collect();id=b.dataset.id;draw()}});$('#client').value=n.client;$('#manager').value=n.manager;$('#hint').value=n.hint;$('#choices').innerHTML=n.choices.map((x,i)=>`<div class="choice"><input data-l="${{i}}" value="${{x.label}}"><select data-n="${{i}}">${{ids.map(k=>`<option value="${{k}}" ${{k===x.next?'selected':''}}>${{name(k)}}</option>`).join('')}}</select><button data-x="${{i}}">×</button></div>`).join('');document.querySelectorAll('[data-x]').forEach(b=>b.onclick=()=>{{collect();n.choices.splice(b.dataset.x,1);draw()}})}function freshNode(){{let i=1,k;while(d.scenario[k='new-node-'+i++]);d.scenario[k]={{client:'Ответ клиента',manager:'Новая реплика менеджера',hint:'Подсказка для менеджера',choices:[]}};return k}}$('#add').onclick=()=>{{collect();let from=id,k=freshNode();d.scenario[from].choices.push({{label:'Новый вариант ответа',next:k}});id=k;draw();$('#client').focus()}};$('#new').onclick=()=>{{collect();id=freshNode();draw();$('#client').focus()}};$('#cancel').onclick=load;$('#save').onclick=async()=>{{collect();let r=await fetch('/api/scenario',{{method:'PUT',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}}),x=await r.json();if(r.ok){{d=x;status.textContent='Сохранено'}}else status.textContent=x.detail}};load()</script>'''.replace("{{", "{").replace("}}", "}"),'admin')
LOGIN='''<!doctype html><html lang="ru"><meta charset="utf-8"><body style="background:#111827;color:white;font:16px system-ui;padding:30px"><form method="post" action="/login"><h1>Навигатор продаж</h1><p>Введите пароль доступа.</p><input name="password" type="password" autocomplete="current-password"><button>Войти</button></form></body></html>'''
@app.get("/",response_class=HTMLResponse)
def home(r:Request):
 role=SESSIONS.get(r.cookies.get("sales_session"))
 if not role: return HTMLResponse(LOGIN)
 safeguard = '''<script>
let inlineSnapshot=null;Object.keys(n).filter(k=>!names[k]).forEach(k=>names[k]=`Новая ветка ${k.replace('new-node-','')}`.trim());
const mapLink=document.createElement('a');mapLink.href='/map';mapLink.textContent='Карта сценария';document.querySelector('header div').insertBefore(mapLink,document.querySelector('header form'));
function cancelInlineEdit(){if(inlineSnapshot){let original=JSON.parse(inlineSnapshot);Object.keys(n).forEach(k=>delete n[k]);Object.assign(n,original.scenario);c=original.current;h=original.history;}inlineSnapshot=null;editing=false;$('edit-panel').hidden=true;$('edit').textContent='Редактировать этот шаг';$('edit-status').textContent='';r();}
const openInlineEdit=$('edit').onclick,saveInlineEdit=$('save-edit').onclick;
$('edit').onclick=()=>{if(editing){cancelInlineEdit();return;}inlineSnapshot=JSON.stringify({scenario:n,current:c,history:h});openInlineEdit();};
$('cancel-edit').onclick=cancelInlineEdit;
$('save-edit').onclick=async()=>{await saveInlineEdit();if(!editing)inlineSnapshot=null;};
</script>'''
 page=app_page(role)
 return HTMLResponse(page.replace('</main></html>',safeguard+'</main></html>') if role=='admin' else page)
def map_page():
 s=load();labels={'start':'Первый звонок','qualification':'Уточнение ситуации','contact':'Передать контакт','planning':'Пока в планах','current_provider':'Уже есть подрядчик','price':'Возражение по цене','proof':'Нужны доказательства','time':'Нет времени'}
 cards=[]
 for key,node in s.items():
  links=''.join(f'<li><strong>{html.escape(x["label"])}</strong> → {html.escape(labels.get(x["next"],"Новая ветка"))}</li>' for x in node['choices']) or '<li>Конец ветки</li>'
  cards.append(f'<article class="map-node"><span>{html.escape(labels.get(key,"Новая ветка"))}</span><h2>{html.escape(node["client"])}</h2><p>{html.escape(node["manager"])}</p><ul>{links}</ul></article>')
 return f'''<style>.map-help{{color:#cbd5e1;margin:0 0 18px}}.map{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:16px}}.map-node{{background:#0f172a;border:1px solid #334155;border-radius:14px;padding:16px;box-shadow:0 12px 28px #0003}}.map-node>span{{color:#67e8f9;font-size:12px;text-transform:uppercase}}.map-node h2{{font-size:18px;margin:8px 0}}.map-node p{{color:#dbeafe;line-height:1.45}}.map-node ul{{border-top:1px solid #334155;margin:14px 0 0;padding:12px 0 0;list-style:none}}.map-node li{{padding:7px 0;color:#cbd5e1}}.map-node strong{{color:#f8fafc}}</style><p class="map-help">Все этапы и переходы сценария. Стрелка показывает, куда ведёт ответ клиента.</p><section class="map">{''.join(cards)}</section>'''
@app.get('/map',response_class=HTMLResponse)
def map_view(r:Request):
 role=SESSIONS.get(r.cookies.get('sales_session'))
 if not role: return RedirectResponse('/',303)
 return HTMLResponse(layout('Карта сценария',map_page(),role))
@app.get("/editor",response_class=HTMLResponse)
def editor(r:Request):
 auth(r,'admin')
 additions = '''<style>
.editor-intro{margin:0 0 18px;padding:14px 16px;border:1px solid #334155;border-radius:12px;background:#172554;color:#dbeafe;line-height:1.45}.editor-intro strong{color:#67e8f9}.nodes{padding:14px!important}.nodes button{border:0!important;background:transparent!important;text-align:left;width:100%;margin:2px 0;padding:10px!important}.nodes button:hover{background:#1e293b!important}.nodes button:first-child{background:#164e63!important}.editor .card{box-shadow:0 18px 45px rgba(0,0,0,.2)}.editor label{display:block;font-weight:600}.editor label:before{content:'Редактируйте текст так, как его увидит менеджер';display:block;color:#94a3b8;font-size:12px;font-weight:400;margin-top:3px}.editor label:nth-of-type(2):before{content:'Эта реплика показывается менеджеру';}.editor label:nth-of-type(3):before{content:'Короткая подсказка, не для клиента';}.choice{padding:8px;border:1px solid #334155;border-radius:10px;margin:8px 0}.choice:before{content:'Если клиент отвечает:';color:#94a3b8;font-size:12px;grid-column:1/-1}</style><script>
</script>'''
 page = editor_page().replace('<div class="editor">', '<div class="editor-intro"><strong>Как работать с редактором.</strong> Слева выберите этап разговора. Справа измените текст и варианты ответов. Нажмите «Сохранить», когда закончите.</div><div class="editor">')
 return HTMLResponse(page.replace('</main></html>', additions + '</main></html>'))
@app.post("/login")
async def login(r:Request):
 f=parse_qs((await r.body()).decode());
 supplied=f.get("password",[""])[0]
 admin_password=os.getenv("SALES_NAVIGATOR_ADMIN_PASSWORD")
 manager_password=os.getenv("SALES_NAVIGATOR_MANAGER_PASSWORD")
 if not admin_password or not manager_password or secrets.compare_digest(admin_password,manager_password):
  raise HTTPException(503,"Авторизация не настроена")
 role='admin' if secrets.compare_digest(supplied,admin_password) else 'manager' if secrets.compare_digest(supplied,manager_password) else None
 if not role: return RedirectResponse("/",303)
 t=secrets.token_urlsafe();SESSIONS[t]=role;x=RedirectResponse("/",303);x.set_cookie("sales_session",t,httponly=True,samesite="lax",secure=True);return x
@app.post("/logout")
def logout(r:Request): SESSIONS.pop(r.cookies.get("sales_session",""),None);x=RedirectResponse("/",303);x.delete_cookie("sales_session");return x
@app.get("/api/scenario")
def get_scenario(r:Request): auth(r);s=load();return {"scenario":s,"revision":revision(s)}
@app.put("/api/scenario")
async def put_scenario(r:Request):
 auth(r,'admin');p=await r.json()
 try:return save(p.get("scenario"),p.get("revision"))
 except ValueError as e:raise HTTPException(422,str(e))
@app.get("/api/scenario/{node_id}")
def node(node_id:str,r:Request):
 auth(r)
 n=load().get(node_id)
 if not n: raise HTTPException(404,"Ветка не найдена")
 return n
