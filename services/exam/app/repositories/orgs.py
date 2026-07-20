from sqlalchemy.ext.asyncio import AsyncSession

from app.models.org import Org


async def create_org(session: AsyncSession, *, name: str) -> Org:
    org = Org(name=name)
    session.add(org)
    await session.flush()
    return org
