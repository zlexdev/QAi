---
title: QA-агент — MVP-план (Фазы 0–3, SaaS-раскладка)
date: 2026-07-05
status: draft
area: tools/mvp
see-also: [mini-plat.md (архитектура + DTO), STACK.md (стек Фаз 0–3)]
---

# QA-агент — MVP-план

> Инстанциация `/mvp` поверх [архитектуры](mini-plat.md) и [стека](STACK.md).
> Отступление от стека: раскладываю как **SaaS** — приватные либы (`asyncbus`/`evented`/`cx`)
> живут за REST-границей в закрытом ядре; в опенсорс потом уходит только тонкая обёртка-клиент.

## ONE question (зачем MVP существует)

> **MVP доказывает, что** автономный агент, получив `URL + репозиторий`, **сам находит баг в
> форме** (5xx / console-error на фаззинге) **и показывает строку в коде, где он живёт** —
> без ручных тестов и без ИИ/платных API.

Прошёл проверку = на демо-таргете хотя бы один `overflow/malicious`-ввод роняет форму, и отчёт
указывает `file:line` хендлера. Не прошёл = корреляция мимо или фаззер ничего не ловит.

## Core-loop (один вертикальный срез, без «и»)

`URL → модель страницы (поля+типы) → матрица вводов по одной форме → снятие эффектов
(сеть+консоль+навигация) → оракул (5xx/console-error) → корреляция запроса в file:line → отчёт`.

Одна форма, один фреймворк-таргет (FastAPI), без обхода графа. Рекурсию не описываю — это Фаза 4.

## SaaS-реформулинг — граница public / private (кладём с дня 1)

Ценность (моат) — оркестрация на приватных либах + корреляция `cx` + хостинг краула. Значит
режем репозиторий по **REST-API**, а не по слоям:

```
PROPRIETARY (SaaS-ядро — закрытое, тут приватные либы)
  api/         FastAPI-гейт:  POST /runs {url, repo_ref} → run_id ; GET /runs/{id} → Finding[]
  engine/      Фазы 0–3:  capture · modeler · fuzzer · analyzer · correlator · report
  backbone/    asyncbus/evented (PRIVATE) — подключается на Фазе 4 (async-подписчики), не в MVP
  cx-корреляция (PRIVATE tool)

OPEN-SOURCE (позже — тонкая обёртка, НОЛЬ приватных зависимостей, MIT)
  qai-client/  REST-клиент + CLI `qai <url> --repo .` → poll → печатает отчёт
  ci/          GitHub Action-обёртка над CLI (regression-gate)
```

**Инвариант границы:** обёртка общается с ядром **только по REST** и не импортирует ничего из
`engine/`/`backbone/`. Приватные либы физически не пересекают границу — ретрофит-цена = 0.

**В MVP строим `engine/` как библиотеку + локальный CLI-раннер.** `api/` — тонкий фасад над тем
же движком (та же `Finding[]`), добавляется, когда нужен хостинг. Движок про API не знает.

## Контракты (заморожены — полные defs в [mini-plat.md §Контракты](mini-plat.md))

`EffectBundle` · `CapturedRequest` · `FieldModel` · `FuzzCase` · `Finding` — Pydantic v2, frozen.
Это единственный словарь между слоями и (позже) через REST-границу. DTO — не сырой dict.

## CUT-лист (осознанно вырезано)

- `[CUT#1]` Обход графа состояний / рекурсия / реплей SPA — Фаза 4, отдельный заход.
- `[CUT#2]` `asyncbus`/`evented` шина — в MVP прямой пайплайн; бус на Фазе 4 (async-подписчики).
- `[CUT#3]` destructive-button guard, staging-only гейты — нужны только с автономным кликером (Ф4).
- `[CUT#4]` Stagehand / Node-рантайм — a11y-snapshot self-contained закрывает инвентарь полей.
- `[CUT#5]` Экстракторы роутов не-FastAPI (Express/Next/Flask) — при 2-м таргет-фреймворке.
- `[CUT#6]` REST-`api/` + опенсорс-обёртка + Docker/деплой — граница спроектирована, слой позже.
- `[CUT#7]` Postgres / SQLite-история — MVP пишет JSON на диск; БД при regression-diff.
- `[CUT#8]` CDP `initiator.stack` как основной сигнал (⚠️ UNVERIFIED на минифае) — бэкенд-корреляция надёжнее.

## Reuse-лестница

1. **Своё готовое (позже):** `asyncbus`/`evented` — за границей, Фаза 4; `cx` — Фаза 3 (поставить codeanalyzer).
2. **Скиллы-обёртки:** `/tg-bot`, `/deploy` — только когда появятся бот/веб-дашборд (CUT#6).
3. **Внешние зрелые:** Playwright, ast-grep, rich, pydantic, structlog — все прошли бой, adopt.
4. **С нуля (ядро-дельта, объём мал):** `CaptureSession`, `PageModeler`, `DataGenerator`+стратегии,
   `Analyzer`, `CodeCorrelator`, `Reporter`.

## Пол качества / потолок абстракции

- **Пол:** типы везде + Pydantic-DTO на границах; типизированные ошибки (`CaptureError`,
  `RouteResolveError`) с аргументами, не глушим; **таймаут+1 retry** на CDP/навигации;
  **валидация входа** (URL, repo-путь) на границе; structlog с `run_id` сквозь весь краул +
  каждая ветка ошибки; `datetime` UTC на таймстемпах эффектов. Only-staging — предупреждением в CLI.
- **Шов (registry, обязателен — это load-bearing тут):** `FieldFuzzStrategy(ABC)` per тип поля,
  open-closed; `Analyzer`/`Correlator`/`Reporter` — независимые потребители одного `EffectBundle`
  (прямой вызов в MVP, готовы стать подписчиками шины на Ф4 без переписывания data-flow).
- **Потолок:** без шины/outbox/FSM (read-only тула, мутаций нет); без Protocol-зоопарка; без
  преждевременной экстракции; корреляция — только FastAPI.

## Витрина = ОТЧЁТ (сюда весь бюджет полировки)

`rich`-таблица findings в терминале + самодостаточный **HTML** (инлайн CSS, тёмная тема ≈`#0a0a0b`,
один акцент, кликабельные `file:line`) по [[design-quality]]. JSON — машинный выход для CI.
Полируем именно отчёт — по нему принимают «зашло/нет», не по чистоте движка.

## Порядок сборки (walking skeleton — каждый шаг = бегущий срез)

0. `contracts/` (DTO) + `CaptureSession` (Playwright+CDP) → на любой URL печатает `EffectBundle` JSON. **[Ф0]**
1. `PageModeler` (a11y-snapshot) → `FieldModel[]` + типы + группы (DOM/label/aria). **[Ф1]**
2. `DataGenerator` + 4–5 стратегий → фаззинг одной формы → `Analyzer` (5xx/console-error оракул). **[Ф2]**
3. `CodeCorrelator` (ast-grep FastAPI-роуты → `cx query` хендлер) → `source_location` в `Finding`. **[Ф3]**
4. `Reporter` (rich + HTML) — **вылизать**. structlog `run_id` сквозь всё. `(mvp)`-маркеры на срезах.

Плюс `demo_target/` — крошечное FastAPI-приложение с 1–2 формами (одна заведомо падает на overflow)
как self-contained фикстура: без него MVP нечего фаззить и нечем доказать ONE question.

## Тест / гейт готовности

`pytest`: мок-страница с формой + мок-бэкенд с 500 → фаззер ловит, коррелятор указывает file:line.
Гигиена-хвост: `ruff` + `mypy --strict` → `/review` → `/cleanup` → `/review`.
Гейт: core-loop сквозной на `demo_target`, отчёт вылизан, пол на месте, граница public/private
не протекает (обёртка не импортит `engine/`), CUT-лист осознан.

## Оценка

~850 LOC, ~4–5 дней. Ступень планирования: lite (300–2k). Среда: нужен `git init` + `uv` + приватный
`codeanalyzer` (для Ф3). `cx` сейчас не в PATH — поставить перед Фазой 3, не блокирует Ф0–2.
