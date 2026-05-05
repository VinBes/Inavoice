from decimal import Decimal


def format_confirmation(data: dict) -> str:
    """Format the invoice preview message for Telegram confirmation."""
    lines = ["📋 Invoice Preview", ""]
    lines += [
        f"Client: {data['display_name']}",
        f"Description: {data['description']}",
        f"Date: {data['service_date']}",
        f"Service: {data['service_description']}",
    ]
    if data.get("rate_type") == "hourly":
        lines += [
            f"Time: {data['time_start']} – {data['time_end']} ({_fmt(data['hours'])} hrs)",
            f"Rate: {_fmt(data['rate'])} HKD/hr",
            f"Total: {_fmt(data['total'])} HKD",
        ]
    else:
        lines.append(f"Flat fee: {_fmt(data['total'])} HKD")
    return "\n".join(lines)


def _fmt(value) -> str:
    """Format a Decimal or numeric value without trailing zeros or scientific notation."""
    return format(Decimal(str(value)).normalize(), "f")
