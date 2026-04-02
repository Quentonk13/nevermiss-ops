# NeverMiss Security Architecture — 5 Layers

## Layer 1: VAULT (Python) — Secrets Encryption
- AES-256-GCM encryption for all secrets at rest
- Environment variables never touch disk in plaintext
- Auto-rotating encryption keys
- Memory wiping after use

## Layer 2: CLOAK (Python + Bash) — Anti-Tracking & Anonymization
- Rotating user agents (500+ real browser fingerprints)
- Request header sanitization (strips all identifying info)
- TLS fingerprint randomization
- Referrer stripping, canvas fingerprint blocking
- DNS-over-HTTPS to prevent ISP snooping

## Layer 3: GUARD (Python) — Runtime Protection
- Code integrity verification (SHA-512 checksums)
- Tamper detection on all skill files
- Anti-debugging / anti-reverse-engineering
- Process isolation and sandboxing
- Import hook that blocks unauthorized modules

## Layer 4: FIREWALL (Bash + Python) — Network Hardening
- Outbound-only connections (no inbound except Telegram webhook)
- IP reputation checking
- Rate limiting on all endpoints
- Connection encryption verification (reject non-TLS)
- Geo-blocking capability

## Layer 5: SENTINEL (Python) — Continuous Monitoring
- Real-time file change detection
- Unauthorized access alerts via Telegram
- Honeypot files that trigger alerts if read
- Audit logging of all operations
- Auto-lockdown on breach detection
