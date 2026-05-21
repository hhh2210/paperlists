# Paperlists Tools

Three complementary entry points for working with the paperlists corpus:

| Directory | What it is | When to use |
|---|---|---|
| `app.py` / `extract.py` | Streamlit web UI + CLI (original tools) | You want to manually browse the corpus on your laptop |
| [`query-api/`](query-api/) | Hosted FastAPI service backed by sqlite FTS5 | You're deploying the service (Railway/HF Spaces) or want a local HTTP layer |
| [`mcp-server/`](mcp-server/) | MCP server for Claude Code / Cursor / Codex / Claude Desktop / any MCP host | You want AI agents to query the corpus directly |
| [`skill/`](skill/) | Cross-tool Skill (`.md` + bundled CLI script) | You want zero-install access from any LLM that loads skills |

The MCP server and Skill both default to the hosted API
(`https://api-production-18d3.up.railway.app`), so end users don't need to
download the ~830MB of raw JSON. Set `PAPERLISTS_API_URL` to point at a
self-hosted instance.

# Paper Search Tool (legacy / local Streamlit)

A Streamlit-based tool for efficiently searching and analyzing conference papers locally. 
## Why This Tool?
- Fast local searching and filtering across multiple fields
- Support for directory and multi-conference search
- Status-based filtering to exclude withdrawn/rejected papers
- User-friendly web interface and command-line support
- Results download in JSON format with source tracking

This tool reduces server load, enables offline analysis, and allows for custom processing and cross-conference comparisons.

## Setup

1. Clone the repo and navigate to the `tools` directory
```bash
git clone https://github.com/hhh2210/paperlists.git
cd paperlists/tools
```
2. Install dependencies: `pip install -r requirements.txt`

## Usage

### Web Interface

1. Run `streamlit run app.py`
2. Access the web UI at `http://localhost:8501`
3. Enter search criteria, select search mode, and analyze results

### Command Line

```bash
cd tools
python extract.py [keyword] [-i INPUT_PATH] [-o OUTPUT_FILE] [-f FIELDS...]
```

- `keyword`: Search keyword (required)
- `-i, --input_path`: Input JSON file or directory (default: iclr2025.json)
- `-o, --output_file`: Output JSON file (optional)
- `-f, --fields`: Fields to search (default: keywords title primary_area topic)

Example:
```bash
cd tools
python extract.py retrieval -i iclr/iclr2025.json -o results.json -f title keywords
```
