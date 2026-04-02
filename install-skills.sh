#!/bin/bash
# ============================================
#  NeverMiss ClawHub Skills Installer
#  Free tools that replace $500+/mo in paid SaaS
# ============================================

echo "[skills-installer] Installing ClawHub skills..."

# Only install if clawhub CLI is available
if ! command -v clawhub &>/dev/null; then
  echo "[skills-installer] clawhub CLI not found, skipping skill installs"
  exit 0
fi

# ── Revenue-Critical Skills (Lead Gen + Outreach) ──────────────
# These are the money-makers

clawhub install cold-outreach 2>/dev/null || echo "[skip] cold-outreach"
# Cold outreach sequencing — replaces Outreach.io ($100/mo)

clawhub install cold-email 2>/dev/null || echo "[skip] cold-email"
# Cold email campaigns — replaces Lemlist ($59/mo)

clawhub install foxreach 2>/dev/null || echo "[skip] foxreach"
# Multi-channel outreach (email + LinkedIn + Twitter)

clawhub install lead-magnets 2>/dev/null || echo "[skip] lead-magnets"
# Auto-generate lead magnets (PDFs, checklists, guides)

# ── CRM & Pipeline (Replace HubSpot/Salesforce) ───────────────

clawhub install workcrm 2>/dev/null || echo "[skip] workcrm"
# Full CRM — replaces HubSpot CRM ($45/mo) and Pipedrive ($15/mo)

clawhub install business-development 2>/dev/null || echo "[skip] business-development"
# BD pipeline management and deal tracking

# ── Copywriting & Content (Replace Jasper/Copy.ai) ────────────

clawhub install reef-copywriting 2>/dev/null || echo "[skip] reef-copywriting"
# AI copywriting — replaces Jasper ($49/mo) and Copy.ai ($36/mo)

clawhub install go-to-market 2>/dev/null || echo "[skip] go-to-market"
# GTM strategy, positioning, messaging frameworks

# ── Social Media (Replace Hootsuite/Buffer) ────────────────────

clawhub install bird 2>/dev/null || echo "[skip] bird"
# Twitter/X automation — replaces Tweet Hunter ($49/mo)

clawhub install bluesky 2>/dev/null || echo "[skip] bluesky"
# Bluesky social automation

# ── Analytics & Email (Replace Mixpanel/Mailchimp) ─────────────

clawhub install brevo 2>/dev/null || echo "[skip] brevo"
# Email marketing — replaces Mailchimp ($20/mo)

clawhub install posthog 2>/dev/null || echo "[skip] posthog"
# Product analytics — replaces Mixpanel ($25/mo)

# ── Viral Content & Video (Oliver's Larry Pattern: $671 MRR) ───

clawhub install olliewazza/larry 2>/dev/null || echo "[skip] olliewazza/larry"
# THE Larry agent — autonomous TikTok slideshows, 8M views in 1 week
# REQUIRES: POSTIZ_API_KEY (postiz.pro — free plan available)
# REQUIRES: OPENAI_API_KEY (for gpt-image-1.5 image generation)
# OPTIONAL: REVENUECAT_API_KEY (subscription revenue tracking)

clawhub install nevo-david/postiz 2>/dev/null || echo "[skip] postiz"
# Postiz Agent CLI — posts to TikTok, Instagram, YouTube, Twitter, LinkedIn,
# Facebook, Threads, Reddit, Pinterest, Mastodon, and 20+ more platforms.
# This is what Larry uses to ACTUALLY post content. Free open-source.
# REQUIRES: POSTIZ_API_KEY (get from postiz.com)
# Rate limit: 30 requests/hour

clawhub install revenuecat 2>/dev/null || echo "[skip] revenuecat"
# RevenueCat — subscription/MRR tracking (what Larry uses for revenue analytics)

clawhub install ugenesys/genviral-skill 2>/dev/null || echo "[skip] genviral-skill"
# Full viral video pipeline: script → voiceover → edit → post → analytics
# Covers TikTok, IG Reels, YouTube Shorts, Pinterest, LinkedIn

clawhub install video-editor-ai 2>/dev/null || echo "[skip] video-editor-ai"
# Batch video processing, auto-subtitles, aspect ratio conversion

# ── Meta-Skills (Self-Improvement) ─────────────────────────────

clawhub install capability-evolver 2>/dev/null || echo "[skip] capability-evolver"
# #1 downloaded skill (35K+). Auto-improves agent performance over time.

clawhub install listing-swarm 2>/dev/null || echo "[skip] listing-swarm"
# Multi-agent listing optimization

# ── Lead Gen & Data (Replace Apollo/ZoomInfo) ─────────────────

clawhub install apollo 2>/dev/null || echo "[skip] apollo"
# Apollo.io API integration — free tier lead enrichment

clawhub install ai-lead-generator 2>/dev/null || echo "[skip] ai-lead-generator"
# Web scraping + LLM lead qualification — replaces ZoomInfo ($250/mo)

clawhub install social-media-lead-generation 2>/dev/null || echo "[skip] social-media-lead-generation"
# Generate leads via social platforms

clawhub install sentiment-priority-scorer 2>/dev/null || echo "[skip] sentiment-priority-scorer"
# Score leads by sentiment, urgency, intent

clawhub install campaign-orchestrator 2>/dev/null || echo "[skip] campaign-orchestrator"
# Multi-channel follow-up sequences — replaces Outreach.io ($100/mo)

# ── SEO (Replace Ahrefs/SEMrush/Surfer) ───────────────────────

clawhub install seo-content-tools 2>/dev/null || echo "[skip] seo-content-tools"
# Competitive research + optimized blog posts — replaces Surfer SEO ($89/mo)

clawhub install seo-research 2>/dev/null || echo "[skip] seo-research"
# Keyword and competitor analysis — replaces Ahrefs ($99/mo)

clawhub install meta-tags-optimizer 2>/dev/null || echo "[skip] meta-tags-optimizer"
# Title tags, meta descriptions, Open Graph — replaces Yoast Premium

clawhub install content-creator 2>/dev/null || echo "[skip] content-creator"
# SEO-optimized marketing content generation

clawhub install aeo-content-free 2>/dev/null || echo "[skip] aeo-content-free"
# Content optimized for AI search citations (GEO/AEO) — unique capability

clawhub install aeo-analytics-free 2>/dev/null || echo "[skip] aeo-analytics-free"
# Track brand mentions by AI assistants — unique capability

clawhub install performance-reporter 2>/dev/null || echo "[skip] performance-reporter"
# SEO reports and traffic analysis — replaces AgencyAnalytics ($49/mo)

# ── Billing & Invoicing (Replace FreshBooks/Chargebee) ─────────

clawhub install stripe 2>/dev/null || echo "[skip] stripe"
# Full Stripe API: payments, subscriptions, invoices, dunning

clawhub install invoice-tracker-pro 2>/dev/null || echo "[skip] invoice-tracker-pro"
# Freelance billing: generate invoices, track payments, send reminders

clawhub install biz-reporter 2>/dev/null || echo "[skip] biz-reporter"
# Business intelligence from GA4, Search Console, Stripe

clawhub install paypilot-agms 2>/dev/null || echo "[skip] paypilot-agms"
# Process payments, send invoices, issue refunds

# ── Scheduling (Replace Calendly) ──────────────────────────────

clawhub install gog 2>/dev/null || echo "[skip] gog"
# Google Workspace: Gmail, Calendar, Drive, Contacts, Sheets, Docs (14K+ downloads)

clawhub install calendar 2>/dev/null || echo "[skip] calendar"
# Calendar management, find free slots, book meetings — replaces Calendly ($12/mo)

# ── Review & Reputation Management ─────────────────────────────

clawhub install nicholasrae-review-reply 2>/dev/null || echo "[skip] nicholasrae-review-reply"
# Monitor reviews and auto-draft replies — replaces Birdeye ($299/mo partial)

clawhub install botsee 2>/dev/null || echo "[skip] botsee"
# Monitor brand AI visibility

clawhub install agent-analytics 2>/dev/null || echo "[skip] agent-analytics"
# Simple website analytics

# ── Extra Outreach & Marketing ──────────────────────────────────

clawhub install kit-email-operator 2>/dev/null || echo "[skip] kit-email-operator"
# AI email marketing for Kit/ConvertKit — replaces ConvertKit ($25/mo)

clawhub install simplified-social-media 2>/dev/null || echo "[skip] simplified-social-media"
# Post, schedule, analyze across all platforms — replaces Buffer ($15/mo)

clawhub install affiliate-master 2>/dev/null || echo "[skip] affiliate-master"
# Full-stack affiliate marketing automation

# ── Meta / Self-Improvement ─────────────────────────────────────

clawhub install auto-skill-hunter 2>/dev/null || echo "[skip] auto-skill-hunter"
# Auto-discovers and installs high-value skills from ClawHub

clawhub install agent-browser 2>/dev/null || echo "[skip] agent-browser"
# Web automation and form filling (11K+ downloads)

# ── Website Generation & Deployment (FREE hosting) ─────────────

clawhub install frontend-design-ultimate 2>/dev/null || echo "[skip] frontend-design-ultimate"
# Full websites from text prompts — React + Tailwind + shadcn/ui

clawhub install landing-page-roast 2>/dev/null || echo "[skip] landing-page-roast"
# Audit landing pages for conversion — sell optimization as a service

clawhub install web-deploy-github 2>/dev/null || echo "[skip] web-deploy-github"
# Auto-deploy static sites to GitHub Pages ($0 hosting forever)

clawhub install vercel 2>/dev/null || echo "[skip] vercel"
# Deploy to Vercel — free tier, custom domains, SSL

clawhub install web-hosting 2>/dev/null || echo "[skip] web-hosting"
# Meta-skill: detect framework, deploy to Vercel/Netlify/GitHub

clawhub install clawpify 2>/dev/null || echo "[skip] clawpify"
# Shopify API — products, orders, customers, inventory, discounts

clawhub install wordpress 2>/dev/null || echo "[skip] wordpress"
# WordPress REST API — posts, pages, categories, users

clawhub install wp-openclaw 2>/dev/null || echo "[skip] wp-openclaw"
# Full AI-managed WordPress — bot runs entire website autonomously

# ── Passive Income (Sell While You Sleep) ──────────────────────

clawhub install clawver-marketplace 2>/dev/null || echo "[skip] clawver-marketplace"
# Autonomous e-commerce store — products, orders, payments, digital downloads

clawhub install clawver-digital-products 2>/dev/null || echo "[skip] clawver-digital-products"
# Create and sell digital products — ebooks, templates, art packs

clawhub install clawver-print-on-demand 2>/dev/null || echo "[skip] clawver-print-on-demand"
# Sell merch via Printful — no inventory, zero upfront cost

clawhub install Michael-laffin/product-description-generator 2>/dev/null || echo "[skip] product-description-generator"
# SEO product descriptions for Amazon, Shopify, eBay, Etsy (bulk CSV)

# ── E-Commerce & Sourcing ─────────────────────────────────────

clawhub install cn-ecommerce-search 2>/dev/null || echo "[skip] cn-ecommerce-search"
# Search 8 Chinese platforms: Taobao, 1688, AliExpress, JD, PDD

clawhub install ecommerce-price-monitor 2>/dev/null || echo "[skip] ecommerce-price-monitor"
# Track prices across platforms, alert on drops — arbitrage tool

# ── Bookkeeping (Replace $500/mo accountant) ───────────────────

clawhub install autonomous-bookkeeper 2>/dev/null || echo "[skip] autonomous-bookkeeper"
# Full auto: email intake → OCR → payment verify → accounting entries

clawhub install quickbooks-online 2>/dev/null || echo "[skip] quickbooks-online"
# Full QuickBooks API — invoices, payments, expenses, journal entries

clawhub install veryfi 2>/dev/null || echo "[skip] veryfi"
# Receipt/invoice OCR — structured data extraction in seconds

# ── Trading & Market Intelligence ──────────────────────────────

clawhub install polyclaw 2>/dev/null || echo "[skip] polyclaw"
# Polymarket prediction market trading — sub-800ms execution

clawhub install finance-watcher 2>/dev/null || echo "[skip] finance-watcher"
# Stock/crypto price monitoring with alerts and daily reports

clawhub install tradekix 2>/dev/null || echo "[skip] tradekix"
# Financial market data — stocks, crypto, forex, indices, news

clawhub install ai-screener 2>/dev/null || echo "[skip] ai-screener"
# Stock/crypto screener with bullish/bearish predictions

# ── Real Estate ────────────────────────────────────────────────

clawhub install ivangdavila/zillow 2>/dev/null || echo "[skip] ivangdavila/zillow"
# Zillow data — Zestimates, ROI calculations, market trends

clawhub install loan 2>/dev/null || echo "[skip] loan"
# Commercial real estate and business loan origination

# ── Sales & Client Management ─────────────────────────────────

clawhub install closing-deals 2>/dev/null || echo "[skip] closing-deals"
# Close deals — objection handling, negotiation, follow-up

clawhub install customer-retention 2>/dev/null || echo "[skip] customer-retention"
# Retention strategies to reduce churn and increase LTV

clawhub install report-generator 2>/dev/null || echo "[skip] report-generator"
# White-label PDF client reports with custom branding

clawhub install saas-orchestrator 2>/dev/null || echo "[skip] saas-orchestrator"
# Orchestrate SaaS operations, spawn sub-agents, track revenue

# ── High-Download Utilities (10K+) ────────────────────────────

clawhub install sql-toolkit 2>/dev/null || echo "[skip] sql-toolkit"
# Connect to SQLite/PostgreSQL/MySQL — unified data backbone

clawhub install agentmail 2>/dev/null || echo "[skip] agentmail"
# Programmatic email for AI agents — inboxes, webhooks, high-volume

echo "[skills-installer] Done. 70+ skills queued for install."
