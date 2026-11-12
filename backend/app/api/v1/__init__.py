from fastapi import APIRouter

from app.api.v1 import account, auth, payments
from app.api.v1.admin import routes as admin

router = APIRouter(prefix="/api/v1")
router.include_router(auth.router)
router.include_router(account.users_router)
router.include_router(account.devices_router)
router.include_router(account.plans_router)
router.include_router(account.subs_router)
router.include_router(account.promo_router)
router.include_router(payments.router)
router.include_router(payments.webhooks)
router.include_router(admin.router)
