from fastapi import APIRouter

from app.api.v1 import account, auth, games, payments, vpn
from app.api.v1.admin import games as admin_games
from app.api.v1.admin import panel as admin_panel
from app.api.v1.admin import routes as admin
from app.api.v1.admin import vpn as admin_vpn

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(account.users_router)
router.include_router(account.devices_router)
router.include_router(account.plans_router)
router.include_router(account.subs_router)
router.include_router(account.promo_router)
router.include_router(account.referral_router)
router.include_router(vpn.router)
router.include_router(payments.router)
router.include_router(payments.webhooks)
router.include_router(games.router)
router.include_router(admin.router)
router.include_router(admin_panel.router)
router.include_router(admin_games.router)
router.include_router(admin_vpn.router)
