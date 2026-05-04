from models.schemas import LLMOutput


async def parse_invoice_text(text: str, previous_data: dict | None = None) -> LLMOutput:
    raise NotImplementedError
