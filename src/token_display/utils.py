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


PRIORITY_CATEGORY_PATTERN = re.compile(r"emergency|priority|urgent|आपात", re.IGNORECASE)


def is_priority_token(token: Token) -> bool:
    """
    A token is a priority token when its category says so
    (`metadata.priority` is true) or its category name suggests it
    (e.g. "Emergency", "Priority").
    """
    category = token.category
    if (category.metadata or {}).get("priority") is True:
        return True
    return bool(PRIORITY_CATEGORY_PATTERN.search(category.name or ""))


def fmt_token_number(token: Token) -> str:
    return f"{token.category.shorthand}-{token.number:03d}"
