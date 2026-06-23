# Deploy — Fly.io (São Paulo / GRU)

Backend co-located with Supabase (`sa-east-1`) so DB queries are intra-region.

## 1. Install + login (one-time)
```bash
# macOS
brew install flyctl
fly auth login          # or: fly auth signup (requires a card — Fly has no free tier)
```

## 2. Create the app + deploy
```bash
cd ~/Documents/projetos/gamenglish/flueai-ai-backend

# fly.toml already exists. If the name "flua-backend" is taken globally,
# change `app = "..."` in fly.toml to something unique (e.g. flua-backend-gru).
fly launch --no-deploy --copy-config --name flua-backend --region gru
```
(If `fly launch` asks to tweak settings, keep the fly.toml as-is.)

## 3. Set the SECRETS (values from your local `.env`)
Non-secret config (APP_ENV, CORS_ORIGINS, models) is already in `fly.toml [env]`.
Only the secrets go here:
```bash
fly secrets set \
  SUPABASE_URL="https://vvmdqjmuvonbraqbnpja.supabase.co" \
  SUPABASE_JWT_SECRET="..." \
  SUPABASE_SERVICE_KEY="..." \
  ANTHROPIC_API_KEY="..." \
  OPENAI_API_KEY="..." \
  REPLICATE_API_KEY="..." \
  ELEVENLABS_API_KEY="..." \
  GOOGLE_TTS_API_KEY="..." \
  DEEPGRAM_API_KEY="..." \
  STRIPE_SECRET_KEY="..." \
  STRIPE_WEBHOOK_SECRET="..." \
  STRIPE_PRICE_STARTER_MONTHLY="..." \
  STRIPE_PRICE_STARTER_YEARLY="..." \
  STRIPE_PRICE_PRO_MONTHLY="..." \
  STRIPE_PRICE_PRO_YEARLY="..."
```

## 4. Deploy
```bash
fly deploy
```
URL will be `https://flua-backend.fly.dev` (or your chosen name). Test:
```bash
curl https://flua-backend.fly.dev/health   # -> {"status":"ok"}
```

## 5. Point the frontend + Stripe at the new URL
- Vercel → project `flueai` → Env vars → set `NUXT_PUBLIC_API_BASE` to the fly.dev URL → Redeploy.
- Stripe webhook → `https://<app>.fly.dev/api/billing/webhook`.

## Notes
- `min_machines_running = 1` keeps one machine warm → no cold start.
- `shared-cpu-1x` / 512MB ≈ a few USD/month, co-located with Supabase = fast.
- The old Render service (`flua-backend.onrender.com`) can be suspended/deleted once Fly is verified.
