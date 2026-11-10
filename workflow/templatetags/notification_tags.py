from django import template

from workflow.notifications import unread_count

register = template.Library()


@register.inclusion_tag("workflow/notification_header.html", takes_context=True)
def notification_header(context):
    request = context.get("request")
    return {"notification_unread_count": unread_count(request.user if request else None)}
