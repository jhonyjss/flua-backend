# FlueAI Backend (FastAPI)

Backend separado do FlueAI — concentra **todas as integrações de IA** e o **billing**, extraídos do servidor Nitro do app Nuxt. O frontend autentica via Supabase e envia o access token como `Authorization: Bearer`; os paths `/api/ai/*`, `/api/voice/*`, `/api/avatar/*` e `/api/realtime/*` são idênticos ao contrato antigo do Nuxt.

## Stack

Python 3.12 · FastAPI · httpx · PyJWT · Stripe SDK · pytest. Provedores via REST (Anthropic, OpenAI, Replicate, Google TTS, ElevenLabs, Deepgram).

## Rodando

```bash
cp .env.example .env
docker compose up --build   # http://localhost:8000 (docs em /docs)

# ou local:
pip install -r requirements-dev.txt
uvicorn app.main:app --reload --port 8000
pytest
```

No Nuxt, `NUXT_PUBLIC_API_BASE=http://localhost:8000` (default em `nuxt.config.ts`). Os services em `app/services/aiService.ts`, `avatarService.ts`, `voiceService.ts` e `realtimeService.ts` chamam este backend via `apiFetch`.

## Endpoints — paridade 100% com o Nuxt (rotas Nitro removidas)

| Endpoint | Status |
|---|---|
| `GET /health` | ✅ |
| **AI** | |
| `POST /api/ai/grammar-analysis` | ✅ |
| `POST /api/ai/conversation-response` | ✅ (cenários, lessonContext, teacherMode) |
| `POST /api/ai/help-answer` | ✅ |
| `POST /api/ai/learning-recommendations` | ✅ |
| `POST /api/ai/validate-objective` | ✅ |
| `POST /api/ai/generate-suggestions` | ✅ |
| `POST /api/ai/dynamic-examples` | ✅ |
| `POST /api/ai/assist` | ✅ |
| `POST /api/ai/generate-class` | ✅ |
| `POST /api/ai/generate-room` | ✅ |
| `POST /api/ai/generate-image` | ✅ (Replicate + Supabase Storage) |
| `POST /api/ai/transcribe` | ✅ JSON base64 PCM + multipart |
| `POST /api/ai/speech-correct` | ✅ pipeline ASR |
| **Voice** | |
| `POST /api/voice/chat` | ✅ OpenAI Responses + tutor prompt |
| `GET/POST /api/voice/usage` | ✅ Supabase `voice_usage` |
| **Avatar** | |
| `POST /api/avatar/speak` | ✅ |
| `POST /api/avatar/tts-whisper` | ✅ TTS + Whisper timestamps |
| `GET /api/avatar/model` | ✅ proxy GLB Ready Player Me |
| **Realtime** | |
| `POST /api/realtime/session` | ✅ |
| **Billing / users / content** | ✅ (inalterados) |

## Arquitetura

```
app/
  core/       config · auth · rate_limit · http
  schemas/    ai · voice · avatar · speech · …
  services/
    ai/       conversation · grammar · validate_objective · … (prompts modulares)
    voice/    chat · usage
    avatar/   tts_whisper · model_proxy
    openai_client · replicate_client · anthropic_client · stt · tts · realtime
  routers/    ai · voice · avatar · realtime · billing · health · …
tests/        pytest com MockTransport — sem chamadas de rede reais
```

Prompts do tutor: fonte única em `app/services/tutor_instructions.py` (usado por `/api/realtime/session` e `/api/voice/chat`).

## Git

Repositório independente em `flueai-ai-backend/`; pode ser versionado à parte do monorepo Nuxt.
