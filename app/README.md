# Research & explainability dashboard

A **read-only** Streamlit app that makes the equity-alpha system's behavior, performance, and
honesty understandable — including to a non-technical viewer. It is **not** an execution or advice
tool: no buy buttons, no broker, no orders, no personalized advice. Every page carries a standing
honesty banner and the data-status caveat.

## Run

```bash
# from the repo root, with the project venv active
pip install -r requirements.txt          # includes streamlit
streamlit run app/main.py
```

The app reads only from `data_cache/` artifacts (full-500 results) and the repo's markdown docs.
It performs **no recomputation and no live API calls** — generate/refresh the artifacts first with:

```bash
python scripts/phase1_build_panel.py     # labeled panel (no cap = full universe)
python scripts/phase2_baselines.py       # baseline results + reports/phase2_baselines.md
```

## Pages
1. **Overview** (`main.py`) — what this is / isn't, project status, honest headline.
2. **Universe explorer** — names/date, sector coverage, and the survivorship drift shown as a
   *measured bias*.
3. **Performance / baselines** — equity curves, gross-vs-net metrics, momentum IC + decile spread,
   and the "real signal vs flashy artifact" read.
4. **Model rankings** — *stub* placeholder for Phase 4/5 (includes the data contract for trivial
   later wiring). No model exists yet.
5. **Methodology & rigor** — surfaces `LEAKAGE_AUDIT.md`, `DECISIONS.md`, `EXPERIMENTS.md` in-app.

## Artifacts each page reads
| Page | Reads |
|---|---|
| Overview | `results/meta.json`, `results/momentum_ic.json`, `EXPERIMENTS.md` |
| Universe explorer | `panel/panel_*.parquet` (newest), `results/baseline_returns.parquet`, `results/baseline_perf.json` |
| Performance | `results/{baseline_returns.parquet, baseline_perf.json, momentum_ic.json, momentum_ic_series.parquet, momentum_quantiles.json, meta.json}` |
| Model rankings | — (stub) |
| Methodology | `LEAKAGE_AUDIT.md`, `DECISIONS.md`, `EXPERIMENTS.md` |

Structure is kept modular (`common.py` holds loaders + the honesty layer) so Phase 3/4 can add
pages or sections without a rewrite.
