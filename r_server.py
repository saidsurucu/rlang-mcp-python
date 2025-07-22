"""
R-Server MCP - Secure Docker-based R execution with caching.

Features:
- Mandatory Docker execution for security
- In-memory result caching
- Async execution support
- Precompiled R script templates
- File management and mounting
"""

import asyncio
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
from functools import lru_cache
from pathlib import Path
from typing import Optional, Literal, Dict, Any

try:
    import docker
except ImportError:
    docker = None
    
from fastmcp import FastMCP

# Create the FastMCP server
mcp = FastMCP("R-Server MCP")

# Global configurations
MOUNTED_DIRECTORY = None
CACHE_SIZE = 100  # Number of cached results
CACHE_TTL = 3600  # Cache time-to-live in seconds

# Performance caches
result_cache: Dict[str, Any] = {}
cache_timestamps: Dict[str, float] = {}


# No session pooling - always use Docker for isolation

# Cache management functions
def get_cache_key(operation: str, params: dict) -> str:
    """Generate a cache key from operation and parameters."""
    cache_data = json.dumps({"op": operation, "params": params}, sort_keys=True)
    return hashlib.md5(cache_data.encode()).hexdigest()

def get_cached_result(cache_key: str) -> Optional[Any]:
    """Get result from cache if valid."""
    if cache_key in result_cache:
        timestamp = cache_timestamps.get(cache_key, 0)
        if time.time() - timestamp < CACHE_TTL:
            return result_cache[cache_key]
        else:
            # Expired, remove from cache
            del result_cache[cache_key]
            del cache_timestamps[cache_key]
    return None

def set_cached_result(cache_key: str, result: Any):
    """Store result in cache."""
    # Implement LRU eviction if cache is full
    if len(result_cache) >= CACHE_SIZE:
        # Remove oldest entry
        oldest_key = min(cache_timestamps.keys(), key=cache_timestamps.get)
        del result_cache[oldest_key]
        del cache_timestamps[oldest_key]
    
    result_cache[cache_key] = result
    cache_timestamps[cache_key] = time.time()

# Docker is mandatory
@lru_cache(maxsize=1)
def check_docker():
    """Check if Docker is installed and running (cached)."""
    if docker is None:
        raise RuntimeError("Docker Python library is not installed. Install with: pip install docker")
    try:
        client = docker.from_env()
        client.ping()
        return True
    except (docker.errors.DockerException, Exception):
        return False

def ensure_docker():
    """Ensure Docker is available or raise an error."""
    if not check_docker():
        error_message = """
❌ Docker is required and must be running!

Please install Docker:
• macOS: Install Docker Desktop from https://docker.com/products/docker-desktop
• Linux: Install Docker Engine: https://docs.docker.com/engine/install/
• Windows: Install Docker Desktop from https://docker.com/products/docker-desktop

After installation:
1. Start Docker Desktop (macOS/Windows) or Docker service (Linux)
2. Pull the R base image: docker pull r-base:latest
3. Restart this MCP server

Docker is required for secure R code execution.
"""
        print(error_message, file=sys.stderr)
        raise RuntimeError("Docker is not installed or not running. Please install Docker to use this MCP server.")

def execute_r_script_docker(r_code: str, timeout: int = 60) -> tuple[str, str, int]:
    """Execute R script in Docker container with mounted directories."""
    if not check_docker():
        return "", "Docker is not available", -1
    
    try:
        client = docker.from_env()
        
        # Create temp directory and script
        with tempfile.TemporaryDirectory() as temp_dir:
            script_path = Path(temp_dir) / "script.R"
            script_path.write_text(r_code)
            
            # Prepare volumes
            volumes = {
                temp_dir: {"bind": "/tmp", "mode": "rw"}
            }
            
            # Add mounted directory if available
            if MOUNTED_DIRECTORY:
                # Mount the user's directory to /data in container
                volumes[str(MOUNTED_DIRECTORY)] = {"bind": "/data", "mode": "ro"}
            
            # Run in container
            result = client.containers.run(
                "r-base:latest",
                f"Rscript /tmp/script.R",
                volumes=volumes,
                working_dir="/data" if MOUNTED_DIRECTORY else "/tmp",
                remove=True,
                stderr=True
            )
            
            output = result.decode('utf-8') if isinstance(result, bytes) else str(result)
            return output, "", 0
            
    except docker.errors.ContainerError as e:
        stderr = e.stderr.decode('utf-8') if e.stderr else str(e)
        return "", stderr, e.exit_status
    except Exception as e:
        return "", str(e), -1


# Precompiled R script templates
R_SCRIPT_TEMPLATES = {
    "ggplot_base": """
library(ggplot2)
library(cowplot)
# Container working directory is already set correctly
{custom_code}
ggsave("{output_path}", width = {width}/{dpi}, height = {height}/{dpi}, dpi = {dpi})
""",
    "execute_base": """
# Container working directory is already set correctly
# Files are available in current directory when mounted
{helper_functions}
{custom_code}
"""
}

def compile_r_script(template: str, **kwargs) -> str:
    """Compile R script from template with parameters."""
    return R_SCRIPT_TEMPLATES[template].format(**kwargs)

# Optimized tools

@mcp.tool
def mount_directory(directory_path: str) -> dict:
    """Mount a directory for R workspace operations."""
    global MOUNTED_DIRECTORY
    
    # Check cache first
    cache_key = get_cache_key("mount_directory", {"path": directory_path})
    cached = get_cached_result(cache_key)
    if cached:
        MOUNTED_DIRECTORY = Path(cached["mounted_path"])
        return cached
    
    try:
        mount_path = Path(directory_path).resolve()
        
        if not mount_path.is_absolute():
            return {"success": False, "message": "Path must be absolute"}
        
        if not mount_path.exists():
            return {"success": False, "message": "Directory does not exist"}
        
        if not mount_path.is_dir():
            return {"success": False, "message": "Path is not a directory"}
        
        MOUNTED_DIRECTORY = mount_path
        workspace_path = mount_path / "r_workspace"
        workspace_path.mkdir(exist_ok=True)
        
        # Quick file listing
        files = list(mount_path.glob("*"))[:5]
        
        result = {
            "success": True,
            "message": "Directory mounted successfully",
            "mounted_path": str(mount_path),
            "workspace_path": str(workspace_path),
            "sample_files": [f.name for f in files],
            "total_files": len(list(mount_path.glob("*")))
        }
        
        set_cached_result(cache_key, result)
        return result
        
    except Exception as e:
        return {"success": False, "message": f"Failed to mount: {str(e)}"}


# Main synchronous tools (FastMCP works better with sync)
@mcp.tool
def render_ggplot(
    code: str,
    output_type: Literal["png", "jpeg", "pdf", "svg"] = "png",
    width: int = 800,
    height: int = 600,
    resolution: int = 96,
    use_cache: bool = True
) -> dict:
    """Render a ggplot2 visualization from R code using Docker."""
    
    # Check cache first
    if use_cache:
        cache_key = get_cache_key("render_ggplot", {
            "code": code,
            "output_type": output_type,
            "width": width,
            "height": height,
            "resolution": resolution
        })
        cached = get_cached_result(cache_key)
        if cached:
            return cached
    
    # Compile script from template
    with tempfile.TemporaryDirectory(prefix="ggplot-") as temp_dir:
        output_path = Path(temp_dir) / f"output.{output_type}"
        
        script = compile_r_script(
            "ggplot_base",
            custom_code=code,
            output_path=output_path,
            width=width,
            height=height,
            dpi=resolution
        )
        
        # Execute with Docker
        stdout, stderr, returncode = execute_r_script_docker(script, 30)
        
        if returncode != 0:
            raise RuntimeError(f"R script failed: {stderr}")
        
        if not output_path.exists():
            raise RuntimeError("Output file not created")
        
        # Read and encode image
        image_data = output_path.read_bytes()
        base64_data = base64.b64encode(image_data).decode('utf-8')
        
        mime_types = {
            "png": "image/png",
            "jpeg": "image/jpeg",
            "pdf": "application/pdf",
            "svg": "image/svg+xml"
        }
        
        result = {
            "type": "image",
            "format": output_type,
            "data": base64_data,
            "mime_type": mime_types[output_type],
            "width": width,
            "height": height,
            "resolution": resolution
        }
        
        if use_cache:
            set_cached_result(cache_key, result)
        
        return result

@mcp.tool
def execute_r_script(
    code: str,
    timeout: int = 60
) -> dict:
    """Execute an R script and return the text output using Docker."""
    
    # Check cache first
    cache_key = get_cache_key("execute_r", {"code": code})
    cached = get_cached_result(cache_key)
    if cached:
        return cached
    
    try:
        # Always use Docker execution
        enhanced_code = compile_r_script(
            "execute_base",
            helper_functions="",
            custom_code=code
        )
        
        stdout, stderr, returncode = execute_r_script_docker(enhanced_code, timeout)
        
        result = {
            "success": returncode == 0,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "summary": f"Execution {'successful' if returncode == 0 else 'failed'}"
        }
        
        set_cached_result(cache_key, result)
        return result
        
    except Exception as e:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": str(e),
            "summary": "Execution failed"
        }

def get_working_directory():
    """Get the current working directory for R operations."""
    return MOUNTED_DIRECTORY if MOUNTED_DIRECTORY else Path.cwd()

# Keep other tools unchanged but add caching where beneficial
@mcp.tool
def list_files(pattern: str = "*", file_type: str = "all") -> dict:
    """List files with caching."""
    cache_key = get_cache_key("list_files", {"pattern": pattern, "type": file_type})
    cached = get_cached_result(cache_key)
    if cached:
        return cached
    
    # Original implementation...
    # (keeping the same logic as before but adding cache at the end)
    from pathlib import Path
    from datetime import datetime
    
    try:
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
        
        unique_files = {}
        for f in all_files:
            unique_files[f["name"]] = f
        
        sorted_files = sorted(unique_files.values(), key=lambda x: x["modified"], reverse=True)
        
        result = {
            "success": True,
            "files": sorted_files,
            "count": len(sorted_files),
            "message": f"Found {len(sorted_files)} files",
            "search_pattern": pattern,
            "file_type_filter": file_type
        }
        
        set_cached_result(cache_key, result)
        return result
        
    except Exception as e:
        return {
            "success": False,
            "files": [],
            "count": 0,
            "message": f"Error: {str(e)}"
        }

# Additional tool implementations

@mcp.tool
def file_info(filename: str) -> dict:
    """Get detailed information about a specific file."""
    import mimetypes
    from datetime import datetime
    
    try:
        base_dir = get_working_directory()
        search_paths = [
            Path(filename) if Path(filename).is_absolute() else None,
            base_dir / filename,
            base_dir / "r_workspace" / filename
        ]
        search_paths = [p for p in search_paths if p]
        
        file_path = None
        for path in search_paths:
            if path.exists() and path.is_file():
                file_path = path
                break
        
        if not file_path:
            return {
                "success": False,
                "filename": filename,
                "message": "File not found"
            }
        
        stat = file_path.stat()
        mime_type, _ = mimetypes.guess_type(str(file_path))
        
        # Docker execution for Excel info
        additional_info = {}
        if file_path.suffix.lower() in ['.xlsx', '.xls']:
            try:
                r_script = f'''
                library(readxl)
                file_path <- "{file_path}"
                sheets <- excel_sheets(file_path)
                cat("SHEETS:", paste(sheets, collapse=","), "\\n")
                '''
                
                stdout, stderr, returncode = execute_r_script_docker(r_script, timeout=10)
                
                if returncode == 0 and "SHEETS:" in stdout:
                    sheets = stdout.split("SHEETS:")[1].split("\\n")[0].strip()
                    additional_info["excel_sheets"] = sheets.split(",") if sheets else []
            except:
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
            "additional_info": additional_info
        }
        
    except Exception as e:
        return {
            "success": False,
            "filename": filename,
            "message": f"Error: {str(e)}"
        }

@mcp.tool
def install_r_package(
    package_name: str,
    version: str = "",
    repo: str = "https://cran.r-project.org"
) -> dict:
    """Install an R package using Docker."""
    if not package_name or not package_name.replace(".", "").replace("_", "").isalnum():
        return {
            "success": False,
            "package": package_name,
            "message": "Invalid package name"
        }
    
    # Install script
    if version:
        install_script = f'''
        if (!requireNamespace("devtools", quietly = TRUE)) {{
          install.packages("devtools", repos="{repo}", quiet=TRUE)
        }}
        devtools::install_version("{package_name}", version = "{version}", repos = "{repo}")
        if (requireNamespace("{package_name}", quietly = TRUE)) {{
          cat("SUCCESS\\n")
          cat("Version:", as.character(packageVersion("{package_name}")), "\\n")
        }} else {{
          cat("FAILED\\n")
        }}
        '''
    else:
        install_script = f'''
        install.packages("{package_name}", repos="{repo}", quiet=FALSE)
        if (requireNamespace("{package_name}", quietly = TRUE)) {{
          cat("SUCCESS\\n")
          cat("Version:", as.character(packageVersion("{package_name}")), "\\n")
        }} else {{
          cat("FAILED\\n")
        }}
        '''
    
    stdout, stderr, returncode = execute_r_script_docker(install_script, timeout=300)
    
    if "SUCCESS" in stdout:
        version = stdout.split("Version:")[1].strip() if "Version:" in stdout else ""
        return {
            "success": True,
            "package": package_name,
            "message": "Package installed successfully",
            "version": version
        }
    else:
        return {
            "success": False,
            "package": package_name,
            "message": "Installation failed",
            "details": stderr
        }

@mcp.tool
def list_r_packages(
    installed_only: bool = True,
    pattern: str = ""
) -> dict:
    """List R packages using Docker."""
    list_script = f'''
    installed <- as.data.frame(installed.packages())
    if ("{pattern}" != "") {{
      installed <- installed[grepl("{pattern}", installed$Package, ignore.case=TRUE), ]
    }}
    
    if (nrow(installed) > 0) {{
      for(i in 1:min(nrow(installed), 50)) {{
        cat(installed$Package[i], "|", installed$Version[i], "\\n")
      }}
    }} else {{
      cat("NO_PACKAGES\\n")
    }}
    '''
    
    stdout, stderr, returncode = execute_r_script_docker(list_script, timeout=30)
    
    if "NO_PACKAGES" in stdout:
        return {"success": True, "packages": [], "count": 0}
    
    packages = []
    for line in stdout.strip().split("\\n"):
        if "|" in line:
            name, version = line.split("|", 1)
            packages.append({"name": name.strip(), "version": version.strip()})
    
    return {
        "success": True,
        "packages": packages,
        "count": len(packages),
        "message": f"Found {len(packages)} packages"
    }

def initialize_server():
    """Initialize the server."""
    print("Initializing R-Server MCP with Docker...", file=sys.stderr)
    
    # Ensure Docker is available
    ensure_docker()
    print("✓ Docker is available and running", file=sys.stderr)
    
    # Pull R base image if needed
    try:
        client = docker.from_env()
        try:
            client.images.get("r-base:latest")
            print("✓ R base image found", file=sys.stderr)
        except docker.errors.ImageNotFound:
            print("Pulling r-base:latest image...", file=sys.stderr)
            client.images.pull("r-base:latest")
            print("✓ R base image pulled", file=sys.stderr)
    except Exception as e:
        print(f"Warning: Could not check/pull R image: {e}", file=sys.stderr)
    
    print("✓ Server ready with Docker execution", file=sys.stderr)

if __name__ == "__main__":
    # Run initialization
    initialize_server()
    
    # Start MCP server
    mcp.run()