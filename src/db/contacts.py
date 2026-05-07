import asyncio

from db.client import get_client
from models.schemas import Contact


async def get_contact(client_id: str) -> Contact | None:
    def _sync():
        r = get_client().table("contacts").select("*").eq("client_id", client_id).execute()
        return r.data[0] if r.data else None

    row = await asyncio.to_thread(_sync)
    if row is None:
        return None
    return Contact.model_validate(row)


async def list_contacts() -> list[Contact]:
    def _sync():
        return get_client().table("contacts").select("*").order("display_name").execute().data

    rows = await asyncio.to_thread(_sync)
    return [Contact.model_validate(r) for r in rows]


async def upsert_contact(contact: Contact) -> None:
    payload = contact.model_dump(mode="json")

    def _sync():
        get_client().table("contacts").upsert(payload, on_conflict="client_id").execute()

    await asyncio.to_thread(_sync)
