from .admin_commands import router as admin_commands_router
from .profile import router as profile_router
from .user_commands import router as user_commands_router

__all__ = [
    "user_commands_router",
    "profile_router",
    "admin_commands_router",
]
