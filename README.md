# Построение метаграфового представления научных документов с содержанием формул

Веб-приложение для извлечения формул, текста, переменных и связей из научных PDF/arXiv-документов. Backend построен на FastAPI, обработка документов сохраняет JSON-артефакты и графовые представления, frontend отдается тем же приложением.

## Возможности

- загрузка PDF или arXiv ID;
- извлечение текста, формул, переменных и контекстов;
- визуализация метаграфа, графов формул и связей переменных;
- пакетная обработка документов;
- создание корпуса из нескольких результатов и скачивание ZIP-архива корпуса;
- экспорт JSON-артефактов.

## Быстрый запуск через Docker

Требуются Docker и Docker Compose.

CPU-вариант используется по умолчанию:

```bash
docker compose up --build
```

CUDA 11.8-вариант для NVIDIA GPU запускается через compose override:

```bash
docker compose -f docker-compose.yml -f docker-compose.cuda.yml up --build
```

Для CUDA нужны установленный NVIDIA driver, NVIDIA Container Toolkit и доступ Docker к GPU.

После запуска откройте:

```text
http://localhost:8000
```

Runtime-данные лежат в `./data` и монтируются в контейнер как `/app/data`. В репозиторий они не попадают.

Первый запуск OCR может занять заметное время: PaddleOCR скачивает модели в `data/models`.

## Флаги Docker-сборки

`Dockerfile` поддерживает два варианта Paddle через build arg `PADDLE_VARIANT`:

- `cpu` - ставит зависимости из `requirements.txt` и `paddlepaddle`;
- `cu118`, `cuda` или `gpu` - ставит зависимости из `requirements-gpu-cu118.txt` и `paddlepaddle-gpu` для CUDA 11.8.

Основные build args:

```text
PADDLE_VARIANT=cpu|cu118|cuda|gpu
FG_DEVICE=cpu|gpu
RUNTIME_IMAGE=python:3.11-slim
INSTALL_SYSTEM_PYTHON=false|true
```

Прямые команды сборки:

```bash
docker build -t formula-graph:cpu --build-arg PADDLE_VARIANT=cpu --build-arg FG_DEVICE=cpu .
docker build -t formula-graph:cu118 --build-arg RUNTIME_IMAGE=nvidia/cuda:11.8.0-cudnn8-runtime-ubuntu22.04 --build-arg INSTALL_SYSTEM_PYTHON=true --build-arg PADDLE_VARIANT=cuda --build-arg FG_DEVICE=gpu .
```

## Переменные окружения

Основные настройки можно задать в `.env` или в `docker-compose.yml`.

```text
PADDLE_VARIANT=cpu
RUNTIME_IMAGE=python:3.11-slim
INSTALL_SYSTEM_PYTHON=false
FG_DATA_DIR=/app/data
FG_DEVICE=cpu
FG_ENABLE_PADDLE=true
FG_RENDER_DPI=300
FG_MAX_PAGES=0
FG_OCR_LANG=auto
FG_STORAGE_RETENTION_DAYS=14
FG_STORAGE_MAX_DOCUMENTS=30
```

`FG_DEVICE=cpu` выбран как безопасный Docker-дефолт. Для GPU используйте `docker-compose.cuda.yml` или выставьте build args вручную.

## Локальная разработка

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm install
npm run build
.\.venv\Scripts\python.exe -m uvicorn backend.app.main:app --host 127.0.0.1 --port 8000
```

Откройте `http://127.0.0.1:8000`.

Для разработки статического frontend отдельно можно поднять:

```powershell
py -3.11 -m http.server 5173 -d frontend
```

В этом режиме frontend автоматически обращается к API на `http://127.0.0.1:8000`.

## Тесты

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest
node --check frontend\assets\app.js
```

## Структура

```text
backend/          FastAPI API, pipeline, graph/export logic
frontend/         статический интерфейс и ReactFlow-визуализация
scripts/          локальные helper-скрипты
tests/            pytest-тесты
data/             runtime-данные, модели, результаты и кеши
Dockerfile        production image with CPU/CUDA build args
docker-compose.yml локальный запуск контейнера
docker-compose.cuda.yml override для NVIDIA GPU
```

В `.gitignore` уже исключены:

- `.venv/`, `node_modules/`, `__pycache__/`, `.pytest_cache/`;
- `data/input`, `data/processed`, `data/results`, `data/models`, `data/sources`;
- `reference/`, локальные логи, скриншоты проверок, временные каталоги и `output/`.
