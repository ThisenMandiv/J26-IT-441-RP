# Deploying the itinerary API (Component 2)

The API runs as one Docker container. The same image works on **Render** (part A) and
**Google Cloud Run** (part B). Both have free tiers. Their limits change over time, so check the
current terms before relying on them.

## 1. Settings: environment variables only

| Variable              | Required | What it does |
|-----------------------|----------|--------------|
| `GOOGLE_MAPS_API_KEY` | no       | Real road travel times from Google. Unset = offline estimates (straight line x 1.3 at APPROX speeds), labelled `"travel_times": "estimated"` in every response. |
| `ALLOWED_ORIGINS`     | no       | Browser origins allowed to call the API (CORS), comma-separated, e.g. `https://trips.example.lk,http://localhost:5173`. Unset = no CORS headers, so browser pages on other sites are blocked. Server-to-server calls and curl work either way. |
| `API_KEY`             | no       | A shared secret. When set, `POST /itinerary`, `/reoptimize` and `/validate` need the header `X-API-Key: <value>`, or they answer **401**. `GET /health` and `/docs` stay open. |
| `PORT`                | set by the host | The port uvicorn listens on. Render and Cloud Run set it; the image defaults to 8080. |

Rules:

- Never put a key in the code, the Dockerfile, `render.yaml` or the repository. Enter keys in the
  host's dashboard (Render) or in Secret Manager (Cloud Run).
- The Google key counts from the environment **only in the container** (entry point
  `app.deploy:app`). Locally (`uvicorn app.main:app`) it is still read from `.env` only, so a stray
  shell variable never switches on paid Google calls (`config.API_GOOGLE_KEY_FROM_ENV`).
- An `API_KEY` used by a browser frontend is visible to anyone who opens the page's code. It keeps
  casual traffic and bots out, but it does not stop a determined person. It is real protection only
  for server-to-server calls.

The server also enforces two limits from `src/config.py` (both APPROX):

- At most `API_MAX_DESTINATIONS` = 50 destinations per request. A request with more gets **422**
  with the message `too many destinations: at most 50 per request, got N`.
- At most `API_MAX_BODY_BYTES` = 256 KB per request body. A larger body gets **413** with
  `request body is too large: ...`.

At startup the log shows one line like this (it shows whether each secret is set, never its value):

```
itinerary API starting: Google Maps key present; default profile realistic; X-API-Key required; CORS origins: https://trips.example.lk
```

**Cache.** Travel matrices are cached in `data/cache/`. If that folder cannot be written (a
read-only file system), the API uses `<temp dir>/itinerary-cache` instead. If the folder is
missing, it is made again. On Render and Cloud Run the disk is wiped when the container restarts,
so the cache starts empty each time. That makes requests slower (and uses more Google calls), but
the answers do not change.

## 2. Try the image locally (optional, needs Docker Desktop running)

From `backend/itinerary`:

```powershell
docker build -t itinerary-api .
docker run --rm -p 8080:8080 -e ALLOWED_ORIGINS=http://localhost:5173 -e API_KEY=dev-secret itinerary-api
curl http://localhost:8080/health
```

To use Google locally in the container, add `-e GOOGLE_MAPS_API_KEY=...` in your own terminal.
Do not put it in a file that is committed.

## A. Render (free web service)

`render.yaml` (in this folder) describes the service: Docker build, free plan, Singapore region,
health check `/health`, and the three variables. It holds names only, never values.

1. Commit and push `backend/itinerary` (Dockerfile, `.dockerignore`, `render.yaml`) to GitHub.
2. In the Render dashboard: **New → Blueprint**, connect the GitHub repository and pick the branch.
3. Set **Blueprint Path** to `backend/itinerary/render.yaml`. Render looks at the repository root by
   default, and this file is not there.
4. Render asks for the values of the three `sync: false` variables:
   - `GOOGLE_MAPS_API_KEY`: your key, or leave it empty for offline estimates.
   - `ALLOWED_ORIGINS`: your frontend's URL(s), comma-separated.
   - `API_KEY`: a long random string, or empty for an open API.
     A random value can be made with `venv\Scripts\python.exe -c "import secrets; print(secrets.token_urlsafe(32))"`.
5. Click **Apply**. Render builds the image and starts it. When `/health` answers, the service is live
   at `https://itinerary-api-XXXX.onrender.com`.
6. Check: open `https://<your-service>.onrender.com/health` and look at the **Logs** tab for the
   startup line.

Changing variables later: open the service, go to **Environment**, edit, then **Save** (Render
redeploys). Render asks for `sync: false` values only when the Blueprint is first created. After
that, it ignores them in `render.yaml` and you set them in the dashboard.

Without a Blueprint: **New → Web Service**, pick the repo, set Language **Docker**, Root Directory
`backend/itinerary`, Instance type **Free**, Health Check Path `/health`, and add the three
variables under **Environment**.

Free-plan behaviour (from Render's docs, checked October 2026): the service **sleeps after 15
minutes without traffic**. The next request wakes it, which takes about a minute. The disk is wiped
on each sleep and restart, so the matrix cache is lost.

## B. Google Cloud Run

Needs a Google Cloud project with billing enabled. Cloud Run has a free monthly allowance, but it
still needs a billing account. Install the [gcloud CLI](https://cloud.google.com/sdk/docs/install),
then in PowerShell from `backend/itinerary`:

1. Log in and choose the project:

   ```powershell
   gcloud auth login
   gcloud config set project YOUR_PROJECT_ID
   gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com secretmanager.googleapis.com
   ```

2. Store secrets in Secret Manager (optional, only the ones you use). Type the value when prompted,
   so it never appears in your command history:

   ```powershell
   $k = Read-Host "Google Maps key"; $k | gcloud secrets create google-maps-key --data-file=-
   $a = Read-Host "Shared API key";  $a | gcloud secrets create itinerary-api-key --data-file=-
   ```

   Let Cloud Run's service account read them. By default it is the Compute Engine default account
   `PROJECT_NUMBER-compute@developer.gserviceaccount.com`:

   ```powershell
   gcloud secrets add-iam-policy-binding google-maps-key --member=serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com --role=roles/secretmanager.secretAccessor
   gcloud secrets add-iam-policy-binding itinerary-api-key --member=serviceAccount:PROJECT_NUMBER-compute@developer.gserviceaccount.com --role=roles/secretmanager.secretAccessor
   ```

3. Build and deploy from source. Cloud Build uses the Dockerfile in this folder:

   ```powershell
   gcloud run deploy itinerary-api --source . --region asia-south1 --allow-unauthenticated `
     --memory 512Mi --max-instances 2 `
     --set-env-vars "^;^ALLOWED_ORIGINS=https://trips.example.lk,http://localhost:5173" `
     --set-secrets "GOOGLE_MAPS_API_KEY=google-maps-key:latest,API_KEY=itinerary-api-key:latest"
   ```

   - `^;^` tells gcloud to split variables on `;` instead of `,`, so the commas inside
     `ALLOWED_ORIGINS` are kept.
   - Leave out a secret in `--set-secrets` (or the whole flag) if you do not use it.
   - `--max-instances 2` caps cost. Cloud Run sets `PORT` (8080) itself.
   - `--allow-unauthenticated` makes the URL public. Access is then controlled by `API_KEY`.

4. gcloud prints the service URL. Check `https://<url>/health`, and look under **Cloud Run →
   itinerary-api → Logs** for the startup line.

Changing variables later (each change makes a new revision):

```powershell
gcloud run services update itinerary-api --region asia-south1 --update-env-vars "^;^ALLOWED_ORIGINS=https://new.example.lk"
gcloud run services update itinerary-api --region asia-south1 --remove-secrets API_KEY
```

Or in the console: **Cloud Run → itinerary-api → Edit & deploy new revision → Variables & Secrets**.

## 3. Calling a deployed API

```powershell
curl https://<your-service>/health
curl -X POST https://<your-service>/itinerary -H "Content-Type: application/json" -H "X-API-Key: <API_KEY>" --data "@request.json"
```

Notes for both hosts:

- **One plan at a time per instance.** The optimizer switches config flags for each request under
  a lock, so requests to one instance wait in a queue. A joint search takes up to `time_limit_s`
  (default 10 s, maximum 60 s). Both hosts allow requests that long.
- **Data honesty.** The deployed API returns the same MOCK, synthetic or APPROX labels and warnings
  as locally. Deploying does not make the estimates real.
