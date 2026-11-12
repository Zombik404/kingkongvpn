# External Accounts, Credentials and Approvals

Nothing here is needed to continue Phase 2. Items are listed in the order they will block work.
**Never send secrets in chat, issues, or commits.** Put them in the deployment secret store (see `SECURITY_POLICY.md`, Phase 2).

| # | Item | Needed by | Who / action | Lead time | Cost |
|---|---|---|---|---|---|
| 1 | Package installs allowed in the build environment (pip/npm) | Phase 2 | You: enable network/package access in Claude settings, or run builds on your machine | minutes | — |
| 2 | Legal entity (company) | Phase 6 (Apple), Phase 10 (Stripe), store listings | You + accountant/lawyer | weeks | varies |
| 3 | D-U-N-S number → **Apple Developer Program, Organization** (VPN apps must be published by an organization) | Phase 6 iOS, Phase 7 macOS | You | 1–4 weeks | ~$99/yr |
| 4 | Google Play Console (organization account) + VpnService policy declaration | Phase 6 Android | You | days–weeks | one-time fee |
| 5 | Staging VPS ×1–2 (Ubuntu 24.04 LTS, public IPv4+IPv6, kernel WireGuard) + SSH public key for deploy | Phase 3 | You authorize provider + spend | hours | low monthly |
| 6 | Cloud provider API tokens for Terraform (staging, then prod) with spending limits set at the provider | Phase 3/4 automation | You | hours | — |
| 7 | Domain name + DNS provider API token (for ACME DNS challenge / automation) | Phase 8 staging, Phase 12 | You choose brand + domain | hours | low |
| 8 | Telegram bot tokens (staging bot + production bot) from @BotFather | Phase 5 | You | minutes | free |
| 9 | Transactional email provider (SMTP/API) + SPF/DKIM/DMARC on domain | Phase 2 staging/prod (dev uses mailpit) | You | days (domain warm-up) | low |
| 10 | Stripe account (test keys first, live after business verification), webhook signing secret | Phase 10 (test keys usable earlier) | You | days | % per txn |
| 11 | Tax approach for EU digital services (VAT OSS, Stripe Tax, or a merchant-of-record such as Paddle) | Phase 10 | You + accountant | weeks | varies |
| 12 | Apple App Store Connect: subscription products, App Store Server API key (.p8), notification URL | Phase 10 | You | days | — |
| 13 | Google Play: subscription products, service account for Play Developer API, Pub/Sub topic for RTDN | Phase 10 | You | days | — |
| 14 | PayPal business account (optional) | Phase 10 | You | days | % per txn |
| 15 | Code-signing: Windows (OV/EV certificate or Azure Trusted Signing), macOS Developer ID | Phase 7 | You | days–weeks | yearly |
| 16 | Object storage bucket for encrypted backups (separate account/region from production) | Phase 2 prod / Phase 11 drill | You | hours | low |
| 17 | GitHub repository (private) + Actions secrets / environments with required reviewers | Before first CI run | You (or connect a folder/repo here) | minutes | free tier OK |
| 18 | Legal review: Privacy Policy, ToS, Refund Policy, VPN legality per target market (e.g. Russia restricts VPN services and app-store availability; data-retention laws differ per server country) | Phase 12 | Lawyer | weeks | varies |
| 19 | Monitoring/alert channels (email/Telegram admin chat for Alertmanager) | Phase 3/11 | You | minutes | free |

## Credentials the platform generates itself (no action needed)
JWT signing keys (Ed25519), internal node CA, node enrollment tokens, refresh token pepper, database passwords for dev. Production values are generated at deploy time and stored only in the secret store.
