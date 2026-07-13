# Paper Daily

Paper Daily fetches recent arXiv papers, uses Codex to rank them against personal research interests, and publishes the results as a static GitHub Pages site.

## Run Locally

```bash
cd submodule/PaperDaily
python scripts/update.py                 # Uses the authenticated Codex CLI
python -m http.server 8000 -d site       # Open http://localhost:8000
```

Use the deterministic keyword fallback when Codex is unavailable or when debugging the site:

```bash
python scripts/update.py --no-codex
```

Research interests, arXiv categories, ranking thresholds, and the daily selection limit are configured in `config.json`. Historical results are stored in `site/data/papers.json`; the same arXiv ID is never added twice.

## Deploy to GitHub Pages

1. Push this directory as an independent GitHub repository. The workflow paths are relative to the repository root.
2. Add `OPENAI_API_KEY` under `Settings → Secrets and variables → Actions`.
3. Select **GitHub Actions** under `Settings → Pages → Build and deployment`.
4. Run `Daily paper radar` manually once. It will then update automatically at 08:30 China Standard Time on weekdays.

Optionally add the Actions variable `CODEX_MODEL` to select a model; otherwise, the Codex default is used. If a Codex call fails, the workflow records the reason and falls back to deterministic keyword scoring, so the site can still be updated.

> arXiv API requests use an explicit User-Agent and a one-second delay between categories. Every entry retains its arXiv ID and original paper link.
