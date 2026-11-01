# Running Lumen permanently on a website

Lumen is one Python process (FastAPI) that serves the API and the website. It needs a machine that stays on and has enough memory for the embedding model, so a normal "static site" host will not work.

## What it needs

| | Default model (`all-mpnet-base-v2`) | Small model (`all-MiniLM-L6-v2`) |
|---|---|---|
| Model download | about 420 MB | about 80 MB |
| Memory to run | plan for about 2 GB | plan for about 1 GB |
| Search quality | best | a little lower |

These memory figures are estimates (PyTorch plus the model plus the index), not measurements. Check with `docker stats` after deploying and pick the server size from that.

Building the image embeds all ~9,000 movies once, which takes several minutes on a small CPU and can use more memory than running does. If the build runs out of memory on a small server, build the image on your own computer and move it with `docker save` / `docker load`, or add swap space to the server.

## Option A: your own small server (recommended)

A cheap virtual server from any provider (for example Hetzner, DigitalOcean or similar) with 2 GB RAM or more and Ubuntu. Prices change, so check the provider's page; this class of server is usually a few euros to ten euros a month.

1. **Point a domain at the server.** Create a DNS `A` record such as `lumen.yourdomain.com` that points to the server's IP address.
2. **Install Docker** on the server (follow the official guide for Ubuntu).
3. **Get the code and start it:**

   ```bash
   git clone https://github.com/vrhvnsk/lumen.git
   cd lumen/deploy
   cp .env.example .env
   nano .env                      # set DOMAIN=lumen.yourdomain.com
   docker compose up -d --build
   ```

4. Open `https://lumen.yourdomain.com`. The first start may need a minute while Caddy gets the HTTPS certificate.

`restart: unless-stopped` makes both containers start again after a crash or a server reboot, so it keeps running permanently.

**Update later:**

```bash
cd lumen && git pull && cd deploy && docker compose up -d --build
```

**Look at logs:** `docker compose logs -f lumen`

**No domain yet?** Run only the app: `docker build -t lumen . && docker run -d --restart unless-stopped -p 80:7860 lumen`, then open the server's IP address (plain HTTP, no certificate).

## Option B: a container platform (Fly.io, Railway, Render and similar)

They can run the `Dockerfile` in the repository root: point the platform at the GitHub repo and let it build the image. Things to check on the pricing page before choosing:

- **Memory limit.** Free and smallest plans are often 256 to 512 MB, which is too little for this app. You would need a plan with at least 1 to 2 GB, so these are normally paid.
- **Sleeping.** Free web services usually stop after some idle minutes and take a while to wake up. That is not "permanent".
- **Port.** The container listens on the `PORT` environment variable (default 7860). Most platforms set it for you.

## Hugging Face Spaces

Spaces used to be the usual free place for projects like this. At the time of writing, Hugging Face's documentation says that creating a Space that runs code (Docker or Gradio) requires a paid plan, and free hardware goes to sleep after a period of inactivity. Check their current terms before relying on it.

## Before you make it public

- **Abuse and cost.** Every search runs the model on your server's CPU. A public site can be hammered by bots. Putting the domain behind a free Cloudflare account (rate limiting, caching of the static files) is a cheap first step. The API already caps `k` and the input length.
- **TMDB.** The footer already carries the required attribution notice. Read TMDB's terms of use for a public site, and for shipping the dataset in the image.
- **Privacy.** The site makes no requests to font or analytics providers. Poster images are loaded from TMDB's image server, so visitors' browsers contact TMDB. Mention this in a privacy note if you add one.
- **Secrets.** The running app needs none. The TMDB key is only used by `scripts/tmdb_loader.py` on your own machine.

## Lighter alternative for tiny servers

If you need to fit into well under 1 GB, the heavy part is PyTorch. A runtime that uses small ONNX models (for example the `fastembed` library) needs far less memory and no PyTorch. That would be a change to `app/embeddings.py`, not something included here.
