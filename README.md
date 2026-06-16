# URL Shortener

A minimal URL shortener built with FastAPI.

## Setup

```bash
python -m venv .venv
.venv\Scripts\activate      # Windows
# source .venv/bin/activate  # macOS/Linux

pip install -r requirements.txt
```

## Run

```bash
uvicorn src.main:app --reload
```

## Usage

**Shorten a URL**
```bash
curl -X POST http://localhost:8000/shorten \
  -H "Content-Type: application/json" \
  -d '{"url": "https://example.com"}'
```

**Follow a short link**
```
GET http://localhost:8000/<code>
```

Interactive docs available at `http://localhost:8000/docs`.
