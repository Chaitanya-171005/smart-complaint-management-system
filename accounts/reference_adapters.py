"""F1's side of the B07 intake contract (docs/B07.md): supply location options for the form.

``LocationOption.key`` is the stable canonical location code, the same value B17 routing rules
use. Only active locations are offered; a renamed block or room keeps its code.
"""

from complaints.reference_data import LocationOption

from .models import Location


def location_options():
    """Active locations as read-only ``LocationOption`` objects, ordered for display."""
    return tuple(
        LocationOption(key=loc.code, block=loc.block, room_area=loc.room_area, floor=loc.floor)
        for loc in Location.objects.filter(active=True).order_by("block", "floor", "room_area")
    )
