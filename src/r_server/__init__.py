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
from typing import Optional, Literal, Dict, Any, Annotated
from pydantic import Field

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

# Persistent R container
R_CONTAINER = None


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

def get_or_create_r_container():
    """Get or create a persistent R container."""
    global R_CONTAINER
    
    if not check_docker():
        raise RuntimeError("Docker is not available")
    
    try:
        client = docker.from_env()
        
        # Check if container exists and is running
        if R_CONTAINER:
            try:
                container = client.containers.get(R_CONTAINER)
                if container.status == 'running':
                    return container
                else:
                    container.remove()
                    R_CONTAINER = None
            except docker.errors.NotFound:
                R_CONTAINER = None
        
        # Create new persistent container
        volumes = {}
        working_dir = "/root"
        
        # Add mounted directory if available
        if MOUNTED_DIRECTORY:
            volumes[str(MOUNTED_DIRECTORY)] = {"bind": "/data", "mode": "ro"}
            working_dir = "/data"
        
        print("Creating persistent R container...", file=sys.stderr)
        
        # Try to use our optimized image first, then fallback to public images
        images_to_try = ["r-server-mcp:latest", "rocker/tidyverse:latest", "r-base:latest"]
        container = None
        
        for image in images_to_try:
            try:
                # Try to pull the image first
                try:
                    client.images.get(image)
                    print(f"✓ Image {image} found locally", file=sys.stderr)
                except docker.errors.ImageNotFound:
                    print(f"Pulling {image}...", file=sys.stderr)
                    client.images.pull(image)
                    print(f"✓ Image {image} pulled successfully", file=sys.stderr)
                
                container = client.containers.run(
                    image,
                    command="tail -f /dev/null",  # Keep container alive
                    volumes=volumes,
                    working_dir=working_dir,
                    detach=True,
                    remove=False
                )
                print(f"✓ Using {image}", file=sys.stderr)
                break
            except docker.errors.ImageNotFound:
                print(f"Image {image} not available, trying next...", file=sys.stderr)
                continue
            except Exception as e:
                print(f"Failed to use {image}: {e}", file=sys.stderr)
                continue
        
        if not container:
            raise RuntimeError("Could not create container with any available image")
        
        # Check what image we're using and install packages accordingly
        image_name = container.image.tags[0] if container.image.tags else "unknown"
        
        if "r-server-mcp" in image_name:
            # Our optimized image - all packages pre-installed
            print("✓ Using r-server-mcp - all packages pre-installed", file=sys.stderr)
            # Just verify packages are available
            verify_script = '''
            cat("Verifying R packages...\\n")
            packages <- c("readxl", "writexl", "dplyr", "tidyr", "ggplot2", "cowplot")
            for(pkg in packages) {
              if(!require(pkg, character.only=TRUE, quietly=TRUE)) {
                stop(paste("Required package", pkg, "not available"))
              }
            }
            cat("All packages verified!\\n")
            '''
            exec_result = container.exec_run(["Rscript", "-e", verify_script])
            if exec_result.exit_code != 0:
                print(f"Warning: Package verification failed: {exec_result.output.decode()}", file=sys.stderr)
        elif "tidyverse" in image_name:
            # rocker/tidyverse already has most packages, just check they're available
            print("✓ Using rocker/tidyverse - most packages pre-installed", file=sys.stderr)
            tidyverse_script = '''
            cat("Checking R packages availability...\\n")
            packages <- c("readxl", "writexl", "dplyr", "tidyr", "ggplot2")
            for(pkg in packages) {
              if(!require(pkg, character.only=TRUE, quietly=TRUE)) {
                cat("Installing missing package:", pkg, "\\n")
                install.packages(pkg, quiet=TRUE)
              }
            }
            cat("All packages ready!\\n")
            '''
            
            # Execute the complete script as one command
            exec_result = container.exec_run(["Rscript", "-e", tidyverse_script])
            if exec_result.exit_code != 0:
                print(f"Warning: Package check failed: {exec_result.output.decode()}", file=sys.stderr)
        else:
            # r-base image needs full package installation
            print("Using r-base - installing packages...", file=sys.stderr)
            # Create a complete R script and execute it as one piece
            full_script = '''
            options(repos = c(CRAN = "https://cloud.r-project.org/"))
            cat("Installing common R packages...\\n")
            
            # Try system packages first (faster)
            system("apt-get update > /dev/null 2>&1", ignore.stderr=TRUE, ignore.stdout=TRUE)
            system("apt-get install -y r-cran-readxl r-cran-dplyr r-cran-tidyr r-cran-ggplot2 > /dev/null 2>&1", ignore.stderr=TRUE, ignore.stdout=TRUE)
            
            # Install remaining packages from CRAN
            packages <- c("readxl", "writexl", "dplyr", "tidyr", "ggplot2", "cowplot")
            for(pkg in packages) {
              if(!require(pkg, character.only=TRUE, quietly=TRUE)) {
                cat("Installing", pkg, "from CRAN...\\n")
                install.packages(pkg, type="binary", quiet=TRUE)
                if(!require(pkg, character.only=TRUE, quietly=TRUE)) {
                  install.packages(pkg, type="source", quiet=TRUE)
                }
              }
            }
            cat("All packages ready!\\n")
            '''
            
            # Execute the complete script as one command
            exec_result = container.exec_run(["Rscript", "-e", full_script])
            if exec_result.exit_code != 0:
                print(f"Warning: Package installation failed: {exec_result.output.decode()}", file=sys.stderr)
        
        print("✓ R packages ready in container", file=sys.stderr)
        
        R_CONTAINER = container.id
        return container
        
    except Exception as e:
        print(f"Error creating R container: {e}", file=sys.stderr)
        raise

def execute_r_script_docker(r_code: str, timeout: int = 60) -> tuple[str, str, int]:
    """Execute R script in persistent Docker container using file approach."""
    try:
        container = get_or_create_r_container()
        
        # Create a temporary R script file in the container
        import uuid
        script_name = f"/tmp/r_script_{uuid.uuid4().hex[:8]}.R"
        
        # Clean up problematic quotes and escape sequences in R code
        # Remove all escape backslashes that are causing quote problems
        cleaned_r_code = r_code
        # Replace escaped quotes with normal quotes
        cleaned_r_code = cleaned_r_code.replace('\\"', '"')
        # Replace escaped newlines with actual newlines
        cleaned_r_code = cleaned_r_code.replace('\\n', '\n')
        # Replace escaped tabs with actual tabs
        cleaned_r_code = cleaned_r_code.replace('\\t', '\t')
        # Handle any other common escape sequences
        cleaned_r_code = cleaned_r_code.replace('\\r', '\r')
        
# Debug messages removed for cleaner output
        
        # Add UTF-8 encoding support to R code
        enhanced_r_code = f"""# Set UTF-8 encoding
Sys.setlocale("LC_ALL", "en_US.UTF-8")
options(encoding = "UTF-8")

{cleaned_r_code}
"""
        
        # Write R code to file using Python's file writing approach
        import tempfile
        import os
        
        # First write to local temp file, then copy to container
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.R', delete=False) as temp_file:
            temp_file.write(enhanced_r_code)
            temp_local_path = temp_file.name
        
        try:
            # Copy file to container using tar archive
            import tarfile
            import io
            
            # Create tar archive in memory
            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode='w') as tar:
                tar.add(temp_local_path, arcname=os.path.basename(script_name))
            tar_stream.seek(0)
            
            # Extract to container
            container.put_archive('/tmp/', tar_stream)
            
        finally:
            # Clean up local temp file
            os.unlink(temp_local_path)
        
        # Execute the R script file with UTF-8 environment
        exec_result = container.exec_run([
            "Rscript", "--encoding=UTF-8", script_name
        ], environment={"LANG": "en_US.UTF-8", "LC_ALL": "en_US.UTF-8"})
        
        # Clean up the temporary file
        container.exec_run(["rm", script_name])
        
        # Decode output with UTF-8
        try:
            output = exec_result.output.decode('utf-8', errors='replace') if exec_result.output else ""
        except Exception:
            # Final fallback
            output = str(exec_result.output) if exec_result.output else ""
        
        return output, "", exec_result.exit_code
        
    except Exception as e:
        return "", str(e), -1

def cleanup_r_container():
    """Clean up the persistent R container."""
    global R_CONTAINER
    
    if R_CONTAINER:
        try:
            client = docker.from_env()
            container = client.containers.get(R_CONTAINER)
            container.remove(force=True)
            print("✓ R container cleaned up", file=sys.stderr)
        except:
            pass
        finally:
            R_CONTAINER = None


# Precompiled R script templates
R_SCRIPT_TEMPLATES = {
    "ggplot_base": """
# Load required packages (already installed in persistent container)
suppressPackageStartupMessages({{
  library(ggplot2)
  library(cowplot)
}})

# Container working directory is already set correctly
{custom_code}

# Save plot to temporary location then copy to output
temp_plot <- "/tmp/temp_plot.{format}"
ggsave(temp_plot, width = {width}/{dpi}, height = {height}/{dpi}, dpi = {dpi})
file.copy(temp_plot, "{output_path}")
""",
    "execute_base": """
# Load common packages (already installed in persistent container)  
suppressPackageStartupMessages({{
  library(readxl)
  library(writexl)
  library(dplyr)
  library(tidyr)
  library(ggplot2)
}})

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

@mcp.tool(
    name="mount_directory",
    description="Mount local directory to access files in R. Use absolute paths like /Users/name/data.",
    annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
)
def mount_directory(
    directory_path: Annotated[str, Field(description="Absolute path to directory containing data files (e.g., /Users/name/Documents/data)")]
) -> dict:
    """Mount local directory to access files in R. Use absolute paths like /Users/name/data."""
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
@mcp.tool(
    name="render_ggplot",
    description="Create ggplot2 visualizations. Pass R code with ggplot commands.",
    annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
)
def render_ggplot(
    code: Annotated[str, Field(description="R code using ggplot2 syntax (e.g., 'ggplot(data) + geom_point(aes(x, y))')")],
    output_type: Annotated[Literal["png", "jpeg", "pdf", "svg"], Field(description="Image format for output")] = "png",
    width: Annotated[int, Field(description="Image width in pixels", ge=100, le=4000)] = 800,
    height: Annotated[int, Field(description="Image height in pixels", ge=100, le=4000)] = 600,
    resolution: Annotated[int, Field(description="DPI resolution for image quality", ge=50, le=300)] = 96,
    use_cache: Annotated[bool, Field(description="Use cached results for identical plots")] = True
) -> dict:
    """Create ggplot2 visualizations. Pass R code with ggplot commands."""
    
    # Check if container is ready
    global R_CONTAINER
    if not R_CONTAINER:
        return {
            "success": False,
            "message": "R container not initialized. Please run initialize_r_container first."
        }
    
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
            format=output_type,
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

@mcp.tool(
    name="execute_r_script",
    description="Run R code and get text output. Use for data analysis, calculations, file operations.",
    annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
)
def execute_r_script(
    code: Annotated[str, Field(description="R code to execute (can read Excel files, do statistics, data manipulation)")],
    timeout: Annotated[int, Field(description="Maximum execution time in seconds", ge=10, le=300)] = 60
) -> dict:
    """Run R code and get text output. Use for data analysis, calculations, file operations."""
    
    # Check if container is ready
    global R_CONTAINER
    if not R_CONTAINER:
        return {
            "success": False,
            "returncode": -1,
            "stdout": "",
            "stderr": "R container not initialized. Please run initialize_r_container first.",
            "summary": "Container not ready"
        }
    
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
@mcp.tool(
    name="list_files",
    description="List files in workspace. Use file_type: excel, csv, text, or all.",
    annotations={"readOnlyHint": True, "openWorldHint": False}
)
def list_files(
    pattern: Annotated[str, Field(description="File name pattern to match (e.g., '*.xlsx', 'data*', '*')")] = "*",
    file_type: Annotated[Literal["excel", "csv", "text", "all"], Field(description="Filter by file type")] = "all"
) -> dict:
    """List files in workspace. Use file_type: excel, csv, text, or all."""
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

# Docker container management tool
@mcp.tool(
    name="initialize_r_container", 
    description="Start R container with packages. Automatically builds optimized image if needed.",
    annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
)
def initialize_r_container() -> dict:
    """Start R container with packages. Automatically builds optimized image if needed."""
    global R_CONTAINER
    
    try:
        ensure_docker()
        client = docker.from_env()
        
        # Clean up any existing container first
        if R_CONTAINER:
            try:
                container = client.containers.get(R_CONTAINER)
                container.remove(force=True)
                print("✓ Cleaned up existing container", file=sys.stderr)
            except:
                pass
            finally:
                R_CONTAINER = None
        
        # Check if our optimized image exists, if not build it
        try:
            client.images.get("r-server-mcp:latest")
            print("✓ Optimized R image found", file=sys.stderr)
        except docker.errors.ImageNotFound:
            print("🔨 Optimized image not found, building...", file=sys.stderr)
            
            # Load Dockerfile from package data
            try:
                import importlib.resources as pkg_resources
                dockerfile_content = pkg_resources.files('r_server').joinpath('Dockerfile.r-server').read_text()
            except ImportError:
                # Fallback for older Python versions
                import pkg_resources
                dockerfile_content = pkg_resources.resource_string('r_server', 'Dockerfile.r-server').decode('utf-8')
            except Exception:
                # Embedded fallback if package data not available
                dockerfile_content = '''# R Server MCP - Optimized Docker Image
FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive
ENV TZ=UTC
ENV LANG=en_US.UTF-8
ENV LC_ALL=en_US.UTF-8

# Install system dependencies and R packages in one layer
RUN apt-get update && apt-get install -y \\
    locales \\
    r-base \\
    r-base-dev \\
    r-cran-readxl \\
    r-cran-writexl \\
    r-cran-dplyr \\
    r-cran-tidyr \\
    r-cran-ggplot2 \\
    r-cran-cowplot \\
    libcurl4-openssl-dev \\
    libssl-dev \\
    libxml2-dev \\
    libfontconfig1-dev \\
    libcairo2-dev \\
    && rm -rf /var/lib/apt/lists/*

# Set up UTF-8 locale
RUN locale-gen en_US.UTF-8

# Set CRAN repository
RUN echo 'options(repos = c(CRAN = "https://cloud.r-project.org/"))' >> /usr/lib/R/etc/Rprofile.site

WORKDIR /workspace
CMD ["tail", "-f", "/dev/null"]
'''
            
            # Build image
            import io
            dockerfile_obj = io.BytesIO(dockerfile_content.encode('utf-8'))
            
            print("📦 Building optimized image (may take 2-3 minutes)...", file=sys.stderr)
            
            # Build with progress
            for log in client.api.build(fileobj=dockerfile_obj, tag="r-server-mcp:latest", rm=True, decode=True):
                if 'stream' in log and log['stream'].strip():
                    print(f"Build: {log['stream'].strip()}", file=sys.stderr)
            
            print("✅ Optimized R image built successfully", file=sys.stderr)
        
        # Now create container with priority to our optimized image
        images_to_try = ["r-server-mcp:latest", "rocker/tidyverse:latest", "r-base:latest"]
        container = None
        
        for image in images_to_try:
            try:
                print(f"Trying to create container with {image}...", file=sys.stderr)
                
                # Setup volumes
                volumes = {}
                working_dir = "/workspace"
                if MOUNTED_DIRECTORY:
                    volumes[str(MOUNTED_DIRECTORY)] = {"bind": "/data", "mode": "ro"}
                    working_dir = "/data"
                
                container = client.containers.run(
                    image,
                    command="tail -f /dev/null",
                    volumes=volumes,
                    working_dir=working_dir,
                    detach=True,
                    remove=False
                )
                print(f"✅ Container created with {image}", file=sys.stderr)
                break
                
            except Exception as e:
                print(f"Failed to use {image}: {str(e)}", file=sys.stderr)
                continue
        
        if not container:
            raise RuntimeError("Could not create container with any available image")
        
        # Quick package verification for our optimized image
        if "r-server-mcp" in str(container.image.tags):
            print("🔍 Verifying packages in optimized image...", file=sys.stderr)
            verify_result = container.exec_run([
                "Rscript", "-e", 
                "packages <- c('readxl', 'writexl', 'dplyr', 'tidyr', 'ggplot2'); for(pkg in packages) { if(!require(pkg, character.only=TRUE, quietly=TRUE)) stop(paste('Missing:', pkg)) }; cat('✅ All packages verified!\\n')"
            ])
            if verify_result.exit_code == 0:
                print("✅ All packages verified and ready", file=sys.stderr)
        
        R_CONTAINER = container.id
        
        return {
            "success": True,
            "container_id": container.id[:12],
            "image_used": str(container.image.tags[0]) if container.image.tags else "unknown",
            "message": "R container initialized successfully with optimized image",
            "status": "ready"
        }
        
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "message": "Failed to initialize R container",
            "status": "failed"
        }

@mcp.tool(
    name="container_status",
    description="Check if R container is running and ready for use.",
    annotations={"readOnlyHint": True, "openWorldHint": False}
)
def container_status() -> dict:
    """Check if R container is running and ready for use."""
    global R_CONTAINER
    
    if not R_CONTAINER:
        return {
            "status": "not_initialized",
            "message": "No R container is currently running",
            "container_id": None
        }
    
    try:
        client = docker.from_env()
        container = client.containers.get(R_CONTAINER)
        
        return {
            "status": container.status,
            "container_id": container.id[:12],
            "image": container.image.tags[0] if container.image.tags else "unknown",
            "message": f"Container is {container.status}",
            "uptime": container.attrs.get("State", {}).get("StartedAt", "unknown")
        }
        
    except docker.errors.NotFound:
        R_CONTAINER = None
        return {
            "status": "not_found",
            "message": "Container was removed externally",
            "container_id": None
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error checking container: {str(e)}",
            "container_id": R_CONTAINER[:12] if R_CONTAINER else None
        }

# Additional tool implementations

@mcp.tool(
    name="file_info",
    description="Get file details including size, type, and Excel sheet names if applicable.",
    annotations={"readOnlyHint": True, "openWorldHint": False}
)
def file_info(
    filename: Annotated[str, Field(description="Name of file to inspect (e.g., 'data.xlsx', 'report.csv')")] 
) -> dict:
    """Get file details including size, type, and Excel sheet names if applicable."""
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
            # Check if container is ready for Excel analysis
            global R_CONTAINER
            if not R_CONTAINER:
                additional_info["excel_info"] = "R container not initialized - run initialize_r_container for Excel analysis"
            else:
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

@mcp.tool(
    name="install_r_package",
    description="Install R package. Common packages (readxl, ggplot2, dplyr) already included.",
    annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
)
def install_r_package(
    package_name: Annotated[str, Field(description="Name of R package to install (e.g., 'forecast', 'randomForest')")],
    version: Annotated[str, Field(description="Specific version to install (optional)")] = "",
    repo: Annotated[str, Field(description="CRAN repository URL")] = "https://cran.r-project.org"
) -> dict:
    """Install R package. Common packages (readxl, ggplot2, dplyr) already included."""
    
    # Check if container is ready
    global R_CONTAINER
    if not R_CONTAINER:
        return {
            "success": False,
            "package": package_name,
            "message": "R container not initialized. Please run initialize_r_container first."
        }
    
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

@mcp.tool(
    name="list_r_packages",
    description="List installed R packages. Use pattern to filter by name.",
    annotations={"readOnlyHint": True, "openWorldHint": False}
)
def list_r_packages(
    installed_only: Annotated[bool, Field(description="Show only installed packages")] = True,
    pattern: Annotated[str, Field(description="Filter packages by name pattern (e.g., 'ggplot', 'data')")] = ""
) -> dict:
    """List installed R packages. Use pattern to filter by name."""
    
    # Check if container is ready
    global R_CONTAINER
    if not R_CONTAINER:
        return {
            "success": False,
            "packages": [],
            "count": 0,
            "message": "R container not initialized. Please run initialize_r_container first."
        }
    
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

# Export mcp for external use
__all__ = ["mcp"]

def main():
    """Main entry point for the MCP server."""
    import atexit
    
    # Register cleanup function
    atexit.register(cleanup_r_container)
    
    try:
        # Run initialization
        initialize_server()
        
        # Start MCP server
        mcp.run()
    except KeyboardInterrupt:
        print("\nShutting down server...", file=sys.stderr)
        cleanup_r_container()
    except Exception as e:
        print(f"Server error: {e}", file=sys.stderr)
        cleanup_r_container()
        raise

if __name__ == "__main__":
    main()