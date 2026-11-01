"""Read-only intake options supplied by F1/F3; never accepted from POST data."""

from dataclasses import dataclass


@dataclass(frozen=True)
class CategoryOption:
    key: str
    name: str
    active: bool = True


@dataclass(frozen=True)
class LocationOption:
    key: str
    block: str
    room_area: str
    floor: str = ""
    active: bool = True

    @property
    def label(self):
        return " / ".join(value for value in (self.block, self.floor, self.room_area) if value)
