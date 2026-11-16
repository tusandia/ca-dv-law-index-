# California DV Law Index

Which California laws are about domestic violence, or materially affect DV
survivors without saying so? This repository finds them, and publishes a
website that updates itself every morning.

POLISCI 158 final project, Stanford.

| Folder | What it is |
|---|---|
| `dv_index/` | The pipeline: codebook, term list, bill download, flagging, sampling for hand-coding, evaluation, daily updates, news. See `dv_index/README.md`. |
| `web/` | The Next.js website, built from `web/data/`. See `web/README.md`. |
| `.github/workflows/daily-update.yml` | Runs every day at 8 a.m. Pacific: updates the data, commits it, deploys the site. |

## Setup

1. Settings → Pages → Source: **GitHub Actions**.
2. Settings → Actions → General → Workflow permissions: **Read and write**.
3. Actions → "Daily update and deploy" → **Run workflow** once.

The site then lives at `https://<username>.github.io/<repository>/` and
refreshes itself each morning.

## Run it locally

```bash
pip install -r requirements.txt
```

```bash
cd dv_index && python update.py && python news.py
```

```bash
cd web && npm install && npm run dev
```

Data: California Legislature bulk downloads (downloads.leginfo.legislature.ca.gov),
public news feeds, and reference material from WomensLaw.org (NNEDV) and the
sources cited in `dv_index/CODEBOOK.md`.
