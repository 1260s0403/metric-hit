"""Local authoring and bounded Telegram publishing for MetricHit.

Credentials are deliberately supplied only at process start through
``METRICHIT_PUBLISHER_BOT_TOKEN``.  They are never persisted, logged, or
accepted through a Telegram message.  The automatic mode is deliberately
limited to one active owner-started, one-hour test run at a time.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable, Protocol
from urllib.request import Request, urlopen

from .local_author import (
    AuthorProfile,
    CANONICAL_FOOTER,
    DeterministicLocalAdapter,
    LocalPostAuthor,
    PostKind,
    PostRequest,
    THEMATIC_DIRECTIONS,
    validate_publication_text,
)


ACCESS_DENIED = "Доступ к контент-паблишеру закрыт."
TEST_INTERVAL_SECONDS = 180
TEST_TOTAL_POSTS = 20
TEST_DURATION_SECONDS = 3600
TEST_POSTS = (
    (PostKind.INSTRUCTION, THEMATIC_DIRECTIONS[0], "Что проверить перед запуском ПФ", "До запуска важно понять границы теста и состояние сайта."),
    (PostKind.DIAGNOSTIC, THEMATIC_DIRECTIONS[1], "Почему одна позиция не описывает выдачу", "Один запрос не заменяет контекст связанных страниц и конкурентов."),
    (PostKind.INFORMATIONAL, THEMATIC_DIRECTIONS[2], "Техническая готовность страницы", "Техническое SEO остаётся частью готовности к любому дальнейшему действию."),
    (PostKind.EXPLANATORY, THEMATIC_DIRECTIONS[3], "Как интент меняет роль страницы", "Запросы с похожими словами могут отвечать на разные задачи пользователя."),
    (PostKind.DIAGNOSTIC, THEMATIC_DIRECTIONS[4], "Регион как часть поискового контекста", "Оценка без региона может смешивать разные условия выдачи."),
    (PostKind.INFORMATIONAL, THEMATIC_DIRECTIONS[5], "Что дают данные до запуска", "Исходная точка нужна не для отчёта, а для понятной интерпретации наблюдений."),
    (PostKind.INSTRUCTION, THEMATIC_DIRECTIONS[2], "Проверка коммерческой релевантности", "Страница должна отвечать ожиданию пользователя, а не только содержать нужные слова."),
    (PostKind.EXPLANATORY, THEMATIC_DIRECTIONS[0], "Тест и постоянная работа это разные режимы", "Ограниченный запуск проверяет гипотезу и не заменяет системную работу с сайтом."),
    (PostKind.DIAGNOSTIC, THEMATIC_DIRECTIONS[5], "Когда изменения мешают оценке", "Несколько одновременных правок усложняют объяснение результата."),
    (PostKind.INFORMATIONAL, THEMATIC_DIRECTIONS[1], "Ранжирование нельзя свести к одному сигналу", "Выдача меняется в контексте запроса, страницы и периода наблюдения."),
    (PostKind.EXPLANATORY, THEMATIC_DIRECTIONS[3], "Семантика это не просто список фраз", "Группа запросов помогает увидеть намерение и роль страницы."),
    (PostKind.INSTRUCTION, THEMATIC_DIRECTIONS[5], "Как фиксировать изменения", "Журнал помогает не приписывать эффект тому, что не проверяли."),
    (PostKind.DIAGNOSTIC, THEMATIC_DIRECTIONS[2], "Почему контент влияет на выводы", "Неясное содержание страницы может быть отдельной причиной слабого соответствия запросу."),
    (PostKind.INFORMATIONAL, THEMATIC_DIRECTIONS[4], "Локальный спрос и страница", "Региональная задача требует смотреть на контекст, а не переносить выводы автоматически."),
    (PostKind.EXPLANATORY, THEMATIC_DIRECTIONS[1], "Период проверки меняет картину", "Короткий срез и длинный период отвечают на разные вопросы."),
    (PostKind.INSTRUCTION, THEMATIC_DIRECTIONS[3], "Как разобрать группу целевых запросов", "Полезно отделить запросы с разными намерениями до изменений на странице."),
    (PostKind.DIAGNOSTIC, THEMATIC_DIRECTIONS[0], "Когда тест лучше остановить", "Условия перестают быть сопоставимыми не из-за эмоции, а из-за изменения исходных данных."),
    (PostKind.INFORMATIONAL, THEMATIC_DIRECTIONS[5], "Позиции и другие наблюдения", "Позиция полезна как часть картины, а не как единственное основание для решения."),
    (PostKind.EXPLANATORY, THEMATIC_DIRECTIONS[6], "Как говорить об обновлениях поиска", "Изменения поисковых систем требуют фактического источника, а не догадок."),
    (PostKind.DIAGNOSTIC, THEMATIC_DIRECTIONS[2], "Почему стабильность сайта важна", "Нестабильная доступность создаёт фон, который мешает читать остальные сигналы."),
)

# These are editorial notes, not a fill-in-the-blanks template.  They give the
# offline author a concrete angle for every scheduled slot without inventing a
# case, a number, or a promised result.
SCHEDULE_INSIGHTS = {
    "Что проверить перед запуском ПФ": (
        "Перед запуском ПФ полезно проверить не только позиции. Откройте целевую страницу с телефона и компьютера: "
        "понятно ли, что именно предлагает компания, как оставить заявку и что произойдёт после обращения. Затем "
        "зафиксируйте дату, список запросов и состояние формы. Если в этот же день меняются цены, тексты или структура, "
        "сравнивать период до и после запуска будет сложнее."
    ),
    "Почему одна позиция не описывает выдачу": (
        "Одна позиция удобна для отчёта, но не объясняет задачу сайта. Один запрос может вести на нужную страницу, "
        "а соседний с тем же смыслом - на каталог, статью или конкурента. Посмотрите группу близких запросов и страницы, "
        "которые получают показы. Так видно, речь о единичном колебании или о том, что страница не занимает понятную "
        "роль для этой темы."
    ),
    "Техническая готовность страницы": (
        "Техническая готовность страницы начинается с базовых вещей, которые видит посетитель: она открывается без "
        "ошибки, не зависает, не ведёт на пустой экран и не теряет форму после отправки. Затем стоит проверить, что "
        "канонический адрес, заголовок и основное содержание относятся к одной услуге. Техническая ошибка редко выглядит "
        "как громкая авария, но она может сделать хорошее предложение недоступным в нужный момент."
    ),
    "Как интент меняет роль страницы": (
        "Похожая формулировка запроса не всегда означает одинаковое намерение. Человек может искать определение, "
        "сравнивать варианты или выбирать исполнителя. Для первого случая полезна понятная статья, для второго - "
        "сравнение, для третьего - страница услуги с условиями и способом связи. Когда все эти задачи пытаются решить "
        "одним текстом, читатель дольше ищет ответ и страница теряет ясность."
    ),
    "Регион как часть поискового контекста": (
        "Регион меняет не только название города в тексте. У пользователя могут быть другие ожидания к срокам, зонам "
        "работы, доставке и способу обращения. Если компания работает в нескольких городах, полезно честно показать, "
        "какие условия действуют в каждом из них. Копия одной страницы с заменой названия города редко отвечает на "
        "вопрос посетителя и затрудняет дальнейшую диагностику."
    ),
    "Что дают данные до запуска": (
        "Данные до запуска нужны, чтобы позже не спорить по памяти. Сохраните перечень страниц, запросов и период, "
        "который вы смотрите. Отдельно отметьте заметные изменения на сайте, сезонные события и рекламу, если они "
        "влияют на поток обращений. Тогда новые наблюдения можно сопоставить с исходной точкой, а не объяснять любое "
        "движение единственной недавно сделанной правкой."
    ),
    "Проверка коммерческой релевантности": (
        "Коммерческая страница отвечает на вопросы до того, как человек нажмёт кнопку. Что входит в услугу, для кого "
        "она подходит, как рассчитывается стоимость, какие сроки и как связаться с компанией. Не обязательно писать "
        "длинный текст, но важные условия не стоит прятать в PDF или сообщать только после звонка. Чем понятнее путь "
        "к обращению, тем легче посетителю оценить предложение."
    ),
    "Тест и постоянная работа это разные режимы": (
        "Тест отвечает на узкий вопрос в ограниченный период. Постоянная работа с сайтом включает семантику, контент, "
        "техническую часть и коммерческие страницы, которые меняются в разном темпе. Не стоит ждать, что один запуск "
        "заменит эту работу или даст окончательный ответ о сайте. Полезнее заранее записать, что именно проверяется "
        "сейчас и какие решения остаются за пределами теста."
    ),
    "Когда изменения мешают оценке": (
        "Если за неделю одновременно поменять дизайн, цены, тексты, структуру каталога и настройки рекламы, причина "
        "изменений в данных останется неясной. Это не означает, что сайт нельзя улучшать. Просто для каждой заметной "
        "правки нужен короткий журнал: что изменили, на каких страницах и когда. Такая запись помогает вернуться к "
        "решению позже, даже если команду или приоритеты уже поменяли."
    ),
    "Ранжирование нельзя свести к одному сигналу": (
        "Разговор о ранжировании часто сводят к одному фактору, потому что так проще объяснить результат. На практике "
        "страница может быть хорошо написана, но плохо отвечать на коммерческий запрос, или быть полезной, но иметь "
        "проблемы с доступностью. Вместо поиска одного универсального сигнала лучше разложить проверку на содержание, "
        "технику, соответствие задаче и фактические наблюдения по группе запросов."
    ),
    "Семантика это не просто список фраз": (
        "Семантика становится полезной, когда запросы объединены по задаче пользователя, а не только по совпадающим "
        "словам. В одной группе могут оказаться выбор услуги, цена, сравнение и инструкция - но для сайта это разные "
        "страницы или разные блоки ответа. Разметка интента помогает увидеть пробелы в структуре и не заставлять одну "
        "страницу одновременно продавать, объяснять и отвечать на все частные вопросы."
    ),
    "Как фиксировать изменения": (
        "Журнал изменений не требует сложной системы. Достаточно даты, страницы, сути правки и причины, по которой "
        "её сделали. Например, добавили блок с условиями, переписали первый экран или исправили форму. Не записывайте "
        "в журнал предполагаемый результат как свершившийся факт. Через несколько недель он станет опорой для проверки: "
        "что изменилось на сайте и какие данные были доступны в тот момент."
    ),
    "Почему контент влияет на выводы": (
        "Контент влияет на выводы не количеством слов, а тем, насколько он закрывает вопрос посетителя. Страница об "
        "услуге должна объяснять предмет разговора, условия и следующий шаг; статья - разбирать тему без маскировки "
        "под продажу. Когда между запросом и содержанием есть разрыв, добавление ключевых фраз редко делает текст "
        "понятнее. Сначала нужно решить, какой ответ читатель действительно ищет."
    ),
    "Локальный спрос и страница": (
        "Локальный спрос часто заметен в деталях запроса: район, город, срочность, выезд или доставка. Эти детали "
        "нужны не ради механической подстановки слов. Они помогают показать реальную географию работы, контакты и "
        "условия для конкретного клиента. Если компания не оказывает услугу в городе, лучше не создавать страницу с "
        "обещанием, которое не удастся выполнить после обращения."
    ),
    "Период проверки меняет картину": (
        "Короткий срез отвечает на вопрос, что произошло сейчас. Более длинный период помогает увидеть, было ли это "
        "обычным колебанием, сезонностью или следствием изменений на сайте. Ошибка возникает, когда эти два режима "
        "сравнения смешивают в одном выводе. Выберите период до проверки и не меняйте его задним числом только потому, "
        "что новая цифра выглядит убедительнее."
    ),
    "Как разобрать группу целевых запросов": (
        "Начните с того, какие вопросы стоят за запросами. Часть из них может вести к одной услуге, а часть - к "
        "категории, сравнению или справочному материалу. Затем посмотрите, есть ли для каждой группы понятная страница "
        "и не конкурируют ли две страницы за один и тот же смысл. Такая разборка полезнее бесконечного расширения списка "
        "фраз: она связывает семантику со структурой сайта."
    ),
    "Когда тест лучше остановить": (
        "Тест стоит остановить, если условия перестали быть сопоставимыми. Например, сайт перенесли, форма перестала "
        "работать, одновременно началась крупная рекламная кампания или изменили десятки целевых страниц. Остановка не "
        "означает провал. Она сохраняет честность наблюдения: сначала фиксируют произошедшее, затем выбирают новый период "
        "и возвращаются к вопросу без смешения разных событий."
    ),
    "Позиции и другие наблюдения": (
        "Позиции полезны, когда рядом есть другие наблюдения: какие страницы получают показы, что происходит с "
        "переходами, есть ли обращения и менялась ли сама страница. Не каждый рост или спад требует немедленной "
        "реакции. Сначала стоит понять масштаб и повторяемость сигнала. Это защищает от решений, принятых по одному "
        "дню, одному запросу или случайной смене порядка результатов."
    ),
    "Как говорить об обновлениях поиска": (
        "Об изменениях поисковых систем легко говорить уверенно, но без источника это остаётся предположением. Для "
        "публичного поста полезно отделить официальное сообщение, наблюдение по данным и собственную гипотезу. Если "
        "подтверждения нет, лучше прямо назвать ограничение, чем строить совет на слухе. Такой подход помогает не "
        "переносить краткосрочное изменение в список обязательных действий для каждого сайта."
    ),
    "Почему стабильность сайта важна": (
        "Стабильность сайта важна не только для технического отчёта. Если страница долго открывается, выдаёт ошибку "
        "или форма теряет введённые данные, посетитель не дойдёт до содержательной части предложения. Проверяйте такие "
        "сценарии после обновлений, смены хостинга и до запуска рекламных или SEO работ. Сначала устраняют препятствие "
        "для пользователя, а затем оценивают более тонкие изменения в содержании и структуре."
    ),
}

# Endings are part of the editorial angle for a particular scheduled subject.
# They are deliberately not a channel-wide product claim or a universal CTA.
SCHEDULE_CONCLUSIONS = {
    "Что проверить перед запуском ПФ": "После такой подготовки тест остаётся отдельным вопросом с понятными условиями. Если страница или форма меняются в процессе, это лучше отметить сразу, а не пытаться восстановить картину по памяти.",
    "Почему одна позиция не описывает выдачу": "Такой просмотр не превращает выдачу в набор догадок. Он помогает заметить, где нужна отдельная страница, а где достаточно уточнить роль уже существующей.",
    "Техническая готовность страницы": "Проверка занимает немного времени, если смотреть на путь посетителя целиком. Результат полезнее записать как конкретную неисправность или подтверждённый сценарий, а не как общее ощущение о сайте.",
    "Как интент меняет роль страницы": "Разделение задач делает структуру сайта спокойнее: у каждого материала появляется свой читатель и свой следующий шаг. Это особенно заметно там, где одна страница раньше пыталась ответить сразу на несколько разных вопросов.",
    "Регион как часть поискового контекста": "Региональная страница работает лучше, когда в ней есть проверяемая информация для местного клиента. Это полезнее, чем расширять число похожих страниц без новых условий, контактов или услуги.",
    "Что дают данные до запуска": "Такой снимок нужен не для красивого отчёта. Он даёт команде общую точку отсчёта, к которой можно вернуться после изменений без спора о том, что было раньше.",
    "Проверка коммерческой релевантности": "Если посетителю приходится уточнять базовые условия в переписке, страница ещё не сделала свою часть работы. Начните с одного неясного вопроса и проверьте, находится ли ответ там, где его ждут увидеть.",
    "Тест и постоянная работа это разные режимы": "У теста должен быть собственный вопрос и конечный момент, а у сайта - регулярный план улучшений. Когда эти режимы не смешиваются, легче понять, что именно обсуждает команда.",
    "Когда изменения мешают оценке": "Журнал не запрещает доработки, он даёт им порядок. По нему видно, какие изменения можно сравнивать между собой, а какие требуют нового периода наблюдения.",
    "Ранжирование нельзя свести к одному сигналу": "Такой разбор не обещает быстрый ответ, зато не заставляет лечить страницу случайным набором приёмов. Каждая найденная проблема получает свою проверку и свою очередь.",
    "Семантика это не просто список фраз": "Хорошая группировка заканчивается не таблицей, а понятным решением: какую задачу закрывает страница и что на ней должно быть для человека. Это снимает лишние повторы в структуре и тексте.",
    "Как фиксировать изменения": "Через время такая запись помогает отделить сделанную работу от её ожидаемого эффекта. Это полезная основа для следующего разбора, даже если цифры пока не изменились.",
    "Почему контент влияет на выводы": "Сначала стоит назвать вопрос, который страница должна закрыть, и только потом оценивать текст. Так доработка остаётся содержательной, а не превращается в механическое добавление фраз.",
    "Локальный спрос и страница": "Полезная локальная страница экономит время и посетителю, и менеджеру: она заранее объясняет, можно ли получить услугу и на каких условиях. Неподтверждённую географию лучше не выдавать за преимущество.",
    "Период проверки меняет картину": "Выбранный период стоит сохранить вместе с причиной выбора. Тогда короткое изменение не будет случайно выдано за тенденцию, а длинный период не скроет важное событие на сайте.",
    "Как разобрать группу целевых запросов": "После такой разборки проще увидеть недостающую страницу или конфликт двух похожих материалов. Это уже предметная задача для сайта, а не абстрактное желание добавить больше ключей.",
    "Когда тест лучше остановить": "Пауза даёт возможность вернуть условия к понятной точке и запустить новый период честно. Продолжать измерение при сломанных исходных данных обычно менее полезно, чем зафиксировать причину остановки.",
    "Позиции и другие наблюдения": "Сводите наблюдения к одному вопросу за раз: что изменилось, где это видно и повторяется ли сигнал. Такой порядок помогает не превращать каждое колебание в срочную правку сайта.",
    "Как говорить об обновлениях поиска": "Аккуратная формулировка не делает материал слабее. Она показывает читателю, где заканчивается подтверждённый факт и начинается рабочая гипотеза, которую ещё нужно проверить на своих данных.",
    "Почему стабильность сайта важна": "После исправления доступности имеет смысл повторно пройти путь пользователя, а не ограничиваться технической отметкой. Так понятно, действительно ли страница снова доступна для обращения.",
}

SCHEDULE_EXPANSIONS = {
    "Что проверить перед запуском ПФ": "Полезно отдельно пройти первый экран, контакты и отправку заявки. Это не оценка продвижения, а проверка того, что после перехода человеку есть куда двигаться дальше.",
    "Почему одна позиция не описывает выдачу": "Смотрите не только место в списке, но и тип ответа, который поисковик показывает рядом. Иногда сама выдача подсказывает, что для запроса нужен другой формат страницы.",
    "Техническая готовность страницы": "Особенно важно проверить это без авторизации и в обычном браузере телефона. Посетитель не видит внутренние настройки сайта, он видит только открывшуюся страницу или препятствие.",
    "Как интент меняет роль страницы": "Перед текстовой доработкой полезно выписать один вопрос, с которым приходит человек. Он быстро показывает, достаточно ли странице объяснения, выбора или условий покупки.",
    "Регион как часть поискового контекста": "Проверьте, совпадают ли адрес, телефон, зона работы и сроки с тем, что написано в тексте. Для посетителя это не детали SEO, а основания доверять предложению.",
    "Что дают данные до запуска": "В снимок стоит включить не только цифры, но и перечень страниц, к которым они относятся. Иначе позже можно сравнивать разные объекты и не заметить подмену вопроса.",
    "Проверка коммерческой релевантности": "Посмотрите на страницу глазами человека, который впервые увидел её по запросу. Если для понимания цены или процесса нужно искать несколько разделов, ответ пока разбит слишком сильно.",
    "Тест и постоянная работа это разные режимы": "Регулярные задачи можно вести своим темпом, не подгоняя их под дату теста. Например, техническая ошибка или пробел в услуге требуют отдельного решения и отдельной проверки.",
    "Когда изменения мешают оценке": "Даже простая таблица с датами помогает не забыть о правках через месяц. В ней важнее точность события, чем длинное объяснение предполагаемого эффекта.",
    "Ранжирование нельзя свести к одному сигналу": "Полезно сначала определить, что именно наблюдается: проблема конкретной страницы, группы запросов или доступа к сайту. После этого набор проверок становится короче и понятнее.",
    "Семантика это не просто список фраз": "Необязательно создавать страницу под каждую формулировку. Важно не смешать на одной странице тех, кто выбирает услугу, и тех, кто пока только изучает тему.",
    "Как фиксировать изменения": "Записывайте и небольшие правки, если они касаются целевой страницы или формы. Позже именно они часто объясняют, почему сравнение двух периодов перестало быть чистым.",
    "Почему контент влияет на выводы": "Проверьте первые абзацы, условия и ответы на частые сомнения. Если ключевой смысл прячется глубоко в тексте, посетитель может уйти раньше, чем найдёт нужную информацию.",
    "Локальный спрос и страница": "Для проверки можно собрать реальные вопросы, которые получает отдел продаж по этому региону. Они часто точнее подсказывают нужные условия на странице, чем повторение названия города.",
    "Период проверки меняет картину": "Если в середине периода был перенос сайта, акция или технический сбой, отметьте это рядом с данными. Без такой отметки сравнение выглядит точным, но отвечает уже на другой вопрос.",
    "Как разобрать группу целевых запросов": "Удобно начать с небольшой группы, где смысл запросов действительно близок. После проверки ролей страниц можно расширять работу, не создавая новый конфликт в структуре.",
    "Когда тест лучше остановить": "К остановке стоит относиться как к записи о состоянии, а не как к оценке результата. Она сохраняет исходные данные для следующего запуска, когда условия снова станут сравнимыми.",
    "Позиции и другие наблюдения": "Добавьте к позиции дату, страницу и источник наблюдения. Тогда одинаковая цифра в отчёте не будет выглядеть одинаково, если за ней стоят разные запросы или разные посадочные страницы.",
    "Как говорить об обновлениях поиска": "Если новость влияет на план работ, сохраните ссылку на первоисточник внутри команды и отделите её от интерпретации. Это помогает не строить изменения сайта на пересказах.",
    "Почему стабильность сайта важна": "Проверяйте не только главную страницу. Ошибка может проявляться на отдельной услуге, в каталоге или на шаге отправки формы, то есть там, где человек уже почти готов обратиться.",
}


_INVITE_REFRAMES = (
    "Полезнее сначала связать решение с одной страницей, группой запросов и задачей пользователя. Тогда следующий шаг определяется контекстом, а не случайной цифрой или отдельной настройкой. Это помогает не смешивать разные причины в одном выводе.",
    "Одна настройка редко отвечает на вопрос сама по себе. Сначала стоит понять, какую задачу решает страница и какие условия действительно относятся к ней. Так решение опирается на наблюдение, а не на привычный шаблон.",
    "Когда в одном запуске оказываются разные страницы и намерения, даже аккуратная статистика становится менее понятной. Начните с одного проверяемого вопроса: это даёт основание для следующего действия, а не только для отчёта.",
    "Сначала зафиксируйте, что именно меняется и какую задачу пользователя это затрагивает. Такой порядок не заменяет подробный разбор, но помогает увидеть, где нужна проверка, а где вывод пока преждевременен.",
)

_INVITE_BRIDGES = (
    "В основном канале MetricHit разбираем, как продолжить такую проверку и не смешивать разные задачи сайта.",
    "В основном канале MetricHit показываем, как разобрать эту тему глубже на уровне страниц и групп запросов.",
    "В основном канале MetricHit продолжаем разбор: как превратить этот принцип в понятный план работы.",
    "В основном канале MetricHit разбираем детали, которые помогают принять следующее решение по проекту.",
)

_INVITE_CONTEXTS = (
    "Дальше важно не подменять этот вопрос более общим отчётом или поспешным выводом.",
    "Так проще увидеть, какие детали действительно относятся к теме, а какие требуют отдельной проверки.",
    "Иначе следующая настройка рискует остаться случайным выбором без понятного основания.",
    "Это оставляет место для дальнейшего решения по фактам, а не для догадки.",
)


class TelegramTransport(Protocol):
    def call(self, method: str, payload: dict[str, object]) -> dict[str, object]: ...


def channel_message_payload(channel_id: int, content: str) -> dict[str, object]:
    """Build the narrowly validated Markdown payload used by invite posts."""
    text = content
    try:
        validate_publication_text(text)
    except ValueError as error:
        raise ValueError("Пост не проходит контроль качества публикации.") from error
    return {
        "chat_id": channel_id,
        "text": text,
        "parse_mode": "Markdown",
        "link_preview_options": {"is_disabled": True},
    }


class UrllibTelegramTransport:
    """Small Telegram API boundary; construction performs no network I/O."""

    def __init__(self, token: str):
        if not token.strip():
            raise ValueError("METRICHIT_PUBLISHER_BOT_TOKEN is required")
        self._base_url = f"https://api.telegram.org/bot{token}/"

    def call(self, method: str, payload: dict[str, object]) -> dict[str, object]:
        request = Request(
            self._base_url + method,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json"}, method="POST",
        )
        with urlopen(request, timeout=35) as response:  # noqa: S310 - fixed Telegram API URL
            result = json.load(response)
        if not result.get("ok"):
            raise RuntimeError(f"Telegram API {method} failed")
        return result


@dataclass(frozen=True)
class Draft:
    job_id: str
    version: int
    topic: str
    content: str
    content_hash: str
    status: str
    image_brief: str
    image_artifact: str


IMAGE_ARTIFACT_REQUIRED = "image-required-before-publication"


def _prepared_image_exists(artifact: str) -> bool:
    """An offline package names a real local asset; a label alone is not a visual."""
    return bool(artifact.strip()) and artifact != IMAGE_ARTIFACT_REQUIRED and Path(artifact).is_file()


@dataclass(frozen=True)
class Decision:
    accepted: bool
    status: str
    reason: str


@dataclass(frozen=True)
class ChannelCandidate:
    channel_id: int
    title: str
    username: str | None


@dataclass(frozen=True)
class ChannelBinding:
    channel_id: int
    title: str
    username: str | None


@dataclass(frozen=True)
class TestSchedule:
    schedule_id: str
    owner_user_id: int
    channel_id: int
    status: str
    started_at: datetime
    ends_at: datetime
    published_slots: int


class ContentPublisherStore:
    """Private SQLite registry for jobs, immutable draft versions and decisions."""

    def __init__(self, database_path: str | Path, now: Callable[[], datetime] | None = None,
                 author: LocalPostAuthor | None = None):
        self.database_path = str(database_path)
        self._now = now or (lambda: datetime.now(UTC))
        self.author = author or LocalPostAuthor(DeterministicLocalAdapter())
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _timestamp(self) -> str:
        return self._now().astimezone(UTC).isoformat()

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS content_jobs (
                    id TEXT PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL,
                    channel_key TEXT NOT NULL CHECK(channel_key = 'metrichit'),
                    topic TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN (
                        'in_review', 'revision_requested', 'rejected', 'ready_to_publish'
                    )),
                    current_version INTEGER NOT NULL CHECK(current_version > 0),
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_drafts (
                    job_id TEXT NOT NULL REFERENCES content_jobs(id),
                    version INTEGER NOT NULL CHECK(version > 0),
                    content TEXT NOT NULL,
                    image_brief TEXT NOT NULL,
                    image_artifact TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    revision_note TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, version)
                );
                CREATE TABLE IF NOT EXISTS content_decisions (
                    id INTEGER PRIMARY KEY,
                    job_id TEXT NOT NULL REFERENCES content_jobs(id),
                    version INTEGER NOT NULL,
                    actor_user_id INTEGER NOT NULL,
                    action TEXT NOT NULL CHECK(action IN ('approve', 'revise', 'reject')),
                    outcome TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_channel_candidates (
                    owner_user_id INTEGER PRIMARY KEY,
                    channel_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    username TEXT,
                    observed_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_channel_binding (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    channel_id INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    username TEXT,
                    bound_by_user_id INTEGER NOT NULL,
                    bound_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_owner_binding (
                    singleton INTEGER PRIMARY KEY CHECK(singleton = 1),
                    owner_user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    verified_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_publications (
                    job_id TEXT NOT NULL REFERENCES content_jobs(id),
                    version INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    telegram_message_id INTEGER NOT NULL,
                    published_at TEXT NOT NULL,
                    PRIMARY KEY(job_id, version)
                );
                CREATE TABLE IF NOT EXISTS content_test_schedule (
                    schedule_id TEXT PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active', 'stopped', 'completed', 'failed')),
                    started_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    stopped_at TEXT,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS content_test_schedule_slots (
                    schedule_id TEXT NOT NULL,
                    slot_index INTEGER NOT NULL CHECK(slot_index >= 0 AND slot_index < 20),
                    due_at TEXT NOT NULL,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('pending', 'sending', 'published', 'skipped')),
                    telegram_message_id INTEGER,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY(schedule_id, slot_index)
                );
                """
            )
            self._migrate_test_schedule_history(connection)
            self._refresh_pending_test_slots(connection)

    @staticmethod
    def _migrate_test_schedule_history(connection: sqlite3.Connection) -> None:
        """Upgrade the original singleton schedule table without losing its run."""
        columns = {
            str(row["name"])
            for row in connection.execute("PRAGMA table_info(content_test_schedule)").fetchall()
        }
        if "singleton" in columns:
            connection.executescript(
                """
                ALTER TABLE content_test_schedule RENAME TO content_test_schedule_legacy;
                CREATE TABLE content_test_schedule (
                    schedule_id TEXT PRIMARY KEY,
                    owner_user_id INTEGER NOT NULL,
                    channel_id INTEGER NOT NULL,
                    status TEXT NOT NULL CHECK(status IN ('active', 'stopped', 'completed', 'failed')),
                    started_at TEXT NOT NULL,
                    ends_at TEXT NOT NULL,
                    stopped_at TEXT,
                    updated_at TEXT NOT NULL
                );
                INSERT INTO content_test_schedule
                    (schedule_id, owner_user_id, channel_id, status, started_at, ends_at, stopped_at, updated_at)
                SELECT schedule_id, owner_user_id, channel_id, status, started_at, ends_at, stopped_at, updated_at
                FROM content_test_schedule_legacy;
                DROP TABLE content_test_schedule_legacy;
                """
            )
        connection.execute(
            """CREATE UNIQUE INDEX IF NOT EXISTS content_test_schedule_one_active
               ON content_test_schedule(status) WHERE status='active'"""
        )

    def _refresh_pending_test_slots(self, connection: sqlite3.Connection) -> None:
        """Replace only unsent legacy slots after a code update; history stays immutable."""
        pending = connection.execute(
            "SELECT schedule_id, slot_index FROM content_test_schedule_slots WHERE status='pending'"
        ).fetchall()
        timestamp = self._timestamp()
        for row in pending:
            slot_index = int(row["slot_index"])
            kind, direction, topic, opening = TEST_POSTS[slot_index]
            content = self._render(topic, opening=opening, kind=kind, direction=direction)
            connection.execute(
                """UPDATE content_test_schedule_slots SET content=?, content_hash=?, updated_at=?
                   WHERE schedule_id=? AND slot_index=? AND status='pending'""",
                (content, self._hash(content), timestamp, str(row["schedule_id"]), slot_index),
            )

    def _render(self, topic: str, revision_note: str = "", opening: str | None = None,
                kind: PostKind = PostKind.INFORMATIONAL, direction: str | None = None) -> str:
        clean_topic = " ".join(topic.split())
        if not clean_topic:
            raise ValueError("Тема не может быть пустой.")
        profile = AuthorProfile(
            tone="прямой, спокойный, профессиональный", audience="владельцы сайтов и SEO-специалисты",
            product_facts=(),
            constraints=(
                "Не раскрывать поисковую механику бота.",
                "Использовать Markdown только для заголовка и строки основного канала; emoji допустимы только в footer.",
                "Не выдумывать кейсы, метрики, факты или обновления поисковых систем.",
                "Инструкции и последовательные действия использовать только для практического формата.",
                "Работать по тематическим направлениям: " + "; ".join(THEMATIC_DIRECTIONS) + ".",
            ),
            default_cta="",
        )
        variant = int(hashlib.sha256(clean_topic.encode("utf-8")).hexdigest(), 16) % len(_INVITE_REFRAMES)
        conclusion = _INVITE_BRIDGES[variant]
        source_notes = f"{_INVITE_REFRAMES[variant]} {_INVITE_CONTEXTS[variant]}"
        content = self.author.draft(profile, PostRequest(
            kind, clean_topic, opening or "Разбираем тему спокойно, без общих обещаний и выдуманных примеров.",
            direction=direction, source_notes=source_notes, conclusion=conclusion,
        )).text
        if revision_note:
            content = content.removesuffix(CANONICAL_FOOTER).rstrip()
            content += f"\n\nУчтено при доработке: {revision_note.strip()}\n\n{CANONICAL_FOOTER}"
        validate_publication_text(content)
        return content

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def create_job(self, owner_user_id: int, topic: str) -> Draft:
        content = self._render(topic)
        job_id = uuid.uuid4().hex[:16]
        version = 1
        timestamp = self._timestamp()
        with self._connect() as connection:
            image_brief = f"Подготовить релевантный визуал для темы: {topic.strip()}."
            connection.execute(
                "INSERT INTO content_jobs VALUES (?, ?, 'metrichit', ?, 'in_review', ?, ?, ?)",
                (job_id, owner_user_id, " ".join(topic.split()), version, timestamp, timestamp),
            )
            connection.execute(
                "INSERT INTO content_drafts VALUES (?, ?, ?, ?, ?, ?, '', ?)",
                (job_id, version, content, image_brief, IMAGE_ARTIFACT_REQUIRED, self._hash(content), timestamp),
            )
        return self.get(job_id)

    def attach_image_artifact(self, job_id: str, version: int, actor_user_id: int, artifact: str) -> Draft:
        """Record an owner-prepared visual; this offline author never creates image files."""
        clean_artifact = artifact.strip()
        if not _prepared_image_exists(clean_artifact):
            raise ValueError("Укажите путь к существующему подготовленному визуалу для публикации.")
        with self._connect() as connection:
            row = connection.execute(
                "SELECT owner_user_id, current_version FROM content_jobs WHERE id=?", (job_id,)
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if int(row["owner_user_id"]) != actor_user_id:
                raise PermissionError(ACCESS_DENIED)
            if int(row["current_version"]) != version:
                raise ValueError("Визуал можно приложить только к актуальной версии.")
            connection.execute(
                "UPDATE content_drafts SET image_artifact=? WHERE job_id=? AND version=?",
                (clean_artifact, job_id, version),
            )
        return self.get(job_id)

    def get(self, job_id: str) -> Draft:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT j.id, j.current_version, j.topic, j.status, d.content, d.content_hash, d.image_brief, d.image_artifact
                   FROM content_jobs j JOIN content_drafts d
                     ON d.job_id = j.id AND d.version = j.current_version
                   WHERE j.id = ?""",
                (job_id,),
            ).fetchone()
        if row is None:
            raise KeyError(job_id)
        return Draft(
            job_id=str(row["id"]), version=int(row["current_version"]), topic=str(row["topic"]),
            content=str(row["content"]), content_hash=str(row["content_hash"]),
            status=str(row["status"]), image_brief=str(row["image_brief"]), image_artifact=str(row["image_artifact"]),
        )

    def list_jobs(self, owner_user_id: int) -> list[Draft]:
        with self._connect() as connection:
            ids = connection.execute(
                "SELECT id FROM content_jobs WHERE owner_user_id = ? ORDER BY created_at DESC, id DESC",
                (owner_user_id,),
            ).fetchall()
        return [self.get(str(row["id"])) for row in ids]

    def request_revision(self, job_id: str, version: int, actor_user_id: int) -> Decision:
        return self._transition(job_id, version, actor_user_id, "revise", "revision_requested")

    def reject(self, job_id: str, version: int, actor_user_id: int) -> Decision:
        return self._transition(job_id, version, actor_user_id, "reject", "rejected")

    def approve(self, job_id: str, version: int, actor_user_id: int) -> Decision:
        return self._transition(job_id, version, actor_user_id, "approve", "ready_to_publish")

    def _transition(
        self, job_id: str, version: int, actor_user_id: int, action: str, target: str
    ) -> Decision:
        timestamp = self._timestamp()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT owner_user_id, current_version, status FROM content_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                return Decision(False, "missing", "Черновик не найден.")
            if int(row["owner_user_id"]) != actor_user_id:
                return Decision(False, str(row["status"]), ACCESS_DENIED)
            if int(row["current_version"]) != version:
                return Decision(False, str(row["status"]), "Эта кнопка относится к устаревшей версии.")
            if str(row["status"]) != "in_review":
                return Decision(False, str(row["status"]), "Решение по этой версии уже принято.")
            changed = connection.execute(
                """UPDATE content_jobs SET status = ?, updated_at = ?
                   WHERE id = ? AND current_version = ? AND status = 'in_review'""",
                (target, timestamp, job_id, version),
            ).rowcount
            if changed != 1:
                return Decision(False, str(row["status"]), "Состояние черновика изменилось.")
            connection.execute(
                "INSERT INTO content_decisions(job_id, version, actor_user_id, action, outcome, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (job_id, version, actor_user_id, action, target, timestamp),
            )
        return Decision(True, target, "Решение сохранено.")

    def revise(self, job_id: str, actor_user_id: int, note: str) -> Draft:
        clean_note = " ".join(note.split())
        if not clean_note:
            raise ValueError("Укажите, что нужно изменить.")
        timestamp = self._timestamp()
        with self._connect() as connection:
            row = connection.execute(
                "SELECT owner_user_id, topic, status, current_version FROM content_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if row is None:
                raise KeyError(job_id)
            if int(row["owner_user_id"]) != actor_user_id:
                raise PermissionError(ACCESS_DENIED)
            if str(row["status"]) != "revision_requested":
                raise ValueError("Сначала нажмите «Доработать» у актуальной версии.")
            version = int(row["current_version"]) + 1
            content = self._render(str(row["topic"]), clean_note)
            connection.execute(
                "INSERT INTO content_drafts VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (job_id, version, content, f"Подготовить релевантный визуал для темы: {row['topic']}.", IMAGE_ARTIFACT_REQUIRED, self._hash(content), clean_note, timestamp),
            )
            connection.execute(
                "UPDATE content_jobs SET status = 'in_review', current_version = ?, updated_at = ? WHERE id = ?",
                (version, timestamp, job_id),
            )
        return self.get(job_id)

    def remember_channel_candidate(self, owner_user_id: int, candidate: ChannelCandidate) -> None:
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO content_channel_candidates(owner_user_id, channel_id, title, username, observed_at)
                   VALUES (?, ?, ?, ?, ?)
                   ON CONFLICT(owner_user_id) DO UPDATE SET channel_id=excluded.channel_id,
                     title=excluded.title, username=excluded.username, observed_at=excluded.observed_at""",
                (owner_user_id, candidate.channel_id, candidate.title, candidate.username, self._timestamp()),
            )

    def bind_channel(self, owner_user_id: int, candidate: ChannelCandidate) -> ChannelBinding:
        with self._connect() as connection:
            existing = connection.execute(
                "SELECT channel_id FROM content_channel_binding WHERE singleton = 1"
            ).fetchone()
            if existing is not None and int(existing["channel_id"]) != candidate.channel_id:
                raise ValueError("Тестовый канал уже подключён; смена канала заблокирована.")
            connection.execute(
                """INSERT INTO content_channel_binding(singleton, channel_id, title, username, bound_by_user_id, bound_at)
                   VALUES (1, ?, ?, ?, ?, ?)
                   ON CONFLICT(singleton) DO NOTHING""",
                (candidate.channel_id, candidate.title, candidate.username, owner_user_id, self._timestamp()),
            )
        return self.channel_binding()

    def bind_verified_owner_channel(
        self, owner_user_id: int, candidate: ChannelCandidate
    ) -> ChannelBinding:
        """Atomically persist the first Telegram-verified owner and exact channel."""
        timestamp = self._timestamp()
        with self._connect() as connection:
            owner = connection.execute(
                "SELECT owner_user_id, channel_id FROM content_owner_binding WHERE singleton = 1"
            ).fetchone()
            if owner is not None and (
                int(owner["owner_user_id"]) != owner_user_id
                or int(owner["channel_id"]) != candidate.channel_id
            ):
                raise ValueError("Владелец и тестовый канал уже привязаны.")
            channel = connection.execute(
                "SELECT channel_id FROM content_channel_binding WHERE singleton = 1"
            ).fetchone()
            if channel is not None and int(channel["channel_id"]) != candidate.channel_id:
                raise ValueError("Тестовый канал уже подключён; смена канала заблокирована.")
            connection.execute(
                """INSERT INTO content_channel_binding
                   (singleton, channel_id, title, username, bound_by_user_id, bound_at)
                   VALUES (1, ?, ?, ?, ?, ?)
                   ON CONFLICT(singleton) DO NOTHING""",
                (candidate.channel_id, candidate.title, candidate.username, owner_user_id, timestamp),
            )
            connection.execute(
                """INSERT INTO content_owner_binding
                   (singleton, owner_user_id, channel_id, verified_at)
                   VALUES (1, ?, ?, ?)
                   ON CONFLICT(singleton) DO NOTHING""",
                (owner_user_id, candidate.channel_id, timestamp),
            )
        return self.channel_binding()

    def verified_owner_user_ids(self) -> frozenset[int]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT owner_user_id FROM content_owner_binding WHERE singleton = 1"
            ).fetchone()
        return frozenset() if row is None else frozenset({int(row["owner_user_id"])})

    def bind_latest_channel_candidate(self, owner_user_id: int) -> ChannelBinding:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT channel_id, title, username FROM content_channel_candidates WHERE owner_user_id = ?",
                (owner_user_id,),
            ).fetchone()
            if row is None:
                raise ValueError("Сначала перешлите боту сообщение из нужного канала.")
        return self.bind_channel(owner_user_id, ChannelCandidate(
            int(row["channel_id"]), str(row["title"]), row["username"],
        ))

    def channel_binding(self) -> ChannelBinding:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT channel_id, title, username FROM content_channel_binding WHERE singleton = 1"
            ).fetchone()
        if row is None:
            raise ValueError("Тестовый канал ещё не привязан.")
        return ChannelBinding(int(row["channel_id"]), str(row["title"]), row["username"])

    def record_publication(self, job_id: str, version: int, actor_user_id: int,
                           channel_id: int, telegram_message_id: int) -> None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT j.owner_user_id, j.current_version, j.status, d.image_artifact
                   FROM content_jobs j JOIN content_drafts d ON d.job_id=j.id AND d.version=j.current_version
                   WHERE j.id = ?""", (job_id,)
            ).fetchone()
            if row is not None and not _prepared_image_exists(str(row["image_artifact"])):
                raise ValueError("Перед публикацией нужен подготовленный визуал для этого поста.")
            if row is None:
                raise KeyError(job_id)
            if int(row["owner_user_id"]) != actor_user_id:
                raise PermissionError(ACCESS_DENIED)
            if int(row["current_version"]) != version or str(row["status"]) != "ready_to_publish":
                raise ValueError("К публикации доступна только одобренная актуальная версия.")
            connection.execute(
                "INSERT INTO content_publications VALUES (?, ?, ?, ?, ?)",
                (job_id, version, channel_id, telegram_message_id, self._timestamp()),
            )

    def is_published(self, job_id: str, version: int) -> bool:
        with self._connect() as connection:
            return connection.execute(
                "SELECT 1 FROM content_publications WHERE job_id = ? AND version = ?", (job_id, version)
            ).fetchone() is not None

    def start_test_schedule(self, owner_user_id: int) -> TestSchedule:
        binding = self.channel_binding()
        started_at = self._now().astimezone(UTC)
        ends_at = started_at + timedelta(seconds=TEST_DURATION_SECONDS)
        schedule_id = uuid.uuid4().hex
        timestamp = started_at.isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing = connection.execute(
                "SELECT status FROM content_test_schedule ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            if existing is not None and str(existing["status"]) != "stopped":
                status = str(existing["status"])
                if status == "active":
                    raise ValueError("Тестовое расписание уже активно.")
                if status == "failed":
                    raise ValueError("Предыдущая отправка завершилась неопределённо; повторный запуск заблокирован.")
                raise ValueError("Тестовое расписание уже завершено; повторный запуск заблокирован.")
            connection.execute(
                """INSERT INTO content_test_schedule
                   (schedule_id, owner_user_id, channel_id, status, started_at, ends_at, stopped_at, updated_at)
                   VALUES (?, ?, ?, 'active', ?, ?, NULL, ?)""",
                (schedule_id, owner_user_id, binding.channel_id, timestamp, ends_at.isoformat(), timestamp),
            )
            for slot_index, (kind, direction, topic, opening) in enumerate(TEST_POSTS):
                content = self._render(topic, opening=opening, kind=kind, direction=direction)
                due_at = started_at + timedelta(seconds=slot_index * TEST_INTERVAL_SECONDS)
                connection.execute(
                    """INSERT INTO content_test_schedule_slots
                       (schedule_id, slot_index, due_at, content, content_hash, status, telegram_message_id, updated_at)
                       VALUES (?, ?, ?, ?, ?, 'pending', NULL, ?)""",
                    (schedule_id, slot_index, due_at.isoformat(), content,
                     self._hash(content), timestamp),
                )
        return self.test_schedule()

    def test_schedule(self) -> TestSchedule:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT s.schedule_id, s.owner_user_id, s.channel_id, s.status, s.started_at, s.ends_at,
                          COUNT(sl.slot_index) FILTER (WHERE sl.status = 'published') AS published_slots
                   FROM content_test_schedule s
                   LEFT JOIN content_test_schedule_slots sl ON sl.schedule_id = s.schedule_id
                   WHERE s.schedule_id=(SELECT schedule_id FROM content_test_schedule ORDER BY rowid DESC LIMIT 1)
                   GROUP BY s.schedule_id"""
            ).fetchone()
        if row is None:
            raise ValueError("Тестовое расписание ещё не запущено.")
        return TestSchedule(
            schedule_id=str(row["schedule_id"]), owner_user_id=int(row["owner_user_id"]),
            channel_id=int(row["channel_id"]), status=str(row["status"]),
            started_at=datetime.fromisoformat(str(row["started_at"])),
            ends_at=datetime.fromisoformat(str(row["ends_at"])),
            published_slots=int(row["published_slots"]),
        )

    def stop_test_schedule(self, owner_user_id: int) -> TestSchedule:
        timestamp = self._timestamp()
        with self._connect() as connection:
            row = connection.execute(
                """SELECT schedule_id, owner_user_id, status FROM content_test_schedule
                   ORDER BY rowid DESC LIMIT 1"""
            ).fetchone()
            if row is None:
                raise ValueError("Активного тестового расписания нет.")
            if int(row["owner_user_id"]) != owner_user_id:
                raise PermissionError(ACCESS_DENIED)
            if str(row["status"]) != "active":
                raise ValueError("Тестовое расписание уже остановлено.")
            connection.execute(
                """UPDATE content_test_schedule SET status='stopped', stopped_at=?, updated_at=?
                   WHERE schedule_id=? AND status='active'""", (timestamp, timestamp, str(row["schedule_id"])),
            )
            connection.execute(
                """UPDATE content_test_schedule_slots SET status='skipped', updated_at=?
                   WHERE schedule_id=? AND status='pending'""", (timestamp, str(row["schedule_id"])),
            )
        return self.test_schedule()

    def claim_due_test_slot(self) -> tuple[TestSchedule, int, str] | None:
        """Durably claim at most one due slot before any external send."""
        current = self._now().astimezone(UTC)
        timestamp = current.isoformat()
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            schedule = connection.execute(
                "SELECT * FROM content_test_schedule WHERE status='active' LIMIT 1"
            ).fetchone()
            if schedule is None or str(schedule["status"]) != "active":
                return None
            schedule_id = str(schedule["schedule_id"])
            if current >= datetime.fromisoformat(str(schedule["ends_at"])):
                connection.execute(
                    """UPDATE content_test_schedule SET status='completed', updated_at=?
                       WHERE schedule_id=? AND status='active'""",
                    (timestamp, schedule_id),
                )
                connection.execute(
                    "UPDATE content_test_schedule_slots SET status='skipped', updated_at=? WHERE schedule_id=? AND status='pending'",
                    (timestamp, schedule_id),
                )
                return None
            due = connection.execute(
                """SELECT slot_index, content FROM content_test_schedule_slots
                   WHERE schedule_id=? AND status='pending' AND due_at<=?
                   ORDER BY slot_index""", (schedule_id, timestamp),
            ).fetchall()
            if not due:
                return None
            chosen = due[-1]
            if len(due) > 1:
                connection.executemany(
                    "UPDATE content_test_schedule_slots SET status='skipped', updated_at=? WHERE schedule_id=? AND slot_index=?",
                    [(timestamp, schedule_id, int(row["slot_index"])) for row in due[:-1]],
                )
            connection.execute(
                """UPDATE content_test_schedule_slots SET status='sending', updated_at=?
                   WHERE schedule_id=? AND slot_index=? AND status='pending'""",
                (timestamp, schedule_id, int(chosen["slot_index"])),
            )
        return self.test_schedule(), int(chosen["slot_index"]), str(chosen["content"])

    def finish_test_slot(self, schedule_id: str, slot_index: int, telegram_message_id: int) -> TestSchedule:
        timestamp = self._timestamp()
        with self._connect() as connection:
            changed = connection.execute(
                """UPDATE content_test_schedule_slots SET status='published', telegram_message_id=?, updated_at=?
                   WHERE schedule_id=? AND slot_index=? AND status='sending'""",
                (telegram_message_id, timestamp, schedule_id, slot_index),
            ).rowcount
            if changed != 1:
                raise ValueError("Слот публикации уже обработан.")
            remaining = connection.execute(
                "SELECT COUNT(*) FROM content_test_schedule_slots WHERE schedule_id=? AND status='pending'",
                (schedule_id,),
            ).fetchone()[0]
            if remaining == 0:
                connection.execute(
                    "UPDATE content_test_schedule SET status='completed', updated_at=? WHERE schedule_id=? AND status='active'",
                    (timestamp, schedule_id),
                )
        return self.test_schedule()

    def fail_test_slot(self, schedule_id: str) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE content_test_schedule SET status='failed', updated_at=? WHERE schedule_id=? AND status='active'",
                (self._timestamp(), schedule_id),
            )


class ContentPublisherBot:
    """Owner-only control UI for manual drafts and one active bounded test."""

    def __init__(
        self, store: ContentPublisherStore, owner_user_ids: set[int] | None, transport: TelegramTransport
    ):
        self.store = store
        self.owner_user_ids = frozenset(owner_user_ids or ())
        self.transport = transport
        self.offset: int | None = None

    @classmethod
    def from_environment(
        cls, store: ContentPublisherStore, owner_user_ids: set[int] | None = None
    ) -> "ContentPublisherBot":
        """Build the live adapter without storing its secret or contacting Telegram."""
        if owner_user_ids is None:
            raw_owner_ids = os.environ.get("METRICHIT_PUBLISHER_OWNER_IDS", "")
            try:
                owner_user_ids = {int(value.strip()) for value in raw_owner_ids.split(",") if value.strip()}
            except ValueError as error:
                raise ValueError("METRICHIT_PUBLISHER_OWNER_IDS must contain numeric Telegram user ids") from error
        return cls(store, owner_user_ids, UrllibTelegramTransport(os.environ.get("METRICHIT_PUBLISHER_BOT_TOKEN", "")))

    @staticmethod
    def review_keyboard(draft: Draft) -> dict[str, object]:
        suffix = f"{draft.job_id}:{draft.version}"
        return {"inline_keyboard": [[
            {"text": "✅ Одобрить", "callback_data": f"cp:a:{suffix}"},
            {"text": "✏️ Доработать", "callback_data": f"cp:v:{suffix}"},
            {"text": "❌ Отклонить", "callback_data": f"cp:r:{suffix}"},
        ]]}

    @staticmethod
    def preview(draft: Draft) -> str:
        return (
            f"Черновик {draft.job_id} · версия {draft.version}\nСтатус: {draft.status}\n\n{draft.content}"
        )

    def poll_once(self, timeout: int = 0) -> int:
        payload: dict[str, object] = {"timeout": timeout}
        if self.offset is not None:
            payload["offset"] = self.offset
        response = self.transport.call("getUpdates", payload)
        updates = response.get("result", []) if response.get("ok") else []
        handled = 0
        for update in updates if isinstance(updates, list) else []:
            if not isinstance(update, dict):
                continue
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                self.offset = update_id + 1
            if self._handle_update(update):
                handled += 1
        self.publish_due_test_post()
        return handled

    def run_forever(self, timeout: int = 5) -> None:
        """Keep polling while the local process is running."""
        while True:
            self.poll_once(timeout=timeout)

    def publish_due_test_post(self) -> bool:
        claimed = self.store.claim_due_test_slot()
        if claimed is None:
            return False
        schedule, _slot_index, _content = claimed
        # Scheduled slots have no owner-prepared visual artifact.  They must
        # never become text-only publications under the invite-channel policy.
        self.store.fail_test_slot(schedule.schedule_id)
        return False

    def _authorized(self, user_id: object, chat: object) -> bool:
        active_owner_ids = self.owner_user_ids or self.store.verified_owner_user_ids()
        return (
            isinstance(user_id, int) and user_id in active_owner_ids
            and isinstance(chat, dict) and chat.get("type") == "private" and chat.get("id") == user_id
        )

    @staticmethod
    def _private_sender(user_id: object, chat: object) -> bool:
        return (
            isinstance(user_id, int) and isinstance(chat, dict)
            and chat.get("type") == "private" and chat.get("id") == user_id
        )

    def _try_bind_verified_owner(
        self, user_id: object, chat: object, message: dict[str, object]
    ) -> bool:
        """Bootstrap only from a private channel forward whose sender is its admin."""
        if self.owner_user_ids or self.store.verified_owner_user_ids():
            return False
        candidate = self._forwarded_channel(message)
        if not self._private_sender(user_id, chat) or candidate is None:
            return False
        try:
            response = self.transport.call("getChatMember", {
                "chat_id": candidate.channel_id, "user_id": int(user_id),
            })
            member = response.get("result") if response.get("ok") is True else None
            status = member.get("status") if isinstance(member, dict) else None
            if status not in {"administrator", "creator", "owner"}:
                return False
            binding = self.store.bind_verified_owner_channel(int(user_id), candidate)
        except Exception:
            return False
        self.transport.call("sendMessage", {
            "chat_id": int(user_id),
            "text": f"Владелец и тестовый канал подтверждены: {binding.title}. Для запуска отправьте /start_test.",
        })
        return True

    def _handle_update(self, update: dict[str, object]) -> bool:
        message = update.get("message")
        if isinstance(message, dict):
            chat, sender, text = message.get("chat"), message.get("from"), message.get("text")
            if not isinstance(chat, dict) or not isinstance(sender, dict):
                return False
            chat_id, user_id = chat.get("id"), sender.get("id")
            if not self._authorized(user_id, chat):
                if self._try_bind_verified_owner(user_id, chat, message):
                    return True
                if isinstance(chat_id, int):
                    self.transport.call("sendMessage", {"chat_id": chat_id, "text": ACCESS_DENIED})
                return True
            candidate = self._forwarded_channel(message)
            if candidate is not None:
                self.store.remember_channel_candidate(int(user_id), candidate)
                binding = self.store.bind_channel(int(user_id), candidate)
                self.transport.call("sendMessage", {
                    "chat_id": int(chat_id),
                    "text": f"Тестовый канал подключён: {binding.title}. Для запуска отправьте /start_test.",
                })
                return True
            if not isinstance(text, str):
                return False
            self._handle_text(int(chat_id), int(user_id), text)
            return True
        callback = update.get("callback_query")
        if isinstance(callback, dict):
            sender, callback_message = callback.get("from"), callback.get("message")
            chat = callback_message.get("chat") if isinstance(callback_message, dict) else None
            user_id = sender.get("id") if isinstance(sender, dict) else None
            callback_id = callback.get("id")
            if not self._authorized(user_id, chat):
                if isinstance(callback_id, str):
                    self._answer(callback_id, ACCESS_DENIED, alert=True)
                return True
            self._handle_callback(str(callback_id), int(user_id), str(callback.get("data", "")))
            return True
        return False

    def _handle_text(self, chat_id: int, user_id: int, text: str) -> None:
        command, _, argument = text.strip().partition(" ")
        try:
            if command == "/draft":
                draft = self.store.create_job(user_id, argument)
                self.transport.call("sendMessage", {
                    "chat_id": chat_id, "text": self.preview(draft),
                    "reply_markup": self.review_keyboard(draft),
                })
                return
            if command == "/show":
                draft = self.store.get(argument.strip())
                self.transport.call("sendMessage", {
                    "chat_id": chat_id, "text": self.preview(draft),
                    "reply_markup": self.review_keyboard(draft) if draft.status == "in_review" else {"inline_keyboard": []},
                })
                return
            if command == "/revise":
                job_id, separator, note = argument.partition(" ")
                if not separator:
                    raise ValueError("Формат: /revise ID что изменить")
                draft = self.store.revise(job_id, user_id, note)
                self.transport.call("sendMessage", {
                    "chat_id": chat_id, "text": self.preview(draft),
                    "reply_markup": self.review_keyboard(draft),
                })
                return
            if command == "/list":
                jobs = self.store.list_jobs(user_id)
                body = "\n".join(f"{item.job_id} · v{item.version} · {item.status} · {item.topic}" for item in jobs)
                self.transport.call("sendMessage", {"chat_id": chat_id, "text": body or "Черновиков пока нет."})
                return
            if command == "/bind":
                binding = self.store.bind_latest_channel_candidate(user_id)
                self.transport.call("sendMessage", {
                    "chat_id": chat_id, "text": f"Привязан канал: {binding.title}.",
                })
                return
            if command == "/start_test":
                self.store.start_test_schedule(user_id)
                self.transport.call("sendMessage", {
                    "chat_id": chat_id,
                    "text": (
                        "Тест запущен: 20 постов, по одному каждые 3 минуты. "
                        "Через час расписание остановится автоматически. Команда остановки: /stop"
                    ),
                })
                return
            if command == "/stop":
                schedule = self.store.stop_test_schedule(user_id)
                self.transport.call("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"Расписание остановлено. Опубликовано: {schedule.published_slots}.",
                })
                return
            if command == "/status":
                schedule = self.store.test_schedule()
                self.transport.call("sendMessage", {
                    "chat_id": chat_id,
                    "text": f"Тест: {schedule.status}. Опубликовано: {schedule.published_slots} из {TEST_TOTAL_POSTS}.",
                })
                return
            if command == "/publish":
                draft = self.store.get(argument.strip())
                binding = self.store.channel_binding()
                if draft.status != "ready_to_publish":
                    raise ValueError("Сначала явно одобрите актуальную версию черновика.")
                if not _prepared_image_exists(draft.image_artifact):
                    raise ValueError("Перед публикацией нужен подготовленный визуал для этого поста.")
                if self.store.is_published(draft.job_id, draft.version):
                    raise ValueError("Эта версия уже опубликована.")
                response = self.transport.call(
                    "sendMessage", channel_message_payload(binding.channel_id, draft.content)
                )
                result = response.get("result")
                message_id = result.get("message_id") if isinstance(result, dict) else None
                if not isinstance(message_id, int):
                    raise RuntimeError("Telegram не вернул идентификатор опубликованного сообщения.")
                self.store.record_publication(draft.job_id, draft.version, user_id, binding.channel_id, message_id)
                self.transport.call("sendMessage", {"chat_id": chat_id, "text": "Опубликовано в привязанном канале."})
                return
            help_text = "Команды теста: /start_test, /status, /stop"
            self.transport.call("sendMessage", {"chat_id": chat_id, "text": help_text})
        except (KeyError, ValueError, PermissionError) as error:
            self.transport.call("sendMessage", {"chat_id": chat_id, "text": f"Ошибка: {error}"})

    def _handle_callback(self, callback_id: str, user_id: int, data: str) -> None:
        parts = data.split(":")
        if len(parts) != 4 or parts[0] != "cp" or parts[1] not in {"a", "v", "r"}:
            self._answer(callback_id, "Неизвестное действие.", alert=True)
            return
        action, job_id = parts[1], parts[2]
        try:
            version = int(parts[3])
        except ValueError:
            self._answer(callback_id, "Некорректная версия.", alert=True)
            return
        if action == "a":
            decision = self.store.approve(job_id, version, user_id)
            message = "Одобрено. Версия готова к публикации, но не опубликована." if decision.accepted else decision.reason
        elif action == "v":
            decision = self.store.request_revision(job_id, version, user_id)
            message = f"{decision.reason} Отправьте /revise {job_id} что изменить" if decision.accepted else decision.reason
        else:
            decision = self.store.reject(job_id, version, user_id)
            message = "Черновик отклонён." if decision.accepted else decision.reason
        self._answer(callback_id, message, alert=not decision.accepted)

    def _answer(self, callback_id: str, text: str, *, alert: bool = False) -> None:
        self.transport.call("answerCallbackQuery", {
            "callback_query_id": callback_id, "text": text, "show_alert": alert,
        })

    @staticmethod
    def _forwarded_channel(message: dict[str, object]) -> ChannelCandidate | None:
        """Extract only a channel source from a private forwarded Telegram update."""
        origin = message.get("forward_origin")
        channel = origin.get("chat") if isinstance(origin, dict) and origin.get("type") == "channel" else None
        if not isinstance(channel, dict):
            channel = message.get("forward_from_chat")
        if not isinstance(channel, dict):
            return None
        channel_id, title, username = channel.get("id"), channel.get("title"), channel.get("username")
        if not isinstance(channel_id, int) or not isinstance(title, str) or not title.strip():
            return None
        return ChannelCandidate(channel_id, title.strip(), username if isinstance(username, str) else None)


def main() -> None:
    """Run the dedicated publisher bot from environment-only configuration."""
    database_path = Path(os.environ.get("METRICHIT_PUBLISHER_DB", "data/content-publisher.sqlite"))
    database_path.parent.mkdir(parents=True, exist_ok=True)
    ContentPublisherBot.from_environment(ContentPublisherStore(database_path)).run_forever()


if __name__ == "__main__":
    main()
