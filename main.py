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

@app.get('/')
async def index(request: Request):
    key: str = request.cookies.get("ccrkey")
    if key:
        return templates.TemplateResponse("index.html", locals())
    else:
        return RedirectResponse("/login")

@app.get('/login')
async def login(request: Request):
    return templates.TemplateResponse("login.html", locals())

@app.post('/login')
async def index(request: Request, response: Response, key: Annotated[str, Form()]):
    try:
        await ojs_get(CCR, key, "/submissions", count=1)
    except Exception as e:
        error = f"Could not login, please check your API key. Error was: {e}"
        return templates.TemplateResponse("login.html", locals())

    response =  RedirectResponse("/", status_code=status.HTTP_302_FOUND)
    response.set_cookie(key="ccrkey",value=key, httponly=True)
    return response

@app.get('/logout')
async def login():
    response =  RedirectResponse("/", status_code=status.HTTP_302_FOUND)
    response.delete_cookie(key="ccrkey", httponly=True)
    return response


async def get_context(request, id):
    key: str = request.cookies.get("ccrkey")
    d = await submission_metadata(CCR, key, id)
    title = d['fullTitle']['en_US']
    abstract = d['abstract']['en_US']

    authors = [dict(name=f"{a['givenName']['en_US']} {a['familyName']['en_US']}",
                    affiliation=a['affiliation']['en_US'])
               for a in d['authors']]
    keywords = "; ".join(d['keywords']['en_US'])
    abstract_paras = [x for x in re.split("</?p>", abstract) if x]
    abstract_paras = [textwrap.fill(p, 120) for p in abstract_paras]
    keywords = [x.strip() for x in re.split("[,;]", keywords)]

    issue_id = d["issueId"]
    doi = d["pub-id::doi"]
    if issue_id:
        issue_title = d['issue']['title']['en_US']
        year = d['issue']['year']
        volume = d['issue']['volume']
        issue = d['issue']['number']
        fpage = 1
        fpage_source = "This is the first article in the issue"
        seqnr = 1
        num_unpublished = 0
        for article in d['issue']['articles']:
            if not article['statusLabel'] == 'Published':
                num_unpublished += 1
                continue
            seqnr += 1
            for pub in article['publications']:
                if pages := pub.get('pages'):
                    if m := re.match(r"(\d+)\s*-+\s*(\d+)", pages):
                        lp = m.group(2)
                        fpage = max(fpage, int(lp)+1)
                        fpage_source = f"Article #{article['id']} ({pub['authorsStringShort']})"
                    else:
                        fpage = None
                        fpage_source = f"Could not parse pages {pages}"
        if doi:
            doi_assigned = True
        else:
            last = d['authors'][0]['familyName']['en_US']
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


@app.post("/upload-link")
async def uploadlink(request: Request, id: Annotated[int, Form()], url: Annotated[str, Form()]):
    context = await get_context(request, id)
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as r:
            r.raise_for_status()
            print(dir(r))
            pdf_bytes = await r.read()
    return create_zip_response(context['doi'], context['jats_xml'], pdf_bytes)

@app.post("/upload-nopdf")
async def uploadlinknopdf(request: Request, id: Annotated[int, Form()]):
    context = await get_context(request, id)
    return create_zip_response(context['doi'], context['jats_xml'], None)


@app.post("/upload")
async def upload(request: Request, id: Annotated[int, Form()], file: UploadFile):
    context = await get_context(request, id)
    pdf_bytes = await file.read()
    return create_zip_response(context['doi'], context['jats_xml'], pdf_bytes)

def create_zip_response(doi, xml, pdf_bytes):
    zip_buffer = io.BytesIO()
    fn = doi.split("/")[1]
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        if pdf_bytes:
            zip_file.writestr(f'{fn}.pdf', pdf_bytes)
        zip_file.writestr(f'{fn}.xml', xml)

    return Response(zip_buffer.getvalue(),
                    media_type='application/x-zip-compressed',
                    headers={'Content-Disposition': f'attachment; filename="{fn}.zip"'})
