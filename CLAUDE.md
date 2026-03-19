# Claude Desktop Configuration for R-Server MCP

This file contains the optimal configuration for using R-Server MCP with Claude Desktop.

## Configuration

Add this to your Claude Desktop MCP configuration:

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

### Environment Variables (Optional)

You can customize container behavior with environment variables:

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
        "R_MCP_MEM_LIMIT": "4g",
        "R_MCP_CPU_QUOTA": "400000",
        "R_MCP_CACHE_TTL": "7200",
        "R_MCP_CACHE_SIZE": "200",
        "R_MCP_SESSION": "true",
        "R_MCP_NETWORK_DISABLED": "true",
        "R_MCP_PII_ENABLED": "true"
      }
    }
  }
}
```

| Variable | Default | Description |
|----------|---------|-------------|
| `R_MCP_MEM_LIMIT` | `2g` | Container memory limit |
| `R_MCP_CPU_QUOTA` | `200000` | CPU quota (100000 = 1 CPU) |
| `R_MCP_CACHE_TTL` | `3600` | Cache time-to-live in seconds |
| `R_MCP_CACHE_SIZE` | `100` | Maximum cached results |
| `R_MCP_SESSION` | `true` | Persist R variables between calls |
| `R_MCP_NETWORK_DISABLED` | `true` | Container network isolation (temporarily enabled only for package installs) |
| `R_MCP_PII_ENABLED` | `false` | PII redaction on R output before sending to LLM |

## PII Protection (Sensitive Data)

When working with sensitive data (healthcare, financial, personal), enable PII protection to automatically redact personally identifiable information from R output before it reaches the LLM.

### Setup

```bash
# Install with privacy extras
pip install 'rlang-mcp-server[privacy]'

# Install multilingual NER model for name detection (optional but recommended)
uv pip install https://github.com/explosion/spacy-models/releases/download/xx_ent_wiki_sm-3.8.0/xx_ent_wiki_sm-3.8.0-py3-none-any.whl
```

Then set `R_MCP_PII_ENABLED=true` in your environment variables.

### What Gets Redacted

| PII Type | Method | Example |
|----------|--------|---------|
| TC Kimlik No | Regex | `12345678901` → `<TR_TC_KIMLIK>` |
| Phone numbers | Regex | `0532 456 7890` → `<TR_PHONE>` |
| Email addresses | Regex | `ali@mail.com` → `<EMAIL>` |
| IBAN | Regex | `TR33000610...` → `<TR_IBAN>` |
| Credit cards | Regex | `4532-1234-5678-9012` → `<CREDIT_CARD>` |
| Patient IDs | Regex | `Hasta No: 2024-15832` → `<TR_HASTA_NO>` |
| Person names | NER | `Ali Yılmaz` → `<PERSON>` (requires xx_ent_wiki_sm) |

### What Passes Through (No False Positives)

- Aggregate statistics: `mean=45.2, sd=12.3, n=150`
- Frequency tables: `table(data$diagnosis)`
- Medical terms: `HbA1c`, `Tip 2 Diyabet`
- R output formatting: `Min. 1st Qu. Median Mean`

### Data Flow

```
R code runs in Docker (local, network disabled)
    ↓
R output (stdout)
    ↓ R_MCP_PII_ENABLED=true
[Presidio Regex] → TC, phone, email, IBAN, credit card, patient ID
[spaCy NER]      → Person names (Ali Yılmaz, Mehmet Öz...)
[Whitelist]      → Filter false positives (medical/statistical terms)
    ↓
Sanitized output → Claude API (no PII leaves your machine)
```

### Fallback Behavior

- If `presidio` is installed → Full regex + NER detection
- If `presidio` is NOT installed → Pure regex fallback (still catches TC, phone, email, IBAN)
- If NER model is not installed → Regex only (no name detection)

## Performance Notes

### First Run
- Initial setup takes ~15-30 seconds
- Docker container creation and R package installation
- Subsequent runs are much faster (~2-3 seconds)

### Persistent Container
- Uses persistent Docker container for all R operations
- Common packages pre-installed: `readxl`, `ggplot2`, `dplyr`, `tidyr`, etc.
- Container automatically cleaned up on server shutdown
- Resource limits enforced (memory, CPU)

### Session Persistence
- R variables persist between `execute_r_script` calls
- Workspace saved/loaded automatically via `.RData`
- Use `clear_session` to reset workspace

### Container Warm-up
- Common R packages (readxl, dplyr, tidyr, ggplot2) are pre-loaded at container start
- Reduces first execution latency

### Network Security
- Container network disabled by default after initial setup
- Temporarily re-enabled only for `install_r_package` and auto library detection
- Automatically disabled again after package installation completes
- Prevents data exfiltration via `download.file()`, `curl`, `url()` etc.

### Docker Images Used
1. **Primary**: `semoss/docker-r-packages:latest` (comprehensive R packages pre-installed)
2. **Fallback 1**: `rocker/tidyverse:latest` (data science packages)
3. **Final Fallback**: `r-base:latest` (minimal R installation)

## Required Dependencies

### System Requirements
- **Docker** (mandatory - must be running)
- **Python 3.12+**
- **uv** or **pip** for package management

### Python Packages
- `fastmcp>=3.1.1`
- `docker>=7.1.0`
- `presidio-analyzer>=2.2.0` (optional, for PII protection)
- `presidio-anonymizer>=2.2.0` (optional, for PII protection)
- `spacy>=3.7.0` (optional, for PII protection)

## Usage Examples

### Mount Directory and Analyze Data
```python
# Mount your data directory
mount_directory("/path/to/your/data")
# Returns: container_path: "/data", usage_example: "Use '/data/' prefix in R code"

# Execute R analysis with file listing and data analysis
execute_r_script("""
library(readxl)

# List files in mounted directory
files <- list.files("/data", pattern="*.xlsx", full.names=TRUE)
print(files)

# Load and analyze data
data <- read_excel("/data/your_file.xlsx")  # Note: /data/ prefix for mounted files
summary(data)
""")
```

### Mount Multiple Directories
```python
# Mount first directory -> /data
mount_directory("/path/to/sales_data")

# Mount second directory -> /data2
mount_directory("/path/to/reports")

# Or specify custom mount point
mount_directory("/path/to/models", mount_point="/models")

# Access all in R
execute_r_script("""
sales <- read_excel("/data/sales.xlsx")
reports <- list.files("/data2")
model <- readRDS("/models/forecast.rds")
""")

# Unmount when done
unmount_directory(unmount_all=True)
```

### Create Visualizations (Auto-captured as Base64)
```python
# Plots are automatically detected and returned as base64 PNG
result = execute_r_script("""
library(ggplot2)
p <- ggplot(mtcars, aes(x=wt, y=mpg)) +
  geom_point() +
  theme_minimal()
print(p)
""")
# result["plot_base64"] contains the PNG image as base64
# result["plot_mime_type"] = "image/png"
```

### Session Persistence
```python
# Set variables in one call
execute_r_script("my_data <- mtcars; my_model <- lm(mpg ~ wt, data=my_data)")

# Access them in the next call - variables persist!
execute_r_script("summary(my_model)")

# Clear session when done
clear_session()
```

### Auto Library Detection
```python
# Missing packages are automatically detected and installed
execute_r_script("""
library(forecast)  # Auto-installed if missing
library(randomForest)  # Auto-installed if missing

model <- auto.arima(AirPassengers)
print(forecast(model, h=12))
""")
```

### Sensitive Data Analysis (with PII Protection)
```python
# With R_MCP_PII_ENABLED=true, personal data is automatically redacted
execute_r_script("""
library(readxl)
data <- read_excel("/data/patients.xlsx")

# Safe: aggregate statistics (pass through)
cat("Ortalama yaş:", mean(data$age), "\n")
cat("Tanı dağılımı:\n")
print(table(data$diagnosis))

# If someone accidentally prints raw data, PII is redacted:
# head(data) → names, TC numbers, phones automatically masked
""")
# Output to Claude: "Ortalama yaş: 45.2" (no PII)
# If PII detected: result["pii_redacted"] = True
```

## Troubleshooting

### Docker Issues
- Ensure Docker Desktop is running
- Check if `r-base:latest` image is available: `docker pull r-base:latest`

### Performance Issues
- First run is slower due to container setup and image pull
- Container persists across all operations for better performance
- If container becomes unresponsive, restart the MCP server
- Pre-built images with compiled packages significantly reduce startup time

### Permission Issues
- Ensure mounted directories are readable
- Check Docker volume mounting permissions

### Error Messages
- R errors now include traceback information and call context
- Warnings are captured with their source location
- Use `container_status` to check container health

### PII Protection Issues
- If names are not detected, install the NER model: `uv pip install xx_ent_wiki_sm@https://...`
- Pure regex fallback still catches TC, phone, email, IBAN, credit card
- Check `result["pii_detections"]` to see what was redacted

## Commands to Remember

```bash
# Check if server is working
uvx --from git+https://github.com/saidsurucu/rlang-mcp-python rlang-mcp-python --help

# Pull Docker images manually (optional)
docker pull semoss/docker-r-packages:latest
docker pull rocker/tidyverse:latest
docker pull r-base:latest

# Check running containers
docker ps | grep -E "r-container|semoss|rocker"

# Install PII protection (optional)
pip install 'rlang-mcp-server[privacy]'
uv pip install https://github.com/explosion/spacy-models/releases/download/xx_ent_wiki_sm-3.8.0/xx_ent_wiki_sm-3.8.0-py3-none-any.whl
```

## Available Tools

The R-Server MCP provides these **7 tools**:

1. **`mount_directory`** - Mount local directories to access files in R (supports multiple directories)
2. **`unmount_directory`** - Unmount a previously mounted directory or all directories
3. **`execute_r_script`** - Run R code with auto plot capture (base64 PNG), auto library detection, session persistence, PII redaction, and enhanced error messages
4. **`container_status`** - Check container health, resource usage, R version, session info, and cache stats
5. **`initialize_r_container`** - Start R container with resource limits and package warm-up
6. **`install_r_package`** - Install R packages on-demand (temporarily enables network)
7. **`clear_session`** - Clear R session workspace (remove all persisted variables)

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

## Updates

- **2026-03-19**: Added PII redaction (Presidio regex + spaCy NER, Turkish support)
- **2026-03-19**: Network disabled by default, temp-enabled for package installs
- **2026-03-18**: Added multiple directory mounting support
- **2026-03-18**: Added inline plot capture (base64 PNG) with auto-detection
- **2026-03-18**: Added R session persistence (.RData workspace)
- **2026-03-18**: Added auto library detection and installation
- **2026-03-18**: Added container resource limits (memory, CPU)
- **2026-03-18**: Added container healthcheck (actual R execution test)
- **2026-03-18**: Added enhanced error messages with traceback
- **2026-03-18**: Added container warm-up (pre-load common packages)
- **2026-03-18**: Added configurable cache (TTL, size via env vars)
- **2026-03-18**: Added `unmount_directory` and `clear_session` tools
- **2026-03-18**: Updated fastmcp dependency to >=3.1.1
- **2025-01-23**: Simplified API - removed redundant tools (list_files, file_info, render_ggplot)
- **2025-01-23**: Switched to semoss/docker-r-packages as primary image
- **2025-01-23**: Fixed container management and locale support
- **2025-01-23**: Added container_status tool for monitoring
- **2025-01-22**: Added persistent container support
- **2025-01-22**: Switched to binary package installation
- **2025-01-22**: Added rocker/tidyverse image support for faster startup
