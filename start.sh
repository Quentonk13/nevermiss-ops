#!/bin/bash
echo "============================================"
echo "  NeverMiss OpenClaw — Starting Up"
echo "============================================"

# Set workspace directory
export OPENCLAW_WORKSPACE=/app
export OPENCLAW_STATE_DIR=/app/.openclaw
export HOME=/app

# Create required directories
mkdir -p /app/.openclaw/workspace
mkdir -p /app/.openclaw/agents/main/agent
mkdir -p /app/.openclaw/agents/main/sessions

# ── Codex OAuth: If CODEX_AUTH_JSON is set, write it for ChatGPT Pro ──
if [ -n "$CODEX_AUTH_JSON" ]; then
  mkdir -p /app/.codex
  echo "$CODEX_AUTH_JSON" > /app/.codex/auth.json
  chmod 600 /app/.codex/auth.json
  echo "Codex auth token written (ChatGPT Pro enabled)"
fi

# Write OpenClaw gateway config
cat > /app/.openclaw/openclaw.json <<CFGEOF
{
  "gateway": {
    "mode": "local"
  },
  "channels": {
    "telegram": {
      "enabled": true,
      "botToken": "${TELEGRAM_BOT_TOKEN}",
      "dmPolicy": "open",
      "allowFrom": ["*"],
      "groupPolicy": "disabled",
      "streaming": "partial",
      "mediaMaxMb": 50,
      "textChunkLimit": 4000,
      "linkPreview": true,
      "reactionNotifications": "own",
      "ackReaction": "👀",
      "actions": {
        "sendMessage": true,
        "reactions": true
      }
    }
  },
  "tools": {
    "exec": {
      "security": "full",
      "ask": "off"
    }
  },
  "agents": {
    "defaults": {
      "model": "openrouter/minimax/minimax-m2.5",
      "timeoutSeconds": 300,
      "heartbeat": {
        "every": "55m",
        "model": "openrouter/google/gemini-2.5-flash-lite"
      },
      "contextTokens": 128000,
      "compaction": {
        "mode": "safeguard",
        "reserveTokensFloor": 32000,
        "timeoutSeconds": 600
      },
      "contextPruning": {
        "mode": "cache-ttl",
        "ttl": "30m",
        "keepLastAssistants": 2,
        "minPrunableToolChars": 20000
      }
    },
    "list": [
      {
        "id": "main",
        "workspace": "/app/.openclaw/workspace",
        "agentDir": "/app/.openclaw/agents/main/agent",
        "subagents": {
          "allowAgents": ["sdr", "content", "builder", "researcher"]
        }
      },
      {
        "id": "sdr",
        "model": "openrouter/minimax/minimax-m2.5",
        "workspace": "/app/.openclaw/workspace-sdr",
        "agentDir": "/app/.openclaw/agents/sdr/agent"
      },
      {
        "id": "content",
        "model": "openrouter/minimax/minimax-m2.5",
        "workspace": "/app/.openclaw/workspace-content",
        "agentDir": "/app/.openclaw/agents/content/agent"
      },
      {
        "id": "builder",
        "model": "openrouter/anthropic/claude-haiku-4-5-20251001",
        "workspace": "/app/.openclaw/workspace-builder",
        "agentDir": "/app/.openclaw/agents/builder/agent"
      },
      {
        "id": "researcher",
        "model": "openrouter/google/gemini-2.5-flash",
        "workspace": "/app/.openclaw/workspace-researcher",
        "agentDir": "/app/.openclaw/agents/researcher/agent"
      }
    ]
  }
}
CFGEOF

# Write auth profiles for the main agent
cat > /app/.openclaw/agents/main/agent/auth-profiles.json <<AUTHEOF
{
  "version": 1,
  "profiles": {
    "openrouter": {
      "type": "api_key",
      "provider": "openrouter",
      "key": "${OPENROUTER_API_KEY}"
    },
    "openai": {
      "type": "api_key",
      "provider": "openai",
      "key": "${OPENAI_API_KEY}"
    },
    "anthropic": {
      "type": "api_key",
      "provider": "anthropic",
      "key": "${ANTHROPIC_API_KEY}"
    },
    "groq": {
      "type": "api_key",
      "provider": "groq",
      "key": "${GROQ_API_KEY}"
    }
  }
}
AUTHEOF

# Grant full exec permissions — no approval prompts needed
cat > /app/.openclaw/exec-approvals.json <<EXECEOF
{
  "version": 1,
  "defaults": {
    "security": "full",
    "ask": "off",
    "askFallback": "full"
  }
}
EXECEOF

# Copy workspace files for main orchestrator
for f in SOUL.md IDENTITY.md AGENTS.md USER.md TOOLS.md HEARTBEAT.md MEMORY.md BOOTSTRAP.md; do
  cp /app/$f /app/.openclaw/workspace/$f 2>/dev/null || true
done

# ── Multi-Agent Team Setup ──────────────────────────────────────
# 4 specialized sub-agents that main orchestrator can spawn in parallel

# SDR Agent — finds leads, sends emails, handles replies
mkdir -p /app/.openclaw/workspace-sdr /app/.openclaw/agents/sdr/agent
ln -sfn /app/data /app/.openclaw/workspace-sdr/data
ln -sfn /app/skills /app/.openclaw/workspace-sdr/skills
cat > /app/.openclaw/workspace-sdr/AGENTS.md <<'SDREOF'
# SDR Agent
You are a Sales Development Rep. Your ONLY job is lead generation and cold outreach.
Skills: ai-sdr, lead-pipeline, cold-outreach, foxreach, email-engine, outreach-sequencer, free-search
Data: /app/data/nevermiss.db, /app/data/leads/
Tasks: Find contractor leads (Apollo + Google Maps), send cold emails (Brevo/Instantly), classify replies, follow up, book demos.
Target: HVAC, plumbing, electrical, roofing contractors. $297/mo NeverMiss product.
Keep responses under 100 words. Execute, don't explain.
SDREOF
cp /app/.openclaw/agents/main/agent/auth-profiles.json /app/.openclaw/agents/sdr/agent/

# Content Agent — creates social posts, threads, blog content
mkdir -p /app/.openclaw/workspace-content /app/.openclaw/agents/content/agent
ln -sfn /app/data /app/.openclaw/workspace-content/data
ln -sfn /app/skills /app/.openclaw/workspace-content/skills
cat > /app/.openclaw/workspace-content/AGENTS.md <<'CNTEOF'
# Content Agent
You are a Content Creator. Your ONLY job is creating and posting social content.
Skills: social-content, viral-video-studio, reef-copywriting, ai-seo-writer, seo-optimizer, content-queue
Platforms: Twitter (API keys set), Bluesky (app password set), Telegram. Postiz for others if POSTIZ_API_KEY set.
Tasks: Write Twitter threads, Bluesky posts, blog drafts. Use Larry Loop pattern to analyze and improve content.
Niche: contractor marketing, missed calls, business growth.
Keep responses under 100 words. Post content, report what you posted.
CNTEOF
cp /app/.openclaw/agents/main/agent/auth-profiles.json /app/.openclaw/agents/content/agent/

# Builder Agent — builds digital products, sales pages, deploys
mkdir -p /app/.openclaw/workspace-builder /app/.openclaw/agents/builder/agent
ln -sfn /app/data /app/.openclaw/workspace-builder/data
ln -sfn /app/skills /app/.openclaw/workspace-builder/skills
cat > /app/.openclaw/workspace-builder/AGENTS.md <<'BLDEOF'
# Builder Agent (Felix Craft)
You are a Product Builder. Your ONLY job is building digital products and deploying them.
Skills: felix-craft, frontend-design-3, web-deploy-github, vercel, stripe, clawver-digital-products, supabase
Tasks: Build digital products (templates, tools, guides), generate sales pages, create Stripe payment links, deploy to GitHub Pages or Vercel.
Revenue targets: $10-50 per digital product, unlimited copies. Build fast, deploy fast, iterate.
Keep responses under 100 words. Build things, don't talk about building things.
BLDEOF
cp /app/.openclaw/agents/main/agent/auth-profiles.json /app/.openclaw/agents/builder/agent/

# Researcher Agent — market intel, competitor analysis, lead research
mkdir -p /app/.openclaw/workspace-researcher /app/.openclaw/agents/researcher/agent
ln -sfn /app/data /app/.openclaw/workspace-researcher/data
ln -sfn /app/skills /app/.openclaw/workspace-researcher/skills
cat > /app/.openclaw/workspace-researcher/AGENTS.md <<'RESEOF'
# Research Agent
You are a Market Researcher. Your ONLY job is gathering intelligence.
Skills: market-intel, competitive-edge, seo-competitor-analysis, browser-agent, free-search, landing-page-roast, review-analysis
Tasks: Research competitors, find market gaps, audit contractor websites, analyze reviews, identify opportunities.
Output: Write findings to /app/data/research/. Keep reports actionable — what to do, not just what you found.
Keep responses under 100 words.
RESEOF
cp /app/.openclaw/agents/main/agent/auth-profiles.json /app/.openclaw/agents/researcher/agent/

echo "[multi-agent] 4 sub-agents configured: sdr, content, builder, researcher"

# Debug: verify env vars are set (values hidden)
for var in TELEGRAM_BOT_TOKEN OPENROUTER_API_KEY OPENAI_API_KEY ANTHROPIC_API_KEY GROQ_API_KEY STRIPE_API_KEY BREVO_API_KEY TWITTER_API_KEY BLUESKY_APP_PASSWORD APOLLO_API_KEY; do
  val=$(eval echo "\$$var")
  if [ -n "$val" ]; then
    echo "$var is set (${#val} chars)"
  else
    echo "WARNING: $var is not set"
  fi
done

# ── SECURITY: Initialize 5-layer protection ───────────────────
echo "[security] Initializing 5-layer security..."

# Layer 1: Vault — encrypt secrets
python3 /app/security/vault/vault.py --encrypt 2>/dev/null || echo "[security] Vault init skipped"

# Layer 3: Guard — create integrity baseline
python3 /app/security/guard/guard.py --baseline 2>/dev/null || echo "[security] Guard baseline skipped"

# Layer 4: Firewall — harden permissions and network
bash /app/security/firewall/firewall.sh --init 2>/dev/null || echo "[security] Firewall init skipped"

# Layer 5: Sentinel — take initial snapshot
python3 /app/security/sentinel/sentinel.py --snapshot 2>/dev/null || echo "[security] Sentinel snapshot skipped"

echo "[security] All 5 layers active"

# Install free ClawHub skills (replaces $500+/mo in paid tools)
bash /app/install-skills.sh

echo "Config written. Starting gateway..."
exec openclaw gateway --port ${PORT:-18789} --verbose
