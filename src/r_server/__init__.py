"""
R-Server MCP - Secure Docker-based R execution with caching.

Features:
- Mandatory Docker execution for security
- In-memory result caching with configurable TTL
- Multiple directory mounting
- Inline plot return (base64 PNG/SVG)
- Session persistence (R workspace .RData)
- Auto library detection and installation
- Container resource limits and healthcheck
- Enhanced error messages with line numbers
"""

import asyncio
import base64
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import uuid
import io
import tarfile
from functools import lru_cache
from pathlib import Path
from typing import Optional, Literal, Dict, Any, List, Annotated
from pydantic import Field

try:
    import docker
except ImportError:
    docker = None

from fastmcp import FastMCP

# Create the FastMCP server
mcp = FastMCP("R-Server MCP")

# ─── Global Configuration ───────────────────────────────────────────────────

# Multiple mounted directories: {host_path: container_mount_point}
MOUNTED_DIRECTORIES: Dict[str, str] = {}

# Cache configuration
CACHE_SIZE = 100
CACHE_TTL = 3600  # seconds, configurable via environment
try:
    CACHE_TTL = int(os.environ.get("R_MCP_CACHE_TTL", "3600"))
    CACHE_SIZE = int(os.environ.get("R_MCP_CACHE_SIZE", "100"))
except ValueError:
    pass

# Container resource limits (configurable via environment)
CONTAINER_MEM_LIMIT = os.environ.get("R_MCP_MEM_LIMIT", "2g")
CONTAINER_CPU_QUOTA = int(os.environ.get("R_MCP_CPU_QUOTA", "200000"))  # 2 CPUs
CONTAINER_NETWORK_DISABLED = os.environ.get("R_MCP_NETWORK_DISABLED", "true").lower() == "true"

# Session persistence
SESSION_ENABLED = os.environ.get("R_MCP_SESSION", "true").lower() == "true"
SESSION_WORKSPACE_PATH = "/tmp/.r_mcp_workspace.RData"

# PII Protection
PII_ENABLED = os.environ.get("R_MCP_PII_ENABLED", "false").lower() == "true"

# Performance caches
result_cache: Dict[str, Any] = {}
cache_timestamps: Dict[str, float] = {}

# Persistent R container
R_CONTAINER = None


# ─── PII Redaction ──────────────────────────────────────────────────────────

# Medical/statistical terms whitelist to reduce false positives from NER
_PII_WHITELIST = {
    # Turkish statistical terms
    "ortalama", "medyan", "standart", "sapma", "varyans", "korelasyon",
    "regresyon", "anlamlı", "güven", "aralığı", "örneklem", "popülasyon",
    "frekans", "dağılım", "histogram", "percentil", "kartil", "çeyrek",
    "minimum", "maksimum", "toplam", "sayı", "oran", "yüzde",
    # Medical terms commonly misidentified as names
    "hastane", "hastanesi", "üniversitesi", "fakültesi", "bölümü",
    "kliniği", "polikliniği", "servisi", "laboratuvarı", "merkezi",
    "eğitim", "araştırma", "devlet", "şehir", "özel", "vakıf",
    "dahiliye", "kardiyoloji", "nöroloji", "ortopedi", "pediatri",
    "onkoloji", "dermatoloji", "üroloji", "göğüs", "beyin", "cerrahi",
    # Common R output terms
    "true", "false", "null", "inf", "nan", "none",
    "min", "max", "mean", "median", "summary", "table",
}

# Regex patterns for Turkish PII
_PII_PATTERNS = {
    "TR_TC_KIMLIK": r'\b[1-9]\d{10}\b',
    "TR_PHONE": r'(?:\+90[\s.-]?\d{3}[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}|\b0[25]\d{2}[\s.-]?\d{3}[\s.-]?\d{2}[\s.-]?\d{2}\b|\b0[25]\d{2}[\s.-]?\d{3}[\s.-]?\d{4}\b)',
    "EMAIL": r'\b[\w.-]+@[\w.-]+\.\w{2,}\b',
    "TR_IBAN": r'\bTR\d{2}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{4}\s?\d{2}\b',
    "CREDIT_CARD": r'\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b',
    "TR_HASTA_NO": r'(?:Hasta\s*(?:No|Numarası|ID|no))\s*[:\s]\s*[\w-]+',
}

# Lazy-loaded PII engine
_pii_engine = None

def _get_pii_engine():
    """Lazy-load PII engine. Returns (analyzer, anonymizer, nlp_ner) or None."""
    global _pii_engine
    if _pii_engine is not None:
        return _pii_engine

    try:
        from presidio_analyzer import AnalyzerEngine, PatternRecognizer, Pattern, RecognizerRegistry
        from presidio_analyzer.nlp_engine import NlpEngineProvider
        from presidio_anonymizer import AnonymizerEngine
        import spacy

        # Registry with Turkish regex recognizers
        registry = RecognizerRegistry(supported_languages=["tr"])
        for entity_name, pattern_str in _PII_PATTERNS.items():
            recognizer = PatternRecognizer(
                supported_entity=entity_name,
                supported_language="tr",
                patterns=[Pattern(entity_name.lower(), pattern_str, 0.9)],
            )
            registry.add_recognizer(recognizer)

        # NLP engine with blank Turkish tokenizer
        model_dir = os.path.join(tempfile.gettempdir(), "spacy_blank_tr")
        if not os.path.exists(model_dir):
            spacy.blank("tr").to_disk(model_dir)

        provider = NlpEngineProvider(nlp_configuration={
            "nlp_engine_name": "spacy",
            "models": [{"lang_code": "tr", "model_name": model_dir}],
        })
        nlp_engine = provider.create_engine()

        analyzer = AnalyzerEngine(
            registry=registry,
            nlp_engine=nlp_engine,
            supported_languages=["tr"],
        )
        anonymizer = AnonymizerEngine()

        # Try to load multilingual NER for name detection
        nlp_ner = None
        try:
            nlp_ner = spacy.load("xx_ent_wiki_sm")
            print("✓ PII: Multilingual NER loaded (name detection active)", file=sys.stderr)
        except OSError:
            print("⚠️ PII: xx_ent_wiki_sm not found, name detection disabled. Install with:", file=sys.stderr)
            print("  uv pip install https://github.com/explosion/spacy-models/releases/download/xx_ent_wiki_sm-3.8.0/xx_ent_wiki_sm-3.8.0-py3-none-any.whl", file=sys.stderr)

        _pii_engine = (analyzer, anonymizer, nlp_ner)
        print("✓ PII protection engine loaded", file=sys.stderr)
        return _pii_engine

    except ImportError:
        print("⚠️ PII protection not available. Install with: uv pip install 'rlang-mcp-server[privacy]'", file=sys.stderr)
        _pii_engine = False  # Mark as attempted but unavailable
        return None


def _is_whitelisted(text: str) -> bool:
    """Check if text is a whitelisted medical/statistical term."""
    lower = text.lower().strip()
    # Check exact match
    if lower in _PII_WHITELIST:
        return True
    # Check if all words are whitelisted
    words = lower.split()
    if all(w in _PII_WHITELIST for w in words):
        return True
    return False


def sanitize_pii(text: str) -> tuple[str, List[dict]]:
    """
    Sanitize PII from text. Returns (sanitized_text, detections).
    Uses Presidio regex + optional NER for name detection.
    Falls back to regex-only if Presidio not installed.
    """
    if not text or not text.strip():
        return text, []

    detections = []
    engine = _get_pii_engine()

    if engine and engine is not False:
        analyzer, anonymizer, nlp_ner = engine

        # Step 1: Presidio regex-based detection
        results = analyzer.analyze(text=text, language="tr")

        # Step 2: NER-based name detection (if available)
        if nlp_ner:
            doc = nlp_ner(text)
            for ent in doc.ents:
                if ent.label_ == "PER" and not _is_whitelisted(ent.text):
                    # Add as a custom result for anonymization
                    from presidio_analyzer import RecognizerResult
                    results.append(RecognizerResult(
                        entity_type="PERSON",
                        start=ent.start_char,
                        end=ent.end_char,
                        score=0.75,
                    ))

        if results:
            # Record detections
            for r in results:
                detections.append({
                    "type": r.entity_type,
                    "score": round(r.score, 2),
                })

            # Anonymize
            anon = anonymizer.anonymize(text=text, analyzer_results=results)
            return anon.text, detections

    elif engine is False:
        # Presidio not installed — use pure regex fallback
        sanitized = text
        for entity_name, pattern_str in _PII_PATTERNS.items():
            matches = list(re.finditer(pattern_str, sanitized))
            for match in reversed(matches):  # Reverse to preserve indices
                detections.append({"type": entity_name, "score": 0.9})
                sanitized = sanitized[:match.start()] + f"<{entity_name}>" + sanitized[match.end():]
        if detections:
            return sanitized, detections

    return text, []


# ─── Cache Management ───────────────────────────────────────────────────────

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
            del result_cache[cache_key]
            del cache_timestamps[cache_key]
    return None

def set_cached_result(cache_key: str, result: Any):
    """Store result in cache with LRU eviction."""
    if len(result_cache) >= CACHE_SIZE:
        oldest_key = min(cache_timestamps.keys(), key=cache_timestamps.get)
        del result_cache[oldest_key]
        del cache_timestamps[oldest_key]
    result_cache[cache_key] = result
    cache_timestamps[cache_key] = time.time()


# ─── Docker Management ──────────────────────────────────────────────────────

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


# ─── Network Control ────────────────────────────────────────────────────────

def _set_container_network(container, enable: bool):
    """Connect or disconnect container from the default bridge network."""
    try:
        client = docker.from_env()
        network = client.networks.get("bridge")
        if enable:
            try:
                network.connect(container)
                print("🔓 Network temporarily enabled for package installation", file=sys.stderr)
            except docker.errors.APIError:
                pass  # Already connected
        else:
            try:
                network.disconnect(container)
                print("🔒 Network disabled after package installation", file=sys.stderr)
            except docker.errors.APIError:
                pass  # Already disconnected
    except Exception as e:
        print(f"⚠️ Network control failed: {e}", file=sys.stderr)


# ─── Library Auto-Detection ─────────────────────────────────────────────────

def detect_libraries(r_code: str) -> List[str]:
    """Parse R code to detect library() and require() calls."""
    patterns = [
        r'library\s*\(\s*["\']?(\w+)["\']?\s*\)',
        r'require\s*\(\s*["\']?(\w+)["\']?\s*\)',
        r'library\s*\(\s*["\']?(\w+)["\']?\s*,',
        r'require\s*\(\s*["\']?(\w+)["\']?\s*,',
    ]
    libraries = set()
    for pattern in patterns:
        libraries.update(re.findall(pattern, r_code))
    return list(libraries)


def auto_install_libraries(container, libraries: List[str]) -> List[str]:
    """Check and install missing libraries. Returns list of newly installed packages."""
    if not libraries:
        return []

    # Check which packages are already installed
    pkg_list = ', '.join(f'"{pkg}"' for pkg in libraries)
    check_script = f'''
    packages <- c({pkg_list})
    missing <- packages[!sapply(packages, requireNamespace, quietly=TRUE)]
    if(length(missing) > 0) cat(paste(missing, collapse=","))
    '''
    result = container.exec_run(["Rscript", "-e", check_script])
    output = result.output.decode('utf-8', errors='replace').strip()

    if not output:
        return []

    missing = [p.strip() for p in output.split(",") if p.strip()]
    if not missing:
        return []

    # Temporarily enable network for installation if it's disabled
    network_was_disabled = CONTAINER_NETWORK_DISABLED
    if network_was_disabled:
        _set_container_network(container, enable=True)

    installed = []
    try:
        for pkg in missing:
            print(f"📦 Auto-installing missing R package: {pkg}", file=sys.stderr)
            install_script = f'''
            options(repos = c(CRAN = "https://cloud.r-project.org/"))
            tryCatch({{
                install.packages("{pkg}", quiet=TRUE, dependencies=TRUE)
                if(requireNamespace("{pkg}", quietly=TRUE)) cat("OK")
                else cat("FAIL")
            }}, error = function(e) cat("FAIL"))
            '''
            res = container.exec_run(["Rscript", "-e", install_script], environment={
                "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"
            })
            res_output = res.output.decode('utf-8', errors='replace').strip()
            if "OK" in res_output:
                installed.append(pkg)
                print(f"  ✓ {pkg} installed", file=sys.stderr)
            else:
                print(f"  ✗ {pkg} installation failed", file=sys.stderr)
    finally:
        # Re-disable network after installation
        if network_was_disabled:
            _set_container_network(container, enable=False)

    return installed


# ─── Plot Detection & Base64 ────────────────────────────────────────────────

def detect_plot_commands(r_code: str) -> bool:
    """Detect if R code contains plotting commands."""
    plot_patterns = [
        r'\bggplot\s*\(',
        r'\bplot\s*\(',
        r'\bbarplot\s*\(',
        r'\bhist\s*\(',
        r'\bboxplot\s*\(',
        r'\bpairs\s*\(',
        r'\bimage\s*\(',
        r'\bcontour\s*\(',
        r'\bheatmap\s*\(',
        r'\bpie\s*\(',
        r'\bgeom_',
        r'\bggsave\s*\(',
        r'\bprint\s*\(\s*p\s*\)',
    ]
    for pattern in plot_patterns:
        if re.search(pattern, r_code):
            return True
    return False


def wrap_plot_capture(r_code: str) -> str:
    """Wrap R code to capture plot output as PNG file."""
    plot_path = "/tmp/.r_mcp_plot.png"
    return f'''
# Auto-capture plot output
.r_mcp_plot_path <- "{plot_path}"
png(.r_mcp_plot_path, width=1200, height=800, res=150)
tryCatch({{
{r_code}
}}, finally = {{
    dev_status <- tryCatch(dev.off(), error = function(e) NULL)
}})

# Check if plot was actually created
if(file.exists(.r_mcp_plot_path) && file.info(.r_mcp_plot_path)$size > 0) {{
    cat("__R_MCP_PLOT_SAVED__\\n")
}} else {{
    cat("__R_MCP_NO_PLOT__\\n")
}}
'''


def extract_plot_base64(container, plot_path: str = "/tmp/.r_mcp_plot.png") -> Optional[str]:
    """Extract plot from container as base64 encoded PNG."""
    try:
        bits, stat = container.get_archive(plot_path)
        # Read tar archive
        data = b"".join(bits)
        tar = tarfile.open(fileobj=io.BytesIO(data))
        member = tar.getmembers()[0]
        f = tar.extractfile(member)
        if f:
            png_data = f.read()
            return base64.b64encode(png_data).decode('utf-8')
    except Exception:
        pass
    return None


# ─── Error Enhancement ──────────────────────────────────────────────────────

def wrap_error_handling(r_code: str) -> str:
    """Wrap R code with enhanced error handling that includes line numbers."""
    return f'''
.r_mcp_result <- tryCatch(
    withCallingHandlers({{
{r_code}
    }},
    warning = function(w) {{
        msg <- conditionMessage(w)
        call_str <- deparse(conditionCall(w))
        cat(paste0("⚠️ Warning: ", msg, " [in: ", call_str, "]\\n"), file=stderr())
        invokeRestart("muffleWarning")
    }}),
    error = function(e) {{
        msg <- conditionMessage(e)
        call_str <- if(!is.null(conditionCall(e))) deparse(conditionCall(e)) else "unknown"

        # Try to extract line info from traceback
        tb <- traceback(3)
        line_info <- ""
        if(!is.null(tb) && length(tb) > 0) {{
            line_info <- paste("\\n  Traceback:", paste(sapply(tb, function(x) paste(x, collapse="")), collapse="\\n    "))
        }}

        cat(paste0("\\n❌ R Error: ", msg, "\\n  In call: ", call_str, line_info, "\\n"), file=stderr())
        invisible(NULL)
    }}
)
'''


# ─── Container Management ───────────────────────────────────────────────────

def get_or_create_r_container():
    """Get or create a persistent R container with resource limits."""
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

        # Build volumes from all mounted directories
        volumes = {}
        working_dir = "/root"

        if MOUNTED_DIRECTORIES:
            for host_path, container_path in MOUNTED_DIRECTORIES.items():
                volumes[host_path] = {"bind": container_path, "mode": "rw"}
            # Use first mounted directory as working dir
            working_dir = list(MOUNTED_DIRECTORIES.values())[0]

        print("Creating persistent R container...", file=sys.stderr)

        images_to_try = ["semoss/docker-r-packages:latest", "rocker/tidyverse:latest", "r-base:latest"]
        container = None

        for image in images_to_try:
            try:
                try:
                    client.images.get(image)
                    print(f"✓ Image {image} found locally", file=sys.stderr)
                except docker.errors.ImageNotFound:
                    print(f"Pulling {image}...", file=sys.stderr)
                    client.images.pull(image)
                    print(f"✓ Image {image} pulled successfully", file=sys.stderr)

                # Container creation with resource limits
                run_kwargs = dict(
                    image=image,
                    command="tail -f /dev/null",
                    volumes=volumes,
                    working_dir=working_dir,
                    environment={
                        "LANG": "C.UTF-8",
                        "LC_ALL": "C.UTF-8",
                        "DEBIAN_FRONTEND": "noninteractive"
                    },
                    detach=True,
                    remove=False,
                    mem_limit=CONTAINER_MEM_LIMIT,
                    cpu_quota=CONTAINER_CPU_QUOTA,
                )

                # Always create container with network enabled for initial setup
                # Network will be disabled after setup if CONTAINER_NETWORK_DISABLED
                container = client.containers.run(**run_kwargs)
                print(f"✓ Using {image} (mem: {CONTAINER_MEM_LIMIT}, cpu_quota: {CONTAINER_CPU_QUOTA})", file=sys.stderr)
                break
            except docker.errors.ImageNotFound:
                print(f"Image {image} not available, trying next...", file=sys.stderr)
                continue
            except Exception as e:
                print(f"Failed to use {image}: {e}", file=sys.stderr)
                continue

        if not container:
            raise RuntimeError("Could not create container with any available image")

        # Install locale support (requires network for apt-get)
        print("Setting up UTF-8 locale support...", file=sys.stderr)
        locale_setup = container.exec_run([
            "sh", "-c",
            "apt-get update -qq && apt-get install -y --no-install-recommends locales && "
            "locale-gen en_US.UTF-8 C.UTF-8 && "
            "echo 'LANG=en_US.UTF-8' > /etc/default/locale && "
            "echo 'LC_ALL=en_US.UTF-8' >> /etc/default/locale"
        ])
        if locale_setup.exit_code == 0:
            print("✓ UTF-8 locale support installed", file=sys.stderr)
        else:
            print("⚠️ Could not install full locale support", file=sys.stderr)

        # Install packages based on image type (requires network)
        image_name = container.image.tags[0] if container.image.tags else "unknown"
        _setup_packages(container, image_name)

        # Disable network AFTER setup is complete
        if CONTAINER_NETWORK_DISABLED:
            _set_container_network(container, enable=False)
            print("🔒 Network disabled (secure mode)", file=sys.stderr)

        # Warm up R session: pre-load common libraries
        print("🔥 Warming up R session...", file=sys.stderr)
        warmup_script = '''
        suppressPackageStartupMessages({
            for(pkg in c("readxl", "writexl", "dplyr", "tidyr", "ggplot2")) {
                tryCatch(library(pkg, character.only=TRUE), error=function(e) NULL)
            }
        })
        cat("R session warm-up complete\\n")
        '''
        container.exec_run(["Rscript", "-e", warmup_script], environment={
            "LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"
        })
        print("✓ R session warmed up", file=sys.stderr)

        R_CONTAINER = container.id
        return container

    except Exception as e:
        print(f"Error creating R container: {e}", file=sys.stderr)
        raise


def _setup_packages(container, image_name: str):
    """Install/verify R packages based on the Docker image type."""
    if "semoss/docker-r-packages" in image_name:
        print("✓ Using semoss/docker-r-packages - comprehensive packages pre-installed", file=sys.stderr)
    elif "r-server-mcp" in image_name:
        print("✓ Using r-server-mcp - all packages pre-installed", file=sys.stderr)
        verify_script = '''
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
        print("✓ Using rocker/tidyverse - most packages pre-installed", file=sys.stderr)
        tidyverse_script = '''
        packages <- c("readxl", "writexl", "dplyr", "tidyr", "ggplot2")
        for(pkg in packages) {
          if(!require(pkg, character.only=TRUE, quietly=TRUE)) {
            cat("Installing missing package:", pkg, "\\n")
            install.packages(pkg, quiet=TRUE)
          }
        }
        cat("All packages ready!\\n")
        '''
        exec_result = container.exec_run(["Rscript", "-e", tidyverse_script])
        if exec_result.exit_code != 0:
            print(f"Warning: Package check failed: {exec_result.output.decode()}", file=sys.stderr)
    else:
        print("Using r-base - installing packages...", file=sys.stderr)
        full_script = '''
        options(repos = c(CRAN = "https://cloud.r-project.org/"))
        cat("Installing common R packages...\\n")
        system("apt-get update > /dev/null 2>&1", ignore.stderr=TRUE, ignore.stdout=TRUE)
        system("apt-get install -y r-cran-readxl r-cran-dplyr r-cran-tidyr r-cran-ggplot2 > /dev/null 2>&1", ignore.stderr=TRUE, ignore.stdout=TRUE)
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
        exec_result = container.exec_run(["Rscript", "-e", full_script])
        if exec_result.exit_code != 0:
            print(f"Warning: Package installation failed: {exec_result.output.decode()}", file=sys.stderr)

    print("✓ R packages ready in container", file=sys.stderr)


# ─── R Script Execution ─────────────────────────────────────────────────────

def execute_r_script_docker(r_code: str, timeout: int = 60) -> tuple[str, str, int]:
    """Execute R script in persistent Docker container."""
    try:
        global R_CONTAINER
        if R_CONTAINER:
            try:
                client = docker.from_env()
                existing_container = client.containers.get(R_CONTAINER)
                existing_container.reload()
                if existing_container.status != 'running':
                    print(f"Container {R_CONTAINER} is {existing_container.status}, recreating...", file=sys.stderr)
                    R_CONTAINER = None
            except docker.errors.NotFound:
                print(f"Container {R_CONTAINER} not found, recreating...", file=sys.stderr)
                R_CONTAINER = None
            except Exception as e:
                print(f"Container check failed: {e}, recreating...", file=sys.stderr)
                R_CONTAINER = None

        container = get_or_create_r_container()
        if not container:
            return "", "Failed to get or create R container", -1

        script_name = f"/tmp/r_script_{uuid.uuid4().hex[:8]}.R"

        # Clean up escape sequences
        cleaned_r_code = r_code
        cleaned_r_code = cleaned_r_code.replace('\\"', '"')
        cleaned_r_code = cleaned_r_code.replace('\\n', '\n')
        cleaned_r_code = cleaned_r_code.replace('\\t', '\t')
        cleaned_r_code = cleaned_r_code.replace('\\r', '\r')

        # Build path info for mounted directories
        path_info = ""
        if MOUNTED_DIRECTORIES:
            path_info = "# MOUNTED DIRECTORIES:\n"
            for host_path, container_path in MOUNTED_DIRECTORIES.items():
                path_info += f"# Host: {host_path} → Container: {container_path}\n"
            path_info += "\n"

        # Session: load workspace if enabled
        session_load = ""
        session_save = ""
        if SESSION_ENABLED:
            session_load = f'''
# Load previous session workspace if available
if(file.exists("{SESSION_WORKSPACE_PATH}")) {{
    tryCatch(
        load("{SESSION_WORKSPACE_PATH}"),
        error = function(e) NULL
    )
}}
'''
            session_save = f'''
# Save session workspace for persistence
tryCatch(
    save.image(file="{SESSION_WORKSPACE_PATH}"),
    error = function(e) NULL
)
'''

        enhanced_r_code = f"""# Set UTF-8 encoding
suppressWarnings(suppressMessages({{
    Sys.setlocale("LC_ALL", "C.UTF-8")
}}))
options(encoding = "UTF-8")

{path_info}{session_load}{cleaned_r_code}
{session_save}"""

        # Write R code to container via tar archive
        with tempfile.NamedTemporaryFile(mode='w', encoding='utf-8', suffix='.R', delete=False) as temp_file:
            temp_file.write(enhanced_r_code)
            temp_local_path = temp_file.name

        try:
            tar_stream = io.BytesIO()
            with tarfile.open(fileobj=tar_stream, mode='w') as tar:
                tar.add(temp_local_path, arcname=os.path.basename(script_name))
            tar_stream.seek(0)
            container.put_archive('/tmp/', tar_stream)
        finally:
            os.unlink(temp_local_path)

        # Execute with UTF-8 environment
        exec_result = container.exec_run([
            "Rscript", "--encoding=UTF-8", script_name
        ], environment={
            "LANG": "C.UTF-8",
            "LC_ALL": "C.UTF-8"
        })

        # Clean up temp script
        container.exec_run(["rm", script_name])

        # Decode output
        try:
            output = exec_result.output.decode('utf-8', errors='replace') if exec_result.output else ""
        except Exception:
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


# ─── R Script Templates ─────────────────────────────────────────────────────

R_SCRIPT_TEMPLATES = {
    "execute_base": """
# Load common packages (already installed in persistent container)
suppressPackageStartupMessages({{
  library(readxl)
  library(dplyr)
  library(tidyr)
  library(ggplot2)
}})

{helper_functions}
{custom_code}
"""
}

def compile_r_script(template: str, **kwargs) -> str:
    """Compile R script from template with parameters."""
    return R_SCRIPT_TEMPLATES[template].format(**kwargs)


# ─── MCP Tools ──────────────────────────────────────────────────────────────

@mcp.tool(
    name="mount_directory",
    description="Mount local directory to access files in R. Supports multiple directories. Use absolute paths.",
    annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
)
def mount_directory(
    directory_path: Annotated[str, Field(description="Absolute path to directory containing data files (e.g., /Users/name/Documents/data)")],
    mount_point: Annotated[str, Field(description="Container mount point (default: auto-assigned /data, /data2, etc.)")] = "",
    read_only: Annotated[bool, Field(description="Mount as read-only (default: False for read-write access)")] = False
) -> dict:
    """Mount local directory to access files in R. Supports multiple directories."""
    global MOUNTED_DIRECTORIES

    try:
        mount_path = Path(directory_path).resolve()

        if not mount_path.is_absolute():
            return {"success": False, "message": "Path must be absolute"}

        if not mount_path.exists():
            return {"success": False, "message": "Directory does not exist"}

        if not mount_path.is_dir():
            return {"success": False, "message": "Path is not a directory"}

        # Determine mount point
        host_str = str(mount_path)
        if mount_point:
            container_mount = mount_point if mount_point.startswith("/") else f"/{mount_point}"
        elif not MOUNTED_DIRECTORIES:
            container_mount = "/data"
        else:
            # Auto-assign next mount point
            idx = len(MOUNTED_DIRECTORIES) + 1
            container_mount = f"/data{idx}"

        # Check if already mounted at same path
        if host_str in MOUNTED_DIRECTORIES:
            container_mount = MOUNTED_DIRECTORIES[host_str]
            return {
                "success": True,
                "message": f"Directory already mounted at {container_mount}",
                "mounted_path": host_str,
                "container_path": container_mount,
                "all_mounts": MOUNTED_DIRECTORIES
            }

        MOUNTED_DIRECTORIES[host_str] = container_mount

        # Create workspace subdirectory
        workspace_path = mount_path / "r_workspace"
        workspace_path.mkdir(exist_ok=True)

        # Restart container with new mounts
        global R_CONTAINER
        container_restarted = False
        if R_CONTAINER:
            try:
                print("🔄 Restarting container with updated mounts...", file=sys.stderr)
                cleanup_r_container()
                get_or_create_r_container()
                container_restarted = True
                print("✅ Container restarted with updated mounts", file=sys.stderr)
            except Exception as e:
                print(f"⚠️ Failed to restart container: {e}", file=sys.stderr)

        # Quick file listing
        files = list(mount_path.glob("*"))[:10]

        return {
            "success": True,
            "message": f"Directory mounted at {container_mount}" + (" (container restarted)" if container_restarted else ""),
            "mounted_path": host_str,
            "container_path": container_mount,
            "workspace_path": str(workspace_path),
            "sample_files": [f.name for f in files],
            "total_files": len(list(mount_path.glob("*"))),
            "container_restarted": container_restarted,
            "all_mounts": MOUNTED_DIRECTORIES,
            "usage_example": f"Use '{container_mount}/' prefix in R code (e.g., read_excel('{container_mount}/file.xlsx'))"
        }

    except Exception as e:
        return {"success": False, "message": f"Failed to mount: {str(e)}"}


@mcp.tool(
    name="unmount_directory",
    description="Unmount a previously mounted directory.",
    annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
)
def unmount_directory(
    directory_path: Annotated[str, Field(description="Host path or container mount point to unmount")] = "",
    unmount_all: Annotated[bool, Field(description="Unmount all directories")] = False
) -> dict:
    """Unmount a previously mounted directory."""
    global MOUNTED_DIRECTORIES

    if unmount_all:
        count = len(MOUNTED_DIRECTORIES)
        MOUNTED_DIRECTORIES.clear()
        if R_CONTAINER:
            cleanup_r_container()
        return {"success": True, "message": f"All {count} directories unmounted", "all_mounts": {}}

    if not directory_path:
        return {"success": False, "message": "Specify directory_path or use unmount_all=True"}

    resolved = str(Path(directory_path).resolve())

    # Check by host path
    if resolved in MOUNTED_DIRECTORIES:
        del MOUNTED_DIRECTORIES[resolved]
    else:
        # Check by container mount point
        found_key = None
        for host, mount in MOUNTED_DIRECTORIES.items():
            if mount == directory_path:
                found_key = host
                break
        if found_key:
            del MOUNTED_DIRECTORIES[found_key]
        else:
            return {"success": False, "message": f"Directory not found in mounts: {directory_path}", "all_mounts": MOUNTED_DIRECTORIES}

    # Restart container
    if R_CONTAINER:
        cleanup_r_container()
        if MOUNTED_DIRECTORIES:
            get_or_create_r_container()

    return {"success": True, "message": "Directory unmounted", "all_mounts": MOUNTED_DIRECTORIES}


@mcp.tool(
    name="execute_r_script",
    description="Run R code and get text output. Auto-detects plots (returns base64 PNG), auto-installs missing packages, and persists R session variables between calls.",
    annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
)
def execute_r_script(
    code: Annotated[str, Field(description="R code to execute (can read Excel files, do statistics, create plots)")],
    timeout: Annotated[int, Field(description="Maximum execution time in seconds", ge=10, le=300)] = 60,
    capture_plot: Annotated[bool, Field(description="Auto-detect and capture plots as base64 PNG (default: True)")] = True,
    session: Annotated[bool, Field(description="Persist R variables between calls (default: True)")] = True
) -> dict:
    """Run R code with auto plot capture, library detection, session persistence, and enhanced errors."""

    global R_CONTAINER
    if not R_CONTAINER:
        try:
            get_or_create_r_container()
            if not R_CONTAINER:
                return {
                    "success": False, "returncode": -1,
                    "stdout": "", "stderr": "Failed to create R container",
                    "summary": "Container creation failed"
                }
        except Exception as e:
            return {
                "success": False, "returncode": -1,
                "stdout": "", "stderr": f"Failed to create R container: {str(e)}",
                "summary": "Container creation failed"
            }

    # Check cache
    cache_key = get_cache_key("execute_r", {"code": code, "capture_plot": capture_plot})
    cached = get_cached_result(cache_key)
    if cached:
        return cached

    try:
        # Auto-detect and install missing libraries
        detected_libs = detect_libraries(code)
        auto_installed = []
        if detected_libs:
            try:
                client = docker.from_env()
                container = client.containers.get(R_CONTAINER)
                auto_installed = auto_install_libraries(container, detected_libs)
            except Exception:
                pass

        # Determine if plot capture is needed
        has_plots = capture_plot and detect_plot_commands(code)

        # Build the R code with enhancements
        user_code = code
        if has_plots:
            user_code = wrap_plot_capture(code)

        # Wrap with error handling
        user_code = wrap_error_handling(user_code)

        # Compile with template
        enhanced_code = compile_r_script(
            "execute_base",
            helper_functions="",
            custom_code=user_code
        )

        # Override session setting
        global SESSION_ENABLED
        original_session = SESSION_ENABLED
        SESSION_ENABLED = session
        docker_result = execute_r_script_docker(enhanced_code, timeout)
        SESSION_ENABLED = original_session

        if docker_result is None or len(docker_result) != 3:
            return {
                "success": False, "returncode": -1,
                "stdout": "", "stderr": "Docker execution returned invalid result",
                "summary": "Docker execution failed"
            }

        stdout, stderr, returncode = docker_result
        stdout = str(stdout) if stdout is not None else ""
        stderr = str(stderr) if stderr is not None else ""
        returncode = int(returncode) if returncode is not None else -1

        result = {
            "success": returncode == 0,
            "returncode": returncode,
            "stdout": stdout,
            "stderr": stderr,
            "summary": f"Execution {'successful' if returncode == 0 else 'failed'}"
        }

        # Add auto-installed packages info
        if auto_installed:
            result["auto_installed_packages"] = auto_installed

        # Extract plot if captured
        if has_plots and "__R_MCP_PLOT_SAVED__" in stdout:
            try:
                client = docker.from_env()
                container = client.containers.get(R_CONTAINER)
                plot_b64 = extract_plot_base64(container)
                if plot_b64:
                    result["plot_base64"] = plot_b64
                    result["plot_mime_type"] = "image/png"
                    result["summary"] += " (plot captured)"
                # Clean up plot sentinel from stdout
                result["stdout"] = stdout.replace("__R_MCP_PLOT_SAVED__\n", "").replace("__R_MCP_PLOT_SAVED__", "")
            except Exception:
                pass

        # Clean up no-plot sentinel
        result["stdout"] = result["stdout"].replace("__R_MCP_NO_PLOT__\n", "").replace("__R_MCP_NO_PLOT__", "")

        # Session info
        if session:
            result["session"] = "active (variables persisted)"

        # PII redaction: sanitize output before it reaches the LLM
        if PII_ENABLED and result["stdout"]:
            sanitized_stdout, pii_detections = sanitize_pii(result["stdout"])
            if pii_detections:
                result["stdout"] = sanitized_stdout
                result["pii_redacted"] = True
                result["pii_detections"] = pii_detections
                result["summary"] += f" (PII redacted: {len(pii_detections)} items)"

        if PII_ENABLED and result["stderr"]:
            sanitized_stderr, _ = sanitize_pii(result["stderr"])
            result["stderr"] = sanitized_stderr

        set_cached_result(cache_key, result)
        return result

    except Exception as e:
        return {
            "success": False, "returncode": -1,
            "stdout": "", "stderr": str(e),
            "summary": "Execution failed"
        }


@mcp.tool(
    name="initialize_r_container",
    description="Start R container with packages. Automatically builds optimized image if needed.",
    annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
)
def initialize_r_container() -> dict:
    """Start R container with packages."""
    global R_CONTAINER

    try:
        ensure_docker()
        client = docker.from_env()

        if R_CONTAINER:
            try:
                container = client.containers.get(R_CONTAINER)
                container.remove(force=True)
            except:
                pass
            finally:
                R_CONTAINER = None

        images_to_try = ["semoss/docker-r-packages:latest", "rocker/rstudio:latest", "rocker/tidyverse:latest", "r-base:latest"]
        container = None

        for image in images_to_try:
            try:
                print(f"Trying to create container with {image}...", file=sys.stderr)

                try:
                    client.images.get(image)
                    print(f"✓ Image {image} found locally", file=sys.stderr)
                except docker.errors.ImageNotFound:
                    try:
                        print(f"Pulling {image}...", file=sys.stderr)
                        client.images.pull(image)
                        print(f"✓ Image {image} pulled successfully", file=sys.stderr)
                    except Exception as pull_error:
                        print(f"Failed to pull {image}: {pull_error}", file=sys.stderr)
                        raise

                # Setup volumes
                volumes = {}
                working_dir = "/workspace"
                if MOUNTED_DIRECTORIES:
                    for host_path, container_path in MOUNTED_DIRECTORIES.items():
                        volumes[host_path] = {"bind": container_path, "mode": "rw"}
                    working_dir = list(MOUNTED_DIRECTORIES.values())[0]

                run_kwargs = dict(
                    image=image,
                    command="tail -f /dev/null",
                    volumes=volumes,
                    working_dir=working_dir,
                    environment={
                        "LANG": "C.UTF-8",
                        "LC_ALL": "C.UTF-8",
                        "DEBIAN_FRONTEND": "noninteractive"
                    },
                    detach=True,
                    remove=False,
                    mem_limit=CONTAINER_MEM_LIMIT,
                    cpu_quota=CONTAINER_CPU_QUOTA,
                )

                # Always create with network for initial setup
                container = client.containers.run(**run_kwargs)
                print(f"✅ Container created with {image}", file=sys.stderr)
                break

            except Exception as e:
                print(f"Failed to use {image}: {str(e)}", file=sys.stderr)
                continue

        if not container:
            raise RuntimeError("Could not create container with any available image")

        # Setup packages (requires network)
        image_tags = str(container.image.tags)
        print(f"📋 Container using image: {image_tags}", file=sys.stderr)
        _setup_packages(container, image_tags)

        # Disable network after setup
        if CONTAINER_NETWORK_DISABLED:
            _set_container_network(container, enable=False)
            print("🔒 Network disabled (secure mode)", file=sys.stderr)

        R_CONTAINER = container.id

        return {
            "success": True,
            "container_id": container.id[:12],
            "image_used": str(container.image.tags[0]) if container.image.tags else "unknown",
            "message": "R container initialized successfully",
            "status": "ready",
            "resource_limits": {
                "memory": CONTAINER_MEM_LIMIT,
                "cpu_quota": CONTAINER_CPU_QUOTA,
                "network_disabled": CONTAINER_NETWORK_DISABLED
            }
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
    description="Check R container status including health, resource usage, and mounted directories.",
    annotations={"readOnlyHint": True, "openWorldHint": False}
)
def container_status() -> dict:
    """Check container health with actual R execution test and resource info."""
    global R_CONTAINER

    if not R_CONTAINER:
        return {
            "status": "not_initialized",
            "message": "No R container is currently running",
            "container_id": "none",
            "mounted_directories": MOUNTED_DIRECTORIES
        }

    try:
        client = docker.from_env()
        container = client.containers.get(R_CONTAINER)

        result = {
            "status": str(container.status),
            "container_id": str(container.id[:12]),
            "image": str(container.image.tags[0] if container.image.tags else "unknown"),
            "message": f"Container is {container.status}",
            "uptime": str(container.attrs.get("State", {}).get("StartedAt", "unknown")),
            "mounted_directories": MOUNTED_DIRECTORIES,
            "resource_limits": {
                "memory": CONTAINER_MEM_LIMIT,
                "cpu_quota": CONTAINER_CPU_QUOTA,
                "network_disabled": CONTAINER_NETWORK_DISABLED
            },
            "session_enabled": SESSION_ENABLED,
            "cache_stats": {
                "cached_results": len(result_cache),
                "max_size": CACHE_SIZE,
                "ttl_seconds": CACHE_TTL
            }
        }

        # Healthcheck: actually run R to verify it works
        if container.status == 'running':
            healthcheck = container.exec_run([
                "Rscript", "-e",
                'cat(paste("R", R.version$major, R.version$minor, "| Packages:", length(.packages(all.available=TRUE))))'
            ], environment={"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"})

            if healthcheck.exit_code == 0:
                r_info = healthcheck.output.decode('utf-8', errors='replace').strip()
                result["healthcheck"] = "healthy"
                result["r_info"] = r_info
            else:
                result["healthcheck"] = "unhealthy"
                result["r_info"] = "R execution failed"

            # Check session workspace
            if SESSION_ENABLED:
                session_check = container.exec_run([
                    "Rscript", "-e",
                    f'if(file.exists("{SESSION_WORKSPACE_PATH}")) {{ cat("Session: active, size:", file.info("{SESSION_WORKSPACE_PATH}")$size, "bytes") }} else {{ cat("Session: no saved workspace") }}'
                ])
                result["session_info"] = session_check.output.decode('utf-8', errors='replace').strip()

        return result

    except docker.errors.NotFound:
        R_CONTAINER = None
        return {
            "status": "not_found",
            "message": "Container was removed externally",
            "container_id": "none",
            "mounted_directories": MOUNTED_DIRECTORIES
        }
    except Exception as e:
        return {
            "status": "error",
            "message": f"Error checking container: {str(e)}",
            "container_id": str(R_CONTAINER[:12]) if R_CONTAINER else "none"
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

    if version:
        install_script = f'''
        sink("/dev/null", type = "message")
        sink("/dev/null", type = "output")
        suppressWarnings(suppressMessages({{
            if (!requireNamespace("devtools", quietly = TRUE)) {{
              install.packages("devtools", repos="{repo}", quiet=TRUE)
            }}
            devtools::install_version("{package_name}", version = "{version}", repos = "{repo}")
            sink()
            sink()
            if (requireNamespace("{package_name}", quietly = TRUE)) {{
              cat("SUCCESS\\n")
              cat("Version:", as.character(packageVersion("{package_name}")), "\\n")
            }} else {{
              cat("FAILED\\n")
            }}
        }}))
        '''
    else:
        install_script = f'''
        cat("Attempting to install {package_name}...\\n")
        tryCatch({{
            install.packages("{package_name}", repos="{repo}", dependencies=TRUE)
            if (requireNamespace("{package_name}", quietly = TRUE)) {{
              cat("SUCCESS\\n")
              cat("Version:", as.character(packageVersion("{package_name}")), "\\n")
            }} else {{
              cat("INSTALL_FAILED: Package not available after installation\\n")
            }}
        }}, error = function(e) {{
            cat("INSTALL_ERROR:", conditionMessage(e), "\\n")
            cat("Trying alternative installation...\\n")
            available_packages <- available.packages(repos="{repo}")
            if ("{package_name}" %in% rownames(available_packages)) {{
                cat("Package found in repository, trying binary installation...\\n")
                tryCatch({{
                    install.packages("{package_name}", repos="{repo}", type="binary", dependencies=TRUE)
                    if (requireNamespace("{package_name}", quietly = TRUE)) {{
                        cat("SUCCESS\\n")
                        cat("Version:", as.character(packageVersion("{package_name}")), "\\n")
                    }} else {{
                        cat("BINARY_INSTALL_FAILED\\n")
                    }}
                }}, error = function(e2) {{
                    cat("BINARY_ERROR:", conditionMessage(e2), "\\n")
                    cat("FINAL_FAILED\\n")
                }})
            }} else {{
                cat("PACKAGE_NOT_FOUND: {package_name} not available in repository\\n")
            }}
        }})
        '''

    # Temporarily enable network for package installation
    network_was_disabled = CONTAINER_NETWORK_DISABLED
    container = None
    if network_was_disabled:
        try:
            client = docker.from_env()
            container = client.containers.get(R_CONTAINER)
            _set_container_network(container, enable=True)
        except Exception as e:
            print(f"⚠️ Could not enable network: {e}", file=sys.stderr)

    try:
        stdout, stderr, returncode = execute_r_script_docker(install_script, timeout=300)
    finally:
        # Re-disable network after installation
        if network_was_disabled and container:
            _set_container_network(container, enable=False)

    if "SUCCESS" in stdout:
        version_str = stdout.split("Version:")[1].strip() if "Version:" in stdout else ""
        return {
            "success": True,
            "package": package_name,
            "message": "Package installed successfully",
            "version": version_str
        }
    else:
        return {
            "success": False,
            "package": package_name,
            "message": "Installation failed",
            "details": stdout + "\n" + stderr,
            "stdout": stdout,
            "stderr": stderr
        }


@mcp.tool(
    name="clear_session",
    description="Clear R session workspace (remove all persisted variables).",
    annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False}
)
def clear_session() -> dict:
    """Clear R session workspace."""
    global R_CONTAINER

    if not R_CONTAINER:
        return {"success": True, "message": "No active session to clear"}

    try:
        client = docker.from_env()
        container = client.containers.get(R_CONTAINER)
        container.exec_run(["rm", "-f", SESSION_WORKSPACE_PATH])
        return {"success": True, "message": "R session workspace cleared. All persisted variables removed."}
    except Exception as e:
        return {"success": False, "message": f"Failed to clear session: {str(e)}"}


# ─── Server Lifecycle ───────────────────────────────────────────────────────

def initialize_server():
    """Initialize the server."""
    print("Initializing R-Server MCP with Docker...", file=sys.stderr)

    ensure_docker()
    print("✓ Docker is available and running", file=sys.stderr)

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
    print(f"  Cache: size={CACHE_SIZE}, TTL={CACHE_TTL}s", file=sys.stderr)
    print(f"  Container limits: mem={CONTAINER_MEM_LIMIT}, cpu_quota={CONTAINER_CPU_QUOTA}", file=sys.stderr)
    print(f"  Session persistence: {'enabled' if SESSION_ENABLED else 'disabled'}", file=sys.stderr)
    print(f"  Network isolation: {'enabled' if CONTAINER_NETWORK_DISABLED else 'disabled'}", file=sys.stderr)

__all__ = ["mcp"]

def main():
    """Main entry point for the MCP server."""
    import atexit

    atexit.register(cleanup_r_container)

    try:
        initialize_server()
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
