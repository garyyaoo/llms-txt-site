# LLMs.txt Generator

Generate an `llms.txt` file for any website — a structured summary of a site's content designed for LLMs.

## How it works

1. **Discover** — crawls the site via sitemap or BFS nav crawler
2. **Score & group** — groups URLs into named sections by content type
3. **Generate** — produces a clean `llms.txt` using rule-based scoring or Gemini

## Running locally

**Backend**
```bash
cd server
pip install -r requirements.txt
export GEMINI_API_KEY=your_key
python app.py
```

**Frontend**
```bash
cd fe
npm install
npm run dev
```

Open `http://localhost:5173`.

## Deploying

### Docker (local)

```bash
docker build -t llmstxt .
docker run -p 8080:8080 -e GEMINI_API_KEY=your_key llmstxt
```

### Docker via AWS

I deployed using AWS App Runner -- its configured to poll an ECR repo for updates.

**1. Create ECR repository (one time)**
```bash
aws ecr create-repository --repository-name llmstxt --region us-east-1
```

**2. Authenticate Docker to ECR**
```bash
aws ecr get-login-password --region us-east-1 | \
  docker login --username AWS --password-stdin \
  <account-id>.dkr.ecr.us-east-1.amazonaws.com
```

**3. Build for `linux/amd64` and push**
```bash
docker buildx build --platform linux/amd64 \
  -t <account-id>.dkr.ecr.us-east-1.amazonaws.com/llmstxt:latest \
  --push .
```
