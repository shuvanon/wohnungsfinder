"""
formatter.py — Builds Telegram notification text.

Separated from telegram.py so the formatting logic can be tested
independently and swapped out if you add other notification channels.
"""

from filters.priority import PriorityResult


def format_notification(listing: dict, result: PriorityResult) -> str:
    """
    Build an HTML-formatted Telegram message for a single listing.

    The priority label and score appear at the top so the most important
    information is visible in the notification preview.
    """
    lines = [
        f"{result.label}  <b>(score: {result.score})</b>",
        "",
        f"🏠 <b>{listing.get('title') or listing.get('address') or 'New listing'}</b>",
        f"📍 {listing.get('address') or 'Address unknown'}",
        "",
        f"🛏  Rooms: <b>{listing.get('rooms', '?')}</b>   "
        f"📐 <b>{listing.get('size_m2', '?')} m²</b>",
        f"💶 Cold rent: <b>€{listing.get('cold_rent', '?')}</b>   "
        f"Total: <b>€{listing.get('total_rent', '?')}</b>",
        f"📋 WBS: {listing.get('wbs') or '—'}",
        f"🗓  Available: {listing.get('available') or '—'}",
        f"🏗  Built: {listing.get('year_built', '?')}   "
        f"Floor: {listing.get('floor') or '—'}",
    ]

    features = listing.get("features")
    if features:
        lines.append(f"✨ {', '.join(features)}")

    if result.reasons:
        lines += [
            "",
            "📊 <b>Priority breakdown:</b>",
        ]
        for reason in result.reasons:
            lines.append(f"   • {reason}")

    lines += [
        "",
        f'🔗 <a href="{listing.get("url", "")}">View full listing →</a>',
    ]

    return "\n".join(lines)
