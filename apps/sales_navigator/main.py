from __future__ import annotations

import hashlib, json, os, re, secrets, html
from copy import deepcopy
from pathlib import Path
from urllib.parse import parse_qs
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse

app = FastAPI(title="Навигатор продаж", docs_url=None, redoc_url=None)
BRAND_LOGO_PATH = Path(__file__).resolve().parents[2] / "work" / "brand" / "logo-horizontal-light.png"
CORE_THEME_STYLE = '''<style>:root{color-scheme:dark;--canvas:#101112;--surface:#151719;--raised:#1a1c1f;--hover:#242628;--active:#282a2d;--line:#393c40;--line-soft:#292c2f;--text:#e4e2dc;--muted:#999a9c;--focus:#d8d6d0}body{margin:0;background:var(--canvas);color:var(--text);font:16px system-ui}main{max-width:960px;margin:auto;padding:28px 20px}header{display:flex;justify-content:space-between;gap:12px;margin-bottom:24px}a,button{background:#242424;color:var(--text);border:1px solid #484848;border-radius:5px;padding:10px;text-decoration:none;font:inherit;cursor:pointer}a:hover,button:hover,a:focus-visible,button:focus-visible{background:#303030;border-color:#626262;outline:2px solid #777a7d;outline-offset:2px}button.primary{background:#dededb;border-color:#dededb;color:#171719;font-weight:700}button.primary:hover,button.primary:focus-visible{background:#f0eee9;border-color:#f0eee9}.card{background:var(--surface);border:1px solid var(--line);border-radius:7px;padding:22px}.label{color:var(--muted);font-size:12px;text-transform:uppercase}.answer{background:#1a1c1f;border-left:3px solid #d8d6d0;padding:12px;margin:8px 0}.choices{display:grid;gap:8px;margin-top:18px}.editor{display:grid;grid-template-columns:210px 1fr;gap:16px}textarea,input,select{box-sizing:border-box;width:100%;margin:5px 0 13px;padding:9px;background:#101112;color:var(--text);border:1px solid var(--line);border-radius:4px;font:inherit}textarea{min-height:72px}.choice{display:grid;grid-template-columns:1fr 150px auto;gap:7px}.status{color:#d8d6d0}@media(max-width:650px){.editor,.choice{grid-template-columns:1fr}header{flex-direction:column}}</style>'''
DEFAULT_SCENARIO = {
 "start":{"client":"Первый холодный контакт","manager":"Здравствуйте. Меня зовут [Имя], я из команды MetricHit. Мы занимаемся продвижением сайтов в Яндексе. С кем можно поговорить по вопросу продвижения вашего сайта?","hint":"Сначала найдите человека, который отвечает за сайт и продвижение.","choices":[{"label":"Я отвечаю за сайт","next":"qualification"},{"label":"Это другой коллега","next":"contact"},{"label":"Сейчас неудобно говорить","next":"time"}]},
 "qualification":{"client":"Да, я отвечаю за сайт.","manager":"Отлично, тогда коротко уточню: вы уже продвигаете сайт в Яндексе или это пока в планах?","hint":"Дайте собеседнику выбрать статус без давления.","choices":[{"label":"Уже продвигаем","next":"current_provider"},{"label":"Пока в планах","next":"planning"}]},
 "contact":{"client":"Этим занимается другой коллега.","manager":"Спасибо. Подскажите, пожалуйста, как к нему обратиться и когда будет удобно коротко созвониться?","hint":"Зафиксируйте имя, роль и время контакта.","choices":[]},
 "planning":{"client":"Пока это только в планах.","manager":"Понял. Что должно произойти, чтобы вы вернулись к вопросу продвижения: новый сайт, сезон или конкретная бизнес-цель?","hint":"Выясните триггер следующего контакта.","choices":[]},
 "current_provider":{"client":"Мы уже работаем с другим подрядчиком.","manager":"Понимаю. Не предлагаю менять всё прямо сейчас — хочу понять, что для вас важнее всего в текущем результате.","hint":"Не спорьте с выбором клиента.","choices":[{"label":"Нас не устраивает цена","next":"price"},{"label":"Нам важна предсказуемость результата","next":"proof"},{"label":"Сейчас нет времени разбираться","next":"time"}]},
 "price":{"client":"Нас прежде всего не устраивает цена.","manager":"Давайте сравним не только сумму, а стоимость результата. Какая задача должна окупиться в первую очередь?","hint":"Переводите разговор от скидки к экономике.","choices":[]},
 "proof":{"client":"Нам важна предсказуемость результата.","manager":"Покажу, как мы фиксируем стартовую точку, контрольные метрики и формат отчёта.","hint":"Предлагайте прозрачный процесс.","choices":[]},
 "time":{"client":"Сейчас нет времени разбираться.","manager":"Тогда не будем перегружать вас. Я подготовлю вариант, который можно оценить за пять минут.","hint":"Снижайте усилие клиента.","choices":[]}}
SHARED_DIALOGUE_NODES = {
 "shared-product":{"title":"Рассказать о сервисе","client":"Расскажите коротко о сервисе.","manager":"MetricHit помогает усилить подготовленное продвижение сайта в Яндексе за счёт искусственных переходов из поиска. Ниже можно выбрать, что разобрать подробнее.","hint":"Не называйте сервис заменой SEO и не обещайте результат.","choices":[{"label":"Как это работает","next":"shared-mechanics"},{"label":"Цены и условия","next":"shared-prices"},{"label":"Ограничения","next":"shared-limits"}]},
 "shared-test":{"title":"Предложить тест","client":"Хочу сначала попробовать.","manager":"Для нового аккаунта доступен бесплатный тест. Можно коротко объяснить условия или сразу перейти в Telegram, чтобы уточнить детали запуска.","hint":"Не обещайте повторный бонус или срок активации.","choices":[{"label":"Условия бесплатного теста","next":"shared-test-details"},{"label":"Перейти в Telegram","next":"shared-telegram"}]},
 "shared-test-details":{"title":"Бесплатный тест","client":"Какие условия у теста?","manager":"Новый пользователь может один раз получить 1 000 тестовых кликов без оплаты и пополнения. Для запуска нужны сайт, регион и запросы; детали удобно уточнить в Telegram.","hint":"Не обещайте повторный бонус или срок активации.","choices":[{"label":"Перейти в Telegram","next":"shared-telegram"}]},
 "shared-prices":{"title":"Цены и условия","client":"Сколько это стоит?","manager":"Цена выполненного клика зависит от суммы пополнения: от 1 000 ₽ — 0,50 ₽; от 10 000 ₽ — 0,40 ₽; от 50 000 ₽ — 0,30 ₽; от 100 000 ₽ — 0,25 ₽. Неиспользованный остаток не сгорает.","hint":"Не обещайте результат за конкретную сумму.","choices":[]},
 "shared-mechanics":{"title":"Как это работает","client":"Как работает MetricHit?","manager":"Сервис создаёт искусственные переходы из поиска Яндекса: перед целевым сайтом открываются другие результаты, а целевой — последним. Это не SEO, не реклама, не лиды и не реальные покупки.","hint":"Говорите прямо: действий внутри сайта бот не совершает.","choices":[]},
 "shared-limits":{"title":"Ограничения","client":"Насколько это безопасно и какой будет результат?","manager":"Нельзя обещать гарантированные позиции, точный срок, заявки, продажи, реальных посетителей или безусловную безопасность. MetricHit — отдельный инструмент для подготовленного продвижения, а не замена SEO.","hint":"Не спорьте и не давайте гарантий — уточните, что для клиента важно проверить.","choices":[]},
 "shared-telegram":{"title":"Перейти в Telegram","client":"Готов продолжить в мессенджере.","manager":"Отлично. Пришлите удобный Telegram-контакт — там уточним детали теста и дальнейшие шаги. Пароль, коды из SMS, письма или 2FA никогда не просим.","hint":"Зафиксируйте контакт и следующий конкретный шаг.","choices":[]},
 "shared-objections-details":{"title":"Возражения","client":"Какие возражения встречаются чаще всего?","manager":"Если клиенту нужны реальные лиды, честно скажите: сервис создаёт искусственные переходы из поиска, а не покупателей. Если уже есть SEO, MetricHit не заменяет его — это отдельный инструмент для подготовленного сайта.","hint":"Не спорьте: уточните, что именно вызывает сомнение.","choices":[]},
 "shared-objections":{"title":"Разобрать сомнения","client":"Я сомневаюсь, что нам это подходит.","manager":"Понимаю. Что вызывает больше всего вопросов: принцип работы, условия теста, цена или ожидаемый результат? Разберём один конкретный пункт без обещаний, которых сервис не даёт.","hint":"Сначала выясните настоящее возражение, затем перейдите к нужному общему узлу.","choices":[{"label":"Возражения","next":"shared-objections-details"},{"label":"Как это работает","next":"shared-mechanics"},{"label":"Цены и условия","next":"shared-prices"},{"label":"Ограничения","next":"shared-limits"}]}}
SHARED_DIALOGUE_ROOTS = ("shared-product","shared-test","shared-objections")
SHARED_DIALOGUE_DIRECT = ("shared-test-details","shared-prices","shared-mechanics","shared-limits","shared-telegram","shared-objections-details")
DEFAULT_QUICK_HELP = {
 "about":{"title":"О MetricHit","body":"MetricHit — сервис для усиления продвижения сайтов в поисковой выдаче Яндекса с помощью поведенческих факторов.\n\nКлиент сам задаёт сайт, регион, запросы, дневные лимиты и расписание. Оплата списывается только за фактически выполненные клики, фиксированной абонентской платы нет."},
 "mechanics":{"title":"Как это работает","body":"Бот работает с поисковой выдачей: по запросу сначала открывает несколько других результатов, а целевой сайт — последним. После этого он не возвращается в поиск.\n\nЭто искусственные переходы из поиска, а не SEO, реклама, лиды или реальные покупатели. Действий внутри сайта бот не совершает."},
 "trial":{"title":"Тест 1 000 кликов","body":"Новый пользователь может один раз получить 1 000 тестовых кликов без оплаты и пополнения.\n\nКлиент регистрируется на mtrhit.ru, присылает логин без пароля и кодов доступа, а менеджер передаёт логин в поддержку для проверки и активации. Начисление не автоматическое. Для существующего аккаунта повторный бонус не обещаем."},
 "prices":{"title":"Цены и тарифы","body":"Цена одного выполненного клика зависит от суммы пополнения: от 1 000 ₽ — 0,50 ₽; от 10 000 ₽ — 0,40 ₽; от 50 000 ₽ — 0,30 ₽; от 100 000 ₽ — 0,25 ₽; от 150 000 ₽ — 0,20 ₽; от 200 000 ₽ — 0,15 ₽.\n\nНеиспользованный остаток не сгорает."},
 "start":{"title":"Как начать","body":"Для запуска нужны сайт, регион продвижения и поисковые запросы. Затем клиент задаёт дневные лимиты и расписание.\n\nЛучше начинать с подготовленных страниц и запросов, по которым сайт уже имеет релевантную посадочную страницу."},
 "cabinet":{"title":"Что видно в кабинете","body":"В личном кабинете клиент настраивает сайт, регион, запросы, дневные лимиты и расписание.\n\nПосле запуска он видит выполненные клики, расходы и изменение позиций. Кабинет находится на mtrhit.ru."},
 "questions":{"title":"Частые вопросы","body":"Точный срок выхода в ТОП обещать нельзя: результат зависит не только от переходов. MetricHit не продаёт лиды и не обещает продажи.\n\nВопросы по документам, возврату, особым условиям и техническим проблемам передаются в поддержку без выдуманных ответов."},
 "objections":{"title":"Возражения","body":"«Мы таким не занимаемся» — уточните, имеется в виду продвижение сайта вообще или именно накрутка ПФ.\n\n«У нас уже есть SEO» — MetricHit не заменяет SEO; это отдельный инструмент для подготовленного сайта.\n\n«Нам нужны реальные лиды» — честно скажите, что сервис даёт искусственные переходы из поиска, а не покупателей."},
 "support":{"title":"Поддержка и контакты","body":"Личный кабинет и регистрация: https://mtrhit.ru/\nTelegram-поддержка: @Metric_Hit\nОфициальный Telegram-канал: @mtr_hit\n\nНикогда не просите пароль, SMS-код, код из письма или код 2FA."},
 "limits":{"title":"Что не обещаем","body":"Не обещаем гарантированный выход в ТОП, точный срок, заявки, продажи, реальных посетителей, безусловную безопасность или гарантированный учёт алгоритмом.\n\nMetricHit помогает усилить подготовленное продвижение, но не заменяет техническое SEO, релевантность страниц и коммерческую проработку сайта."}}
SESSIONS:dict[str,str]={}

def store_path(): return Path(os.getenv("SALES_NAVIGATOR_DATA_PATH", Path(__file__).resolve().parents[2]/"data"/"sales_navigator"/"scenario.json"))
def quick_help_path(): return Path(os.getenv("SALES_NAVIGATOR_HELP_PATH", store_path().with_name("quick_help.json")))
def revision(s): return hashlib.sha256(json.dumps(s,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
def validate(s):
 if not isinstance(s,dict) or "start" not in s: raise ValueError("Нужна стартовая ветка.")
 for key,node in s.items():
  if not isinstance(key,str) or not key or not isinstance(node,dict): raise ValueError("Некорректная ветка.")
  if any(not isinstance(node.get(x),str) or not node[x].strip() for x in ("client","manager","hint")): raise ValueError("Заполните все поля ветки.")
  if "title" in node and (not isinstance(node["title"],str) or not node["title"].strip()): raise ValueError("Укажите название ветки.")
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
def validate_quick_help(items):
 if not isinstance(items,dict) or not set(DEFAULT_QUICK_HELP).issubset(items): raise ValueError("Справка должна содержать все исходные разделы.")
 if len(items)>50: raise ValueError("В справке может быть не больше 50 разделов.")
 for key,item in items.items():
  if not isinstance(key,str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}",key): raise ValueError("Некорректный идентификатор раздела справки.")
  if not isinstance(item,dict) or set(item)!={"title","body"}: raise ValueError("Некорректный раздел справки.")
  for field,limit in (("title",100),("body",5000)):
   value=item[field]
   if not isinstance(value,str) or not value.strip() or len(value)>limit: raise ValueError("Заполните название и текст справки.")
   if "<" in value or ">" in value: raise ValueError("HTML в справке не поддерживается.")
 return items
def load_quick_help():
 p=quick_help_path()
 if not p.exists(): return deepcopy(DEFAULT_QUICK_HELP)
 try: return validate_quick_help(json.loads(p.read_text(encoding="utf-8")))
 except Exception as error: raise HTTPException(500,"Сохранённая Быстрая справка повреждена; она не была перезаписана.") from error
def save_quick_help(items,old):
 validate_quick_help(items)
 if old!=revision(load_quick_help()): raise HTTPException(409,"Быстрая справка изменена в другой вкладке. Обновите страницу.")
 p=quick_help_path();p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(".new")
 with t.open("w",encoding="utf-8") as f: json.dump(items,f,ensure_ascii=False,indent=2);f.flush();os.fsync(f.fileno())
 os.replace(t,p);return {"items":items,"revision":revision(items)}
def auth(r,required_role=None):
 role=SESSIONS.get(r.cookies.get("sales_session"))
 if not role: raise HTTPException(401,"Требуется вход")
 if required_role and role!=required_role: raise HTTPException(403,"Недостаточно прав")
 return role
@app.get("/brand/logo-horizontal-light.png", include_in_schema=False)
def brand_logo(): return FileResponse(BRAND_LOGO_PATH, media_type="image/png")
def layout(title,body,role):
 editor_link=' <a href="/editor">Редактор</a>' if role=='admin' else ''
 return f'''<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{title}</title>{CORE_THEME_STYLE}<main><header><h1>{title}</h1><div><a href="/">Сценарий</a>{editor_link} <form style="display:inline" method="post" action="/logout"><button>Выйти</button></form></div></header>{body}</main></html>'''
def app_page(role):
 s=load();is_admin=role=='admin';shortcuts=[{"key":"start","label":"Первый контакт"}]+[{"key":key,"label":SHARED_DIALOGUE_NODES[key]["title"]} for key in SHARED_DIALOGUE_ROOTS+SHARED_DIALOGUE_DIRECT]
 edit_controls=''' <button id="edit">Редактировать этот шаг</button></p><section id="edit-panel" class="card" hidden style="margin-top:18px"><div class="label">Редактирование текущего шага</div><label>Название ветки<input id="edit-title" aria-label="Название ветки"></label><label>Клиент говорит<textarea id="edit-client"></textarea></label><label>Ответ менеджера<textarea id="edit-manager"></textarea></label><label>Подсказка для менеджера<textarea id="edit-hint"></textarea></label><div class="label">Варианты ответа клиента</div><div id="edit-choices" class="choices"></div><p><button id="add-choice">+ Добавить вариант ответа</button></p><p><button id="save-edit" class="primary">Сохранить изменения</button> <button id="cancel-edit">Отменить</button> <span id="edit-status" class="status"></span></p></section>''' if is_admin else '</p>'
 edit_script=f'''function fill(){{let x=n[c],ids=Object.keys(n);$('edit-client').value=x.client;$('edit-manager').value=x.manager;$('edit-hint').value=x.hint;$('edit-choices').innerHTML=x.choices.map((y,i)=>`<div class="choice" data-choice="${{i}}"><input aria-label="Вариант ответа клиента" value="${{y.label}}"><select aria-label="Следующий шаг">${{ids.map(k=>`<option value="${{k}}" ${{k===y.next?'selected':''}}>${{name(k)}}</option>`).join('')}}</select><span><button type="button" data-open="${{i}}">Открыть связанную ветку</button> <button type="button" data-remove="${{i}}">Удалить</button></span></div>`).join('');document.querySelectorAll('[data-remove]').forEach(b=>b.onclick=()=>{{pull();n[c].choices.splice(+b.dataset.remove,1);fill()}});document.querySelectorAll('[data-open]').forEach(b=>b.onclick=()=>{{pull();let from=c,k=n[from].choices[+b.dataset.open].next;h.push(from);c=k;r();fill();$('edit-status').textContent='Открыта связанная ветка ответа клиента';$('edit-client').focus()}})}}function pull(){{let x=n[c];x.client=$('edit-client').value.trim();x.manager=$('edit-manager').value.trim();x.hint=$('edit-hint').value.trim();document.querySelectorAll('[data-choice]').forEach(row=>{{let i=+row.dataset.choice;x.choices[i].label=row.querySelector('input').value.trim();x.choices[i].next=row.querySelector('select').value}})}}function freshNode(){{let i=1,k;while(n[k='new-node-'+i++]);n[k]={{client:'Ответ клиента',manager:'Новая реплика менеджера',hint:'Подсказка для менеджера',choices:[]}};return k}}$('edit').onclick=()=>{{editing=!editing;$('edit-panel').hidden=!editing;$('edit').textContent=editing?'Закрыть редактирование':'Редактировать этот шаг';$('edit-status').textContent='';if(editing)fill()}};$('add-choice').onclick=()=>{{pull();let k=freshNode();n[c].choices.push({{label:'Новый вариант ответа',next:k}});fill();$('edit-status').textContent='Добавлен вариант ответа. Заполните его текст и откройте связанную ветку.';let inputs=document.querySelectorAll('[data-choice] input');inputs[inputs.length-1].focus();inputs[inputs.length-1].select()}};$('cancel-edit').onclick=()=>{{editing=false;$('edit-panel').hidden=true;$('edit').textContent='Редактировать этот шаг';$('edit-status').textContent='';r()}};$('save-edit').onclick=async()=>{{pull();let q=await fetch('/api/scenario',{{method:'PUT',headers:{{'Content-Type':'application/json'}},body:JSON.stringify({{scenario:n,revision:v}})}}),z=await q.json();if(!q.ok){{$('edit-status').textContent=z.detail;return}}v=z.revision;$('edit-status').textContent='Сохранено';editing=false;$('edit-panel').hidden=true;$('edit').textContent='Редактировать этот шаг';r()}};''' if is_admin else ''
 if is_admin:
  edit_script += '''
const legacyBranchNames={...names};
const escapeBranchName=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
function syncBranchNames(){Object.keys(n).forEach(key=>{names[key]=escapeBranchName(n[key].title||legacyBranchNames[key]||`Новая ветка ${key.replace('new-node-','')}`)})}
const originalInlineFill=fill,originalInlinePull=pull,originalInlineFreshNode=freshNode;
pull=function(){originalInlinePull();n[c].title=$('edit-title').value.trim();syncBranchNames()};
freshNode=function(){let key=originalInlineFreshNode();n[key].title=`Новый ответ клиента ${key.replace('new-node-','')}`;syncBranchNames();return key};
fill=function(){syncBranchNames();originalInlineFill();$('edit-title').value=n[c].title||legacyBranchNames[c]||`Новая ветка ${c.replace('new-node-','')}`;
 document.querySelectorAll('[data-choice]').forEach(row=>{let index=+row.dataset.choice,actions=row.querySelector('span');
  ['up','down'].forEach(direction=>{let button=document.createElement('button');button.type='button';button.dataset[direction]=index;button.textContent=direction==='up'?'↑':'↓';button.title=direction==='up'?'Поднять ответ':'Опустить ответ';button.setAttribute('aria-label',direction==='up'?'Поднять вариант ответа':'Опустить вариант ответа');button.disabled=direction==='up'?index===0:index===n[c].choices.length-1;
   button.onclick=()=>{pull();let choices=n[c].choices,other=index+(direction==='up'?-1:1);if(other<0||other>=choices.length)return;[choices[index],choices[other]]=[choices[other],choices[index]];fill();$('edit-status').textContent='Порядок ответов изменён в текущей ветке'};actions.insertBefore(button,actions.firstChild)});
  let open=actions.querySelector('[data-open]'),originalOpen=open.onclick;open.onclick=()=>{originalOpen();$('edit-title').focus();$('edit-title').select()};
 });};
'''
 return layout("Навигатор продаж",f'''<section class="card"><div class="label">Клиент говорит</div><h2 id="client"></h2><div class="label">Ответ менеджера</div><div id="manager" class="answer"></div><p id="hint"></p><section class="conversation-shortcuts" aria-label="Быстрый переход по разговору"><span>Быстрый переход</span><div id="conversation-shortcuts-buttons"></div></section><div id="choices" class="choices"></div><p><button id="back">← Назад</button> <button id="restart">Начать заново</button>{edit_controls}</section><script>const n={json.dumps(s,ensure_ascii=False)},names={{start:'Первый звонок',qualification:'Уточнение ситуации',contact:'Передать контакт',planning:'Пока в планах',current_provider:'Уже есть подрядчик',price:'Возражение по цене',proof:'Нужны доказательства',time:'Нет времени'}},shortcutNodes={json.dumps(SHARED_DIALOGUE_NODES,ensure_ascii=False)},shortcutRoots={json.dumps(SHARED_DIALOGUE_ROOTS,ensure_ascii=False)},shortcutList={json.dumps(shortcuts,ensure_ascii=False)};let c='start',h=[],editing=false,v='{revision(s)}';const $=x=>document.getElementById(x),name=x=>names[x]||n[x]?.title||'Новая ветка';function r(){{let x=n[c]||shortcutNodes[c];$('client').textContent=x.client;$('manager').textContent=x.manager;$('hint').textContent='Подсказка: '+x.hint;$('choices').innerHTML='';x.choices.forEach(y=>{{let b=document.createElement('button');b.textContent=y.label;b.onclick=()=>{{h.push(c);c=y.next;r()}};$('choices').append(b)}});$('back').disabled=!h.length}}function openShortcut(key){{if(editing||(!n[key]&&!shortcutNodes[key]))return;h.push(c);c=key;r()}}shortcutList.forEach(item=>{{let button=document.createElement('button');button.type='button';button.className='conversation-shortcut';button.textContent=item.label;button.onclick=()=>openShortcut(item.key);$('conversation-shortcuts-buttons').append(button)}});{edit_script}$('back').onclick=()=>{{if(!editing){{c=h.pop();r()}}}};$('restart').onclick=()=>{{if(!editing){{c='start';h=[];r()}}}};r()</script>''',role)
def editor_page(): return layout("Редактор сценария",'''<div class="editor"><aside class="card"><div id="nodes"></div><button id="new">+ Новая ветка</button></aside><section class="card"><label>Что говорит клиент<textarea id="client"></textarea></label><label>Ответ менеджера<textarea id="manager"></textarea></label><label>Подсказка<textarea id="hint"></textarea></label><div id="choices"></div><button id="add">+ Вариант ответа</button><p><button class="primary" id="save">Сохранить</button> <button id="cancel">Отменить</button> <span id="status" class="status"></span></p></section></div><script>let d,id='start';const names={{start:'Первый звонок',qualification:'Уточнение ситуации',contact:'Передать контакт',planning:'Пока в планах',current_provider:'Уже есть подрядчик',price:'Возражение по цене',proof:'Нужны доказательства',time:'Нет времени'}};const name=x=>names[x]||'Новая ветка';const $=x=>document.querySelector(x);async function load(){{d=await (await fetch('/api/scenario')).json();id='start';draw()}}function collect(){{let n=d.scenario[id];n.client=$('#client').value;n.manager=$('#manager').value;n.hint=$('#hint').value;document.querySelectorAll('[data-l]').forEach(x=>n.choices[x.dataset.l].label=x.value);document.querySelectorAll('[data-n]').forEach(x=>n.choices[x.dataset.n].next=x.value)}function draw(){{let n=d.scenario[id],ids=Object.keys(d.scenario);$('#nodes').innerHTML=ids.map(x=>`<button data-id="${{x}}">${{x===id?'● ':''}}${{name(x)}}</button>`).join('<br>');document.querySelectorAll('[data-id]').forEach(b=>b.onclick=()=>{{collect();id=b.dataset.id;draw()}});$('#client').value=n.client;$('#manager').value=n.manager;$('#hint').value=n.hint;$('#choices').innerHTML=n.choices.map((x,i)=>`<div class="choice"><input data-l="${{i}}" value="${{x.label}}"><select data-n="${{i}}">${{ids.map(k=>`<option value="${{k}}" ${{k===x.next?'selected':''}}>${{name(k)}}</option>`).join('')}}</select><button data-x="${{i}}">×</button></div>`).join('');document.querySelectorAll('[data-x]').forEach(b=>b.onclick=()=>{{collect();n.choices.splice(b.dataset.x,1);draw()}})}function freshNode(){{let i=1,k;while(d.scenario[k='new-node-'+i++]);d.scenario[k]={{client:'Ответ клиента',manager:'Новая реплика менеджера',hint:'Подсказка для менеджера',choices:[]}};return k}}$('#add').onclick=()=>{{collect();let from=id,k=freshNode();d.scenario[from].choices.push({{label:'Новый вариант ответа',next:k}});id=k;draw();$('#client').focus()}};$('#new').onclick=()=>{{collect();id=freshNode();draw();$('#client').focus()}};$('#cancel').onclick=load;$('#save').onclick=async()=>{{collect();let r=await fetch('/api/scenario',{{method:'PUT',headers:{{'Content-Type':'application/json'}},body:JSON.stringify(d)}}),x=await r.json();if(r.ok){{d=x;status.textContent='Сохранено'}}else status.textContent=x.detail}};load()</script>'''.replace("{{", "{").replace("}}", "}"),'admin')
SCENARIO_NAV_STYLE = '''<style>
body{--branch-nav-width:282px;display:grid;grid-template-columns:calc(var(--branch-nav-width) + 8px) minmax(0,1fr) 232px;gap:16px;align-items:start;min-height:100vh}
main{max-width:860px;width:100%;box-sizing:border-box;justify-self:center;margin:0;padding:28px 16px}
.conversation-shortcuts{margin:18px 0;padding:12px;background:#17191b;border:1px solid var(--line);border-radius:6px}.conversation-shortcuts>span{display:block;color:var(--muted);font-size:12px;text-transform:uppercase;margin-bottom:8px}.conversation-shortcuts>div{display:flex;flex-wrap:wrap;gap:7px}.conversation-shortcut{padding:7px 9px;background:#202225;border-color:#484848;font-size:14px}
.branch-nav{position:sticky;top:0;box-sizing:border-box;height:100vh;display:flex;flex-direction:column;overflow:visible;margin:8px 0 8px 8px;padding:18px 14px;background:#0c0d0e;border:1px solid var(--line-soft);border-radius:7px}
.brand-logo{display:block;width:208px;max-width:100%;height:auto;margin:0 0 22px}
.branch-nav h2{font-size:20px;line-height:1.2;margin:0 0 16px}
.branch-nav label{display:block;color:var(--muted);font-size:13px}
.branch-nav input{margin:6px 0 4px;background:#101112}
.nav-resizer{position:absolute;z-index:5;top:18px;right:-9px;width:16px;height:calc(100% - 36px);padding:0;border:0;background:transparent;cursor:col-resize;touch-action:none}
.nav-resizer:before{content:'';position:absolute;top:0;bottom:0;left:7px;width:2px;border-radius:2px;background:#393c40;transition:background .15s,box-shadow .15s}
.nav-resizer:hover:before,.nav-resizer:focus-visible:before,.nav-resizer[data-dragging="true"]:before{background:#d8d6d0;box-shadow:0 0 0 3px #d8d6d022}
.nav-resizer:focus-visible{outline:none}
.nav-heading{display:flex;justify-content:space-between;align-items:center;gap:8px}
#nav-mobile-toggle{display:none}
#nav-status{min-height:18px;color:#d8d6d0;font-size:13px;line-height:1.4;margin:4px 0}
.nav-content{display:flex;flex-direction:column;flex:1;min-height:0}
.nav-tree{margin-top:10px;flex:1;min-height:0;overflow-y:auto}
.nav-row{display:flex;align-items:center;min-width:0;box-sizing:border-box;min-height:36px;margin:2px 0;border-left:3px solid transparent;border-radius:7px}
.nav-row.current{background:#282a2d;border-left-color:#d8d6d0}
.nav-row.current .nav-open{font-weight:700}
.nav-row.reference .nav-open{color:#c4c4c1}
.nav-open,.nav-toggle{background:transparent;border:0;box-shadow:none;border-radius:5px;padding:5px 4px}
.nav-open{flex:1;min-width:0;text-align:left;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;line-height:1.3}
.nav-open:hover,.nav-toggle:not(:disabled):hover{background:#242628}
.nav-toggle,.nav-spacer{flex:none;width:24px;height:28px;text-align:center;padding:4px 0;color:var(--muted)}
.nav-toggle:disabled{cursor:default;opacity:.6}
.nav-group{margin:12px 0 4px;border-top:1px solid var(--line);padding-top:10px}.nav-group-title{margin:0 0 5px;padding:0 4px;color:var(--muted);font-size:12px;text-transform:uppercase}
.nav-empty{color:var(--muted);font-size:14px;padding:10px 5px}
.quick-help{position:sticky;top:8px;box-sizing:border-box;max-height:calc(100vh - 16px);overflow-y:auto;margin:0 8px 0 0;padding:16px 12px;background:#151719;border:1px solid var(--line);border-radius:7px}
.quick-help h2{font-size:18px;margin:0 0 5px}
.quick-help>p{margin:0 0 13px;color:var(--muted);font-size:13px;line-height:1.4}
.quick-help-buttons{display:grid;gap:7px}
.quick-help-button{width:100%;text-align:left;background:#202225;border-color:#484848;padding:9px 10px;font-size:14px;line-height:1.25}
.quick-help-button:hover,.quick-help-button:focus-visible{border-color:#777a7d;background:#282a2d}
.quick-help-actions{margin-top:12px;padding-top:12px;border-top:1px solid var(--line)}
.quick-help-actions button{width:100%;font-size:13px;padding:8px 10px}
.help-modal[hidden]{display:none}
.help-modal{position:fixed;z-index:1000;inset:0;display:grid;place-items:center;padding:20px;background:#000c;backdrop-filter:blur(5px)}
.help-dialog{position:relative;box-sizing:border-box;width:min(620px,100%);max-height:min(78vh,720px);overflow-y:auto;padding:26px;background:#1a1c1f;border:1px solid #55585a;border-radius:7px;box-shadow:0 28px 90px #000b}
.help-dialog h2{margin:0 42px 16px 0;font-size:25px}
.help-dialog-content{color:#e4e2dc;line-height:1.6}
.help-dialog-content p{margin:0 0 12px}
.help-dialog-content ul{margin:0;padding-left:21px}
.help-dialog-content li{margin:8px 0}
.help-close{position:absolute;top:14px;right:14px;width:38px;height:38px;padding:0;font-size:22px;line-height:1}
.help-editor-dialog{width:min(820px,100%)}
.help-editor-layout{display:grid;grid-template-columns:210px minmax(0,1fr);gap:16px;margin:0 0 16px}
.help-editor-list{display:grid;align-content:start;gap:5px;max-height:390px;overflow-y:auto}
.help-editor-item{display:grid;grid-template-columns:minmax(0,1fr) auto auto;gap:3px}.help-editor-list button{background:transparent;border-color:transparent;text-align:left;padding:8px}.help-editor-list button[aria-current="true"]{background:#282a2d;border-color:#777a7d}.help-editor-item .help-order{padding:8px;min-width:34px;text-align:center}
.help-editor-fields label{display:block;font-weight:600}.help-editor-fields textarea{min-height:230px;resize:vertical}.help-editor-note{margin:0;color:var(--muted);font-size:13px;line-height:1.45}.help-editor-status{display:inline-block;margin-left:8px;color:#d8d6d0}
body.help-open{overflow:hidden}
@media(max-width:980px){
 body{display:block}
 .branch-nav{position:relative;height:auto;max-height:70vh;margin:10px 12px 0;padding:12px 14px}
 .nav-resizer{display:none}
 .branch-nav[data-mobile-closed="true"] .nav-content{display:none}
 #nav-mobile-toggle{display:inline-block;font-size:13px;padding:7px 9px}
 .branch-nav h2{font-size:18px;margin:0}
 main{max-width:none;padding:14px 12px}
 .quick-help{position:relative;max-height:none;margin:0 12px 14px;padding:14px}
 .quick-help-buttons{grid-template-columns:repeat(2,minmax(0,1fr))}
 .help-dialog{padding:22px 18px}
 .help-editor-layout{grid-template-columns:1fr}.help-editor-list{grid-template-columns:repeat(2,minmax(0,1fr));max-height:none}.help-editor-fields textarea{min-height:180px}
}
@media(max-width:520px){
 .quick-help-buttons{grid-template-columns:1fr}
 .help-editor-list{grid-template-columns:1fr}
}
</style>'''
SCENARIO_NAV_PANEL = '''<aside id="branch-nav" class="branch-nav" aria-label="Навигация по веткам" data-mobile-closed="true"><img class="brand-logo" src="/brand/logo-horizontal-light.png" alt="MH MetricHit"><button id="nav-resizer" class="nav-resizer" type="button" role="separator" aria-label="Изменить ширину дерева веток" aria-orientation="vertical" aria-valuemin="220" aria-valuemax="480" aria-valuenow="282"></button><div class="nav-heading"><h2>Навигатор</h2><button id="nav-mobile-toggle" type="button" aria-expanded="false" aria-controls="nav-content">Открыть ветки</button></div><div id="nav-content" class="nav-content"><label for="nav-search">Найти ветку</label><input id="nav-search" type="search" placeholder="Найти ветку" autocomplete="off"><p id="nav-status" role="status" aria-live="polite"></p><div id="nav-tree" class="nav-tree" aria-label="Ветки сценария"></div></div></aside>'''
def quick_help_panel(is_admin):
 editor = '''<div class="quick-help-actions"><button id="edit-quick-help" type="button">Редактировать справку</button></div><div id="help-editor-modal" class="help-modal" hidden><section class="help-dialog help-editor-dialog" role="dialog" aria-modal="true" aria-labelledby="help-editor-title"><button id="help-editor-close" class="help-close" type="button" aria-label="Закрыть редактор справки">×</button><h2 id="help-editor-title">Редактировать Быструю справку</h2><div class="help-editor-layout"><div><button id="help-editor-add" type="button">+ Новый раздел</button><div id="help-editor-list" class="help-editor-list" aria-label="Разделы справки"></div></div><div class="help-editor-fields"><label for="help-edit-title">Название раздела</label><input id="help-edit-title" maxlength="100"><label for="help-edit-body">Текст</label><textarea id="help-edit-body" maxlength="5000"></textarea><p class="help-editor-note">Обычный текст: пустая строка отделяет абзацы. HTML не поддерживается.</p></div></div><p><button id="help-editor-save" class="primary" type="button">Сохранить</button> <button id="help-editor-cancel" type="button">Отменить</button><span id="help-editor-status" class="help-editor-status" role="status" aria-live="polite"></span></p></section></div>''' if is_admin else ''
 return f'''<aside id="quick-help" class="quick-help" aria-label="Быстрая справка"><h2>Быстрая справка</h2><p>Откройте подсказку, не прерывая разговор.</p><div id="quick-help-buttons" class="quick-help-buttons"></div>{editor}</aside><div id="help-modal" class="help-modal" hidden><section class="help-dialog" role="dialog" aria-modal="true" aria-labelledby="help-title" aria-describedby="help-content"><button id="help-close" class="help-close" type="button" aria-label="Закрыть справку">×</button><h2 id="help-title"></h2><div id="help-content" class="help-dialog-content"></div></section></div>'''
SCENARIO_NAV_SCRIPT = '''<script>
const navLegacyNames={start:'Первый звонок',qualification:'Уточнение ситуации',contact:'Передать контакт',planning:'Пока в планах',current_provider:'Уже есть подрядчик',price:'Возражение по цене',proof:'Нужны доказательства',time:'Нет времени'};
const navTitle=key=>n[key]?.title||shortcutNodes[key]?.title||navLegacyNames[key]||`Новая ветка ${key.replace('new-node-','')}`;
const navPanel=$('branch-nav'),navTree=$('nav-tree'),navSearch=$('nav-search'),navStatus=$('nav-status'),navResizer=$('nav-resizer');
const navWidthMin=220,navWidthMax=480,navWidthStorage='sales-navigator-branch-width';
let navExpanded=new Set(['start']),navOtherExpanded=false,navLastCurrent=null;
function navSetWidth(value,persist=true){
 const width=Math.max(navWidthMin,Math.min(navWidthMax,Math.round(value)));
 document.body.style.setProperty('--branch-nav-width',`${width}px`);navResizer.setAttribute('aria-valuenow',String(width));
 if(persist)try{localStorage.setItem(navWidthStorage,String(width))}catch(error){}
 return width;
}
try{const savedWidth=Number(localStorage.getItem(navWidthStorage));if(Number.isFinite(savedWidth)&&savedWidth>0)navSetWidth(savedWidth,false)}catch(error){}
let navResizeStartX=0,navResizeStartWidth=0;
navResizer.onpointerdown=event=>{if(matchMedia('(max-width:980px)').matches)return;event.preventDefault();navResizeStartX=event.clientX;navResizeStartWidth=Number(navResizer.getAttribute('aria-valuenow'))||navPanel.getBoundingClientRect().width;navResizer.dataset.dragging='true';navResizer.setPointerCapture?.(event.pointerId)};
navResizer.onpointermove=event=>{if(navResizer.dataset.dragging!=='true')return;navSetWidth(navResizeStartWidth+event.clientX-navResizeStartX,false)};
function navFinishResize(event){if(navResizer.dataset.dragging!=='true')return;navResizer.dataset.dragging='false';navSetWidth(Number(navResizer.getAttribute('aria-valuenow'))||282);if(event?.pointerId!==undefined&&navResizer.hasPointerCapture?.(event.pointerId))navResizer.releasePointerCapture(event.pointerId)}
navResizer.onpointerup=navFinishResize;navResizer.onpointercancel=navFinishResize;
navResizer.onkeydown=event=>{let width=Number(navResizer.getAttribute('aria-valuenow'))||282;if(event.key==='ArrowLeft')width-=16;else if(event.key==='ArrowRight')width+=16;else if(event.key==='Home')width=navWidthMin;else if(event.key==='End')width=navWidthMax;else return;event.preventDefault();navSetWidth(width)};
function navGraph(){
 const seen=new Set(),paths=new Map();
 function visit(key,trail,incoming=''){
  if(!n[key]||typeof n[key]!=='object')return null;
  if(seen.has(key))return {key,incoming,reference:true,children:[]};
  seen.add(key);paths.set(key,[...trail,key]);
  const choices=Array.isArray(n[key].choices)?n[key].choices:[];
  const children=[];
  for(const choice of choices){
   if(!choice||typeof choice.next!=='string'||!n[choice.next])continue;
   const child=visit(choice.next,[...trail,key],String(choice.label||''));
   if(child)children.push(child);
  }
  return {key,incoming,reference:false,children};
 }
 const root=visit('start',[]);
 const other=[];
 for(const key of Object.keys(n))if(!seen.has(key)){const node=visit(key,[]);if(node)other.push(node)}
 return {root,other,paths};
}
function navShortcutGraph(){
 const seen=new Set(),paths=new Map();
 function visit(key,trail,incoming=''){
  if(!shortcutNodes[key])return null;
  if(seen.has(key))return {key,incoming,reference:true,children:[]};
  seen.add(key);paths.set(key,[...trail,key]);
  const children=[];for(const choice of shortcutNodes[key].choices||[]){const child=visit(choice.next,[...trail,key],String(choice.label||''));if(child)children.push(child)}
  return {key,incoming,reference:false,children};
 }
 return {roots:shortcutRoots.map(key=>visit(key,[])).filter(Boolean),paths};
}
function navMatches(node,query){return navTitle(node.key).toLocaleLowerCase('ru-RU').includes(query)||node.incoming.toLocaleLowerCase('ru-RU').includes(query)}
function navHasMatch(node,query){return !query||navMatches(node,query)||node.children.some(child=>navHasMatch(child,query))}
function navWarnUnsaved(){
 const message='Сначала сохраните изменения или нажмите «Отменить» в редакторе шага.';
 navStatus.textContent=message;
 if($('edit-status'))$('edit-status').textContent=message;
}
function navOpenBranch(key){
 if(editing){navWarnUnsaved();return}
 if(!n[key]&&!shortcutNodes[key])return;
 navStatus.textContent='';
 if(key!==c){h.push(c);c=key;r()}
 if(matchMedia('(max-width:650px)').matches){
  navPanel.dataset.mobileClosed='true';$('nav-mobile-toggle').textContent='Открыть ветки';$('nav-mobile-toggle').setAttribute('aria-expanded','false');
  document.querySelector('main').scrollIntoView({block:'start'});
 }
}
function navRenderNode(node,depth,query,selectedPath,container){
 if(!navHasMatch(node,query))return;
 const row=document.createElement('div');row.className='nav-row'+(node.reference?' reference':'')+(node.key===c&&!node.reference?' current':'');
 row.dataset.navKey=node.key;row.style.paddingLeft=`${Math.min(depth,4)*13}px`;
 const hasChildren=node.children.length>0;
 if(hasChildren&&!node.reference){
  const toggle=document.createElement('button');toggle.type='button';toggle.className='nav-toggle';toggle.dataset.navToggle=node.key;
  const open=query||navExpanded.has(node.key);toggle.textContent=open?'⌄':'›';
  toggle.setAttribute('aria-expanded',String(!!open));toggle.setAttribute('aria-label',`${open?'Свернуть':'Развернуть'} ветку ${navTitle(node.key)}`);
  const protectedPath=node.key!==c&&selectedPath.includes(node.key);
  toggle.disabled=protectedPath&&!query;toggle.title=toggle.disabled?'Путь к текущей ветке остаётся открытым':'';
  toggle.onclick=()=>{if(navExpanded.has(node.key))navExpanded.delete(node.key);else navExpanded.add(node.key);navRender();[...navTree.querySelectorAll('[data-nav-toggle]')].find(button=>button.dataset.navToggle===node.key)?.focus()};
  row.append(toggle);
 }else{const spacer=document.createElement('span');spacer.className='nav-spacer';spacer.setAttribute('aria-hidden','true');spacer.textContent=node.reference?'↗':'';row.append(spacer)}
 const open=document.createElement('button');open.type='button';open.className='nav-open';open.dataset.navOpen=node.key;open.textContent=navTitle(node.key);
 open.title=node.incoming?`Ответ клиента: ${node.incoming}`:navTitle(node.key);
 if(node.key===c&&!node.reference)open.setAttribute('aria-current','step');
 if(node.reference)open.setAttribute('aria-label',`Открыть уже показанную ветку ${navTitle(node.key)}`);
 open.onclick=()=>navOpenBranch(node.key);row.append(open);container.append(row);
 if(query||navExpanded.has(node.key))for(const child of node.children)navRenderNode(child,depth+1,query,selectedPath,container);
}
function navRender(){
 const graph=navGraph(),shortcutGraph=navShortcutGraph(),selectedPath=graph.paths.get(c)||shortcutGraph.paths.get(c)||[c],query=navSearch.value.trim().toLocaleLowerCase('ru-RU');
 const currentChanged=c!==navLastCurrent;
 if(currentChanged){navExpanded=new Set(selectedPath);navOtherExpanded=graph.other.some(node=>graph.paths.get(c)?.[0]===node.key);navLastCurrent=c}
 for(const key of selectedPath.slice(0,-1))navExpanded.add(key);
 navTree.replaceChildren();
 if(graph.root)navRenderNode(graph.root,0,query,selectedPath,navTree);
 const visibleOther=graph.other.filter(node=>navHasMatch(node,query));
 if(visibleOther.length){
  const group=document.createElement('div');group.className='nav-group';group.dataset.navGroup='other';
  const toggle=document.createElement('button');toggle.type='button';toggle.className='nav-open';toggle.textContent=`Другие ветки (${visibleOther.length})`;
  toggle.setAttribute('aria-expanded',String(!!(query||navOtherExpanded)));
  toggle.onclick=()=>{navOtherExpanded=!navOtherExpanded;navRender()};group.append(toggle);navTree.append(group);
  if(query||navOtherExpanded)for(const node of visibleOther)navRenderNode(node,0,query,selectedPath,navTree);
 }
 const shared=shortcutGraph.roots.filter(node=>navHasMatch(node,query));
 if(shared.length){
  const group=document.createElement('div');group.className='nav-group';group.dataset.navGroup='shared';
  const title=document.createElement('p');title.className='nav-group-title';title.textContent='Общие ответы';group.append(title);navTree.append(group);
  for(const node of shared)navRenderNode(node,0,query,selectedPath,group);
 }
 if(query&&!navTree.querySelector('[data-nav-key]')){const empty=document.createElement('p');empty.className='nav-empty';empty.textContent='Ветка не найдена';navTree.append(empty)}
 if(currentChanged||!query)navTree.querySelector('.nav-row.current')?.scrollIntoView({block:'nearest'});
}
const originalScenarioRender=r;
r=function(){
 originalScenarioRender();
 if(!editing&&navStatus.textContent.startsWith('Сначала сохраните'))navStatus.textContent='';
 document.querySelectorAll('#choices button').forEach((button,index)=>{const open=button.onclick;button.onclick=()=>{if(editing){navWarnUnsaved();return}const activeNode=n[c]||shortcutNodes[c],next=activeNode?.choices[index]?.next;if(!n[next]&&!shortcutNodes[next]){navStatus.textContent='Связанная ветка недоступна. Выберите другую ветку.';return}open()}});
 navRender();
};
navSearch.oninput=()=>{navRender();navTree.querySelector('.nav-row.current')?.scrollIntoView({block:'nearest'})};
document.querySelectorAll('header a').forEach(link=>link.addEventListener('click',event=>{if(editing){event.preventDefault();navWarnUnsaved()}}));
document.querySelector('header form')?.addEventListener('submit',event=>{if(editing){event.preventDefault();navWarnUnsaved()}});
$('nav-mobile-toggle').onclick=()=>{
 const closed=navPanel.dataset.mobileClosed==='true';navPanel.dataset.mobileClosed=String(!closed);
 $('nav-mobile-toggle').textContent=closed?'Свернуть ветки':'Открыть ветки';
 $('nav-mobile-toggle').setAttribute('aria-expanded',String(closed));
 if(closed)navSearch.focus();
};
r();
</script>'''
def quick_help_script(items,is_admin):
 return '''<script>
let helpItems=__HELP_ITEMS__,helpRevision=__HELP_REVISION__,helpLastFocus=null,helpEditorLastFocus=null,helpEditorActive=null,helpEditorItems=null;
const helpIsAdmin=__HELP_ADMIN__,helpModal=$('help-modal'),helpTitle=$('help-title'),helpContent=$('help-content'),helpClose=$('help-close'),helpButtons=$('quick-help-buttons');
function helpText(body,target){target.replaceChildren();String(body).trim().split(/\\n\\s*\\n/).forEach(part=>{const paragraph=document.createElement('p');paragraph.textContent=part.trim();target.append(paragraph)})}
function renderHelpButtons(){helpButtons.replaceChildren();Object.entries(helpItems).forEach(([key,item])=>{const button=document.createElement('button');button.type='button';button.className='quick-help-button';button.dataset.help=key;button.textContent=item.title;button.onclick=()=>openHelp(key);helpButtons.append(button)})}
function openHelp(key){const item=helpItems[key];if(!item)return;helpLastFocus=document.activeElement;helpTitle.textContent=item.title;helpText(item.body,helpContent);helpModal.hidden=false;document.body.classList.add('help-open');helpClose.focus()}
function closeHelp(){if(helpModal.hidden)return;helpModal.hidden=true;document.body.classList.remove('help-open');helpLastFocus?.focus?.()}
renderHelpButtons();helpClose.onclick=closeHelp;helpModal.onclick=event=>{if(event.target===helpModal)closeHelp()};
if(helpIsAdmin){
 const helpEditorModal=$('help-editor-modal'),helpEditorList=$('help-editor-list'),helpEditorTitleInput=$('help-edit-title'),helpEditorBodyInput=$('help-edit-body'),helpEditorStatus=$('help-editor-status');
 function drawHelpEditor(){helpEditorList.replaceChildren();const entries=Object.entries(helpEditorItems);entries.forEach(([key,item],index)=>{const row=document.createElement('div');row.className='help-editor-item';const button=document.createElement('button');button.type='button';button.textContent=item.title;button.setAttribute('aria-current',String(key===helpEditorActive));button.onclick=()=>{collectHelpEditor();helpEditorActive=key;drawHelpEditor()};row.append(button);[['↑',-1,'выше'],['↓',1,'ниже']].forEach(([label,step,word])=>{const move=document.createElement('button');move.type='button';move.className='help-order';move.textContent=label;move.setAttribute('aria-label',`Переместить ${item.title} ${word}`);move.disabled=index+step<0||index+step>=entries.length;move.onclick=()=>moveHelpEditor(key,step);row.append(move)});helpEditorList.append(row)});const item=helpEditorItems[helpEditorActive];helpEditorTitleInput.value=item.title;helpEditorBodyInput.value=item.body}
 function collectHelpEditor(){if(!helpEditorActive)return;helpEditorItems[helpEditorActive]={title:helpEditorTitleInput.value.trim(),body:helpEditorBodyInput.value.trim()}}
 function moveHelpEditor(key,step){collectHelpEditor();const entries=Object.entries(helpEditorItems),index=entries.findIndex(([current])=>current===key),target=index+step;if(target<0||target>=entries.length)return;[entries[index],entries[target]]=[entries[target],entries[index]];helpEditorItems=Object.fromEntries(entries);drawHelpEditor()}
 function freshHelpKey(){let number=1,key;do{key=`custom-${number++}`}while(helpEditorItems[key]);return key}
 async function openHelpEditor(){helpEditorLastFocus=document.activeElement;const response=await fetch('/api/quick-help'),payload=await response.json();if(!response.ok){helpEditorStatus.textContent=payload.detail||'Не удалось открыть справку';return}helpItems=payload.items;helpRevision=payload.revision;helpEditorItems=JSON.parse(JSON.stringify(helpItems));helpEditorActive=Object.keys(helpEditorItems)[0];helpEditorStatus.textContent='';drawHelpEditor();helpEditorModal.hidden=false;document.body.classList.add('help-open');helpEditorTitleInput.focus()}
 function closeHelpEditor(){if(helpEditorModal.hidden)return;helpEditorModal.hidden=true;document.body.classList.remove('help-open');helpEditorLastFocus?.focus?.()}
 $('edit-quick-help').onclick=openHelpEditor;$('help-editor-close').onclick=closeHelpEditor;$('help-editor-cancel').onclick=closeHelpEditor;$('help-editor-add').onclick=()=>{collectHelpEditor();helpEditorActive=freshHelpKey();helpEditorItems[helpEditorActive]={title:'Новый раздел',body:'Добавьте описание для менеджера.'};drawHelpEditor();helpEditorTitleInput.focus();helpEditorTitleInput.select()};helpEditorModal.onclick=event=>{if(event.target===helpEditorModal)closeHelpEditor()};
 $('help-editor-save').onclick=async()=>{collectHelpEditor();const response=await fetch('/api/quick-help',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify({items:helpEditorItems,revision:helpRevision})}),payload=await response.json();if(!response.ok){helpEditorStatus.textContent=payload.detail||'Не удалось сохранить';return}helpItems=payload.items;helpRevision=payload.revision;renderHelpButtons();helpEditorStatus.textContent='Сохранено';closeHelpEditor()};
}
document.addEventListener('keydown',event=>{if(event.key!=='Escape')return;if(helpIsAdmin&&!$('help-editor-modal').hidden)closeHelpEditor();else if(!helpModal.hidden)closeHelp()});
</script>'''.replace('__HELP_ITEMS__',json.dumps(items,ensure_ascii=False)).replace('__HELP_REVISION__',json.dumps(revision(items))).replace('__HELP_ADMIN__','true' if is_admin else 'false')
LOGIN='''<!doctype html><html lang="ru"><meta charset="utf-8"><body style="background:#101112;color:#e4e2dc;font:16px system-ui;padding:30px"><form method="post" action="/login"><h1>Навигатор продаж</h1><p>Введите пароль доступа.</p><input name="password" type="password" autocomplete="current-password"><button>Войти</button></form></body></html>'''
@app.get("/",response_class=HTMLResponse)
def home(r:Request):
 role=SESSIONS.get(r.cookies.get("sales_session"))
 if not role: return HTMLResponse(LOGIN)
 help=load_quick_help()
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
 page=page.replace('<main>',SCENARIO_NAV_STYLE+SCENARIO_NAV_PANEL+'<main>')
 return HTMLResponse(page.replace('</main></html>','</main>'+quick_help_panel(role=='admin')+(safeguard if role=='admin' else '')+SCENARIO_NAV_SCRIPT+quick_help_script(help,role=='admin')+'</html>'))
def map_page():
 s=load();labels={'start':'Первый звонок','qualification':'Уточнение ситуации','contact':'Передать контакт','planning':'Пока в планах','current_provider':'Уже есть подрядчик','price':'Возражение по цене','proof':'Нужны доказательства','time':'Нет времени'}
 def branch_name(key): return s[key].get('title') or labels.get(key) or 'Новая ветка '+key.replace('new-node-','')
 cards=[]
 for key,node in s.items():
  links=''.join(f'<li><strong>{html.escape(x["label"])}</strong> → {html.escape(branch_name(x["next"]))}</li>' for x in node['choices']) or '<li>Конец ветки</li>'
  cards.append(f'<article class="map-node"><span>{html.escape(branch_name(key))}</span><h2>{html.escape(node["client"])}</h2><p>{html.escape(node["manager"])}</p><ul>{links}</ul></article>')
 return f'''<style>.map-help{{color:#b9b9b6;margin:0 0 18px}}.map{{display:grid;grid-template-columns:repeat(auto-fit,minmax(270px,1fr));gap:16px}}.map-node{{background:#151719;border:1px solid #393c40;border-radius:7px;padding:16px;box-shadow:0 12px 28px #0003}}.map-node>span{{color:#b9b9b6;font-size:12px;text-transform:uppercase}}.map-node h2{{font-size:18px;margin:8px 0}}.map-node p{{color:#e4e2dc;line-height:1.45}}.map-node ul{{border-top:1px solid #393c40;margin:14px 0 0;padding:12px 0 0;list-style:none}}.map-node li{{padding:7px 0;color:#b9b9b6}}.map-node strong{{color:#f0eee9}}</style><p class="map-help">Все этапы и переходы сценария. Стрелка показывает, куда ведёт ответ клиента.</p><section class="map">{''.join(cards)}</section>'''
@app.get('/map',response_class=HTMLResponse)
def map_view(r:Request):
 role=SESSIONS.get(r.cookies.get('sales_session'))
 if not role: return RedirectResponse('/',303)
 return HTMLResponse(layout('Карта сценария',map_page(),role))
@app.get("/editor",response_class=HTMLResponse)
def editor(r:Request):
 auth(r,'admin')
 additions = '''<style>
 .editor-intro{margin:0 0 18px;padding:14px 16px;border:1px solid #393c40;border-radius:7px;background:#1a1c1f;color:#e4e2dc;line-height:1.45}.editor-intro strong{color:#f0eee9}.nodes{padding:14px!important}.nodes button{border:0!important;background:transparent!important;text-align:left;width:100%;margin:2px 0;padding:10px!important}.nodes button:hover{background:#242628!important}.nodes button:first-child{background:#282a2d!important}.editor .card{box-shadow:0 18px 45px rgba(0,0,0,.2)}.editor label{display:block;font-weight:600}.editor label:before{content:'Редактируйте текст так, как его увидит менеджер';display:block;color:#999a9c;font-size:12px;font-weight:400;margin-top:3px}.editor label:first-of-type:before{content:'Название видно в списке веток и переходах'}.editor label:nth-of-type(3):before{content:'Эта реплика показывается менеджеру';}.editor label:nth-of-type(4):before{content:'Короткая подсказка, не для клиента';}.choice{padding:8px;border:1px solid #393c40;border-radius:6px;margin:8px 0}.choice:before{content:'Если клиент отвечает:';color:#999a9c;font-size:12px;grid-column:1/-1}</style><script>
const legacyBranchNames={...names};
const escapeBranchName=value=>String(value).replace(/[&<>"']/g,char=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
function syncBranchNames(){Object.keys(d.scenario).forEach(key=>{names[key]=escapeBranchName(d.scenario[key].title||legacyBranchNames[key]||`Новая ветка ${key.replace('new-node-','')}`)})}
const originalEditorCollect=collect,originalEditorDraw=draw,originalEditorFreshNode=freshNode;
collect=function(){originalEditorCollect();d.scenario[id].title=$('#title').value.trim();syncBranchNames()};
freshNode=function(){let key=originalEditorFreshNode();d.scenario[key].title=`Новый ответ клиента ${key.replace('new-node-','')}`;syncBranchNames();return key};
draw=function(){syncBranchNames();originalEditorDraw();$('#title').value=d.scenario[id].title||legacyBranchNames[id]||`Новая ветка ${id.replace('new-node-','')}`;
 document.querySelectorAll('#choices .choice').forEach((row,index)=>{let remove=row.querySelector('[data-x]'),actions=document.createElement('span'),choices=d.scenario[id].choices;row.append(actions);
  ['up','down'].forEach(direction=>{let button=document.createElement('button');button.type='button';button.dataset[direction]=index;button.textContent=direction==='up'?'↑':'↓';button.title=direction==='up'?'Поднять ответ':'Опустить ответ';button.setAttribute('aria-label',direction==='up'?'Поднять вариант ответа':'Опустить вариант ответа');button.disabled=direction==='up'?index===0:index===choices.length-1;
   button.onclick=()=>{collect();let siblings=d.scenario[id].choices,other=index+(direction==='up'?-1:1);if(other<0||other>=siblings.length)return;[siblings[index],siblings[other]]=[siblings[other],siblings[index]];draw();$('#status').textContent='Порядок ответов изменён в текущей ветке'};actions.append(button)});actions.append(remove);
 });};
$('#title').oninput=()=>{d.scenario[id].title=$('#title').value.trim();syncBranchNames();let selected=document.querySelector(`#nodes [data-id="${id}"]`);if(selected)selected.textContent='● '+($('#title').value.trim()||legacyBranchNames[id]||id)};
const originalAdd=$('#add').onclick,originalNew=$('#new').onclick;
$('#add').onclick=()=>{originalAdd();$('#title').focus();$('#title').select()};
$('#new').onclick=()=>{originalNew();$('#title').focus();$('#title').select()};
$('#save').onclick=async()=>{collect();let response=await fetch('/api/scenario',{method:'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(d)}),result=await response.json();if(response.ok){d=result;$('#status').textContent='Сохранено';draw()}else $('#status').textContent=result.detail};
</script>'''
 page = editor_page().replace('<div class="editor">', '<div class="editor-intro"><strong>Как работать с редактором.</strong> Слева выберите этап разговора. Справа измените текст и варианты ответов. Нажмите «Сохранить», когда закончите.</div><div class="editor">').replace('<section class="card"><label>Что говорит клиент', '<section class="card"><label>Название ветки<input id="title" aria-label="Название ветки"></label><label>Что говорит клиент')
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
@app.get("/api/quick-help")
def get_quick_help(r:Request):
 auth(r,'admin');items=load_quick_help();return {"items":items,"revision":revision(items)}
@app.put("/api/quick-help")
async def put_quick_help(r:Request):
 auth(r,'admin');p=await r.json()
 try:return save_quick_help(p.get("items"),p.get("revision"))
 except ValueError as e:raise HTTPException(422,str(e))
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
