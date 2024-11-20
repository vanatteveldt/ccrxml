import aiohttp


async def ojs_get(base_url, token, endpoint, **params):
    url = f"{base_url.strip('/')}/api/v1/{endpoint.lstrip('/')}"
    async with aiohttp.ClientSession(headers={"User-Agent": "curl/8.5.0"}) as session:
        async with session.get(
            url, params=params, headers=dict(Authorization=f"Bearer {token}")
        ) as r:
            r.raise_for_status()
            return await r.json()


async def submission_metadata(base_url, token, id):
    pubid = (await ojs_get(base_url, token, f"/submissions/{id}"))[
        "currentPublicationId"
    ]
    meta = await ojs_get(base_url, token, f"/submissions/{id}/publications/{pubid}")
    if meta["issueId"]:
        meta["issue"] = await ojs_get(base_url, token, f"/issues/{meta['issueId']}")
    return meta


if __name__ == "__main__":
    import asyncio
    import json
    import os

    key = os.environ["CCR_KEY"]
    BASE = os.environ["OJS_URL"]

    async def main(key):
        print(key)
        d = await submission_metadata(BASE, key, 8778)
        print(json.dumps(d, indent=4))
        print(d["pub-id::doi"])
        print("-----")
        x = await ojs_get(BASE, key, "/submissions/180", stageId=5)
        print(json.dumps(x, indent=4))
        print("-----")
        x = await ojs_get(BASE, key, "/issues")
        print(json.dumps(x, indent=4))
        print("-----")
        x = await ojs_get(BASE, key, "/submissions/180/publications/114")
        print(json.dumps(x, indent=4))

    asyncio.run(main(key))
