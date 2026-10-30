"""Package Bóc Tách Dữ Liệu Chuyến Xe & Container (Parsing Layer)."""

from src.parsing.ai_fallback import AIFallbackExtractor
from src.parsing.trip_parser import TripParser

__all__ = ["AIFallbackExtractor", "TripParser"]
