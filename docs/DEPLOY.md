# DeepDive deployment walkthrough (Fly.io + Cloudflare Access)

Takes ~30 min end-to-end. You'll need to do the account actions; everything else is already scaffolded in the repo.

## What you end up with

- DeepDive running 24/7 on Fly.io at `deepdive.yourdomain.com`
- Testers click the link, enter their email, get a 6-digit code, use the app. No installs, no keys, no accounts.
- Your API keys live in Fly's secret vault, never in git.
- ~$5–6/mo ongoing (1 GB VM, always-on) or ~$1–2/mo (scale-to-zero, cold start on first request).

## Prereqs

- A domain you already own (any registrar).
- ~$5/mo in your wallet.
- An hour of time.

## Part 1 — GitHub private repo (5 min)

1. Go to [github.com/new](https://github.com/new). Name it `deepdive`. **Set visibility: Private.** Skip README/license (we have them).
2. Follow the "push an existing repo" instructions GitHub shows you. Roughly:
   ```bash
   cd C:\DeepDive
   git add .
   git commit -m "Initial commit"
   git remote add origin git@github.com:<you>/deepdive.git
   git push -u origin main
   ```

## Part 2 — Fly.io account + app (10 min)

1. Install the Fly CLI: [fly.io/docs/getting-started/installing-flyctl](https://fly.io/docs/getting-started/installing-flyctl). On Windows:
   ```powershell
   iwr https://fly.io/install.ps1 -useb | iex
   ```
2. Sign up and log in:
   ```bash
   fly auth signup    # or `fly auth login` if you already have an account
   ```
3. Add billing info at [fly.io/dashboard/personal/billing](https://fly.io/dashboard/personal/billing). Minimum spend for this setup is ~$2/mo; budget $5–6/mo.
4. From the repo root:
   ```bash
   fly launch --no-deploy
   ```
   - Accept the existing `fly.toml` when prompted
   - Let it pick a unique app name (or set your own — edit `fly.toml`'s `app` line if you want a custom one)
   - It'll create the app but not deploy yet
5. Set secrets (replace with your real keys):
   ```bash
   fly secrets set ANTHROPIC_API_KEY=sk-ant-... \
                   GOOGLE_AI_API_KEY=your-google-key \
                   TWITTER_BEARER_TOKEN=your-twitter-token
   ```
   Keys are encrypted at rest on Fly. Leaving optional ones blank is fine — the tiers that need them just disable.
6. Deploy:
   ```bash
   fly deploy
   ```
   First deploy takes ~3–5 min (builds Docker image, pushes, starts). You'll get a temporary URL like `deepdive-nate.fly.dev`. Hit that URL — you should see the DeepDive landing page.

## Part 3 — Custom domain (5 min)

1. In your DNS provider (wherever your domain lives — Namecheap, Cloudflare, GoDaddy, etc.), add a **CNAME record**:
   - Name/Host: `deepdive` (or whatever subdomain you want)
   - Target: your Fly app's hostname (e.g., `deepdive-nate.fly.dev`)
   - TTL: Auto / 300
2. Tell Fly to issue an SSL cert:
   ```bash
   fly certs add deepdive.yourdomain.com
   fly certs show deepdive.yourdomain.com    # wait for "Status: Ready"
   ```
   DNS propagation + cert issuance takes 1–10 minutes. The `certs show` command will tell you exactly what's pending.

## Part 4 — Cloudflare Access (email OTP, 10 min)

This is what gives your non-technical testers the "just type your email, get a code" experience.

**A. Move DNS to Cloudflare** (skip if your domain is already on Cloudflare)

1. Sign up at [dash.cloudflare.com/sign-up](https://dash.cloudflare.com/sign-up).
2. Click "Add a site" → enter your domain → pick the **Free** plan.
3. Cloudflare scans your existing DNS; accept the import.
4. Cloudflare gives you two nameservers (e.g., `ana.ns.cloudflare.com` + `bob.ns.cloudflare.com`). Go to your registrar and replace your nameservers with those. Takes up to 24 hours to propagate but usually 30 min.
5. Wait for Cloudflare's dashboard to say "Active."

**B. Enable Zero Trust (free up to 50 users)**

1. In the Cloudflare dashboard, click "Zero Trust" in the left sidebar.
2. Pick a team name (any). Select the **Free** plan when prompted.

**C. Create an Access application**

1. Zero Trust dashboard → Access → Applications → **Add an application** → Self-hosted.
2. Application name: `DeepDive`.
3. Application domain: `deepdive.yourdomain.com`.
4. Leave identity providers at the default (One-time PIN) — this is the email OTP.
5. Click Next.

**D. Create a policy**

1. Policy name: `testers`.
2. Action: **Allow**.
3. Include rule: **Emails** → add each tester's email address, comma-separated (or **Emails ending in** if you want to allow everyone from, say, `@yourcompany.com`).
4. Save.

**E. Test it**

From a browser where you aren't logged in anywhere, hit `https://deepdive.yourdomain.com`. You should see a Cloudflare email prompt. Enter your email, check your inbox for the 6-digit code, paste it. You land on DeepDive.

## Part 5 — Share with testers

Text them:

> Hey, beta-testing a research tool I built. Click https://deepdive.yourdomain.com — enter your email, it'll email you a 6-digit code, that's your login. Let me know what breaks.

## Part 6 — Operating it

```bash
fly logs                       # tail app logs
fly status                     # app health
fly scale memory 2048          # bump to 2GB if 1GB is tight
fly deploy                     # ship an update after git push
fly secrets set KEY=value      # rotate or add a key
fly dashboard                  # opens the Fly web UI
```

## Cost visibility

- Fly: [fly.io/dashboard/personal/billing](https://fly.io/dashboard/personal/billing)
- Anthropic: [console.anthropic.com/settings/usage](https://console.anthropic.com/settings/usage) — set a monthly spending alert here
- Google AI Studio: [aistudio.google.com/usage](https://aistudio.google.com/usage)

## Scale-to-zero vs. always-on

`fly.toml` defaults to `auto_stop_machines = true, min_machines_running = 0` — the VM sleeps when nobody's using it and wakes in ~5–10s on first request. Saves ~60% vs. always-on for low-traffic beta.

If the cold start bothers testers, set `min_machines_running = 1` in `fly.toml` and redeploy. Cost bumps to ~$5.70/mo.

## Removing a tester

Zero Trust → Access → Applications → DeepDive → policy → remove the email → save. Effect is immediate; they'll get a Cloudflare denial on next request.

## If something breaks

- App returns 502: check `fly logs`, usually a Python error or OOM. Bump memory with `fly scale memory 2048`.
- Cert stuck in "Pending": check `fly certs show` — usually a DNS issue. Verify the CNAME points at the right Fly hostname.
- Tester gets "Access denied" despite being on the allowlist: confirm their email in Zero Trust → Access → policy → they have to type the exact email they were added with.
- Rate-limit 429s from Anthropic: check the dashboard's usage graph; may need to drop `MAX_CONCURRENT_AGENTS` via `fly secrets set MAX_CONCURRENT_AGENTS=2`.
