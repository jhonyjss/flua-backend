# FlueAI Backend (FastAPI)

Backend separado do FlueAI — concentra as **integrações de IA** e o **billing**, extraídos do servidor Nitro do app Nuxt (`gamenglish/server/api`). O frontend continua autenticando via Supabase e envia o access token como `Authorization: Bearer` — os paths são idênticos aos do Nuxt para permitir cutover por proxy/env var, sem mudar o cliente.

## Stack

Python 3.12 · FastAPI · httpx · PyJWT (verificação do JWT do Supabase) · Stripe SDK · pytest. Provedores chamados via REST (Anthropic, OpenAI, Google TTS, ElevenLabs, Deepgram) — sem SDKs pesados, fácil de mockar.

## Rodando

```bash
cp .env.example .env        # preencha as chaves
docker compose up --build   # API em http://localhost:8000 (docs em /docs)

# ou local:
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
pytest                      # 40 testes, todos com provedores mockados
```

## Endpoints (paridade com o Nuxt)

| Endpoint | Origem no Nuxt | Status |
|---|---|---|
| `GET /health` | — | ✅ |
| `POST /api/ai/grammar-analysis` | `server/api/ai/grammar-analysis.post.ts` | ✅ |
| `POST /api/ai/conversation-response` | `server/api/ai/conversation-response.post.ts` | ✅ |
| `POST /api/ai/help-answer` | `server/api/ai/help-answer.post.ts` | ✅ |
| `POST /api/ai/learning-recommendations` | `server/api/ai/learning-recommendations.post.ts` | ✅ |
| `POST /api/ai/transcribe` (multipart) | `server/api/ai/transcribe.post.ts` | ✅ Deepgram nova-2 |
| `POST /api/avatar/speak` | `server/api/avatar/speak.post.ts` | ✅ Google/ElevenLabs/OpenAI/Deepgram + chunking |
| `POST /api/realtime/session` | `server/api/realtime/session.post.ts` | ✅ gpt-realtime, client_secrets, semantic_vad, retry |
| `POST /api/stripe/create-checkout-session` | `server/api/stripe/...` | ✅ |
| `POST /api/stripe/create-portal-session` | idem | ✅ |
| `POST /api/stripe/cancel-subscription` | idem | ✅ |
| `GET /api/stripe/get-invoices` | idem | ✅ |
| `POST /api/stripe/webhook` | idem | ⚠️ verifica assinatura + dispatch; **sync das tabelas Supabase ainda no Nuxt** (TODO no código) |
| `GET/PATCH /api/users/me/profile`, `…/dashboard-stats`, `…/streak`, `…/completed-lessons`, `…/sessions`, `…/subscription` | `useAuth`/`useLessonProgress`/`useStreaks`/`useSubscription` | ✅ |
| `…/progress`, `…/unlocked-lessons`, `…/in-progress-lessons`, `…/lessons/{id}/topics`, `…/achievements` (GET) | `useLessonProgress`/`useStreaks` | ✅ |
| `POST …/lessons/{id}/start\|complete\|unlock`, `…/lessons/{id}/topics`, `…/sessions`, `…/xp`, `…/practice`, `…/achievements/{id}` | lógica server-side atômica | ✅ |
| `GET/POST /api/users/me/vocabulary`, `…/vocabulary/summary`, `GET …/grammar-progress` | `useProgress`/`useFlashcards` | ✅ |
| `GET /api/content/speaking-classes\|grammar-bank\|vocabulary-bank` | `useLessons`/banks | ✅ |
| `assist / generate-class / generate-room / generate-image / dynamic-examples / validate-objective / generate-suggestions` | `server/api/ai/*` | 🔜 fase 2 (mesmo padrão de `services/ai_endpoints.py`) |
| `voice/*`, `session/*`, `admin/*`, `blog`, `whatsapp/zapi` | — | 🔜 fases seguintes |

## Arquitetura

```
app/
  core/      config (pydantic-settings) · auth (JWT Supabase HS256) · rate_limit (sliding window) · http (client mockável)
  schemas/   contratos Pydantic espelhando as interfaces TS do Nuxt
  services/  anthropic_client · ai_endpoints (prompts puros/testáveis) · tts · stt · realtime · stripe_service · supabase_admin
  routers/   ai · avatar · realtime · billing · health
tests/       40 testes — auth, rate limit, IA (Anthropic mockado), TTS, realtime, billing/webhook
```

Decisões principais: prompts e parsing são **funções puras** (testáveis sem rede); todo HTTP de saída passa por `core/http.http_client()` (os testes injetam `httpx.MockTransport`); rate limit em memória por usuário (trocar por Redis em multi-réplica); Stripe price IDs só em env vars.

## Migração (cutover sem downtime)

1. Deploy deste serviço (`docker compose up`) com as mesmas chaves do Nuxt.
2. No Nuxt, aponte os `$fetch('/api/ai/...')` para `NUXT_PUBLIC_API_BASE` (este serviço) — paths são idênticos; ou proxie via Nitro `routeRules`.
3. Valide os fluxos de voz/IA em staging; o webhook do Stripe permanece no Nuxt até o sync de tabelas ser portado (item ⚠️ acima).
4. Porte os endpoints fase 2 e por fim aposente o `server/api` do Nuxt.

## Git

Repositório independente — `git init` já executado nesta pasta; adicione o remote:

```bash
git remote add origin git@github.com:SEU_USUARIO/flueai-backend.git
git push -u origin main
```
