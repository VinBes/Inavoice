from models.schemas import InvoiceData


def format_confirmation(data: InvoiceData) -> str:
    lines = [
        f"*Invoice Preview*",
        f"Client: {data.client_id}",
        f"Date: {data.invoice_date}",
        f"Due: {data.due_date}",
        f"Description: {data.description}",
        "",
    ]
    for item in data.line_items:
        lines.append(f"  {item.description}: {item.quantity} × {item.unit_price} = {item.total}")
    lines.append(f"*Total: {data.total}*")
    return "\n".join(lines)
