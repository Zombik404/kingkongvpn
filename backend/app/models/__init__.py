"""ORM models. Importing this package registers every table on `Base.metadata`."""

from app.models.base import Base
from app.models.billing import (
    Campaign,
    FamilyMember,
    Payment,
    PaymentEvent,
    Plan,
    PlanPrice,
    PromoCode,
    PromoRedemption,
    ReferralMilestone,
    ReferralReward,
    Subscription,
)
from app.models.games import (
    BonusLedger,
    BonusWallet,
    GameProfile,
    GameRoom,
    GameRoomPlayer,
    GameRound,
    GameRoundPlayer,
)
from app.models.ops import (
    AuditLog,
    Notification,
    NotificationPreference,
    Setting,
    SupportTicket,
    TicketMessage,
)
from app.models.user import AuthSession, RefreshToken, User, UserActionToken
from app.models.vpn import Device, DeviceUsageDaily, Location, PeerAssignment, Server

__all__ = [
    "AuditLog",
    "AuthSession",
    "Base",
    "BonusLedger",
    "BonusWallet",
    "Campaign",
    "Device",
    "DeviceUsageDaily",
    "FamilyMember",
    "GameProfile",
    "GameRoom",
    "GameRoomPlayer",
    "GameRound",
    "GameRoundPlayer",
    "Location",
    "Notification",
    "NotificationPreference",
    "Payment",
    "PaymentEvent",
    "PeerAssignment",
    "Plan",
    "PlanPrice",
    "PromoCode",
    "PromoRedemption",
    "ReferralMilestone",
    "ReferralReward",
    "RefreshToken",
    "Server",
    "Setting",
    "Subscription",
    "SupportTicket",
    "TicketMessage",
    "User",
    "UserActionToken",
]
