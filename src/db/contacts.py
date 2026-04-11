from db.client import get_client


async def get_contact(client_id: str) -> dict | None:
    raise NotImplementedError


async def list_contacts() -> list[dict]:
    raise NotImplementedError


async def upsert_contact(data: dict) -> None:
    raise NotImplementedError
