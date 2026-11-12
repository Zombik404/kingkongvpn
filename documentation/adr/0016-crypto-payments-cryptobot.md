# ADR-016 — Crypto payments through Crypto Pay (@CryptoBot)

Status: accepted for the test version (2026-11-12). Extends ADR-008.

**Decision.** First payment provider is the Crypto Pay API of @CryptoBot. Prices are kept in USD;
customers pay in Gram (formerly Toncoin) or USDC (stablecoin, avoids volatility after receipt).
Tariffs: 1, 3, 6, 12 months at $5 / $13 / $24 / $42 (`app.cli bootstrap-catalog`).
The client asks the API which codes it offers and maps GRAM↔TON, so the rename on @CryptoBot's
side needs no deploy.
Testnet (@CryptoTestnetBot) during the test, mainnet at launch.

**Why @CryptoBot over Cryptomus / Wallet Pay / own wallet.** Payment happens inside Telegram;
instant self-service app creation with a testnet; HMAC-SHA256 webhooks with documented retries
(17 over 3 days). Cryptomus: browser checkout, MD5 signatures, and a record AML penalty from
FINTRAC (Oct 2025). Wallet Pay: application/approval, API in beta. Own TON wallet: no
intermediary, but we'd have to watch the chain and match transfers ourselves — revisit later.

**Known risks (accepted by the owner).**
- Telegram's rules require Telegram Stars for digital goods sold in bots and Mini Apps; selling
  for crypto can get the bot hidden for mobile users. Mitigation path: add Stars as the
  in-bot method and move crypto checkout to a web page before public launch.
- Funds sit with a custodial provider: withdraw regularly.
- Price volatility after receipt applies to Gram payments only; USDC is offered alongside.

**Rules implemented.** Access only from provider-confirmed data (signed webhook or our
authenticated `getInvoices` call); amount/currency/payload must match our payment row; period
from our price; idempotent and race-safe; webhook optional (60 s polling fallback).
