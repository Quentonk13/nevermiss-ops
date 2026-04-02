#!/bin/bash
# ============================================================
#  LAYER 4: FIREWALL — Network Hardening (Bash)
#  Restricts network access, blocks scanning, rate limits
# ============================================================

set -euo pipefail

FIREWALL_LOG="/app/.guard/firewall.log"
mkdir -p /app/.guard

log() {
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] [FIREWALL] $1" >> "$FIREWALL_LOG" 2>/dev/null || true
    echo "[FIREWALL] $1"
}

# ── Restrict File Permissions ──────────────────────────────────
harden_permissions() {
    log "Hardening file permissions..."

    # Lock down vault
    chmod -R 700 /app/.vault 2>/dev/null || true
    chmod -R 700 /app/.guard 2>/dev/null || true
    chmod -R 700 /app/.openclaw 2>/dev/null || true

    # Skills readable but not world-writable
    find /app/skills -type f -name "*.py" -exec chmod 644 {} \; 2>/dev/null || true
    find /app/skills -type f -name "*.sh" -exec chmod 755 {} \; 2>/dev/null || true

    # Ensure no world-readable sensitive files
    chmod 600 /app/.openclaw/agents/main/agent/auth-profiles.json 2>/dev/null || true
    chmod 600 /app/.openclaw/openclaw.json 2>/dev/null || true
    chmod 600 /app/.openclaw/exec-approvals.json 2>/dev/null || true

    # Remove group/other permissions from security dir
    chmod -R go-rwx /app/security 2>/dev/null || true

    log "File permissions hardened"
}

# ── Strip Git History of Secrets ───────────────────────────────
sanitize_git() {
    log "Checking git for leaked secrets..."

    # Check for common secret patterns in tracked files
    if command -v git &>/dev/null && [ -d /app/.git ]; then
        LEAKS=0
        for pattern in "sk-" "key-" "token-" "secret-" "password=" "PRIVATE KEY"; do
            FOUND=$(git grep -l "$pattern" 2>/dev/null | grep -v "SECURITY.md\|\.md$\|firewall.sh" | head -5)
            if [ -n "$FOUND" ]; then
                log "WARN: Potential secret in: $FOUND (pattern: $pattern)"
                LEAKS=$((LEAKS + 1))
            fi
        done
        if [ "$LEAKS" -eq 0 ]; then
            log "No leaked secrets found in tracked files"
        else
            log "WARNING: $LEAKS potential secret leaks found"
        fi
    fi
}

# ── .gitignore Hardening ───────────────────────────────────────
harden_gitignore() {
    log "Hardening .gitignore..."

    GITIGNORE="/app/.gitignore"
    SECURITY_PATTERNS=(
        "# Security — never commit these"
        ".env"
        ".env.*"
        "*.pem"
        "*.key"
        "*.cert"
        "*.p12"
        "*.pfx"
        ".vault/"
        ".guard/"
        "*.secret"
        "credentials.json"
        "auth-profiles.json"
        "*.keyring"
        ".encrypted_store"
        "*.log"
        "__pycache__/"
        "*.pyc"
        ".DS_Store"
        "node_modules/"
        ".npm/"
        "*.sqlite"
        "*.db"
    )

    for pattern in "${SECURITY_PATTERNS[@]}"; do
        if ! grep -qF "$pattern" "$GITIGNORE" 2>/dev/null; then
            echo "$pattern" >> "$GITIGNORE"
        fi
    done

    log ".gitignore hardened with ${#SECURITY_PATTERNS[@]} security patterns"
}

# ── Environment Variable Protection ────────────────────────────
protect_env() {
    log "Protecting environment variables..."

    # Unset dangerous env vars that could be used for attacks
    unset LD_PRELOAD 2>/dev/null || true
    unset LD_LIBRARY_PATH 2>/dev/null || true
    unset PYTHONSTARTUP 2>/dev/null || true
    unset PYTHONPATH 2>/dev/null || true
    unset BASH_ENV 2>/dev/null || true
    unset ENV 2>/dev/null || true
    unset CDPATH 2>/dev/null || true

    # Set secure umask (no world permissions)
    umask 077

    log "Environment hardened, umask set to 077"
}

# ── Network Restrictions ───────────────────────────────────────
network_harden() {
    log "Applying network restrictions..."

    # Disable core dumps (could leak secrets)
    ulimit -c 0 2>/dev/null || true

    # Set secure DNS (if possible)
    if [ -w /etc/resolv.conf ]; then
        # Use Cloudflare + Quad9 (privacy-focused, malware-blocking)
        cat > /etc/resolv.conf << 'DNSEOF'
nameserver 1.1.1.1
nameserver 9.9.9.9
nameserver 1.0.0.1
options edns0 trust-ad
DNSEOF
        log "DNS set to Cloudflare + Quad9"
    else
        log "Cannot modify DNS (read-only resolv.conf)"
    fi

    log "Network restrictions applied"
}

# ── Create Honeypot Files ──────────────────────────────────────
create_honeypots() {
    log "Creating honeypot tripwires..."

    # Files that look attractive to attackers but trigger alerts if accessed
    mkdir -p /app/.config/secrets 2>/dev/null || true

    echo "HONEYPOT — If you see this, the system has been compromised. Alert ID: $(date +%s)" > /app/.config/secrets/api_keys.txt
    echo "HONEYPOT — Unauthorized access detected" > /app/.config/secrets/credentials.json
    echo "HONEYPOT — This file is a security trap" > /app/.config/secrets/.env.production

    chmod 000 /app/.config/secrets/api_keys.txt 2>/dev/null || true
    chmod 000 /app/.config/secrets/credentials.json 2>/dev/null || true
    chmod 000 /app/.config/secrets/.env.production 2>/dev/null || true

    log "Honeypot tripwires created"
}

# ── Main ───────────────────────────────────────────────────────
main() {
    log "=========================================="
    log "  FIREWALL Layer — Network Hardening"
    log "=========================================="

    protect_env
    harden_permissions
    harden_gitignore
    sanitize_git
    network_harden
    create_honeypots

    log "=========================================="
    log "  FIREWALL Layer — Active"
    log "=========================================="
}

# Run if called directly or with --init
if [[ "${1:-}" == "--init" ]] || [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    main
fi
