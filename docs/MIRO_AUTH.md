# Miro Authentication Guide

This guide covers every method of authenticating with the Miro REST API v2
and explains how to use each method with `lucid2miro --upload`.

---

## Quick start (Personal Access Token — recommended for CLI use)

```bash
# 1. Create a token (one-time setup — see § Creating a Personal Access Token below)
# 2. Set the environment variable
export MIRO_TOKEN=your_token_here          # macOS / Linux
$env:MIRO_TOKEN = "your_token_here"        # Windows PowerShell

# 3. Upload
python lucid2miro.py diagram.csv --upload
```

---

## Authentication methods

### Method 1 — Personal Access Token (PAT)  ✅ Recommended for CLI

A PAT is the simplest authentication method.  It is tied to your Miro account
and acts on your behalf.

**When to use:**  
- Running the CLI manually or in automation scripts  
- Personal / team use  
- No need to act as another user  

**How to create a PAT:**

1. Log in to Miro → click your profile icon (top right) → **Profile settings**.  
2. In the left sidebar select **Your apps**.  
3. Click **Create new app**.  
4. Enter an app name (e.g. `lucid2miro`) and choose a team.  
5. Click **Create app**.  
6. Under **OAuth scopes**, enable:  
   - `boards:read` — to verify an existing board  
   - `boards:write` — to create boards and add items  
7. Scroll to **Access tokens** → click **Copy** next to the access token.  

> **Security tip:** Treat the token like a password.  Never commit it to source
> control.  Store it in an environment variable or a secrets manager.

**Using the token:**

```bash
# Option A — environment variable (recommended)
export MIRO_TOKEN=eyJhbGciOiJSU...
python lucid2miro.py diagram.csv --upload

# Option B — command-line flag (visible in shell history)
python lucid2miro.py diagram.csv --upload --token eyJhbGciOiJSU...
```

**Token scopes required:**

| Scope         | When needed                                    |
|---------------|------------------------------------------------|
| `boards:read` | `--board-id` (verifying an existing board)     |
| `boards:write`| Creating boards, frames, shapes, connectors    |

---

### Method 2 — OAuth 2.0  (for app integrations)

OAuth 2.0 is used when your application needs to act on behalf of other users,
or when distributing the tool to users who each have their own Miro accounts.

**When to use:**  
- Building a web app or multi-user integration  
- Acting on behalf of users other than the token owner  

**Flow overview (Authorization Code):**

```
1. Redirect the user to:
   https://miro.com/oauth/authorize
     ?response_type=code
     &client_id=<YOUR_CLIENT_ID>
     &redirect_uri=<YOUR_REDIRECT_URI>

2. User approves → Miro redirects to your URI with ?code=<AUTH_CODE>

3. Exchange the code for a bearer token:
   POST https://api.miro.com/v1/oauth/token
   Content-Type: application/x-www-form-urlencoded

   grant_type=authorization_code
   &client_id=<YOUR_CLIENT_ID>
   &client_secret=<YOUR_CLIENT_SECRET>
   &code=<AUTH_CODE>
   &redirect_uri=<YOUR_REDIRECT_URI>

4. Use the returned access_token as the bearer token:
   Authorization: Bearer <access_token>
```

The OAuth bearer token is structurally identical to a PAT — pass it via
`MIRO_TOKEN` or `--token`.

**Token refresh:**  
OAuth tokens expire.  Use the `refresh_token` from step 3 to get a new token:

```
POST https://api.miro.com/v1/oauth/token
grant_type=refresh_token&refresh_token=<REFRESH_TOKEN>&...
```

---

### Method 3 — Service Account / CI/CD

For automated pipelines (GitHub Actions, Jenkins, etc.) use a PAT stored as
a secret:

**GitHub Actions example:**

```yaml
env:
  MIRO_TOKEN: ${{ secrets.MIRO_TOKEN }}

steps:
  - name: Upload diagrams to Miro
    run: |
      python lucid2miro.py ./exports/ --format csv --upload \
        --output-dir ./converted/
```

**GitLab CI / CD:**

```yaml
variables:
  MIRO_TOKEN: $MIRO_TOKEN   # set in Settings → CI/CD → Variables

upload_to_miro:
  script:
    - python lucid2miro.py diagram.csv --upload --summary
```

---

## Board targeting options

### Create a new board (default)

```bash
python lucid2miro.py diagram.csv --upload
```

The tool creates a new board using the document title as the board name.
Override with `--board-name` or `-t`:

```bash
python lucid2miro.py diagram.csv --upload -t "Q3 Architecture"
```

### Target a specific team / workspace

Find your team ID in Miro: **Team settings** → the URL contains
`/app/settings/team/<TEAM_ID>/`.

```bash
python lucid2miro.py diagram.csv --upload --team-id 3141592
```

### Upload into an existing board

Append content to a board that already exists:

```bash
python lucid2miro.py diagram.csv --upload --board-id uXjVPabc1234=
```

The board ID is the long alphanumeric string in the board's URL:  
`https://miro.com/app/board/uXjVPabc1234=/`

---

## Naming options

All naming flags apply in both single-file and batch modes.

### Board name

| Flag | Effect | Example |
|------|--------|---------|
| *(none)* | Uses source document title | `"My AWS Architecture"` |
| `--board-name NAME` | Explicit board title | `--board-name "Sprint 12 Infra"` |
| `-t NAME` | Alias for `--board-name` | `-t "Sprint 12 Infra"` |

### Frame names (one frame per Lucidchart page/tab)

| Flag | Effect | Example output |
|------|--------|----------------|
| *(none)* | Uses page title as-is | `"Production VPC"` |
| `--frame-prefix PREFIX` | Prepends text | `--frame-prefix "Q3: "` → `"Q3: Production VPC"` |
| `--frame-suffix SUFFIX` | Appends text | `--frame-suffix " (Draft)"` → `"Production VPC (Draft)"` |

Both flags can be combined:

```bash
python lucid2miro.py diagram.csv --upload \
  --frame-prefix "2026 Arch: " \
  --frame-suffix " [Review]"
# → "2026 Arch: Production VPC [Review]"
```

---

## Board access / sharing policy

Control who can access newly created boards:

| Flag value | Behaviour |
|------------|-----------|
| `private` *(default)* | Only you (the token owner) can access the board |
| `view` | Anyone with the link can view |
| `comment` | Anyone with the link can comment |
| `edit` | Anyone with the link can edit |

```bash
python lucid2miro.py diagram.csv --upload --access view
```

---

## Custom icons (icon map)

Lucidchart exports do not embed image data.  SVG icons and custom shapes
appear as empty `image` placeholders unless you supply an icon map.

### Icon map format

Create a JSON file (e.g. `icon-map.json`) with any combination of:

```json
{
  "by_id": {
    "shape-abc123": "https://cdn.example.com/icons/ec2.png",
    "shape-def456": "https://cdn.example.com/icons/s3.png"
  },
  "by_name": {
    "AmazonEC2":    "https://cdn.example.com/icons/ec2.png",
    "AWSLambda":    "https://cdn.example.com/icons/lambda.png",
    "SVGPathBlock2":"https://cdn.example.com/icons/generic.svg"
  },
  "default": "https://cdn.example.com/icons/placeholder.png"
}
```

- `by_id` — matches on Lucidchart shape ID (from the CSV `Id` column)
- `by_name` — matches on shape name / class (from CSV `Name` or JSON `class`)
- `default` — fallback URL used when no specific match is found

If no match is found and no `default` is set, the icon is skipped and
counted in the upload summary's `Skipped icons` line.

### Using the icon map

```bash
python lucid2miro.py diagram.csv --upload --icon-map icon-map.json
```

### Finding shape IDs

Run a dry-run with `--summary` to see all icon shape names before uploading:

```bash
python lucid2miro.py diagram.csv --upload --dry-run --summary
```

---

## Dry run — simulate without uploading

```bash
python lucid2miro.py diagram.csv --upload --dry-run
python lucid2miro.py diagram.csv --upload --dry-run --summary  # verbose output
```

Dry-run mode lays out the diagram and prints what would be created, but
makes no API calls and does not require a valid token.

---

## Troubleshooting

### HTTP 401 — Authentication failed

- Verify the token is copied correctly (no leading/trailing spaces).
- Confirm the token has not expired or been revoked.
- Re-generate the token in Miro: **Profile settings → Your apps → [app name] → Tokens**.
- Confirm you set `MIRO_TOKEN` (not `MIRO_API_TOKEN` or similar).

### HTTP 403 — Permission denied

- Verify the token scope includes `boards:write`.
- If using `--team-id`, confirm you are a member of that team.
- Some Miro plans restrict board creation to specific roles — check with your Miro admin.

### HTTP 429 — Rate limit

- The tool retries automatically (up to 3 times, respecting `Retry-After`).
- For very large diagrams (hundreds of shapes), consider splitting into batches.

### Board not visible after upload

- New boards default to `--access private`.  The board is only visible to the
  token owner unless you set `--access view|comment|edit` or share the board manually.
- Check **My boards** in Miro: `https://miro.com/app/dashboard/`

---

## API reference links

- Miro REST API v2 overview: https://developers.miro.com/docs/rest-api-reference  
- Authentication & scopes: https://developers.miro.com/docs/getting-started  
- Boards endpoint: https://developers.miro.com/reference/boards  
- Frames endpoint: https://developers.miro.com/reference/frames  
- Shapes endpoint: https://developers.miro.com/reference/shapes  
- Connectors endpoint: https://developers.miro.com/reference/connectors  
- Rate limits: https://developers.miro.com/docs/rest-api-rate-limiting  
