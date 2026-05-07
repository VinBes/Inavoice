from datetime import date
from decimal import Decimal


def format_confirmation(data: dict) -> str:
    """Format the invoice preview message for Telegram confirmation."""
    lines = ["📋 Invoice Preview", ""]
    lines += [
        f"Client: {data['display_name']}",
        f"Description: {data['description']}",
        f"Service date: {data['service_date']}",
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
    invoice_date = data.get("invoice_date")
    due_date = data.get("due_date")
    if invoice_date or due_date:
        lines.append("")
        if invoice_date:
            lines.append(f"Invoice date: {_fmt_date(invoice_date)}")
        if due_date:
            lines.append(f"Due date: {_fmt_date(due_date)}")
    return "\n".join(lines)


def _fmt(value) -> str:
    """Format a Decimal or numeric value without trailing zeros or scientific notation."""
    return format(Decimal(str(value)).normalize(), "f")


def _fmt_date(value) -> str:
    if isinstance(value, date):
        return value.strftime("%-d %B %Y")
    return str(value)
