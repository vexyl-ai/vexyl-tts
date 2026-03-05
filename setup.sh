#!/bin/bash
# ============================================================
# VEXYL-TTS — One-step Setup Script
# ============================================================
# Sets up Python venv, installs dependencies,
# downloads the model, and creates .env
# ============================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"

MODEL_ID="ai4bharat/indic-parler-tts"
VENV_DIR="venv"
ENV_FILE=".env"

# ── Colors ──────────────────────────────────────────────────
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
BOLD='\033[1m'
NC='\033[0m'

step=0
total_steps=5

print_step() {
    step=$((step + 1))
    echo ""
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BOLD}  [$step/$total_steps] $1${NC}"
    echo -e "${BLUE}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
}

print_ok() {
    echo -e "  ${GREEN}✓${NC} $1"
}

print_warn() {
    echo -e "  ${YELLOW}!${NC} $1"
}

print_error() {
    echo -e "  ${RED}✗${NC} $1"
}

# ── Header ──────────────────────────────────────────────────
echo ""
echo -e "${CYAN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${CYAN}║${NC}  ${BOLD}VEXYL-TTS Server — Setup${NC}                            ${CYAN}║${NC}"
echo -e "${CYAN}║${NC}  ai4bharat/indic-parler-tts                          ${CYAN}║${NC}"
echo -e "${CYAN}╚══════════════════════════════════════════════════════╝${NC}"

# ── Step 1: Check Python 3 ─────────────────────────────────
print_step "Checking Python 3"

if command -v python3 &>/dev/null; then
    PY_VERSION=$(python3 --version 2>&1)
    print_ok "Found: $PY_VERSION"
else
    print_warn "Python 3 not found. Attempting install via Homebrew..."
    if command -v brew &>/dev/null; then
        brew install python3
        PY_VERSION=$(python3 --version 2>&1)
        print_ok "Installed: $PY_VERSION"
    else
        print_error "Python 3 is required. Please install it:"
        echo "         macOS:  brew install python3"
        echo "         Ubuntu: sudo apt install python3 python3-venv"
        exit 1
    fi
fi

# ── Step 2: Create virtual environment ─────────────────────
print_step "Creating Python virtual environment"

if [ -d "$VENV_DIR" ]; then
    print_ok "Virtual environment already exists at ./$VENV_DIR"
else
    python3 -m venv "$VENV_DIR"
    print_ok "Created virtual environment at ./$VENV_DIR"
fi

# Activate
source "$VENV_DIR/bin/activate"
print_ok "Activated venv ($(python3 --version))"

# Upgrade pip quietly
pip install --upgrade pip -q
print_ok "pip upgraded"

# ── Step 3: Install dependencies ───────────────────────────
print_step "Installing Python dependencies"

echo -e "  ${CYAN}Installing PyTorch (CPU)...${NC}"
pip install torch --index-url https://download.pytorch.org/whl/cpu -q
print_ok "torch (CPU)"

echo -e "  ${CYAN}Installing parler-tts from GitHub...${NC}"
pip install git+https://github.com/huggingface/parler-tts.git -q
print_ok "parler-tts"

echo -e "  ${CYAN}Installing transformers, websockets, numpy, soundfile...${NC}"
pip install transformers websockets numpy soundfile huggingface_hub -q
print_ok "transformers, websockets, numpy, soundfile, huggingface_hub"

# ── Step 4: Download model ─────────────────────────────────
print_step "Downloading Indic Parler-TTS model"

# This model is NOT gated — no HuggingFace login required
if python3 -c "
from parler_tts import ParlerTTSForConditionalGeneration
ParlerTTSForConditionalGeneration.from_pretrained('$MODEL_ID', local_files_only=True)
" &>/dev/null 2>&1; then
    CACHE_SIZE=$(du -sh ~/.cache/huggingface/hub/models--ai4bharat--indic-parler-tts 2>/dev/null | cut -f1)
    print_ok "Model already cached ($CACHE_SIZE)"
else
    echo -e "  ${CYAN}Downloading $MODEL_ID (~4-6 GB)...${NC}"
    echo -e "  ${CYAN}This may take several minutes depending on your connection.${NC}"
    echo ""

    python3 -c "
from parler_tts import ParlerTTSForConditionalGeneration
from transformers import AutoTokenizer
print('Downloading model...')
model = ParlerTTSForConditionalGeneration.from_pretrained('$MODEL_ID')
print('Downloading tokenizers...')
tokenizer = AutoTokenizer.from_pretrained('$MODEL_ID')
desc_tokenizer = AutoTokenizer.from_pretrained(model.config.text_encoder._name_or_path)
print()
"
    if [ $? -eq 0 ]; then
        CACHE_SIZE=$(du -sh ~/.cache/huggingface/hub/models--ai4bharat--indic-parler-tts 2>/dev/null | cut -f1)
        print_ok "Model downloaded ($CACHE_SIZE)"
    else
        print_error "Model download failed."
        echo ""
        echo "  Check your internet connection and try again."
        exit 1
    fi
fi

# ── Step 5: Create .env and run.sh ─────────────────────────
print_step "Creating config files"

if [ -f "$ENV_FILE" ]; then
    print_ok ".env already exists (keeping existing)"
else
    cat > "$ENV_FILE" <<'EOF'
VEXYL_TTS_HOST=127.0.0.1
VEXYL_TTS_PORT=8092
VEXYL_TTS_DEVICE=cpu
VEXYL_TTS_CACHE_SIZE=200
EOF
    print_ok "Created .env"
fi

if [ -f "run.sh" ]; then
    print_ok "run.sh already exists (keeping existing)"
else
    cat > run.sh <<'SCRIPT'
#!/bin/bash
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$SCRIPT_DIR"
if [ -f .env ]; then
    export $(grep -v '^#' .env | xargs)
fi
source venv/bin/activate
python3 vexyl_tts_server.py
SCRIPT
    chmod +x run.sh
    print_ok "Created run.sh"
fi

# ── Done ────────────────────────────────────────────────────
echo ""
echo -e "${GREEN}╔══════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║${NC}  ${BOLD}Setup complete!${NC}                                     ${GREEN}║${NC}"
echo -e "${GREEN}╚══════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "  ${BOLD}To start the server:${NC}"
echo "    ./run.sh"
echo ""
echo -e "  ${BOLD}To test in browser:${NC}"
echo "    open test.html"
echo ""
echo -e "  ${BOLD}Server will listen on:${NC}"
echo "    ws://127.0.0.1:8092"
echo ""
echo -e "  ${BOLD}Config:${NC}"
echo "    .env          — Server settings"
echo "    run.sh        — Start script"
echo "    test.html     — Browser test client"
echo ""
echo -e "  Model cached at:"
echo "    ~/.cache/huggingface/hub/models--ai4bharat--indic-parler-tts"
echo ""
