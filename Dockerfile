FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN groupadd --gid 10001 app \
    && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

COPY pyproject.toml README.md ./
COPY src ./src
COPY streamlit_app.py ./

RUN python -m pip install --upgrade pip \
    && python -m pip install .

USER app

EXPOSE 8000 8501

CMD ["uvicorn", "network_cost_workbench.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
