from django.core.checks import Error, Tags, register
from django.core.exceptions import ValidationError

from .feedback_policy import maximum_reopens


@register(Tags.models)
def check_reopen_policy(app_configs, **kwargs):
    try:
        maximum_reopens()
    except ValidationError:
        return [Error("COMPLAINT_MAX_REOPENS must be an integer from 0 to 32767.",
                      id="workflow.E001")]
    return []
