from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Literal, Protocol, runtime_checkable


GenerationTask = Literal["research", "topic", "plan", "article", "telegram", "vk", "review"]


class ProviderError(RuntimeError):
    pass


class ProviderConfigurationError(ProviderError):
    pass


@dataclass(frozen=True)
class TextGenerationRequest:
    task: GenerationTask
    model: str
    topic: str
    primary_query: str
    article_platform: str
    account_id: str
    input_text: str
    instructions: str


@dataclass(frozen=True)
class TextGenerationResult:
    provider: str
    model: str
    text: str
    input_tokens: int
    output_tokens: int

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


@runtime_checkable
class TextGenerationProvider(Protocol):
    name: str

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult: ...


class DeterministicFakeProvider:
    name = "fake"

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        text = self._content(request)
        return TextGenerationResult(
            provider=self.name,
            model=request.model,
            text=text,
            input_tokens=max(1, len((request.instructions + request.input_text).encode("utf-8")) // 4),
            output_tokens=max(1, len(text.encode("utf-8")) // 4),
        )

    @staticmethod
    def _content(request: TextGenerationRequest) -> str:
        values = {
            "topic": request.topic,
            "query": request.primary_query,
            "platform": request.article_platform,
            "account": request.account_id,
        }
        if request.task == "research":
            return (
                "Исследовательская гипотеза: материал должен отвечать на практический вопрос "
                f"«{values['query']}» через последовательность диагностики, запуска и контроля. "
                "Факты продукта: MetricHit предназначен для накрутки и улучшения ПФ при продвижении "
                "сайтов в Яндексе; результат теста нужно оценивать вместе с техническим SEO, "
                "релевантностью страницы и коммерческой готовностью сайта."
            )
        if request.task == "topic":
            return (
                f"Тема «{values['topic']}» соответствует запросу «{values['query']}» и подходит "
                f"для площадки {values['platform']}: читателю можно дать воспроизводимый чек-лист, "
                "а MetricHit показать как инструмент управляемого теста ПФ."
            )
        if request.task == "plan":
            return (
                "План: 1) определить исходную страницу и запрос; 2) проверить техническую и "
                "коммерческую готовность; 3) задать ограниченный тест; 4) наблюдать клики, расходы "
                "и позиции; 5) принять решение по данным."
            )
        if request.task == "article":
            return f"""<!-- simulation draft; provider=fake; model={request.model} -->

# {values['topic']}

Запрос «{values['query']}» часто воспринимают слишком узко: как поиск кнопки, после которой позиции должны вырасти сами. На практике управляемый тест поведенческих факторов начинается не с количества переходов, а с ответа на три вопроса: какую страницу усиливаем, по каким запросам и как поймём, что эксперимент полезен.

## 1. Зафиксируйте исходную точку

Выберите одну посадочную страницу и компактную группу запросов с одинаковым интентом. Запишите текущие позиции, органические переходы, конверсионное действие и технические ограничения страницы. Если смешать информационные и коммерческие запросы, итог будет трудно интерпретировать.

## 2. Проверьте саму страницу

ПФ не исправляют медленную загрузку, неверный интент, слабое предложение или сломанный путь до заявки. До теста проверьте индексацию, мобильную версию, соответствие заголовка запросу, понятность следующего шага и отсутствие критических ошибок. Это не формальность: иначе эксперимент измерит недостатки страницы, а не эффект выбранной тактики.

## 3. Ограничьте первый тест

Первый запуск нужен для проверки управляемости, а не для попытки охватить всё семантическое ядро. Задайте регион, небольшой список запросов, дневные лимиты и расписание. Не меняйте одновременно страницу, запросы и интенсивность: при нескольких переменных нельзя понять причину результата.

## 4. Смотрите на связку показателей

Отдельная позиция в конкретный день ничего не доказывает. Сопоставляйте выполненные клики, расход, динамику позиций и качество целевого действия. Отмечайте даты изменений на сайте и апдейтов поиска. Рабочий вывод появляется из серии наблюдений, а не из одного удачного скриншота.

## 5. Масштабируйте только понятный сценарий

Если тест стабилен, расширяйте его по одной оси: добавьте близкие запросы, вторую страницу или скорректируйте лимит. Если результата нет, сначала проверьте релевантность, техническое состояние и коммерческие факторы. Увеличение объёма не превращает неясный эксперимент в качественный.

## Где здесь MetricHit

MetricHit — сервис накрутки и улучшения поведенческих факторов для продвижения сайтов в Яндексе. В нём можно настроить сайт, регион, запросы, дневные лимиты и расписание, а затем контролировать клики, расходы и позиции. Это инструмент усиления подготовленного сайта, а не замена техническому SEO и работе с релевантностью.

Хотите проверить MetricHit на своём проекте? Зарегистрируйтесь и получите 1 000 кликов на тест без пополнения баланса. Для начисления отправьте логин в Telegram-поддержку.
"""
        if request.task == "telegram":
            return f"""<!-- simulation draft; provider=fake; model={request.model} -->

Первый тест ПФ лучше начинать не с объёма, а с управляемости.

Проверьте три вещи:

1. Одна посадочная страница и запросы с единым интентом.
2. Зафиксированные позиции, клики и целевое действие до запуска.
3. Один изменяемый параметр за итерацию — лимит, запросы или страница.

MetricHit помогает настроить накрутку и улучшение ПФ для продвижения сайта в Яндексе и видеть выполненные клики, расходы и позиции в одном контуре.

Проверьте MetricHit на своём проекте без пополнения баланса. Зарегистрируйтесь, отправьте логин в поддержку — начислим 1 000 кликов на тест.
"""
        if request.task == "vk":
            return f"""<!-- simulation draft; provider=fake; model={request.model} -->

Мини-аудит перед запуском улучшения ПФ

Возьмите страницу, которую хотите продвигать в Яндексе, и письменно ответьте:

— какой один интент она закрывает;
— какие запросы действительно ведут на неё;
— что пользователь должен сделать после перехода;
— какие показатели вы сравните до и после теста.

Если ответы расплывчаты, сначала доработайте страницу. Если конкретны — можно запускать ограниченный эксперимент и менять по одному параметру. MetricHit нужен именно для такого управляемого контура: настройка запросов, региона, лимитов и расписания, контроль кликов, расходов и позиций.

Протестируйте MetricHit без пополнения баланса: создайте аккаунт, отправьте логин в Telegram-поддержку и получите 1 000 кликов на тест.
"""
        if request.task == "review":
            return (
                "Review пройден: материал соответствует заявленной теме и основному запросу; "
                "продукт описан прямо; публикация и гарантии результата не заявлены; CTA ведёт к "
                "регистрации и тесту без пополнения баланса. Перед публикацией требуется решение владельца."
            )
        raise ProviderError(f"Unsupported generation task: {request.task}")


class OpenAIProvider:
    name = "openai"

    def __init__(self) -> None:
        if not os.environ.get("OPENAI_API_KEY"):
            raise ProviderConfigurationError("OPENAI_API_KEY is required for the OpenAI provider")
        from openai import OpenAI

        self._client = OpenAI()

    def generate(self, request: TextGenerationRequest) -> TextGenerationResult:
        user_input = json.dumps(
            {
                "task": request.task,
                "topic": request.topic,
                "primary_query": request.primary_query,
                "article_platform": request.article_platform,
                "account_id": request.account_id,
                "stage_input": request.input_text,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        response = self._client.responses.create(
            model=request.model,
            instructions=request.instructions,
            input=user_input,
            store=False,
        )
        text = response.output_text
        if not text or not text.strip():
            raise ProviderError("OpenAI response did not contain text output")
        usage = response.usage
        return TextGenerationResult(
            provider=self.name,
            model=request.model,
            text=text.strip() + "\n",
            input_tokens=int(getattr(usage, "input_tokens", 0) or 0),
            output_tokens=int(getattr(usage, "output_tokens", 0) or 0),
        )


def create_provider(name: Literal["fake", "openai"]) -> TextGenerationProvider:
    if name == "fake":
        return DeterministicFakeProvider()
    if name == "openai":
        return OpenAIProvider()
    raise ProviderConfigurationError(f"Unsupported provider: {name}")
