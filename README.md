# Python R-Server MCP

A secure, Docker-based Model Context Protocol (MCP) server for R data visualization and analysis, built with Python and FastMCP.

**What is this?** This tool allows you to perform statistical analysis in R through natural language conversations with LLM models like Claude. All R code is executed in secure Docker containers, ensuring complete isolation and security.

**Key Benefits:**
- 🗣️ **Natural Language Interface**: Chat with AI to perform complex statistical analyses
- 🐳 **Secure Docker Execution**: All R code runs in isolated containers with network disabled
- 📊 **Automatic R Execution**: AI runs R code and returns results without you writing code
- 📁 **Multiple Directory Mounting**: Mount multiple local directories for R to access
- 📈 **Inline Plot Capture**: Plots automatically returned as base64 PNG images
- 🔒 **PII Protection**: Optional auto-redaction of personal data before it reaches the LLM
- 💾 **Session Persistence**: R variables persist between calls
- ⚡ **Smart Caching**: Configurable result caching for instant repeated operations
- 📦 **Auto Library Detection**: Missing R packages automatically installed

*🌐 [Türkçe](README_TR.md) | **English***

## Overview

This project is inspired by [gdbelvin's rlang-mcp-server](https://github.com/gdbelvin/rlang-mcp-server) but is a complete Python reimplementation using the FastMCP framework. While the original Go version provided basic R visualization tools, this Python version extends the functionality with comprehensive security, file management, and data privacy features.

## Features

### 🎨 **Visualization & Analysis**
- **ggplot2 Rendering**: Execute R code with ggplot2 commands and return publication-ready visualizations
- **Inline Plot Capture**: Plots automatically detected and returned as base64 PNG
- **R Script Execution**: Run any R script with smart file handling and return formatted output
- **Session Persistence**: R variables and workspace persist between calls via `.RData`

### 📁 **File Management**
- **Multiple Directory Mounting**: Mount multiple local directories with custom mount points
- **Smart File Discovery**: Use R scripts to explore and analyze files in mounted directories
- **Unmount Support**: Cleanly unmount directories when done

### 📦 **Package Management**
- **Auto Library Detection**: `library()` and `require()` calls parsed, missing packages auto-installed
- **Package Installation**: Install R packages on-demand with version control
- **Automatic Dependencies**: Smart package dependency resolution
- **Temporary Network**: Network temporarily enabled only during package installation

### 🛡️ **Security & Isolation**
- **Mandatory Docker**: All R code execution in isolated containers
- **Network Disabled by Default**: Container cannot access internet during R execution
- **Resource Limits**: Configurable memory (default 2GB) and CPU limits
- **PII Redaction**: Optional automatic detection and masking of personal data in R output
- **Temporary Network Only**: Network enabled only for package installs, then disabled
- **Container Isolation**: Complete process and filesystem isolation
- **Enhanced Error Messages**: R errors include traceback and call context

### 🔒 **PII Protection** (Optional)
- **Regex Detection**: TC Kimlik No, phone numbers, email, IBAN, credit cards, patient IDs
- **NER Name Detection**: Person names detected via multilingual spaCy model
- **Medical Whitelist**: Statistical and medical terms excluded from false positives
- **Fallback Support**: Works with or without Presidio installed (regex fallback)
- **Zero Data Leakage**: PII redacted before output reaches the LLM API

### 🚀 **Performance & Experience**
- **FastMCP Framework**: Modern Python MCP implementation (v3.1.1+)
- **Smart Caching**: Configurable in-memory caching (size + TTL via environment variables)
- **Persistent Containers**: Reuses same container for all operations (no startup overhead)
- **Container Warm-up**: Common R packages pre-loaded at container start
- **Pre-compiled Packages**: Uses Docker images with pre-installed R packages

## Quick Start

### Prerequisites

- **Docker** (mandatory - must be running)
- **Python 3.12+**
- **uv** (recommended) or pip

#### macOS

```bash
brew install uv
brew install python@3.12
brew install --cask docker
```

#### Windows

```powershell
pip install uv
# Install Python 3.12+ from https://www.python.org/downloads/windows/
# Install Docker Desktop from https://www.docker.com/products/docker-desktop
```

#### Linux (Ubuntu/Debian)

```bash
sudo apt update
sudo apt install python3.12 python3.12-venv python3-pip docker.io
pip install uv
sudo systemctl start docker && sudo systemctl enable docker
```

**Note**: Local R installation is not required - all R execution happens inside Docker containers.

### Installation

```bash
# Method 1: Install directly from GitHub (recommended)
uvx --from git+https://github.com/saidsurucu/rlang-mcp-python rlang-mcp-python

# Method 2: Clone and install locally
git clone https://github.com/saidsurucu/rlang-mcp-python.git
cd rlang-mcp-python
uv sync

# Method 3: Install with pip
pip install git+https://github.com/saidsurucu/rlang-mcp-python

# Optional: Install PII protection
pip install 'rlang-mcp-server[privacy]'
uv pip install https://github.com/explosion/spacy-models/releases/download/xx_ent_wiki_sm-3.8.0/xx_ent_wiki_sm-3.8.0-py3-none-any.whl
```

## Claude Desktop Integration

1. Open Claude Desktop
2. Go to **Settings** > **Developer** > **Edit Config**
3. Add this configuration:

```json
{
  "mcpServers": {
    "r-server-python": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/saidsurucu/rlang-mcp-python",
        "rlang-mcp-python"
      ]
    }
  }
}
```

### With Environment Variables (Recommended for Sensitive Data)

```json
{
  "mcpServers": {
    "r-server-python": {
      "command": "uvx",
      "args": [
        "--from",
        "git+https://github.com/saidsurucu/rlang-mcp-python",
        "rlang-mcp-python"
      ],
      "env": {
        "R_MCP_PII_ENABLED": "true",
        "R_MCP_NETWORK_DISABLED": "true",
        "R_MCP_MEM_LIMIT": "4g"
      }
    }
  }
}
```

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `R_MCP_MEM_LIMIT` | `2g` | Container memory limit |
| `R_MCP_CPU_QUOTA` | `200000` | CPU quota (100000 = 1 CPU) |
| `R_MCP_CACHE_TTL` | `3600` | Cache time-to-live in seconds |
| `R_MCP_CACHE_SIZE` | `100` | Maximum cached results |
| `R_MCP_SESSION` | `true` | Persist R variables between calls |
| `R_MCP_NETWORK_DISABLED` | `true` | Container network isolation |
| `R_MCP_PII_ENABLED` | `false` | PII redaction on R output |

## Tools Available

This server provides **7 tools**:

| Tool | Description | Category |
|------|-------------|----------|
| `mount_directory` | Mount local directories (supports multiple, custom mount points) | Directory |
| `unmount_directory` | Unmount directories (single or all) | Directory |
| `execute_r_script` | Run R code with plot capture, auto library detection, session persistence, PII redaction | Execution |
| `container_status` | Check health, resources, R version, session, cache stats | Monitoring |
| `initialize_r_container` | Start container with resource limits and warm-up | Container |
| `install_r_package` | Install packages on-demand (temp network enable) | Packages |
| `clear_session` | Clear R workspace (remove persisted variables) | Session |

## PII Protection

When working with sensitive data (healthcare, financial, personal), enable PII protection to automatically redact personally identifiable information from R output before it reaches the LLM.

### How It Works

```
R code runs in Docker (local, network disabled)
    ↓
R output (stdout)
    ↓ R_MCP_PII_ENABLED=true
[Presidio Regex] → TC, phone, email, IBAN, credit card, patient ID
[spaCy NER]      → Person names (Ali Yılmaz, Mehmet Öz...)
[Whitelist]      → Filter false positives (medical/statistical terms)
    ↓
Sanitized output → LLM API (no PII leaves your machine)
```

### What Gets Redacted

| PII Type | Example | Redacted As |
|----------|---------|-------------|
| TC Kimlik No | `12345678901` | `<TR_TC_KIMLIK>` |
| Phone | `0532 456 7890` | `<TR_PHONE>` |
| Email | `ali@mail.com` | `<EMAIL>` |
| IBAN | `TR33000610...` | `<TR_IBAN>` |
| Credit Card | `4532-1234-5678-9012` | `<CREDIT_CARD>` |
| Patient ID | `Hasta No: 2024-15832` | `<TR_HASTA_NO>` |
| Person Name | `Ali Yılmaz` | `<PERSON>` |

### What Passes Through (No False Positives)

- `mean=45.2, sd=12.3, n=150` — aggregate statistics
- `table(data$diagnosis)` — frequency tables
- `HbA1c`, `Tip 2 Diyabet` — medical terms
- `Min. 1st Qu. Median Mean` — R output

### Fallback Behavior

| Installed | Detection |
|-----------|-----------|
| `presidio` + `xx_ent_wiki_sm` | Full: regex + name detection |
| `presidio` only | Regex: TC, phone, email, IBAN, credit card |
| Neither | Pure regex fallback (no extra dependencies) |

## Security Model

```
┌─────────────────────────────────────────────────┐
│                 Security Layers                  │
├─────────────────────────────────────────────────┤
│ 1. Docker Isolation    │ All R code in container │
│ 2. Network Disabled    │ No internet by default  │
│ 3. Resource Limits     │ Memory + CPU caps       │
│ 4. PII Redaction       │ Output sanitized        │
│ 5. Temp Network Only   │ Package installs only   │
└─────────────────────────────────────────────────┘
```

## Usage Examples

### Basic Analysis
> "Mount my data directory at /Users/me/data and analyze the sales_data.xlsx file. Show summary statistics and monthly trends."

### Visualization
> "Create a publication-ready boxplot comparing revenue by quarter using my data."

### Sensitive Data (with PII enabled)
> "Load the patient data and show me aggregate statistics: mean age, diagnosis distribution, and HbA1c levels by treatment group."

R output is automatically sanitized — even if raw data is accidentally printed, personal information is redacted before reaching the AI.

### Session Workflow
```python
# Step 1: Load data (persists in session)
execute_r_script("data <- read_excel('/data/patients.xlsx')")

# Step 2: Analyze (data variable still available)
execute_r_script("summary(data)")

# Step 3: Visualize (still in session)
execute_r_script("ggplot(data, aes(x=age)) + geom_histogram()")

# Step 4: Clean up
clear_session()
```

## Docker Support

Docker is mandatory for security. The server uses pre-built Docker images:

1. **`semoss/docker-r-packages`** (primary — comprehensive R packages)
2. **`rocker/tidyverse`** (fallback — data science packages)
3. **`r-base`** (final fallback — minimal R)

Images are automatically pulled on first use. The container:
- Runs with network disabled (re-enabled only for package installs)
- Has memory and CPU limits enforced
- Persists across all operations in the session
- Is automatically cleaned up on server shutdown

## Development

```bash
# Install development dependencies
uv sync --dev

# Install PII protection for testing
uv pip install presidio-analyzer presidio-anonymizer spacy
uv pip install https://github.com/explosion/spacy-models/releases/download/xx_ent_wiki_sm-3.8.0/xx_ent_wiki_sm-3.8.0-py3-none-any.whl

# Run linting
uv run ruff check
uv run black --check .
```

## Troubleshooting

### Docker Issues
```bash
# Ensure Docker is running
docker --version

# Start Docker (Linux)
sudo systemctl start docker

# macOS/Windows: Ensure Docker Desktop is running
```

### PII Protection Issues
```bash
# Check if presidio is installed
python -c "import presidio_analyzer; print('OK')"

# Install NER model for name detection
uv pip install https://github.com/explosion/spacy-models/releases/download/xx_ent_wiki_sm-3.8.0/xx_ent_wiki_sm-3.8.0-py3-none-any.whl

# Verify NER model works
python -c "import spacy; nlp = spacy.load('xx_ent_wiki_sm'); print('NER OK')"
```

### Common Issues
- **First run slow**: Normal — Docker image pull + container setup (~15-30s)
- **Package install fails**: Network temporarily enabled, check Docker network
- **Container unresponsive**: Restart the MCP server
- **PII not detected**: Ensure `R_MCP_PII_ENABLED=true` is set

## Comparison with Original

| Feature | Original (Go) | This Version (Python) |
|---------|---------------|----------------------|
| Core Tools | 2 | **7** |
| Directory Mounting | ❌ | ✅ (multiple) |
| Plot Capture | Basic | ✅ (auto base64 PNG) |
| Session Persistence | ❌ | ✅ (.RData) |
| Auto Library Install | ❌ | ✅ |
| Network Isolation | ❌ | ✅ (default) |
| PII Protection | ❌ | ✅ (Presidio + NER) |
| Resource Limits | ❌ | ✅ (memory + CPU) |
| Container Healthcheck | ❌ | ✅ |
| Modern Framework | ❌ | ✅ (FastMCP 3.1+) |

## Contributing

Contributions are welcome! Please submit pull requests for any enhancements.

## License

Creative Commons Attribution-NonCommercial 4.0 International (CC-BY-NC 4.0)

This work is licensed under a [Creative Commons Attribution-NonCommercial 4.0 International License](http://creativecommons.org/licenses/by-nc/4.0/).

## Acknowledgments

- Inspired by [gdbelvin's rlang-mcp-server](https://github.com/gdbelvin/rlang-mcp-server)
- Built with [FastMCP](https://github.com/jlowin/fastmcp)
- PII protection powered by [Microsoft Presidio](https://github.com/microsoft/presidio) and [spaCy](https://spacy.io/)
- Powered by [uv](https://github.com/astral-sh/uv) for fast Python package management
