# scripts

Starting the local demo (see `dev_docs/architecture/demo.md`). Run from Git Bash, each in its own terminal.

| Script | Purpose |
| --- | --- |
| `demo_backend.sh` | Starts the local PostgreSQL (if its `start.sh` sits next to the env file), migrates the demo database to head and runs the API with background workers on port 8000. Settings: `DECENTRA_ENV`, `PYTHON`, `DEMO_KEY`. |
| `demo_frontend.sh` | Runs the Decentra panel on port 3005 (`PORT`), with the same `DEMO_KEY`. |

Optional: `ollama serve` with the configured model, for the AI switch and chat customers.
