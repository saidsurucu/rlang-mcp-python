# Python R-Server MCP

A comprehensive Model Context Protocol (MCP) server for R data visualization and analysis, built with Python and FastMCP.

**What is this?** This tool allows you to perform statistical analysis in R through natural language conversations with LLM models like Claude. Instead of writing R code manually, you can simply describe what analysis you want, and the AI will execute R scripts, create visualizations, and analyze your data for you.

**Key Benefits:**
- 🗣️ **Natural Language Interface**: Chat with AI to perform complex statistical analyses
- 📊 **Automatic R Execution**: AI runs R code and returns results without you writing code
- 📁 **Direct File Access**: Mount local directories so AI can work with your Excel/CSV files
- 📈 **Publication-Ready Plots**: Generate professional ggplot2 visualizations through conversation
- 🔄 **Interactive Analysis**: Ask follow-up questions and refine your analysis iteratively

*🌐 [Türkçe](README_TR.md) | **English***

## Overview

This project is inspired by [gdbelvin's rlang-mcp-server](https://github.com/gdbelvin/rlang-mcp-server) but is a complete Python reimplementation using the FastMCP framework. While the original Go version provided basic R visualization tools, this Python version extends the functionality with comprehensive file management capabilities and enhanced user experience.

## Features

### 🎨 **Visualization & Analysis**
- **ggplot2 Rendering**: Execute R code with ggplot2 commands and return publication-ready visualizations
- **R Script Execution**: Run any R script with smart file handling and return formatted output
- **Multiple Formats**: Support for PNG, JPEG, PDF, and SVG output formats
- **Customizable Output**: Control image dimensions, resolution, and quality

### 📁 **File Management** (New!)
- **Directory Mounting**: Mount local directories to access files directly in R workspace
- **File Listing**: Browse and filter files in the workspace with detailed metadata
- **File Inspection**: Get detailed information about files including Excel sheet structure
- **Smart File Discovery**: Automatic file detection and suggestion for missing files

### 📦 **Package Management**
- **Package Installation**: Install R packages on-demand with version control
- **Package Listing**: Browse installed packages with filtering capabilities
- **Automatic Dependencies**: Smart package dependency resolution

### 🛡️ **Security & Isolation**
- **Docker Support**: Required containerized execution for enhanced security
- **Path Sanitization**: Protection against directory traversal attacks
- **File Access Control**: Secure file system access with proper permission checks

### 🚀 **Developer Experience**
- **FastMCP Framework**: Modern Python MCP implementation with excellent performance
- **uv Package Manager**: Lightning-fast dependency management and virtual environments
- **Comprehensive Testing**: Full test suite with integration and unit tests
- **Rich Documentation**: Detailed API documentation and usage examples

## Quick Start

### Prerequisites

Before installing the MCP server, you need to install the required dependencies on your system:

#### macOS

```bash
# Install Homebrew (if not already installed)
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"

# Install R
brew install r

# Install uv (Python package manager)
brew install uv

# Install Python 3.12+ (if not already installed)
brew install python@3.12

# Install Docker (required for secure execution)
brew install --cask docker
```

#### Windows

```powershell
# Install R from CRAN
# Download and install from: https://cran.r-project.org/bin/windows/base/

# Install Python 3.12+ from python.org
# Download from: https://www.python.org/downloads/windows/

# Install uv using pip
pip install uv

# Install Docker Desktop (required for secure execution)
# Download from: https://www.docker.com/products/docker-desktop
```

#### Linux (Ubuntu/Debian)

```bash
# Update package list
sudo apt update

# Install R
sudo apt install r-base r-base-dev

# Install Python 3.12+
sudo apt install python3.12 python3.12-venv python3-pip

# Install uv
pip install uv

# Install Docker (required for secure execution)
sudo apt install docker.io
sudo systemctl start docker
sudo systemctl enable docker
```

### Installation

After installing the prerequisites, install the MCP server:

```bash
# Method 1: Install directly from GitHub (recommended)
uvx --from git+https://github.com/saidsurucu/rlang-mcp-python rlang-mcp-python

# Method 2: Clone and install locally
git clone https://github.com/saidsurucu/rlang-mcp-python.git
cd rlang-mcp-python
uv sync

# Method 3: Install with pip
pip install git+https://github.com/saidsurucu/rlang-mcp-python
```

### System Requirements

- **Python 3.12+**
- **R 4.0+** (packages are installed automatically)
- **uv** (recommended) or pip for package management
- **Docker** (required for secure containerized execution)

### Running the Server

```bash
# Using uvx (recommended)
uvx --from . r-server-mcp

# Or using uv run
uv run r-server-mcp

# Or using Python directly
python -m r_server
```

## Tools Available

This server provides **7 comprehensive tools**:

| Tool | Description | Category |
|------|-------------|----------|
| `mount_directory` | Mount a local directory for R operations | Directory Management |
| `list_files` | List and filter workspace files | File Management |  
| `file_info` | Get detailed file information | File Management |
| `render_ggplot` | Generate ggplot2 visualizations | Visualization |
| `execute_r_script` | Execute R scripts with smart file handling | Execution |
| `install_r_package` | Install R packages on-demand | Package Management |
| `list_r_packages` | List and search installed packages | Package Management |

## MCP Integration

### Claude Desktop Configuration

Add to your `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "r-server-python": {
      "command": "uvx",
      "args": [
        "--from", 
        "/path/to/rlang-mcp-python",
        "r-server-mcp"
      ],
      "disabled": false
    }
  }
}
```

## Step-by-Step Usage Workflow

### Step 1: Mount Your Data Directory

First, tell Claude to mount your data directory. Use a prompt like:

> "Please mount my data directory at /Users/you/Documents/data-analysis as the R working directory so you can analyze the files in that folder."

This command:
- Sets the specified path as the R working directory
- Creates an `r_workspace` subdirectory automatically
- Allows Claude to read all files in this directory
- Returns confirmation with available files

### Step 2: Explore Available Data

Ask Claude to explore your data files:

> "List all the files in my mounted directory, especially Excel files, and show me what data is available for analysis."

> "Can you give me detailed information about the sales_data.xlsx file, including what sheets it contains?"

### Step 3: Analyze Your Data

Now request analysis of your data:

> "Please analyze the sales data in sales_data.xlsx. Load the data, show me a summary, and calculate monthly sales totals grouped by month."

> "Read the financial data from quarterly_report.xlsx and perform a comprehensive analysis comparing Q1 and Q2 performance."

### Step 4: Create Visualizations

Request custom visualizations:

> "Create a bar chart showing monthly sales by category using the data in sales_data.xlsx. Make it publication-ready with proper labels and colors."

> "Generate a boxplot comparing revenue distribution between quarters and departments from my quarterly report data."

### Directory Structure Method

The recommended workflow uses directory mounting:

> "Please mount my data directory so you can analyze all my Excel files for trends and patterns."

### Complete Workflow Example

Here's how you might interact with Claude for a full analysis:

**Initial Setup:**
> "Please mount my project directory at /Users/you/Documents/financial-analysis so you can access my data files."

**Data Exploration:**
> "What Excel files do you see in the directory? Can you tell me about the structure of quarterly_report.xlsx?"

**Analysis Request:**
> "Please perform a comprehensive financial analysis using the quarterly report data. I want to see:
> - Summary statistics for each quarter
> - Revenue comparisons between Q1 and Q2  
> - Performance by department
> - Any notable trends or patterns"

**Visualization Request:**
> "Create professional visualizations showing:
> 1. Revenue distribution by quarter and department as a boxplot
> 2. Department performance comparison as a bar chart
> Make sure they're suitable for a business presentation."

**Follow-up Analysis:**
> "Based on the analysis, what are the key insights about our quarterly performance? Are there any departments that need attention?"

## Docker Support

Docker is required for secure execution:

```bash
# Build Docker image
docker build -f Dockerfile.python -t r-server-mcp .

# Run with Docker Compose
docker-compose -f docker-compose.python.yml up
```

## Development

```bash
# Install development dependencies
uv sync --dev

# Run tests
uv run pytest

# Run linting
uv run ruff check
uv run black --check .

# Type checking
uv run mypy r_server.py
```

## Troubleshooting

### Common Issues

#### R not found
```bash
# macOS: Ensure R is in PATH
echo 'export PATH="/usr/local/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc

# Windows: Add R to system PATH
# Add C:\Program Files\R\R-x.x.x\bin to your PATH environment variable

# Linux: Install R development packages
sudo apt install r-base-dev
```

#### Python version issues
```bash
# Check Python version
python --version

# Use specific Python version with uv
uv python install 3.12
uv python pin 3.12
```

#### R package installation failures
```bash
# macOS: Install system dependencies
brew install harfbuzz fribidi
brew install --cask xquartz

# Ubuntu/Debian: Install system dependencies
sudo apt install libcurl4-openssl-dev libssl-dev libxml2-dev
sudo apt install libharfbuzz-dev libfribidi-dev

# Windows: Use binary packages
# In R console:
install.packages('ggplot2', type='binary')
```

#### uv command not found
```bash
# Install uv globally
pip install --user uv

# Or use curl on Unix systems
curl -LsSf https://astral.sh/uv/install.sh | sh

# Windows: Use pip or download from GitHub releases
```

#### Permission denied errors
```bash
# Linux/macOS: Fix R library permissions
sudo chmod -R 755 /usr/local/lib/R
sudo chown -R $USER /usr/local/lib/R/site-library

# Or install packages in user library
# In R console:
.libPaths()  # Check library paths
install.packages('ggplot2', lib=.libPaths()[1])
```

#### Docker issues
```bash
# Start Docker service (Linux)
sudo systemctl start docker

# Add user to docker group (Linux)
sudo usermod -aG docker $USER
# Logout and login again

# macOS/Windows: Ensure Docker Desktop is running
```

### Verification

Test your installation:

```bash
# Test R installation
Rscript -e "R.version.string"

# Test R packages
Rscript -e "library(ggplot2); library(readxl); cat('R packages OK\n')"

# Test Python/uv
uv --version
python --version

# Test MCP server
uvx --from git+https://github.com/saidsurucu/rlang-mcp-python rlang-mcp-python --help
```

## Comparison with Original

| Feature | Original (Go) | This Version (Python) |
|---------|---------------|----------------------|
| Core Tools | 2 | **7** |
| Directory Mounting | ❌ | ✅ |
| File Management | ❌ | ✅ |
| Package Management | ❌ | ✅ |
| File Access Control | ❌ | ✅ |
| Smart File Handling | ❌ | ✅ |
| Modern Framework | ❌ | ✅ (FastMCP) |
| Package Manager | Go modules | **uv** |
| Testing Suite | Basic | **Comprehensive** |

## Contributing

Contributions are welcome! Please read our contributing guidelines and submit pull requests for any enhancements.

## License

Creative Commons Attribution-NonCommercial 4.0 International (CC-BY-NC 4.0)

This work is licensed under a [Creative Commons Attribution-NonCommercial 4.0 International License](http://creativecommons.org/licenses/by-nc/4.0/).

## Acknowledgments

- Inspired by [gdbelvin's rlang-mcp-server](https://github.com/gdbelvin/rlang-mcp-server)
- Built with [FastMCP](https://github.com/jlowin/fastmcp)
- Powered by [uv](https://github.com/astral-sh/uv) for fast Python package management