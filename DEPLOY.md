# Deploying

Two pieces: the Python engine on Fly.io (it needs ffmpeg and runs for a minute per video) and the
Next.js site on Vercel.

## Live (2026-10-20)

- Site: https://github-wrapped-2026.vercel.app (Vercel project `roastmygithub`; also answers on roastmygithub-two.vercel.app)
- Engine: https://wrapped-2026-engine.fly.dev (Fly app `wrapped-2026-engine`, region yyz, 10 GB volume `roast_data`).
  Fly rejects app names containing "GitHub" (abuse filter), hence the name.
- Secrets on Fly: `LLM_API_KEY`, `GITHUB_TOKEN` (fine-grained, public repositories read-only, no permissions),
  `SESSION_SECRET` (shared with Vercel).
- Secrets on Vercel: `SESSION_SECRET` (same value as Fly), `GITHUB_CLIENT_ID` / `GITHUB_CLIENT_SECRET` from the GitHub
  OAuth app "Wrapped 2026" (callback `https://github-wrapped-2026.vercel.app/api/auth/callback`; GitHub rejects
  app names starting with "GitHub").
- Sign-in: wraps that already exist open for anyone; writing a new one needs Sign in with GitHub, 3 per account
  per UTC day (`ROAST_ROASTS_PER_DAY`), at most 300 a day across the site (`ROAST_DAILY_CAP`, about $12 of LLM).
  Counts live in `/data/out/_quota/<date>.json` on the volume.
  When the GitHub token expires, lookups fail; replace it with
  `fly secrets set GITHUB_TOKEN=<new> --app wrapped-2026-engine` (no site redeploy needed).

## 1. Engine on Fly.io

```bash
fly launch --no-deploy --copy-config          # uses fly.toml; pick the app name and region
fly volumes create roast_data --size 10       # cache, generated art, voices and videos
fly secrets set GITHUB_TOKEN=ghp_... LLM_API_KEY=sk-ant-... LLM_MODEL=claude-sonnet-5-5
fly secrets set ROAST_WEB_ORIGIN=https://<your-site>.vercel.app
fly deploy
curl https://<app>.fly.dev/api/health
```

- `GITHUB_TOKEN` only needs public read access (a fine-grained token with no repository
  permissions is enough); it reads public profiles, not yours.
- The LLM key pays for one script per login, persona and voice style, written once and kept (there is no public refresh): about $0.04 with Sonnet 5.5 (measured 2026-10-20). Haiku 4.5 is about $0.016 but its jokes are flatter and it keeps the stock "that's not X, that's Y" phrasing; Opus 5.5 is about $0.08 and the funniest. Paid Magic Hour art and voice are tied to those lines.
- Magic Hour keys are never configured on the server: visitors supply their own per request.
- `ROAST_RATE_LIMIT` (default 20 requests a minute per IP) and `ROAST_JOB_WORKERS` (default 4)
  are tunable in `[env]`.

## 2. Site on Vercel

```bash
vercel link                                      # from the repo root; the project's Root Directory is `web`
vercel env add NEXT_PUBLIC_API_URL production   # https://<app>.fly.dev
vercel --prod
```

With the project connected to GitHub (`vercel git connect`, after linking your GitHub account to Vercel
under Account Settings → Authentication), every push to `main` deploys the site on its own; the engine
still needs `fly deploy`.

Then put the Vercel URL in `ROAST_WEB_ORIGIN` on Fly (comma-separate several origins) and in
`roast_repo_url` / the share text if the domain differs from `roastmygithub-two.vercel.app` (the live site since 2026-10-20; `roastmygithub.vercel.app` belongs to someone else).

## 3. Checks

- `https://<site>/<login>` plays the wrap; the first load of a new login takes about 20 s.
- `https://<site>/api/og/<login>?persona=senior` is the share card (needs the Fly URL to be
  public: the image renderer refuses private addresses).
- Opt-out requests arrive as issues; merge the login into `OPTOUT.md` and redeploy Fly.
