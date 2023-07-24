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
CCR = "https://computationalcommunication.org/ccr"


@app.get("/")
async def index(request: Request):
    key: str = request.cookies.get("ccrkey")
    if key:
        return templates.TemplateResponse("index.html", locals())
    else:
        return RedirectResponse("/login")


@app.get("/login")
async def login(request: Request):
    return templates.TemplateResponse("login.html", locals())


@app.post("/login")
async def index(request: Request, response: Response, key: Annotated[str, Form()]):
    try:
        await ojs_get(CCR, key, "/submissions", count=1)
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


async def get_context(request, id):
    key: str = request.cookies.get("ccrkey")
    d = await submission_metadata(CCR, key, id)
    title = d["fullTitle"]["en_US"]
    abstract = d["abstract"]["en_US"]

    authors = [
        dict(
            name=f"{a['givenName']['en_US']} {a['familyName']['en_US']}",
            affiliation=a["affiliation"]["en_US"],
        )
        for a in d["authors"]
    ]
    keywords = "; ".join(d["keywords"]["en_US"])
    abstract_paras = [x for x in re.split("</?p>", abstract) if x]
    abstract_paras = [textwrap.fill(p, 120) for p in abstract_paras]
    keywords = [x.strip() for x in re.split("[,;]", keywords)]

    issue_id = d["issueId"]
    doi = d["pub-id::doi"]
    if issue_id:
        seqnr = 1
        issue_title = d["issue"]["title"]["en_US"]
        year = d["issue"]["year"]
        volume = d["issue"]["volume"]
        issue = d["issue"]["number"]

        for article in d["issue"]["articles"]:
            for pub in article["publications"]:
                if pub_doi := pub["pub-id::doi"]:
                    if m := re.match(r"10.5117/CCR\d+.\d+.(\d+).\w+", pub_doi):
                        pub_seqnr = int(m.group(1))
                        if pub_seqnr >= seqnr:
                            seqnr = pub_seqnr + 1
                    else:
                        raise Exception(r"Cannot parse doi! {pub_doi}")
        fpage = (seqnr - 1) * 100 + 1
        if doi:
            doi_assigned = True
        else:
            last = d["authors"][0]["familyName"]["en_US"]
            last = re.sub(r"\W", "", unidecode(last).upper())[:4]
            doi = f"10.5117/CCR{year}.{issue}.{seqnr}.{last}"

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
