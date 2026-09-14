from __future__ import annotations

import os
import secrets
from html import escape
from urllib.parse import parse_qs

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

app = FastAPI(title="Навигатор продаж", docs_url=None, redoc_url=None)

# This is deliberately a small, editable in-code sample.  A later stage can
# move scenarios into an editor and database without changing the UI contract.
SCENARIO = {
    "start": {
        "client": "Первый холодный контакт",
        "manager": "Здравствуйте. Меня зовут [Имя], я из команды MetricHit. Мы занимаемся продвижением сайтов в Яндексе. С кем можно поговорить по вопросу продвижения вашего сайта?",
        "hint": "Цель первого вопроса — не продавать сразу, а найти человека, который отвечает за сайт и продвижение.",
        "choices": [
            {"label": "Я отвечаю за сайт", "next": "qualification"},
            {"label": "Это другой коллега", "next": "contact"},
            {"label": "Сейчас неудобно говорить", "next": "time"},
        ],
    },
    "qualification": {
        "client": "Да, я отвечаю за сайт.",
        "manager": "Отлично, тогда коротко уточню: вы уже продвигаете сайт в Яндексе или это пока в планах?",
        "hint": "Задайте вопрос ровно так и дайте собеседнику выбрать статус без давления.",
        "choices": [
            {"label": "Уже продвигаем", "next": "current_provider"},
            {"label": "Пока в планах", "next": "planning"},
        ],
    },
    "contact": {
        "client": "Этим занимается другой коллега.",
        "manager": "Спасибо. Подскажите, пожалуйста, как к нему обратиться и когда будет удобно коротко созвониться?",
        "hint": "Зафиксируйте имя, роль и удобное время контакта — не пытайтесь продолжать продажу через нерелевантного собеседника.",
        "choices": [],
    },
    "planning": {
        "client": "Пока это только в планах.",
        "manager": "Понял. Что должно произойти, чтобы вы вернулись к вопросу продвижения: новый сайт, сезон или конкретная бизнес-цель?",
        "hint": "Выясните триггер и согласуйте спокойный следующий контакт вместо немедленного предложения.",
        "choices": [],
    },
    "current_provider": {
        "client": "Мы уже работаем с другим подрядчиком.",
        "manager": "Понимаю. Не предлагаю менять всё прямо сейчас — хочу понять, что для вас важнее всего в текущем результате.",
        "hint": "Не спорьте с выбором клиента. Сначала выясните критерий, по которому он оценивает текущего подрядчика.",
        "choices": [
            {"label": "Нас не устраивает цена", "next": "price"},
            {"label": "Нам важна предсказуемость результата", "next": "proof"},
            {"label": "Сейчас нет времени разбираться", "next": "time"},
        ],
    },
    "price": {
        "client": "Нас прежде всего не устраивает цена.",
        "manager": "Давайте сравним не только сумму, а стоимость результата. Какая задача должна окупиться в первую очередь?",
        "hint": "Переводите разговор от скидки к экономике и приоритету клиента.",
        "choices": [
            {"label": "Хочу увидеть расчёт", "next": "calculation"},
            {"label": "Всё равно дорого", "next": "pilot"},
        ],
    },
    "proof": {
        "client": "Нам важна предсказуемость результата.",
        "manager": "Согласен: обещания здесь не помогают. Покажу, как мы фиксируем стартовую точку, контрольные метрики и формат отчёта.",
        "hint": "Предлагайте прозрачный процесс и понятные критерии, а не гарантии, которые нельзя подтвердить.",
        "choices": [{"label": "Покажите пример отчёта", "next": "report"}],
    },
    "time": {
        "client": "Сейчас нет времени разбираться.",
        "manager": "Тогда не будем перегружать вас. Я задам два коротких вопроса и подготовлю вариант, который можно оценить за пять минут.",
        "hint": "Снижайте усилие клиента: предложите следующий шаг с ясным объёмом времени.",
        "choices": [{"label": "Хорошо, задавайте", "next": "qualification"}],
    },
    "calculation": {
        "client": "Хочу увидеть расчёт.",
        "manager": "Отлично. Зафиксируем текущую конверсию и средний чек — на их основе подготовлю два варианта с разным темпом запуска.",
        "hint": "Следующий шаг: запросите только данные, без которых расчёт невозможен.",
        "choices": [],
    },
    "pilot": {
        "client": "Всё равно дорого.",
        "manager": "Тогда начнём с ограниченного пилота с заранее согласованными метриками. После него решите, есть ли смысл масштабироваться.",
        "hint": "Не снижайте цену автоматически: уменьшите объём и сделайте решение обратимым.",
        "choices": [],
    },
    "report": {
        "client": "Покажите пример отчёта.",
        "manager": "Покажу структуру: исходная точка, действия, динамика метрик и выводы. После этого выберем, какие показатели важны именно вам.",
        "hint": "Закончите вопросом: какие метрики клиент готов считать успехом?",
        "choices": [],
    },
}
SESSIONS: set[str] = set()


def expected_password() -> str:
    return os.getenv("SALES_NAVIGATOR_PASSWORD", "demo")


def authenticated(request: Request) -> bool:
    return request.cookies.get("sales_navigator_session") in SESSIONS


def require_auth(request: Request) -> None:
    if not authenticated(request):
        raise HTTPException(status_code=401, detail="Требуется вход")


def page() -> str:
    initial = SCENARIO["start"]
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Навигатор продаж</title><style>
:root {{ color-scheme: dark; font-family: Inter, system-ui, sans-serif; background:#111827; color:#f8fafc; }}
body {{ margin:0; min-height:100vh; background:radial-gradient(circle at top right,#164e63,#111827 45%); }}
main {{ max-width:850px; margin:0 auto; padding:32px 20px 56px; }}
header {{ display:flex; justify-content:space-between; align-items:center; gap:16px; margin-bottom:34px; }}
h1 {{ margin:0; font-size:clamp(1.5rem,4vw,2.25rem); }} .eyebrow {{ color:#67e8f9; font-size:.82rem; letter-spacing:.12em; text-transform:uppercase; }}
.card {{ background:rgba(15,23,42,.9); border:1px solid #334155; border-radius:18px; padding:24px; box-shadow:0 20px 50px rgba(0,0,0,.25); }}
.label {{ color:#94a3b8; font-size:.84rem; text-transform:uppercase; letter-spacing:.08em; }}
.client {{ font-size:1.35rem; margin:8px 0 22px; }} .answer {{ border-left:3px solid #22d3ee; padding:12px 16px; background:#172554; border-radius:0 10px 10px 0; line-height:1.5; }}
.hint {{ margin-top:18px; color:#cbd5e1; line-height:1.45; }} .choices {{ display:grid; gap:10px; margin-top:24px; }}
button {{ cursor:pointer; font:inherit; border-radius:10px; border:1px solid #475569; padding:13px 15px; text-align:left; color:#f8fafc; background:#1e293b; }} button:hover {{ border-color:#67e8f9; background:#0f3b4d; }}
.actions {{ display:flex; gap:10px; margin-top:24px; }} .actions button {{ text-align:center; }} .secondary {{ background:transparent; }} form {{ margin:0; }}
</style></head><body><main><header><div><div class="eyebrow">MetricHit · прототип</div><h1>Навигатор продаж</h1></div><form method="post" action="/logout"><button class="secondary">Выйти</button></form></header>
<section class="card"><div class="label">Клиент говорит</div><div id="client" class="client">{escape(initial['client'])}</div><div class="label">Ответ менеджера</div><div id="manager" class="answer">{escape(initial['manager'])}</div><div id="hint" class="hint">Подсказка: {escape(initial['hint'])}</div><div id="choices" class="choices"></div><div class="actions"><button id="back" class="secondary">← Назад</button><button id="restart" class="secondary">Начать заново</button></div></section>
</main><script>
const nodes = {SCENARIO!r}; let current = 'start', history = [];
const client = document.querySelector('#client'), manager = document.querySelector('#manager'), hint = document.querySelector('#hint'), choices = document.querySelector('#choices');
function render() {{ const node=nodes[current]; client.textContent=node.client; manager.textContent=node.manager; hint.textContent='Подсказка: '+node.hint; choices.innerHTML='';
 if (!node.choices.length) choices.innerHTML='<div class="hint">Ветка завершена. Зафиксируйте следующий шаг в CRM.</div>';
 node.choices.forEach(choice => {{ const button=document.createElement('button'); button.textContent=choice.label; button.onclick=()=>{{history.push(current); current=choice.next; render();}}; choices.append(button); }});
 document.querySelector('#back').disabled=!history.length; }}
document.querySelector('#back').onclick=()=>{{if(history.length){{current=history.pop();render();}}}}; document.querySelector('#restart').onclick=()=>{{current='start';history=[];render();}}; render();
</script></body></html>"""


LOGIN_PAGE = """<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>Вход — Навигатор продаж</title><style>body{margin:0;min-height:100vh;display:grid;place-items:center;background:#111827;color:#f8fafc;font:16px system-ui}.box{width:min(360px,calc(100% - 48px));padding:28px;background:#1e293b;border:1px solid #475569;border-radius:16px}input,button{box-sizing:border-box;width:100%;padding:12px;border-radius:9px;margin-top:12px;font:inherit}input{border:1px solid #64748b;background:#0f172a;color:white}button{border:0;background:#22d3ee;color:#083344;font-weight:700;cursor:pointer}.note{color:#94a3b8;font-size:.9rem;line-height:1.4}</style></head><body><form class="box" method="post" action="/login"><h1>Навигатор продаж</h1><p class="note">Локальный прототип. Для демонстрации используйте пароль <code>demo</code>; в запуске пароль задаётся переменной окружения.</p><label>Пароль<input name="password" type="password" required autofocus></label><button>Войти</button></form></body></html>"""


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return HTMLResponse(page() if authenticated(request) else LOGIN_PAGE)


@app.post("/login")
async def login(request: Request) -> RedirectResponse:
    """Accept the tiny form without adding a multipart dependency to the OS."""
    form = parse_qs((await request.body()).decode("utf-8"), keep_blank_values=True)
    password = form.get("password", [""])[0]
    if not secrets.compare_digest(password, expected_password()):
        return RedirectResponse("/", status_code=303)
    token = secrets.token_urlsafe(32)
    SESSIONS.add(token)
    response = RedirectResponse("/", status_code=303)
    response.set_cookie("sales_navigator_session", token, httponly=True, samesite="lax")
    return response


@app.post("/logout")
def logout(request: Request) -> RedirectResponse:
    token = request.cookies.get("sales_navigator_session")
    if token:
        SESSIONS.discard(token)
    response = RedirectResponse("/", status_code=303)
    response.delete_cookie("sales_navigator_session")
    return response


@app.get("/api/scenario/{node_id}")
def scenario_node(node_id: str, request: Request) -> JSONResponse:
    require_auth(request)
    node = SCENARIO.get(node_id)
    if node is None:
        raise HTTPException(status_code=404, detail="Ветка не найдена")
    return JSONResponse(node)
