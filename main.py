from functools import cache
import os
import sys
from fastapi import FastAPI, Request, Response, UploadFile
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
import starlette.status as status
import re
from typing import Annotated, Union, Optional
from ojs import ojs_get, submission_metadata
from fastapi import Form
import textwrap
import io
import zipfile
from unidecode import unidecode
import aiohttp

templates = Jinja2Templates(directory="templates")

app = FastAPI()


@app.get("/")
async def index(request: Request):
    key: str = request.cookies.get("ccrkey")
    backend_url = ojs_url()

    if key:
        return templates.TemplateResponse("index.html", locals())
    else:
        return RedirectResponse("/login")


@app.get("/login")
async def login(request: Request):
    return templates.TemplateResponse("login.html", locals())


@cache
def ojs_url():
    URL = os.environ.get("OJS_URL")
    if not URL:
        raise ValueError("Please set OJS_URL as environment variable!")
    return URL


@app.post("/login")
async def index(request: Request, response: Response, key: Annotated[str, Form()]):
    try:
        await ojs_get(ojs_url(), key, "/submissions", count=1)
    except Exception as e:
        error = f"Could not login, please check your API key. Error was: {e}"
        return templates.TemplateResponse("login.html", locals())

    response = RedirectResponse("/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(key="ccrkey", value=key, httponly=True)
    return response


@app.get("/logout")
async def login():
    response = RedirectResponse("/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="ccrkey", httponly=True)
    return response


def text(value, languages=("en_US", "en")):
    for language in languages:
        if language in value:
            return value[language]
    raise KeyError("Cannot find any of {`languages`} in `value`")


async def get_context(request, id):
    key: str = request.cookies.get("ccrkey")
    backend_url = ojs_url()
    d = await submission_metadata(backend_url, key, id)
    title = text(d["fullTitle"])
    abstract = text(d["abstract"])
    authors = [
        dict(
            name=f"{text(a['givenName'])} {text(a['familyName'])}",
            affiliation=text(a["affiliation"]),
        )
        for a in d["authors"]
    ]
    keywords = "; ".join(text(d["keywords"]))
    abstract_paras = [x for x in re.split("</?p>", abstract) if x]
    abstract_paras = [textwrap.fill(p, 120) for p in abstract_paras]
    keywords = [x.strip() for x in re.split("[,;]", keywords)]

    issue_id = d["issueId"]
    if "pub-id::oid" in d:
        doi = d["pub-id::doi"]
    elif "doiObject" in d:
        doi = d["doiObject"]["doi"] if d["doiObject"] else None
    else:
        raise ValueError("No DOI information present")

    if issue_id:
        issue_title = text(d["issue"]["title"])
        year = d["issue"]["year"]
        volume = d["issue"]["volume"]
        issue = d["issue"]["number"]
        if doi:
            doi_assigned = True
            if not (m := re.match(r"10.5117/CCR\d+.\d+.(\d+).\w+", doi)):
                raise Exception(r"Cannot parse doi! {doi}")
            seqnr = int(m.group(1))
        else:
            seqnr = 1
            for article in d["issue"]["articles"]:
                for pub in article["publications"]:
                    if pub_doi := pub["pub-id::doi"]:
                        if m := re.match(r"10.5117/CCR\d+.\d+.(\d+).\w+", pub_doi):
                            pub_seqnr = int(m.group(1))
                            if pub_seqnr >= seqnr:
                                seqnr = pub_seqnr + 1
                        else:
                            raise Exception(r"Cannot parse doi! {pub_doi}")
            last = text(d["authors"][0]["familyName"])
            last = re.sub(r"\W", "", unidecode(last).upper())[:4]
            doi = f"10.5117/CCR{year}.{issue}.{seqnr}.{last}"

        fpage = 1
    else:
        fpage_source = "Assign to an issue first"
    jats_xml = templates.get_template("jats.xml").render(locals())

    return locals()


@app.get("/submission")
async def submission(request: Request, id: int, latex=None):
    context = await get_context(request, id)

    return templates.TemplateResponse("submission.html", context)


@app.post("/upload-link", status_code=302)
async def uploadlink(
    request: Request, id: Annotated[int, Form()], url: Annotated[str, Form()]
):
    context = await get_context(request, id)
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            r.raise_for_status()
            pdf_bytes = await r.read()

    fn = context["doi"].split("/")[1]
    zip_bytes = create_zip(fn, context["jats_xml"], pdf_bytes)
    url = await post_tmpfile(f"{fn}.zip", zip_bytes)
    return RedirectResponse(url, status_code=302)

    # return create_zip_response(context['doi'], context['jats_xml'], pdf_bytes)


@app.post("/upload-nopdf")
async def uploadlinknopdf(request: Request, id: Annotated[int, Form()]):
    context = await get_context(request, id)
    return create_zip_response(context["doi"], context["jats_xml"], None)


@app.post("/upload")
async def upload(request: Request, id: Annotated[int, Form()], file: UploadFile):
    context = await get_context(request, id)
    pdf_bytes = await file.read()
    return create_zip_response(context["doi"], context["jats_xml"], pdf_bytes)


def create_zip_response(doi, xml, pdf_bytes):
    fn = doi.split("/")[1]
    zip_bytes = create_zip(fn, xml, pdf_bytes)

    return Response(
        zip_bytes,
        media_type="application/x-zip-compressed",
        headers={"Content-Disposition": f'attachment; filename="{fn}.zip"'},
    )


async def post_tmpfile(fn, bytes):
    bytesio = io.BytesIO(bytes)
    data = aiohttp.FormData()
    data.add_field("file", bytesio, filename=fn)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            "https://tmpfiles.org/api/v1/upload", data=data
        ) as response:
            print(response)
            response.raise_for_status()
            return (await response.json())["data"]["url"]


def create_zip(fn, xml, pdf_bytes):
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(
        zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED
    ) as zip_file:
        if pdf_bytes:
            zip_file.writestr(f"{fn}.pdf", pdf_bytes)
        zip_file.writestr(f"{fn}.xml", xml)
    return zip_buffer.getvalue()
