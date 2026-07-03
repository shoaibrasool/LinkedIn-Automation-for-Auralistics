FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml setup.py ./
COPY src/ ./src/

RUN pip install --no-cache-dir -e .

EXPOSE 8000

CMD ["uvicorn", "linkedin_agent.api:app", "--host", "0.0.0.0", "--port", "8000"]
