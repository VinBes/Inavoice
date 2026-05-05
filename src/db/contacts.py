import asyncio

from db.client import get_client


async def get_contact(client_id: str) -> dict | None:
    def _sync():
        r = get_client().table("contacts").select("*").eq("client_id", client_id).execute()
        return r.data[0] if r.data else None

    return await asyncio.to_thread(_sync)


async def list_contacts() -> list[dict]:
    def _sync():
        return get_client().table("contacts").select("*").order("display_name").execute().data

    return await asyncio.to_thread(_sync)


async def upsert_contact(data: dict) -> None:
    def _sync():
        get_client().table("contacts").upsert(data, on_conflict="client_id").execute()

    await asyncio.to_thread(_sync)
