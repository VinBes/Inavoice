import asyncio
import pathlib

import jinja2
import structlog

import config

log = structlog.get_logger()

_BASE = pathlib.Path(__file__).parent.parent  # src/

_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(str(_BASE / "templates")),
    autoescape=True,
)


async def generate_pdf(data: dict, invoice_number: str) -> bytes:
    """Render the Jinja2 invoice template and convert to PDF bytes via WeasyPrint."""
    def _sync() -> bytes:
        import weasyprint  # lazy: requires native Pango/GObject libs (present in Docker, not macOS)
        tpl = _env.get_template("invoice.html")
        html = tpl.render(
            invoice_number=invoice_number,
            invoice_date=_fmt_date(data["invoice_date"]),
            due_date=_fmt_date(data["due_date"]),
            display_name=data["display_name"],
            address_lines=_split_lines(data.get("address", "")),
            description=data["description"],
            service_date=data["service_date"],
            service_description=data["service_description"],
            time_start=data.get("time_start"),
            time_end=data.get("time_end"),
            hours=data.get("hours"),
            rate=data.get("rate"),
            rate_type=data["rate_type"],
            total=data["total"],
            sender_name=config.SENDER_NAME,
            sender_address_lines=_split_lines(config.SENDER_ADDRESS),
            account_holder=config.ACCOUNT_HOLDER,
            bank_name=config.BANK_NAME,
            bank_code=config.BANK_CODE,
            bank_account=config.BANK_ACCOUNT,
            fps_id=config.FPS_ID,
            business_registration=config.BUSINESS_REGISTRATION,
        )
        return weasyprint.HTML(string=html, base_url=str(_BASE)).write_pdf()

    pdf_bytes = await asyncio.to_thread(_sync)
    log.info("pdf_generator.generated", invoice_number=invoice_number, size=len(pdf_bytes))
    return pdf_bytes


def _fmt_date(d) -> str:
    return d.strftime("%-d %B %Y")


def _split_lines(text: str) -> list[str]:
    return [line.strip() for line in text.split("\n") if line.strip()]
