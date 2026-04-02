FROM node:22-slim

# Install Python 3 + pip for skill scripts
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright dependencies for browser-agent
RUN npx playwright install-deps chromium 2>/dev/null || true

# Install OpenClaw globally
RUN npm install -g openclaw
# Enable built-in Telegram plugin (bundled, just needs enabling)
RUN openclaw plugins enable telegram
# Create workspace directory
WORKDIR /app

# Copy project files
COPY . .

# Install Python dependencies
RUN pip3 install --break-system-packages \
    beautifulsoup4 \
    playwright

# Install Playwright browser
RUN python3 -m playwright install chromium 2>/dev/null || true

# Create data directories (persistent via Railway volume)
RUN mkdir -p data/conversations \
    data/market_research/verticals \
    data/optimization/script_versions \
    data/competitive_edge/competitor_reviews \
    data/browser_screenshots \
    data/browser_cache \
    data/website_audits \
    data/competitor_snapshots \
    data/ceo_memory/knowledge \
    data/ceo_memory/daily_notes \
    data/ceo_memory/tacit \
    data/ceo_memory/strategic_reviews \
    data/ceo_memory/morning_briefs

# Make startup script executable
RUN chmod +x /app/start.sh

# OpenClaw gateway default port
EXPOSE 18789

# Start via startup script — QR code shows in Railway logs
CMD ["/app/start.sh"]
