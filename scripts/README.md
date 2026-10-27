# scripts

Starting the local demo (see `dev_docs/architecture/demo.md`). Run from Git Bash, each in its own terminal.

| Script | Purpose |
| --- | --- |
| `demo_backend.sh` | Starts the local PostgreSQL (if its `start.sh` sits next to the env file), migrates the demo database to head and runs the API with background workers on port 8000. Settings: `DECENTRA_ENV`, `PYTHON`, `DEMO_KEY`, `RELOAD=1` (restart by itself when a file under `backend/app` changes). |
| `load_run.py` | Runs one scenario (e.g. `LOAD-10`, `LOAD-20`, `LOAD-100`) on the running demo backend through its doors: start, Play until it pauses by itself, finish the run, print the measurements (`--out` saves them as JSON). Python standard library only. |
| `demo_all.sh` | Everything in one terminal: starts the local PostgreSQL, the backend in the background (output in `~/decentra-backend.log`) and the frontend on port 3005; Ctrl+C stops the frontend and the backend (the database keeps running). |
| `demo_frontend.sh` | Runs the Decentra panel on port 3005 (`PORT`), with the same `DEMO_KEY`. |

Optional: `ollama serve` with the configured model, for the AI switch and chat customers.
