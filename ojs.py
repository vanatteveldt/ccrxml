
import aiohttp

async def ojs_get(base_url, token, endpoint, **params):
    url = f"{base_url.strip('/')}/api/v1/{endpoint.lstrip('/')}"
    async with aiohttp.ClientSession() as session:
        async with session.get(url, params=params, headers=dict(Authorization=f"Bearer {token}")) as r:
            r.raise_for_status()
            return await r.json()

async def submission_metadata(base_url, token, id):
    pubid = (await ojs_get(base_url, token, f"/submissions/{id}"))['currentPublicationId']
    return await ojs_get(base_url, token, f"/submissions/{id}/publications/{pubid}")


if __name__=='__main__':
    import asyncio
    import json
    KEY = "..."
    BASE = "https://computationalcommunication.org/ccr"
    async def main(BASE, KEY):
        d = await submission_metadata(BASE, KEY, 188)
        print(json.dumps(d, indent=4))

    asyncio.run(main(BASE, KEY))
