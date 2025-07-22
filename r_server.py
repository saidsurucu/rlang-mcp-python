"""
R-Server MCP - A FastMCP server for R data analysis, visualization, and script execution.

Provides 7 comprehensive tools:
- mount_directory: Mount local directories for R operations
- list_files: List and filter workspace files  
- file_info: Get detailed file information
- render_ggplot: Generate visualizations using R's ggplot2 library
- execute_r_script: Execute R scripts with smart file handling
- install_r_package: Install R packages on-demand
- list_r_packages: List and search installed packages
"""

import asyncio
import base64
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional, Literal

import docker

from fastmcp import FastMCP

# Create the FastMCP server
mcp = FastMCP("R-Server MCP")

# Global variable to store mounted directory
MOUNTED_DIRECTORY = None

# Check and install R packages automatically
def ensure_r_packages():
    """Check if required R packages are installed and install them if missing."""
    required_packages = ["ggplot2", "cowplot", "readxl", "writexl", "dplyr", "tidyr"]
    
    print("Checking R package dependencies...", file=sys.stderr)
    
    for package in required_packages:
        check_script = f"""
        if (!requireNamespace("{package}", quietly = TRUE)) {{
          cat("MISSING\\n")
        }} else {{
          cat("OK\\n")
        }}
        """
        
        try:
            result = subprocess.run(
                ["Rscript", "-e", check_script],
                capture_output=True,
                text=True,
                timeout=5
            )
            
            if "MISSING" in result.stdout:
                print(f"Installing R package: {package}...", file=sys.stderr)
                install_script = f"""
                install.packages("{package}", repos="https://cran.r-project.org", quiet=TRUE)
                if (requireNamespace("{package}", quietly = TRUE)) {{
                  cat("SUCCESS\\n")
                }} else {{
                  cat("FAILED\\n")
                }}
                """
                
                install_result = subprocess.run(
                    ["Rscript", "-e", install_script],
                    capture_output=True,
                    text=True,
                    timeout=120  # Give more time for installation
                )
                
                if "SUCCESS" in install_result.stdout:
                    print(f"✓ Successfully installed {package}", file=sys.stderr)
                else:
                    print(f"✗ Failed to install {package}: {install_result.stderr}", file=sys.stderr)
            else:
                print(f"✓ {package} already available", file=sys.stderr)
                
        except subprocess.TimeoutExpired:
            print(f"✗ Timeout checking/installing {package}", file=sys.stderr)
        except Exception as e:
            print(f"✗ Error with {package}: {e}", file=sys.stderr)
    
    print("R package check completed.", file=sys.stderr)

# Ensure packages are installed on import (with shorter timeout for startup)
try:
    # Quickly check critical packages only at startup
    critical_packages = ["ggplot2", "cowplot"]  # Most important ones
    
    print("Quick R package check...", file=sys.stderr)
    for pkg in critical_packages:
        check_script = f'if (!requireNamespace("{pkg}", quietly = TRUE)) cat("MISSING\\n") else cat("OK\\n")'
        result = subprocess.run(["Rscript", "-e", check_script], capture_output=True, text=True, timeout=3)
        
        if "MISSING" in result.stdout:
            print(f"Installing critical package: {pkg}...", file=sys.stderr)
            install_script = f'install.packages("{pkg}", repos="https://cran.r-project.org", quiet=TRUE)'
            subprocess.run(["Rscript", "-e", install_script], timeout=60)
    
    print("✓ Critical R packages ready", file=sys.stderr)
except Exception as e:
    print(f"R package check skipped: {e}", file=sys.stderr)

# Output formats supported
OutputFormat = Literal["png", "jpeg", "pdf", "svg"]

@mcp.tool
def mount_directory(
    directory_path: str
) -> dict:
    """
    Mount a directory for R workspace operations.
    
    Args:
        directory_path: Path to the directory to mount (must be absolute path)
    
    Returns:
        Dictionary with mount status and details
    """
    global MOUNTED_DIRECTORY
    from pathlib import Path
    import os
    
    try:
        # Convert to Path object
        mount_path = Path(directory_path).resolve()
        
        # Security checks
        if not mount_path.is_absolute():
            return {
                "success": False,
                "message": "Path must be absolute",
                "details": f"Provided path: {directory_path}"
            }
        
        # Check if directory exists
        if not mount_path.exists():
            return {
                "success": False,
                "message": "Directory does not exist",
                "details": f"Path not found: {mount_path}"
            }
        
        if not mount_path.is_dir():
            return {
                "success": False,
                "message": "Path is not a directory",
                "details": f"Path is a file: {mount_path}"
            }
        
        # Check read permissions
        if not os.access(mount_path, os.R_OK):
            return {
                "success": False,
                "message": "No read permission for directory",
                "details": f"Cannot read: {mount_path}"
            }
        
        # Set the mounted directory
        MOUNTED_DIRECTORY = mount_path
        
        # Create r_workspace subdirectory if it doesn't exist
        workspace_path = mount_path / "r_workspace"
        workspace_path.mkdir(exist_ok=True)
        
        # List some files to confirm
        files = list(mount_path.glob("*"))[:5]
        file_names = [f.name for f in files]
        
        print(f"✓ Mounted directory: {mount_path}", file=sys.stderr)
        
        return {
            "success": True,
            "message": "Directory mounted successfully",
            "mounted_path": str(mount_path),
            "workspace_path": str(workspace_path),
            "sample_files": file_names,
            "total_files": len(list(mount_path.glob("*"))),
            "details": f"R operations will now use this directory as base path"
        }
        
    except Exception as e:
        return {
            "success": False,
            "message": f"Failed to mount directory: {str(e)}",
            "details": ""
        }

def get_working_directory():
    """Get the current working directory for R operations."""
    if MOUNTED_DIRECTORY:
        return MOUNTED_DIRECTORY
    return Path.cwd()


@mcp.tool
def list_files(
    pattern: str = "*",
    file_type: str = "all"
) -> dict:
    """
    List files in the R working directory.
    
    Args:
        pattern: File pattern to match (e.g., "*.xlsx")
        file_type: Filter by file type (all, excel, csv, text)
    
    Returns:
        Dictionary with file list and details
    """
    from pathlib import Path
    import glob
    import os
    from datetime import datetime
    
    try:
        # Check both mounted directory and r_workspace
        base_dir = get_working_directory()
        search_dirs = [base_dir, base_dir / "r_workspace"]
        all_files = []
        
        type_patterns = {
            "excel": ["*.xlsx", "*.xls"],
            "csv": ["*.csv", "*.tsv"],
            "text": ["*.txt"],
            "all": [pattern]
        }
        
        patterns = type_patterns.get(file_type, [pattern])
        
        for search_dir in search_dirs:
            if search_dir.exists():
                for pat in patterns:
                    files = list(search_dir.glob(pat))
                    for file_path in files:
                        if file_path.is_file():
                            stat = file_path.stat()
                            all_files.append({
                                "name": file_path.name,
                                "path": str(file_path),
                                "size_bytes": stat.st_size,
                                "size_mb": round(stat.st_size / (1024*1024), 2),
                                "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
                                "extension": file_path.suffix,
                                "directory": "workspace" if "r_workspace" in str(file_path) else "current"
                            })
        
        # Remove duplicates and sort
        unique_files = {}
        for f in all_files:
            unique_files[f["name"]] = f
        
        sorted_files = sorted(unique_files.values(), key=lambda x: x["modified"], reverse=True)
        
        return {
            "success": True,
            "files": sorted_files,
            "count": len(sorted_files),
            "message": f"Found {len(sorted_files)} files matching criteria",
            "search_pattern": pattern,
            "file_type_filter": file_type
        }
        
    except Exception as e:
        return {
            "success": False,
            "files": [],
            "count": 0,
            "message": f"Error listing files: {str(e)}"
        }

@mcp.tool
def file_info(filename: str) -> dict:
    """
    Get detailed information about a specific file.
    
    Args:
        filename: Name of the file to inspect
    
    Returns:
        Dictionary with detailed file information
    """
    from pathlib import Path
    import mimetypes
    from datetime import datetime
    
    try:
        # Search in multiple locations
        base_dir = get_working_directory()
        search_paths = [
            Path(filename) if Path(filename).is_absolute() else None,
            base_dir / filename,
            base_dir / "r_workspace" / filename
        ]
        search_paths = [p for p in search_paths if p]  # Remove None
        
        file_path = None
        for path in search_paths:
            if path.exists() and path.is_file():
                file_path = path
                break
        
        if not file_path:
            return {
                "success": False,
                "filename": filename,
                "message": "File not found",
                "details": f"Searched in: current directory, r_workspace"
            }
        
        # Get file stats
        stat = file_path.stat()
        mime_type, _ = mimetypes.guess_type(str(file_path))
        
        # Try to get additional info for data files
        additional_info = {}
        
        if file_path.suffix.lower() in ['.xlsx', '.xls']:
            try:
                # Get Excel sheet info
                r_script = f'''
                library(readxl)
                file_path <- "{file_path}"
                sheets <- excel_sheets(file_path)
                cat("SHEETS:", paste(sheets, collapse=","), "\\n")
                
                # Get first sheet info
                if (length(sheets) > 0) {{
                  data <- read_excel(file_path, sheet = 1)
                  cat("ROWS:", nrow(data), "\\n")
                  cat("COLS:", ncol(data), "\\n")
                  cat("COLNAMES:", paste(names(data), collapse=","), "\\n")
                }}
                '''
                
                result = subprocess.run(
                    ["Rscript", "-e", r_script],
                    capture_output=True,
                    text=True,
                    timeout=10
                )
                
                if result.returncode == 0:
                    output = result.stdout
                    if "SHEETS:" in output:
                        sheets = output.split("SHEETS:")[1].split("\\n")[0].strip()
                        additional_info["excel_sheets"] = sheets.split(",") if sheets else []
                    if "ROWS:" in output:
                        additional_info["rows"] = output.split("ROWS:")[1].split("\\n")[0].strip()
                    if "COLS:" in output:
                        additional_info["columns"] = output.split("COLS:")[1].split("\\n")[0].strip()
                    if "COLNAMES:" in output:
                        cols = output.split("COLNAMES:")[1].split("\\n")[0].strip()
                        additional_info["column_names"] = cols.split(",") if cols else []
                        
            except Exception:
                additional_info["excel_info"] = "Could not read Excel file details"
        
        return {
            "success": True,
            "filename": filename,
            "path": str(file_path),
            "size_bytes": stat.st_size,
            "size_mb": round(stat.st_size / (1024*1024), 2),
            "extension": file_path.suffix,
            "mime_type": mime_type,
            "created": datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
            "modified": datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            "is_readable": os.access(file_path, os.R_OK),
            "additional_info": additional_info,
            "message": "File information retrieved successfully"
        }
        
    except Exception as e:
        return {
            "success": False,
            "filename": filename,
            "message": f"Error getting file info: {str(e)}",
            "details": ""
        }

def execute_r_script_docker(r_code: str, host_temp_dir: str = None) -> tuple[str, str, int]:
    """
    Execute R script in a Docker container for security and isolation.
    
    Args:
        r_code: R code to execute
        host_temp_dir: Host directory to mount (for file I/O)
    
    Returns:
        Tuple of (stdout, stderr, return_code)
    """
    
    try:
        client = docker.from_env()
        
        # Use provided temp dir or create one
        if host_temp_dir:
            host_temp_path = Path(host_temp_dir)
            script_file = host_temp_path / "script.R"
            script_file.write_text(r_code)
        else:
            # Create a temporary directory on the host
            with tempfile.TemporaryDirectory() as temp_dir:
                host_temp_path = Path(temp_dir)
                script_file = host_temp_path / "script.R"
                script_file.write_text(r_code)
                return _run_docker_container(client, str(host_temp_path))
        
        return _run_docker_container(client, str(host_temp_path))
            
    except docker.errors.ImageNotFound:
        raise RuntimeError("Docker image 'r-base:latest' not found. Please pull it with: docker pull r-base")
    except docker.errors.DockerException as e:
        raise RuntimeError(f"Docker execution failed: {str(e)}")
    except Exception as e:
        raise RuntimeError(f"Unexpected error during Docker execution: {str(e)}")

def _run_docker_container(client, host_temp_path: str) -> tuple[str, str, int]:
    """Helper function to run Docker container."""
    # Container paths
    container_temp_dir = "/tmp/r_work"
    container_script_path = f"{container_temp_dir}/script.R"
    
    # Volume mapping
    volumes = {host_temp_path: {"bind": container_temp_dir, "mode": "rw"}}
    
    # Run R script in container
    try:
        result = client.containers.run(
            "r-base:latest",
            f"Rscript {container_script_path}",
            volumes=volumes,
            working_dir=container_temp_dir,
            remove=True,
            stderr=True
        )
        return result.decode('utf-8') if isinstance(result, bytes) else str(result), "", 0
        
    except docker.errors.ContainerError as e:
        stderr_output = e.stderr.decode('utf-8') if e.stderr else str(e)
        return "", stderr_output, e.exit_status

def execute_r_script_local(r_code: str, timeout: int = 60) -> tuple[str, str, int]:
    """
    Execute R script locally using subprocess.
    
    Returns:
        Tuple of (stdout, stderr, return_code)
    """
    with tempfile.NamedTemporaryFile(mode='w', suffix='.R', delete=False) as script_file:
        script_file.write(r_code)
        script_path = script_file.name
    
    try:
        result = subprocess.run(
            ["Rscript", script_path],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.stdout, result.stderr, result.returncode
        
    except subprocess.TimeoutExpired:
        return "", f"Script execution timed out after {timeout} seconds", -1
    except FileNotFoundError:
        return "", "R is not installed or not in PATH. Please install R and ensure 'Rscript' is available.", -1
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass

@mcp.tool
def render_ggplot(
    code: str,
    output_type: OutputFormat = "png",
    width: int = 800,
    height: int = 600,
    resolution: int = 96,
    use_docker: bool = False
) -> dict:
    """
    Render a ggplot2 visualization from R code.
    
    Args:
        code: R code containing ggplot2 commands
        output_type: Output format (png, jpeg, pdf, svg)
        width: Width of the output image in pixels (100-5000)
        height: Height of the output image in pixels (100-5000)
        resolution: Resolution of the output image in DPI (72-600)
        use_docker: Execute R code in Docker container for security
    
    Returns:
        Dictionary containing the base64-encoded image and metadata
    """
    # Validate arguments
    if not code.strip():
        raise ValueError("Code is required")
    
    if width < 100 or width > 5000:
        raise ValueError("Width must be between 100 and 5000")
        
    if height < 100 or height > 5000:
        raise ValueError("Height must be between 100 and 5000")
        
    if resolution < 72 or resolution > 600:
        raise ValueError("Resolution must be between 72 and 600")
    
    # Create temporary directory for R script and output
    with tempfile.TemporaryDirectory(prefix="ggplot-") as temp_dir:
        script_path = Path(temp_dir) / "script.R"
        output_path = Path(temp_dir) / f"output.{output_type}"
        
        # Generate R script content with smart file handling
        r_script = f'''
# Load required libraries
library(ggplot2)
library(cowplot)

# Set working directory based on mounted path
base_dir <- "{get_working_directory()}"
setwd(base_dir)
workspace_dir <- file.path(base_dir, "r_workspace")

if (dir.exists(workspace_dir)) {{
  workspace_files <- list.files(workspace_dir, full.names = TRUE)
  if (length(workspace_files) > 0) {{
    cat("Found workspace files:", paste(basename(workspace_files), collapse=", "), "\\n")
  }}
}}

# Set output parameters
width <- {width}
height <- {height}
dpi <- {resolution}
output_file <- "{output_path}"
pdf(NULL)

# Execute the provided code
{code}

# Save the last plot
ggsave(output_file, width = width/dpi, height = height/dpi, dpi = dpi)
'''
        
        # Write R script to file
        script_path.write_text(r_script)
        
        try:
            # Execute R script (Docker or local)
            if use_docker:
                stdout, stderr, returncode = execute_r_script_docker(r_script, str(temp_dir))
                if returncode != 0:
                    raise RuntimeError(f"R script execution failed: {stderr}")
            else:
                stdout, stderr, returncode = execute_r_script_local(r_script, timeout=60)
                if returncode != 0:
                    raise RuntimeError(f"R script execution failed: {stderr}")
            
            # Check if output file was created
            if not output_path.exists():
                raise RuntimeError("Output file was not created")
            
            # Read and encode the image
            image_data = output_path.read_bytes()
            base64_data = base64.b64encode(image_data).decode('utf-8')
            
            # Determine MIME type
            mime_types = {
                "png": "image/png",
                "jpeg": "image/jpeg", 
                "pdf": "application/pdf",
                "svg": "image/svg+xml"
            }
            
            # Return structured image data
            return {
                "type": "image",
                "format": output_type,
                "data": base64_data,
                "mime_type": mime_types[output_type],
                "width": width,
                "height": height,
                "resolution": resolution
            }
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("R script execution timed out")
        except FileNotFoundError:
            raise RuntimeError("R is not installed or not in PATH. Please install R and ensure 'Rscript' is available.")

@mcp.tool
def execute_r_script(
    code: str,
    timeout: int = 60,
    use_docker: bool = False
) -> dict:
    """
    Execute an R script and return the text output.
    
    Args:
        code: R code to execute
        timeout: Maximum execution time in seconds (1-300, ignored for Docker)
        use_docker: Execute R code in Docker container for security
    
    Returns:
        Dictionary containing the script output and execution status
    """
    # Validate arguments
    if not code.strip():
        raise ValueError("Code is required")
    
    if timeout < 1 or timeout > 300:
        raise ValueError("Timeout must be between 1 and 300 seconds")
    
    try:
        # Enhanced R script with smart file handling
        enhanced_code = f"""
# Smart file handling setup
base_dir <- "{get_working_directory()}"
setwd(base_dir)
workspace_dir <- file.path(base_dir, "r_workspace")

if (dir.exists(workspace_dir)) {{
  # List available workspace files
  workspace_files <- list.files(workspace_dir, full.names = FALSE)
  if (length(workspace_files) > 0) {{
    cat("📁 Available workspace files:", paste(workspace_files, collapse=", "), "\\n")
    
    # Helper function to read files from workspace
    read_workspace_file <- function(filename) {{
      file_path <- file.path(workspace_dir, filename)
      if (file.exists(file_path)) {{
        return(file_path)
      }} else {{
        # Try to find similar files
        similar_files <- workspace_files[grepl(gsub("\\\\..*", "", filename), workspace_files, ignore.case = TRUE)]
        if (length(similar_files) > 0) {{
          cat("⚠️ File '", filename, "' not found, but similar files available: ", paste(similar_files, collapse=", "), "\\n")
          return(file.path(workspace_dir, similar_files[1]))
        }}
        return(NULL)
      }}
    }}
  }}
}}

# Original user code
{code}
"""
        
        # Execute R script (Docker or local)
        if use_docker:
            stdout, stderr, returncode = execute_r_script_docker(enhanced_code)
        else:
            stdout, stderr, returncode = execute_r_script_local(enhanced_code, timeout)
        
        # Return structured data
        return {
            "success": returncode == 0,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "summary": f"Execution {'successful' if returncode == 0 else 'failed'}"
        }
        
    except RuntimeError as e:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "summary": "Execution failed"
        }

@mcp.tool
def install_r_package(
    package_name: str,
    version: str = "",
    repo: str = "https://cran.r-project.org",
    force_reinstall: bool = False,
    force_source: bool = False
) -> dict:
    """
    Install an R package.
    
    Args:
        package_name: Name of the R package to install
        version: Specific version to install (optional, e.g., "1.0.0")
        repo: Repository URL (default: CRAN)
        force_reinstall: Reinstall even if package exists
        force_source: Skip binary installation and force source compilation
    
    Returns:
        Dictionary with installation status and details
    """
    # Validate package name (basic security check)
    if not package_name or not package_name.replace(".", "").replace("_", "").isalnum():
        return {
            "success": False,
            "package": package_name,
            "message": "Invalid package name. Only alphanumeric characters, dots, and underscores allowed.",
            "details": ""
        }
    
    print(f"Processing R package installation: {package_name}", file=sys.stderr)
    
    try:
        # First check if package already exists (unless force reinstall)
        if not force_reinstall:
            check_script = f"""
            if (requireNamespace("{package_name}", quietly = TRUE)) {{
              cat("ALREADY_INSTALLED\\n")
              cat("Version:", as.character(packageVersion("{package_name}")), "\\n")
            }} else {{
              cat("NOT_INSTALLED\\n")
            }}
            """
            
            check_result = subprocess.run(
                ["Rscript", "-e", check_script],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if "ALREADY_INSTALLED" in check_result.stdout:
                installed_version = ""
                if "Version:" in check_result.stdout:
                    installed_version = check_result.stdout.split("Version:")[1].strip()
                
                return {
                    "success": True,
                    "package": package_name,
                    "message": f"Package already installed",
                    "version": installed_version,
                    "details": "No installation needed"
                }
        
        # Prepare installation script
        if version:
            # Install specific version
            install_script = f"""
            # Try to install specific version
            tryCatch({{
              if (!requireNamespace("devtools", quietly = TRUE)) {{
                install.packages("devtools", repos="{repo}", quiet=TRUE)
              }}
              devtools::install_version("{package_name}", version = "{version}", repos = "{repo}", quiet = TRUE)
              
              if (requireNamespace("{package_name}", quietly = TRUE)) {{
                cat("SUCCESS\\n")
                cat("Version:", as.character(packageVersion("{package_name}")), "\\n")
              }} else {{
                cat("FAILED\\n")
              }}
            }}, error = function(e) {{
              cat("ERROR:", conditionMessage(e), "\\n")
            }})
            """
        else:
            # Install latest version with robust strategy
            if force_source:
                # Skip binary installation and go straight to source
                install_script = f"""
                tryCatch({{
                  cat("Force source installation requested for {package_name}\\n")
                  
                  # Install common dependencies first
                  common_deps <- c("Rcpp", "RcppArmadillo", "numDeriv", "zoo", "xts")
                  for (dep in common_deps) {{
                    if (!requireNamespace(dep, quietly = TRUE)) {{
                      cat("Installing dependency:", dep, "\\n")
                      tryCatch({{
                        install.packages(dep, repos="{repo}", type="source", quiet=TRUE)
                      }}, error = function(e) {{
                        cat("Dependency installation error for", dep, ":", e$message, "\\n")
                      }})
                    }}
                  }}
                  
                  # Source installation with compiler flags
                  Sys.setenv(PKG_CPPFLAGS = "-I/opt/homebrew/include -I/usr/local/include")
                  Sys.setenv(PKG_LIBS = "-L/opt/homebrew/lib -L/usr/local/lib")
                  install.packages("{package_name}", repos="{repo}", type="source", quiet=FALSE)
                  
                  if (requireNamespace("{package_name}", quietly = TRUE)) {{
                    cat("SUCCESS\\n")
                    cat("Version:", as.character(packageVersion("{package_name}")), "\\n")
                  }} else {{
                    cat("FAILED\\n")
                  }}
                }}, error = function(e) {{
                  cat("ERROR:", conditionMessage(e), "\\n")
                }})
                """
            else:
                install_script = f"""
                tryCatch({{
                  cat("Attempting installation of {package_name}\\n")
                  
                  # Strategy 1: Try binary installation first (fastest)
                  cat("Step 1: Trying binary installation\\n")
                  tryCatch({{
                    install.packages("{package_name}", repos="{repo}", type="binary", quiet=TRUE)
                  }}, error = function(e) {{
                    if (grepl("type.*binary.*not supported", e$message, ignore.case=TRUE)) {{
                      cat("Binary installation not supported on this platform, skipping to source\\n")
                    }} else {{
                      cat("Binary installation error:", e$message, "\\n")
                    }}
                  }})
                  
                  if (requireNamespace("{package_name}", quietly = TRUE)) {{
                    cat("SUCCESS\\n")
                    cat("Version:", as.character(packageVersion("{package_name}")), "\\n")
                  }} else {{
                cat("Step 2: Binary failed, trying source with dependencies\\n")
                
                # Strategy 2: Install common dependencies first
                common_deps <- c("Rcpp", "RcppArmadillo", "numDeriv", "zoo", "xts")
                for (dep in common_deps) {{
                  if (!requireNamespace(dep, quietly = TRUE)) {{
                    cat("Installing dependency:", dep, "\\n")
                    tryCatch({{
                      install.packages(dep, repos="{repo}", type="binary", quiet=TRUE)
                    }}, error = function(e) {{
                      if (grepl("type.*binary.*not supported", e$message, ignore.case=TRUE)) {{
                        cat("Binary not supported for", dep, ", trying source\\n")
                        install.packages(dep, repos="{repo}", type="source", quiet=TRUE)
                      }} else {{
                        cat("Dependency installation error for", dep, ":", e$message, "\\n")
                      }}
                    }})
                  }}
                }}
                
                # Strategy 3: Source installation with compiler flags
                Sys.setenv(PKG_CPPFLAGS = "-I/opt/homebrew/include -I/usr/local/include")
                Sys.setenv(PKG_LIBS = "-L/opt/homebrew/lib -L/usr/local/lib")
                install.packages("{package_name}", repos="{repo}", type="source", quiet=FALSE)
                
                if (requireNamespace("{package_name}", quietly = TRUE)) {{
                  cat("SUCCESS\\n")
                  cat("Version:", as.character(packageVersion("{package_name}")), "\\n")
                }} else {{
                  cat("Step 3: Trying alternative repository\\n")
                  
                  # Strategy 4: Try R-universe or other repos
                  alt_repos <- c("https://cran.microsoft.com/", "https://cloud.r-project.org/")
                  for (alt_repo in alt_repos) {{
                    tryCatch({{
                      install.packages("{package_name}", repos=alt_repo, type="binary", quiet=TRUE)
                    }}, error = function(e) {{
                      if (grepl("type.*binary.*not supported", e$message, ignore.case=TRUE)) {{
                        cat("Binary not supported, trying source from", alt_repo, "\\n")
                        install.packages("{package_name}", repos=alt_repo, type="source", quiet=TRUE)
                      }}
                    }})
                    if (requireNamespace("{package_name}", quietly = TRUE)) {{
                      cat("SUCCESS\\n")
                      cat("Version:", as.character(packageVersion("{package_name}")), "\\n")
                      break
                    }}
                  }}
                  
                  if (!requireNamespace("{package_name}", quietly = TRUE)) {{
                    cat("FAILED\\n")
                  }}
                }}
              }}
            }}, error = function(e) {{
              cat("ERROR:", conditionMessage(e), "\\n")
            }})
            """
        
        # Execute installation
        install_result = subprocess.run(
            ["Rscript", "-e", install_script],
            capture_output=True,
            text=True,
            timeout=300  # 5 minutes timeout for installation
        )
        
        if "SUCCESS" in install_result.stdout:
            installed_version = ""
            if "Version:" in install_result.stdout:
                installed_version = install_result.stdout.split("Version:")[1].strip()
            
            print(f"✓ Successfully installed R package: {package_name}", file=sys.stderr)
            return {
                "success": True,
                "package": package_name,
                "message": "Package installed successfully",
                "version": installed_version,
                "details": install_result.stdout
            }
        elif "ERROR:" in install_result.stdout:
            error_msg = install_result.stdout.split("ERROR:")[1].strip()
            return {
                "success": False,
                "package": package_name,
                "message": f"Installation failed: {error_msg}",
                "details": install_result.stderr
            }
        else:
            return {
                "success": False,
                "package": package_name,
                "message": "Installation failed for unknown reason",
                "details": f"stdout: {install_result.stdout}, stderr: {install_result.stderr}"
            }
            
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "package": package_name,
            "message": "Installation timed out (5 minutes)",
            "details": "Consider installing manually or checking internet connection"
        }
    except Exception as e:
        return {
            "success": False,
            "package": package_name,
            "message": f"Unexpected error: {str(e)}",
            "details": ""
        }

@mcp.tool
def list_r_packages(
    installed_only: bool = True,
    pattern: str = ""
) -> dict:
    """
    List R packages.
    
    Args:
        installed_only: Only show installed packages (default: True)
        pattern: Filter packages by name pattern (optional)
    
    Returns:
        Dictionary with package list and details
    """
    try:
        if installed_only:
            list_script = f"""
            installed <- as.data.frame(installed.packages())
            if ("{pattern}" != "") {{
              installed <- installed[grepl("{pattern}", installed$Package, ignore.case=TRUE), ]
            }}
            
            if (nrow(installed) > 0) {{
              for(i in 1:nrow(installed)) {{
                cat("PACKAGE:", installed$Package[i], "\\n")
                cat("VERSION:", installed$Version[i], "\\n")
                cat("TITLE:", installed$Title[i], "\\n")
                cat("---\\n")
              }}
            }} else {{
              cat("NO_PACKAGES\\n")
            }}
            """
        else:
            list_script = """
            available <- available.packages()
            cat("AVAILABLE_PACKAGES:", nrow(available), "\\n")
            """
        
        result = subprocess.run(
            ["Rscript", "-e", list_script],
            capture_output=True,
            text=True,
            timeout=30
        )
        
        if "NO_PACKAGES" in result.stdout:
            return {
                "success": True,
                "packages": [],
                "count": 0,
                "message": "No packages found matching criteria"
            }
        
        # Parse package information
        packages = []
        if "PACKAGE:" in result.stdout:
            lines = result.stdout.split("---")
            for chunk in lines:
                if "PACKAGE:" in chunk:
                    package_info = {}
                    for line in chunk.strip().split("\\n"):
                        if "PACKAGE:" in line:
                            package_info["name"] = line.split("PACKAGE:")[1].strip()
                        elif "VERSION:" in line:
                            package_info["version"] = line.split("VERSION:")[1].strip()
                        elif "TITLE:" in line:
                            package_info["title"] = line.split("TITLE:")[1].strip()
                    
                    if package_info.get("name"):
                        packages.append(package_info)
        
        return {
            "success": True,
            "packages": packages,
            "count": len(packages),
            "message": f"Found {len(packages)} packages"
        }
        
    except Exception as e:
        return {
            "success": False,
            "packages": [],
            "count": 0,
            "message": f"Error listing packages: {str(e)}"
        }

if __name__ == "__main__":
    mcp.run()
