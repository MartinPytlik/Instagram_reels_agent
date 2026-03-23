"""
Datové modely Instagram Reels Bota.
"""

from enum import Enum


class PredictedActionType(str, Enum):
    """Typ akce vrácené prediktorem."""
    LIKE             = "like"
    SAVE             = "save"
    SKIP             = "skip"
    FINISH_WATCHING  = "finish_watching"
    CONTINUE_WATCHING = "continue_watching"
    REWATCH          = "rewatch"


class PredictedAction:
    """Jedna akce doporučená prediktorem, volitelně s délkou trvání."""

    def __init__(self, action_type: PredictedActionType, seconds: int | None = None):
        self.action_type = action_type
        self.seconds = seconds

    def to_string(self) -> str:
        if self.action_type == PredictedActionType.CONTINUE_WATCHING and self.seconds:
            return f"continue_watching_for: {self.seconds} seconds"
        return self.action_type.value

    def __repr__(self) -> str:
        return f"PredictedAction({self.to_string()!r})"
