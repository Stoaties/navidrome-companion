"""navidrome-companion: management web app for a lightweight Pi music server.

Provides authenticated web UIs for downloading music (yt-dlp), importing Spotify
playlists (spotdl), and configuring the public domain and users. Sits in front of
Navidrome, which serves the actual library.
"""
import os
import secrets

from fastapi import FastAPI, Request, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.sessions import SessionMiddleware

from . import db, downloader, caddy

BASE_DIR = os.path.dirname(__file__)

app = FastAPI(title="navidrome-companion")
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")),
          name="static")


def _session_secret() -> str:
    secret = db.get_setting("session_secret")
    if not secret:
        secret = secrets.token_hex(32)
        db.set_setting("session_secret", secret)
    return secret


# Initialize storage and the signed-session middleware at import time, before
# the app serves any request (Starlette builds its middleware stack lazily on
# the first request, so add_middleware must run here, not in a startup hook).
db.init_db()

# Seed the default admin account on first boot only.
if db.count_users() == 0:
    db.create_user(
        os.environ.get("DEFAULT_ADMIN_USERNAME", "admin"),
        os.environ.get("DEFAULT_ADMIN_PASSWORD", "changeme"),
        is_admin=True,
        must_change_pw=True,
    )

app.add_middleware(SessionMiddleware, secret_key=_session_secret(),
                   max_age=60 * 60 * 24 * 7)


@app.on_event("startup")
def _startup():
    # Best-effort: align Caddy with stored settings once containers are up.
    try:
        caddy.push_config()
    except Exception:  # noqa: BLE001 - Caddy may not be up yet; ignore.
        pass


# ----------------------------------------------------------------- auth ---
def current_user(request: Request):
    return request.session.get("user")


def require_user(request: Request):
    user = current_user(request)
    if not user:
        raise HTTPException(status_code=307, headers={"Location": "/login"})
    return user


def require_admin(request: Request):
    user = require_user(request)
    row = db.get_user(user)
    if not row or not row["is_admin"]:
        raise HTTPException(status_code=403, detail="Admin only")
    return user


@app.exception_handler(HTTPException)
async def _auth_redirect(request: Request, exc: HTTPException):
    # Turn the 307 raised by require_user into an actual redirect for browsers.
    if exc.status_code == 307 and exc.headers and "Location" in exc.headers:
        return RedirectResponse(exc.headers["Location"], status_code=307)
    return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)


@app.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str | None = None):
    if current_user(request):
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        "login.html", {"request": request, "error": error})


@app.post("/login")
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    row = db.get_user(username)
    if row and db.verify_password(password, row["pw_salt"], row["pw_hash"]):
        request.session["user"] = username
        if row["must_change_pw"]:
            return RedirectResponse("/account?first=1", status_code=303)
        return RedirectResponse("/", status_code=303)
    return templates.TemplateResponse(
        "login.html",
        {"request": request, "error": "Invalid username or password."},
        status_code=401,
    )


@app.get("/logout")
def logout(request: Request):
    request.session.clear()
    return RedirectResponse("/login", status_code=303)


# ------------------------------------------------------------ dashboard ---
@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, user: str = Depends(require_user)):
    row = db.get_user(user)
    return templates.TemplateResponse(
        "dashboard.html",
        {
            "request": request,
            "user": user,
            "is_admin": bool(row["is_admin"]),
            "jobs": db.list_jobs(10),
            "domain": db.get_setting("public_domain", ""),
        },
    )


# ------------------------------------------------------------- downloads ---
@app.post("/download")
def download_url(request: Request, url: str = Form(...),
                 user: str = Depends(require_user)):
    url = url.strip()
    if url:
        downloader.enqueue("url", url)
    return RedirectResponse("/", status_code=303)


@app.post("/spotify")
def download_spotify(request: Request, url: str = Form(...),
                     user: str = Depends(require_user)):
    url = url.strip()
    if url:
        downloader.enqueue("spotify", url)
    return RedirectResponse("/", status_code=303)


@app.get("/api/jobs")
def api_jobs(request: Request, user: str = Depends(require_user)):
    return [dict(r) for r in db.list_jobs(20)]


@app.get("/api/jobs/{job_id}")
def api_job(job_id: str, request: Request, user: str = Depends(require_user)):
    row = db.get_job(job_id)
    if not row:
        raise HTTPException(404, "No such job")
    return dict(row)


# -------------------------------------------------------------- account ---
@app.get("/account", response_class=HTMLResponse)
def account(request: Request, first: int = 0, user: str = Depends(require_user)):
    return templates.TemplateResponse(
        "account.html",
        {"request": request, "user": user, "first": bool(first), "msg": None},
    )


@app.post("/account")
def change_password(request: Request, current: str = Form(...),
                    new: str = Form(...), confirm: str = Form(...),
                    user: str = Depends(require_user)):
    row = db.get_user(user)
    msg = None
    if not db.verify_password(current, row["pw_salt"], row["pw_hash"]):
        msg = ("error", "Current password is incorrect.")
    elif new != confirm:
        msg = ("error", "New passwords do not match.")
    elif len(new) < 6:
        msg = ("error", "New password must be at least 6 characters.")
    else:
        db.set_password(user, new)
        msg = ("ok", "Password updated.")
    return templates.TemplateResponse(
        "account.html",
        {"request": request, "user": user, "first": False, "msg": msg},
    )


# ------------------------------------------------------------- settings ---
@app.get("/settings", response_class=HTMLResponse)
def settings_page(request: Request, user: str = Depends(require_admin)):
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "domain": db.get_setting("public_domain", ""),
            "acme_email": db.get_setting("acme_email", ""),
            "spotify_client_id": db.get_setting("spotify_client_id", ""),
            "spotify_client_secret": db.get_setting("spotify_client_secret", ""),
            "users": db.list_users(),
            "msg": None,
        },
    )


@app.post("/settings")
def save_settings(request: Request, public_domain: str = Form(""),
                  acme_email: str = Form(""), spotify_client_id: str = Form(""),
                  spotify_client_secret: str = Form(""),
                  user: str = Depends(require_admin)):
    db.set_setting("public_domain", public_domain.strip())
    db.set_setting("acme_email", acme_email.strip())
    db.set_setting("spotify_client_id", spotify_client_id.strip())
    db.set_setting("spotify_client_secret", spotify_client_secret.strip())
    ok, message = caddy.push_config()
    msg = ("ok" if ok else "error", message)
    return templates.TemplateResponse(
        "settings.html",
        {
            "request": request,
            "user": user,
            "domain": public_domain.strip(),
            "acme_email": acme_email.strip(),
            "spotify_client_id": spotify_client_id.strip(),
            "spotify_client_secret": spotify_client_secret.strip(),
            "users": db.list_users(),
            "msg": msg,
        },
    )


@app.post("/users/add")
def add_user(request: Request, username: str = Form(...),
             password: str = Form(...), is_admin: str = Form(""),
             user: str = Depends(require_admin)):
    username = username.strip()
    if username and not db.get_user(username):
        db.create_user(username, password, is_admin=bool(is_admin),
                       must_change_pw=True)
    return RedirectResponse("/settings", status_code=303)


@app.post("/users/delete")
def remove_user(request: Request, username: str = Form(...),
                user: str = Depends(require_admin)):
    # Never allow deleting the last remaining account.
    if username != user and db.count_users() > 1:
        db.delete_user(username)
    return RedirectResponse("/settings", status_code=303)


@app.get("/healthz")
def healthz():
    return {"ok": True}
