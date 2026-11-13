from __future__ import annotations

from fastapi import APIRouter, Request, Response, status

from app.api.deps import Client, Ctx, CurrentPrincipal, Db
from app.i18n import negotiate
from app.schemas.auth import (
    AcceptedOut,
    EmailIn,
    LoginIn,
    MfaChallengeOut,
    MfaVerifyIn,
    PasswordChangeIn,
    PasswordResetConfirmIn,
    RefreshIn,
    RegisterIn,
    TelegramLoginIn,
    TokenIn,
    TokenPairOut,
    TotpCodeIn,
    TotpDisableIn,
    TotpSetupOut,
)
from app.services.auth import AuthService, MfaRequired, TokenPair

router = APIRouter(prefix="/auth", tags=["auth"])

_CHECK_EMAIL = "If the address can receive mail from us, a message is on its way."


def _pair_out(pair: TokenPair) -> TokenPairOut:
    return TokenPairOut(
        access_token=pair.access_token,
        refresh_token=pair.refresh_token,
        expires_in=pair.expires_in,
        session_id=pair.session_id,
    )


@router.post("/register", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedOut)
async def register(
    body: RegisterIn, request: Request, ctx: Ctx, db: Db, client: Client
) -> AcceptedOut:
    """Create an account and email a verification link. Same answer for existing emails."""
    locale = negotiate(body.locale, request.headers.get("accept-language"))
    await AuthService(ctx, db).register(str(body.email), body.password, locale, client)
    return AcceptedOut(detail=_CHECK_EMAIL)


@router.post("/verify-email", status_code=status.HTTP_204_NO_CONTENT)
async def verify_email(body: TokenIn, ctx: Ctx, db: Db) -> Response:
    await AuthService(ctx, db).verify_email(body.token)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/resend-verification", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedOut
)
async def resend_verification(body: EmailIn, ctx: Ctx, db: Db, client: Client) -> AcceptedOut:
    await AuthService(ctx, db).resend_verification(str(body.email), client)
    return AcceptedOut(detail=_CHECK_EMAIL)


@router.post("/login", response_model=TokenPairOut | MfaChallengeOut)
async def login(body: LoginIn, ctx: Ctx, db: Db, client: Client) -> TokenPairOut | MfaChallengeOut:
    """Returns tokens, or `mfa_required` + a short-lived `mfa_token` for `/auth/mfa/verify`."""
    result = await AuthService(ctx, db).login(str(body.email), body.password, client)
    if isinstance(result, MfaRequired):
        return MfaChallengeOut(mfa_token=result.mfa_token)
    return _pair_out(result)


@router.post("/telegram/webapp", response_model=TokenPairOut)
async def telegram_webapp(body: TelegramLoginIn, ctx: Ctx, db: Db, client: Client) -> TokenPairOut:
    """Mini App sign-in with `Telegram.WebApp.initData`; creates the account on first use."""
    return _pair_out(await AuthService(ctx, db).telegram_webapp_login(body.init_data, client))


@router.post("/mfa/verify", response_model=TokenPairOut)
async def mfa_verify(body: MfaVerifyIn, ctx: Ctx, db: Db, client: Client) -> TokenPairOut:
    return _pair_out(await AuthService(ctx, db).complete_mfa(body.mfa_token, body.code, client))


@router.post("/refresh", response_model=TokenPairOut)
async def refresh(body: RefreshIn, ctx: Ctx, db: Db, client: Client) -> TokenPairOut:
    """Rotate the refresh token. Reusing a rotated token revokes the whole session."""
    return _pair_out(await AuthService(ctx, db).refresh(body.refresh_token, client))


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(principal: CurrentPrincipal, ctx: Ctx, db: Db, client: Client) -> Response:
    await AuthService(ctx, db).logout(principal, client)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/logout-all", status_code=status.HTTP_204_NO_CONTENT)
async def logout_all(principal: CurrentPrincipal, ctx: Ctx, db: Db, client: Client) -> Response:
    await AuthService(ctx, db).logout_all(principal, client)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/password-reset/request", status_code=status.HTTP_202_ACCEPTED, response_model=AcceptedOut
)
async def password_reset_request(body: EmailIn, ctx: Ctx, db: Db, client: Client) -> AcceptedOut:
    await AuthService(ctx, db).request_password_reset(str(body.email), client)
    return AcceptedOut(detail=_CHECK_EMAIL)


@router.post("/password-reset/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def password_reset_confirm(
    body: PasswordResetConfirmIn, ctx: Ctx, db: Db, client: Client
) -> Response:
    """Sets the new password and signs out every session."""
    await AuthService(ctx, db).confirm_password_reset(body.token, body.new_password, client)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/password/change", status_code=status.HTTP_204_NO_CONTENT)
async def password_change(
    body: PasswordChangeIn, principal: CurrentPrincipal, ctx: Ctx, db: Db, client: Client
) -> Response:
    """Keeps the current session, signs out all others."""
    await AuthService(ctx, db).change_password(
        principal, body.current_password, body.new_password, client
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/mfa/totp/setup", response_model=TotpSetupOut)
async def totp_setup(principal: CurrentPrincipal, ctx: Ctx, db: Db) -> TotpSetupOut:
    setup = await AuthService(ctx, db).totp_setup(principal)
    return TotpSetupOut(secret=setup.secret, otpauth_uri=setup.otpauth_uri)


@router.post("/mfa/totp/enable", status_code=status.HTTP_204_NO_CONTENT)
async def totp_enable(
    body: TotpCodeIn, principal: CurrentPrincipal, ctx: Ctx, db: Db, client: Client
) -> Response:
    await AuthService(ctx, db).totp_enable(principal, body.code, client)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/mfa/totp/disable", status_code=status.HTTP_204_NO_CONTENT)
async def totp_disable(
    body: TotpDisableIn, principal: CurrentPrincipal, ctx: Ctx, db: Db, client: Client
) -> Response:
    await AuthService(ctx, db).totp_disable(principal, body.password, body.code, client)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
