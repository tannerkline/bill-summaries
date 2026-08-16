# Model integrations

The application uses `ollama.py` to generate summaries through a locally hosted
Ollama instance. By default it targets `http://ollama:11434` and
`qwen3.6:35b`; configure `OLLAMA_BASE_URL` and `OLLAMA_MODEL` to override
those values.

