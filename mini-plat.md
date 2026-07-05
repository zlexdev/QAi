---
title: AI Web-Testing Agent — автономный краулер-фаззер с корреляцией в код
date: 2026-07-05
updated: 2026-07-05
status: draft
area: tools
tags: [testing, playwright, ai-agent, e2e, fuzzing, crawler, qa, cdp, code-intel]
sources:
  - https://playwright.dev/docs/test-agents  (checked 2026-07-05)
  - https://playwright.dev/docs/getting-started-mcp  (checked 2026-07-05)
  - https://github.com/browserbase/stagehand  (checked 2026-07-05)
  - https://github.com/crawljax/crawljax  (checked 2026-07-05)
  - https://github.com/lucgagan/auto-playwright  (checked 2026-07-05)
  - https://bug0.com/blog/20-underdog-open-source-projects-pushing-limits-ai-playwright  (checked 2026-07-05)
  - https://www.qawolf.com/mapping-ai  (checked 2026-07-05)
  - https://arxiv.org/html/2509.05197v1  (checked 2026-07-05)
---

# AI Web-Testing Agent — автономный краулер-фаззер с корреляцией в код

> **TL;DR / Verdict:** Собери автономного агента, который берёт на вход URL, **обходит
> граф состояний приложения** (клики/формы/навигация), на каждом действии снимает «пакет
> эффектов» (сеть + консоль + редиректы + diff DOM), **типизирует поля и фаззит их**, ловит
> ошибки и **привязывает каждый запрос к строке в исходнике**. Это связка уже готовых
> кусков: **Playwright+CDP** (браузер/сеть/консоль), идея **Crawljax** (state-flow graph),
> **Stagehand** (снятие модели страницы), **ast-grep + `cx`** (запрос → код). Цельного такого
> инструмента на рынке нет — все куски есть, сборки нет. Это и есть ниша.
>
> **Use when:** нужен autonomous-QA/regression-gate поверх своего продукта, или живая карта
> «страница → запрос → хендлер» для легаси. **Avoid when:** нужен один-два ручных теста —
> тогда просто Playwright codegen или Playwright MCP в чате, без всей машинерии.

## Что это

Не «ещё один тест-раннер», а **model-based exploratory tester**: агент строит модель
приложения на лету и сам решает, куда тыкать дальше. Академический прародитель —
[**Crawljax**](https://github.com/crawljax/crawljax) (Java, обходит AJAX-сайты и строит
*state-flow graph*: узлы = уникальные состояния DOM, рёбра = события, переводящие между
ними). Наша дельта над Crawljax — четыре слоя, которых у него нет:

1. **Типизация полей + фаззинг** — по типу инпута (число/строка/дропдаун/дата/файл)
   генерим матрицу вводов (валид/пусто/граница/оверфлоу/инъекция/юникод).
2. **Захват стека сетевых запросов** — через CDP, с фронтовым initiator-стеком.
3. **Корреляция запрос → исходник** — `POST /order/pay` → `OrderService.pay` в
   `order/service.py:88` через `ast-grep` + `cx`.
4. **Триаж ошибок как оракул** — console-error / 5xx / нарушенный инвариант = баг.

## Почему это работает через реюз — карта «слой → готовый инструмент»

Ключ MVP: **почти ничего не писать с нуля**. Каждый слой закрывается зрелым куском.

| Слой | Что нужно | Берём готовое | Пишем сами (glue) |
|---|---|---|---|
| Драйвер браузера | навигация, клики, ввод | **Playwright** (Python) | — |
| Захват сети + стека | все запросы, initiator-стек, тайминги | **CDP** `Network.*` через `page.context.new_cdp_session()` | тонкий `CaptureSession` |
| Захват консоли/ошибок | `console.error`, `pageerror`, unhandled rejection | Playwright `page.on('console'/'pageerror')` | маппер в DTO |
| Захват навигаций | редиректы (3xx), SPA `pushState`, reload | Playwright `framenavigated` + init-script хук на `history` | `NavTracker` |
| Модель страницы | инвентарь полей+типов, кнопок, ссылок | **Stagehand** `observe`/`extract` (или a11y-snapshot Playwright) | `PageModeler` |
| NL-действия (опц.) | «заполни форму логина» без селекторов | **Stagehand** `act` / **auto-playwright** `ai()` | — |
| Обход графа | очередь состояний, дедуп, стейт-машина | **идея Crawljax** (алгоритм, не код) | `Explorer` |
| Генерация данных | матрица вводов по типу поля | — (нет готового) | `DataGenerator` + стратегии |
| Запрос → код | route-таблица, резолв в хендлер | **ast-grep** (декораторы роутов) + **`cx`** (граф вызовов) | `CodeCorrelator` |
| Шина событий | развязать capture ↔ analyze ↔ report | **asyncbus** / **evented** (свои либы) | подписчики |
| Отчёт | JSON + граф состояний | — | `Reporter` |

Итог: `Explorer`, `DataGenerator`, `CodeCorrelator`, `PageModeler`, `Reporter` + тонкие
capture-обёртки — это и есть весь собственный код. Остальное — конфигурация чужих либ.

## Архитектура

```
┌─ Orchestrator (Explorer) ──────────────────────────────┐
│  frontier queue · state dedup · budget · replay engine  │
└───────┬─────────────────────────────────────┬──────────┘
        │ emits domain events (asyncbus)       │
┌───────▼────────┐  ┌──────────────┐  ┌────────▼─────────┐
│ Capture layer  │  │ PageModeler  │  │ DataGenerator    │
│ Playwright+CDP │  │ поля/типы/    │  │ матрица вводов   │
│ net·console·nav│  │ группировка   │  │ per field-type   │
└───────┬────────┘  └──────────────┘  └──────────────────┘
        │ EffectBundle (типизированный DTO)
┌───────▼────────┐  ┌──────────────────────┐  ┌───────────┐
│ Analyzer       │  │ CodeCorrelator        │  │ Reporter  │
│ error/invariant│  │ request → route → src │  │ JSON+graph│
└────────────────┘  │ (ast-grep / cx)       │  └───────────┘
                    └──────────────────────┘
```

Всё на шине событий: Capture эмитит `RequestObserved`, `ConsoleError`, `Navigated`,
`ActionCompleted` → Analyzer/Correlator/Reporter подписаны. Бизнес-логика эмитит **факты**,
не зовёт транспорты — по паттерну events-not-transports.

## Ядро: цикл обхода («прогонять всё там же до конца»)

```
State = (нормализованный URL, структурный хеш DOM, auth-контекст)
Frontier = приоритетная очередь (State, ещё-не-пробованное Action)

while Frontier and budget_left:
    state   = Frontier.pop()
    restore(state)                          # реплей пути действий от чекпоинта (логина)
    model   = PageModeler(snapshot())       # поля+типы, кнопки, ссылки, ГРУППЫ
    actions = enumerate_actions(model)      # форма×вариант-данных, клики, ссылки
    for action in actions:
        effect = execute_and_capture(action)   # сеть + консоль + навигация + DOM-diff
        findings += Analyzer(effect)           # ошибки, 4xx/5xx, инварианты
        CodeCorrelator(effect.requests)        # запрос → файл:строка
        for new_state in effect.reached_states:
            if unseen(new_state): Frontier.push(new_state)   # рекурсия
```

- **Дедуп состояний** — по сигнатуре (URL + *структурный* хеш DOM, не контент; иначе
  таймстемпы/пагинация взрывают граф).
- **Реплей** — каждому State хранится путь действий от чекпоинта (логина); восстановление =
  реплей, т.к. in-memory стейт SPA нельзя просто «перейти по URL».
- **Бюджеты** — max-depth, max-actions, wall-clock; trap-detection на однотипные состояния.

## Захват — два разных «стека»

1. **Кто на фронте инициировал запрос** — CDP `Network.requestWillBeSent.initiator.stack`
   (JS-фреймы: url, function, line, col). Это «стек запросов» в браузере.
2. **Где на бэке реализован** — это уже `CodeCorrelator` (ниже).

Редиректы/переходы: `framenavigated` + 3xx в ответах + инжект-хук на `history.pushState`
(для SPA-роутинга). Каждый переход → кандидат нового State → в очередь.

## Контракты (DTO на границах — заморожены)

```python
class EffectBundle(BaseModel):            # frozen, эмитится Capture-слоем
    action_id: str
    requests: list[CapturedRequest]
    console:  list[ConsoleEntry]          # level, text, source_url:line, stack
    navigations: list[NavEvent]           # from_url, to_url, kind: redirect|push|reload
    dom_diff: DomDiff                      # появилось / исчезло / изменилось
    reached_states: list[StateRef]

class CapturedRequest(BaseModel):
    method: HttpMethod                    # StrEnum
    url: HttpUrl
    route_template: str | None            # /users/{id} — нормализованный путь
    status: int
    response_kind: ResponseKind           # ok|client_error|server_error|network_fail (StrEnum)
    initiator_stack: list[StackFrame]     # фронтовый стек (CDP)
    request_body: JsonValue | None

class FieldModel(BaseModel):
    selector: str
    kind: FieldKind                       # text|number|email|date|select|checkbox|file (StrEnum)
    label: str | None
    group_id: str | None                  # к какой форме/кнопке относится
    constraints: FieldConstraints         # min/max/required/pattern/options

class FuzzCase(BaseModel):
    value: str
    intent: FuzzIntent                    # valid|empty|boundary|overflow|malicious|unicode
    expect: ExpectedOutcome               # accept|reject_gracefully|either

class Finding(BaseModel):
    severity: Severity                    # 🔴|🟡|🟢 (StrEnum)
    kind: FindingKind                     # server_error|console_error|invariant|broken_link…
    at_state: StateRef
    action_id: str
    request: CapturedRequest | None
    source_location: SourceRef | None     # ← из CodeCorrelator: file:line + symbol
    detail: str
```

## CodeCorrelator — «где в коде реализуется запрос»

Двухступенчато, полностью на своём стеке (`ast-grep` + `cx`, без ИИ и платных API):

1. **Индекс роутов** (один раз, инкрементально потом) — по фреймворку вытащить объявления:
   - FastAPI/Flask → `ast-grep` по декораторам `@router.{method}("...")`.
   - Express/Next → route-файлы / `app.get('...')`.
   - Строим `RouteTable: route_template → (file, line, handler_symbol)`.
2. **Резолв запроса** — `CapturedRequest.route_template` → лукап в `RouteTable` →
   `handler_symbol` → **`cx query <handler> --raw`** (что вызывает, какие поля пишет, кто
   дёргает). Так связываем «`POST /order/pay` → `OrderService.pay` в `order/service.py:88`
   → трогает `Wallet.balance`».
3. **Фолбэк** (динамические пути): `grep -rn "<path-fragment>" | cx query --grep --raw`.

Это то, чего нет ни у Stagehand, ни у QA.tech — они не ходят в исходники.

## Группировка «связанные поля ↔ кнопки»

Три сигнала по возрастанию надёжности:

1. **Статически из DOM**: границы `<form>`, `label[for]`, `aria-controls/labelledby`,
   общий контейнер-предок, `fieldset`.
2. **Для SPA без `<form>`**: кластеризация по ближайшему общему предку + видимой секции.
3. **Динамически (сильнейший)**: жмёшь submit-кандидат → смотришь, **значения каких полей
   улетели в теле запроса**. Поля из payload = группа этой кнопки. Даёт маппинг
   «кнопка → запрос → поля» бесплатно из того же `EffectBundle`. ИИ — только на
   неоднозначные мультистеп-визарды.

## Генерация вводов по типам

Registry-паттерн, одна стратегия на тип, расширяемо (open-closed):

```python
class FieldFuzzStrategy(ABC):             # base seam
    @abstractmethod
    def variants(self, field: FieldModel) -> list[FuzzCase]: ...
# реализации: Text / Number / Email / Date / Select / Checkbox / File
```

**Оракул** (что считать багом): `valid` → не должно быть 5xx/console-error; `malicious`/
`overflow` → должен быть **корректный reject**, не 500 и не молчаливый проглот. На
load-bearing путях — assert инвариантов (баланс ≥ 0, статус-переход валиден).

## Защитные рельсы (без них автономный кликер = катастрофа)

- **Классификатор риска кнопок** — до клика распознать destructive (`Delete`, `Pay`,
  `Withdraw`, `Transfer`). Дефолт: destructive → **dry-run / allowlist**, не жать вслепую.
- **Только staging**, не prod. Идемпотентность там, где среда не одноразовая.
- **Trap-detection** — бесконечные календари/пагинации/«добавить поле» → лимит глубины
  однотипных состояний.
- **Auth** — логин один раз → `storageState` персист → детект разлогина (улетел на
  `/login` → восстановить сессию).

---

## MVP-план (реюз-first, поэтапно)

Философия: **каждая фаза выдаёт работающий вертикальный срез**, начиная с самого дешёвого.
Рекурсию по графу и destructive-guard добавляем не раньше, чем нужны.

### Фаза 0 — Capture-скелет (~1 день, ~150 LOC glue)
- Playwright (Python) + `new_cdp_session()`. Подписки на `Network.*`, `console`,
  `pageerror`, `framenavigated`.
- Выход: на любой URL печатается `EffectBundle` (сеть+консоль+навигация) в JSON.
- **Реюз:** Playwright целиком. Пишем только маппер событий → DTO.

### Фаза 1 — Модель страницы + типизация полей (~1 день, ~200 LOC)
- `PageModeler`: a11y-snapshot Playwright **или** Stagehand `extract` со Zod/Pydantic-схемой
  → `list[FieldModel]` + кнопки + ссылки.
- Группировка сигналами 1–2 (статические из DOM).
- Выход: `URL → PageModel` c типами полей и группами.
- **Реюз:** Stagehand `observe`/`extract` для инвентаря; a11y-snapshot как бесплатный фолбэк.

### Фаза 2 — Фаззер одной формы (~1 день, ~250 LOC)
- `DataGenerator` + 4–5 стратегий (Text/Number/Email/Select/Date).
- Прогон матрицы по одной форме → `EffectBundle` на каждый вариант → `Analyzer` (4xx/5xx +
  console-error как оракул).
- Выход: отчёт «форма X: вариант `overflow` → 500, вот запрос».
- **Реюз:** ничего готового — это ядро-дельта, пишем сами. Но объём мал.

### Фаза 3 — Корреляция в код (~1–2 дня, ~250 LOC)
- `CodeCorrelator`: `ast-grep` строит `RouteTable`, `cx query` резолвит хендлер+граф.
- Прошиваем `source_location` в каждый `Finding`.
- Выход: отчёт с прямыми ссылками `file:line` на реализацию упавшего запроса.
- **Реюз:** ast-grep + `cx` (codeanalyzer) целиком; пишем только route-экстрактор под
  один фреймворк (начать с FastAPI — под твой стек).

### Фаза 4 — Обход графа + рекурсия (~3–5 дней, ~600 LOC — это уже «большая» фаза)
- `Explorer`: frontier-очередь, дедуп по структурному хешу DOM, реплей путей, бюджеты.
- Классификатор destructive-кнопок + dry-run guard.
- Выход: полный state-flow graph + все findings до исчерпания бюджета.
- **Реюз:** алгоритм Crawljax как чертёж; asyncbus/evented для шины. Код обхода — свой.

### Границы MVP
- **MVP = Фазы 0–3** (одна форма, без рекурсии): ~850 LOC, ~4–5 дней. Уже полезно —
  фаззит формы и показывает, где в коде ломается.
- **Фаза 4** превращает его в автономный краулер — это отдельный заход (300–2k LOC,
  кросс-слойно) → полный `/swarm-plan` + worktree, не инлайн.

### Стек MVP
`Python 3.12` · `playwright` · опц. `stagehand-py` · `ast-grep` (CLI) · `codeanalyzer` (`cx`) ·
`asyncbus`/`evented` (свои) · `pydantic` DTO · `structlog`.

---

## Сравнение с существующими

| | Обход графа | Типизация+фаззинг полей | Стек сети (CDP) | Запрос→код | Лиценз. |
|---|---|---|---|---|---|
| **Crawljax** | ✅ (эталон) | ❌ | ❌ (Selenium) | ❌ | OSS, Java, устар. |
| **Stagehand** | частично (`agent`) | частично (`extract`) | ❌ | ❌ | MIT |
| **Playwright Test Agents** | ✅ (Planner) | ❌ | частично | ❌ | OSS |
| **QA.tech / Momentic** | ✅ (knowledge graph) | частично | ❌ | ❌ | SaaS |
| **Этот агент** | ✅ (реюз идеи) | ✅ | ✅ | ✅ | свой, self-host |

## Реформулинги (архитектурные пивоты)

- **Не тестер, а «карта приложения как сервис»** — побочный продукт обхода: граф
  `страница → действие → запрос → хендлер → модели`. Живой архитектурный атлас легаси.
- **Не разовый прогон, а CI-gate** — храни baseline графа; на каждом PR диффь `EffectBundle`
  prod-ветки vs PR-ветки, репорть только регрессии (новый 500, пропавший редирект,
  изменённый payload). Regression-diff агент — ниши в OSS нет.
- **Не фронт-инструмент, а бэкенд-observability** — «наблюдённый запрос → строка кода →
  граф `cx`» = автопокрытие эндпоинтов реальным трафиком + поиск мёртвых роутов (есть в
  `RouteTable`, не встретился в обходе).

## Gotchas & pitfalls

- **Дедуп состояний — главная ловушка.** Хешируй *структуру* DOM (теги/роли/иерархию), не
  контент; иначе один список с таймстемпами = бесконечно новые состояния.
- **Реплей SPA.** Нельзя «перейти по URL» — in-memory стейт теряется. Только реплей пути
  действий от чекпоинта. Заложи это с Фазы 4, не прикручивай потом.
- **Crawljax брать как алгоритм, не как код** — Java/Selenium-стек устарел относительно
  Playwright/CDP; переписывай мотор обхода сам, там же получаешь сеть/консоль из коробки.
- **Автономный клик по prod = снос данных.** Destructive-guard и staging-only — не опция.
- > ⚠️ UNVERIFIED: точность CDP `initiator.stack` на минифицированном/бандленном фронте без
  source-map может давать бесполезные фреймы — проверить на реальном таргете до ставки на
  фронтовый стек как на сигнал (бэкенд-корреляция через `RouteTable` надёжнее).

## Sources

- [Playwright Test Agents](https://playwright.dev/docs/test-agents) — Planner/Generator/Healer (checked 2026-07-05)
- [Playwright MCP](https://playwright.dev/docs/getting-started-mcp) — live-browser tools, console/network (checked 2026-07-05)
- [Stagehand (GitHub)](https://github.com/browserbase/stagehand) — act/extract/observe/agent, MIT (checked 2026-07-05)
- [Crawljax (GitHub)](https://github.com/crawljax/crawljax) — state-flow graph, эталон обхода (checked 2026-07-05)
- [auto-playwright](https://github.com/lucgagan/auto-playwright) — NL-действия, OSS (checked 2026-07-05)
- [20 OSS AI+Playwright projects (Bug0)](https://bug0.com/blog/20-underdog-open-source-projects-pushing-limits-ai-playwright) (checked 2026-07-05)
- [QA Wolf Mapping AI](https://www.qawolf.com/mapping-ai) — knowledge-graph обход (checked 2026-07-05)
- [AI Agents for Web Testing: case study (arXiv)](https://arxiv.org/html/2509.05197v1) (checked 2026-07-05)

## See also

- [QA-агент — конкретный MVP-стек (Фазы 0–3)](ai-web-testing-agent-stack.md) — что `pip install`, чем деплоить, порядок сборки
- [ast-grep](../tools/) · codeanalyzer `cx` — движок корреляции запрос→код
- [Site pentest recon](../../) — тот же state-graph обход используют security-сканеры (ZAP форкнул Crawljax)
