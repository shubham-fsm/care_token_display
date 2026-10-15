import re

from care.emr.models import Token
from care.emr.models.scheduling.schedule import SchedulableResource
from care.emr.resources.scheduling.schedule.spec import SchedulableResourceTypeOptions
from care.users.models import User


def fmt_user_name(obj: User) -> str:
    parts = [obj.prefix, obj.first_name, obj.last_name, obj.suffix]
    return " ".join(filter(None, parts))


def fmt_schedule_resource_name(obj: SchedulableResource) -> str:
    if obj.resource_type == SchedulableResourceTypeOptions.practitioner.value:
        return fmt_user_name(obj.user)
    if obj.resource_type == SchedulableResourceTypeOptions.healthcare_service.value:
        return obj.healthcare_service.name
    if obj.resource_type == SchedulableResourceTypeOptions.location.value:
        return obj.location.name
    raise ValueError("Invalid resource type")


EMERGENCY_CATEGORY_PATTERN = re.compile(r"emergency|urgent|आपात", re.IGNORECASE)
HIGH_PRIORITY_CATEGORY_PATTERN = re.compile(
    r"senior|elderly|pregnan|priority|vip|divyang|disab|वरिष्ठ|गर्भवती", re.IGNORECASE
)

EMERGENCY, HIGH, NORMAL = 0, 1, 2


def token_priority_rank(token: Token) -> int:
    """
    Call order of a token, the same as the queue page's Serve Next:
    0 emergency, 1 high (senior citizens, pregnant women, divyang, ...),
    2 normal. An admin sets it per token category ("Call priority",
    stored in `metadata.priority`); otherwise the category name decides.
    """
    category = token.category
    flag = (category.metadata or {}).get("priority")
    if flag == "emergency":
        return EMERGENCY
    if flag is True or flag == "high":
        return HIGH
    if flag == "normal":
        return NORMAL
    name = category.name or ""
    if EMERGENCY_CATEGORY_PATTERN.search(name):
        return EMERGENCY
    if HIGH_PRIORITY_CATEGORY_PATTERN.search(name):
        return HIGH
    return NORMAL


def is_priority_token(token: Token) -> bool:
    """An emergency token: highlighted as "Emergency" on the board."""
    return token_priority_rank(token) == EMERGENCY


def fmt_token_number(token: Token) -> str:
    return f"{token.category.shorthand}-{token.number:03d}"
