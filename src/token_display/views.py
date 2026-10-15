import re

from care.emr.models import Token, TokenSubQueue
from care.emr.resources.scheduling.schedule.spec import SchedulableResourceTypeOptions
from care.emr.resources.scheduling.token.spec import TokenStatusOptions
from care.emr.resources.scheduling.token_sub_queue.spec import (
    TokenSubQueueStatusOptions,
)
from care.security.authorization import AuthorizationController
from django.db.models import Exists, OuterRef
from django.utils import timezone
from django.utils.timezone import make_naive
from rest_framework.exceptions import PermissionDenied
from rest_framework.renderers import TemplateHTMLRenderer
from rest_framework.response import Response
from rest_framework.views import APIView

from token_display.authentication import QueryParamTokenAuthentication
from token_display.settings import plugin_settings
from token_display.utils import (
    fmt_schedule_resource_name,
    fmt_token_number,
    is_priority_token,
    token_priority_rank,
)

TRUTHY_QUERY_VALUES = {"1", "true", "yes"}

# A `prefix-<lang>.wav` fragment must exist for each accepted lang code.
# Validation is purely defensive against arbitrary-string injection into the
# fragment URL; the fragment loader will surface a missing-file error if the
# operator names a lang we don't have audio for.
_VA_LANG_RE = re.compile(r"^[A-Za-z0-9_-]{1,16}$")


def _parse_bool_query_param(value: str | None) -> bool:
    if value is None:
        return False
    return value.strip().lower() in TRUTHY_QUERY_VALUES


def _parse_optional_bool_query_param(value: str | None) -> bool | None:
    """Like `_parse_bool_query_param`, but returns ``None`` when absent."""
    if value is None:
        return None
    return _parse_bool_query_param(value)


def _parse_va_lang_query_param(value: str | None) -> list[str] | None:
    """Parse a comma-separated `?va_lang=` value.

    Returns ``None`` when the parameter is absent so the caller can fall back
    to the configured default. An explicit empty value (``?va_lang=``) yields
    an empty list, which suppresses voice playback. Invalid tokens are
    silently dropped.
    """
    if value is None:
        return None
    parts = [p.strip() for p in value.split(",") if p.strip()]
    return [p for p in parts if _VA_LANG_RE.match(p)]


class SubQueuesTokenDisplayView(APIView):
    """
    Main view that renders the full SSR token display page for a facility.
    """

    authentication_classes = [QueryParamTokenAuthentication]
    renderer_classes = [TemplateHTMLRenderer]
    template_name = "token_display/display.html"

    def show_breaks(self) -> bool:
        """
        Whether inactive sub-queues are shown as "on break" instead of being
        hidden. Off unless enabled explicitly via SHOW_INACTIVE_AS_BREAK or
        `?show_breaks=1`, since marking a service point inactive does not
        otherwise mean a break.
        """
        override = _parse_optional_bool_query_param(self.request.query_params.get("show_breaks"))
        return override if override is not None else bool(plugin_settings.SHOW_INACTIVE_AS_BREAK)

    def get_sub_queue_objects(self, only_with_active_tokens: bool = False):
        external_ids = self.kwargs["sub_queue_external_ids"].split(",")
        statuses = [TokenSubQueueStatusOptions.active.value]
        if self.show_breaks():
            statuses.append(TokenSubQueueStatusOptions.inactive.value)
        sub_queues = TokenSubQueue.objects.filter(
            external_id__in=external_ids,
            status__in=statuses,
        )
        if only_with_active_tokens:
            active_token_exists = Token.objects.filter(
                sub_queue=OuterRef("pk"),
                queue__resource=OuterRef("resource"),
                queue__date=make_naive(timezone.now()).date(),
                queue__is_primary=True,
                status__in=[
                    TokenStatusOptions.CREATED.value,
                    TokenStatusOptions.IN_PROGRESS.value,
                ],
            )
            sub_queues = sub_queues.annotate(_has_active_tokens=Exists(active_token_exists)).filter(
                _has_active_tokens=True
            )
        order = {external_id: index for index, external_id in enumerate(external_ids)}
        return sorted(sub_queues, key=lambda sq: order.get(str(sq.external_id), len(order)))

    def authorize_request(self):
        # Authorize against the unfiltered set so permission errors are not
        # masked by the active-tokens filter.
        for sub_queue in self.get_sub_queue_objects():
            if not AuthorizationController.call("can_list_token", sub_queue.resource, self.request.user):
                raise PermissionDenied("You do not have permission read tokens for this resource")

    def get(self, request, sub_queue_external_ids: str):
        """
        Render the full token display page with static data.
        """
        self.authorize_request()
        only_with_active_tokens = _parse_bool_query_param(request.query_params.get("only_with_active_tokens"))
        va_lang_override = _parse_va_lang_query_param(request.query_params.get("va_lang"))
        va_langs = va_lang_override if va_lang_override is not None else list(plugin_settings.VA_DEFAULT_LANG or [])
        sub_queues = self.get_sub_queue_objects(only_with_active_tokens=only_with_active_tokens)
        item_count = len(sub_queues)

        # When every resource on the board is a non-practitioner (a healthcare
        # service or a physical location), the board represents service
        # counters rather than doctors' rooms. In that mode the template drops
        # the "Doctor" column and labels the identifier column "Counter"
        # instead of "Room". A board with any practitioner keeps the full
        # Doctor | Room | Token layout.
        counter_layout = bool(sub_queues) and all(
            sub_queue.resource.resource_type != SchedulableResourceTypeOptions.practitioner.value
            for sub_queue in sub_queues
        )

        today = make_naive(timezone.now()).date()

        # Fetch token data for each sub-queue
        sub_queues_with_data = []
        for sub_queue in sub_queues:
            on_break = sub_queue.status == TokenSubQueueStatusOptions.inactive.value
            todays_tokens = Token.objects.filter(
                queue__resource=sub_queue.resource,
                queue__date=today,
                queue__is_primary=True,
            ).select_related("category")

            # "Now calling": the token has been called to this counter / room
            # but the patient has not arrived yet (status still CREATED). It
            # stays highlighted until the doctor starts serving it, however
            # long the patient takes to come.
            called_token = (
                todays_tokens.filter(sub_queue=sub_queue, status=TokenStatusOptions.CREATED.value)
                .order_by("-modified_date")
                .first()
            )
            # "In consultation": the patient is being served.
            serving_token = (
                todays_tokens.filter(sub_queue=sub_queue, status=TokenStatusOptions.IN_PROGRESS.value)
                .order_by("-modified_date")
                .first()
            )
            token = None if on_break else (called_token or serving_token)

            token_code = fmt_token_number(token) if token else None
            is_calling = bool(token and token == called_token)
            is_priority = bool(token and is_priority_token(token))

            # Next: tokens still waiting in the queue (not yet called to any
            # counter) in the order Serve Next calls them: emergency, then
            # high priority, then the rest, each in order of arrival.
            waiting = list(
                todays_tokens.filter(
                    sub_queue__isnull=True,
                    status=TokenStatusOptions.CREATED.value,
                ).order_by("created_date")[:500]
            )
            waiting.sort(key=token_priority_rank)
            upcoming_tokens = [fmt_token_number(t) for t in waiting[:2]]

            sub_queues_with_data.append(
                {
                    "id": str(sub_queue.external_id),
                    "sub_queue_name": sub_queue.name,
                    "resource_name": fmt_schedule_resource_name(sub_queue.resource),
                    "token": token_code or "--",
                    "token_code": token_code,
                    "upcoming_tokens": upcoming_tokens,
                    "is_calling": is_calling,
                    "is_priority": is_priority,
                    "on_break": on_break,
                }
            )

        missed_tokens = self.get_missed_tokens(sub_queues)

        # When no announcement languages are configured, suppress the
        # announcer markup entirely and let the static <meta refresh>
        # fallback (rendered in the template) drive page reloads.
        announcement_payload = (
            None
            if not va_langs
            else {
                "sub_queues": [
                    {"id": entry["id"], "token_code": entry["token_code"]} for entry in sub_queues_with_data
                ],
                "langs": va_langs,
                "auto_refresh_interval": plugin_settings.AUTO_REFRESH_INTERVAL,
            }
        )

        return Response(
            {
                "sub_queues": sub_queues_with_data,
                "item_count": item_count,
                "auto_refresh_interval": plugin_settings.AUTO_REFRESH_INTERVAL,
                "only_with_active_tokens": only_with_active_tokens,
                "announcement_payload": announcement_payload,
                "counter_layout": counter_layout,
                "missed_tokens": missed_tokens,
            }
        )

    def get_missed_tokens(self, sub_queues) -> list[str]:
        """
        Tokens marked "awaiting re-call" (unfulfilled) today for the resources
        shown on this board, most recently missed first. Patients use this to
        know they must report back to the counter.
        """
        limit = plugin_settings.MISSED_TOKENS_LIMIT
        if not limit or not sub_queues:
            return []
        resource_ids = {sub_queue.resource_id for sub_queue in sub_queues}
        missed_qs = (
            Token.objects.filter(
                queue__resource_id__in=resource_ids,
                queue__date=make_naive(timezone.now()).date(),
                queue__is_primary=True,
                status=TokenStatusOptions.UNFULFILLED.value,
            )
            .select_related("category")
            .order_by("-modified_date")[:limit]
        )
        return [fmt_token_number(t) for t in missed_qs]
