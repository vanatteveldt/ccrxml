from fastapi import FastAPI, Request, Response, UploadFile
from fastapi.templating import Jinja2Templates
from fastapi.responses import RedirectResponse
import starlette.status as status
import re
from typing import Annotated
from ojs import ojs_get, submission_metadata
from fastapi import Form
import textwrap
import io
import zipfile


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


@app.get("/submission")
async def submission(request: Request, id: int, latex=None):
    key: str = request.cookies.get("ccrkey")
    d = await submission_metadata(CCR, key, id)

    title = d['fullTitle']['en_US']
    abstract = d['abstract']['en_US']

    authors = [dict(name=f"{a['givenName']['en_US']} {a['familyName']['en_US']}",
                    affiliation=a['affiliation']['en_US'])
               for a in d['authors']]
    keywords = "; ".join(d['keywords']['en_US'])

    if latex:
        if m := re.search(r"\\volume\{(\d+)\}", latex):
            volume = int(m.group(1))
        if m := re.search(r"\\pubyear\{(\d+)\}", latex):
            year = int(m.group(1))
        if m := re.search(r"\\pubnumber\{(\d+)\}", latex):
            issue = int(m.group(1))
        if m := re.search(r"\\firstpage\{(\d+)\}", latex):
            fpage = int(m.group(1))
        if m := re.search(r"\\doi\{([\d\.]+/.*)\}", latex):
            doi = m.group(1)


    return templates.TemplateResponse("submission.html", locals())

@app.post("/check")
async def check(request: Request,
                title: Annotated[str, Form()],
                abstract: Annotated[str, Form()],
                doi: Annotated[str, Form()],
                volume: Annotated[str, Form()],
                year: Annotated[str, Form()],
                issue: Annotated[str, Form()],
                fpage: Annotated[str, Form()],
                keywords: Annotated[str, Form()],
                ):
    form_data = await request.form()
    authors = []
    for i in range(10):
        name = form_data.get(f'author-{i}-name')
        if not name:
            break
        authors.append(dict(name=name, affiliation=form_data.get(f'author-{i}-affiliation')))
    abstract_paras = [x for x in re.split("</?p>", abstract) if x]
    abstract_paras = [textwrap.fill(p, 120) for p in abstract_paras]
    keywords = [x.strip() for x in re.split("[,;]", keywords)]
    xml = templates.get_template("jats.xml").render(locals())
    return templates.TemplateResponse("check.html", locals())

@app.post("/upload")
async def upload(xml: Annotated[str, Form()], doi: Annotated[str, Form()], file: UploadFile):
    zip_buffer = io.BytesIO()
    pdf_bytes = await file.read()
    fn = doi.split("/")[1]
    with zipfile.ZipFile(zip_buffer, mode="w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr(f'{fn}.pdf', pdf_bytes)
        zip_file.writestr(f'{fn}.xml', xml)

    return Response(zip_buffer.getvalue(),
                    media_type='application/x-zip-compressed',
                    headers={'Content-Disposition': f'attachment; filename="{fn}.zip"'})
