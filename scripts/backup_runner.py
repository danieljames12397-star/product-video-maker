#!/usr/bin/env python3
"""Backup Post Queue runner.

Runs on GitHub Actions every 30 minutes. It does NOTHING while the Make
organization is active (Make's own Post Queue Runner 6949302 posts then).
Only when Make is paused (e.g. credits used up) does it read the Make data
store "Post Queue" (195844) through the Make API, publish every due
"pending" record itself, and write status/result back to the same record,
so Make never posts it a second time after it resumes.

Secrets (GitHub > Settings > Secrets and variables > Actions):
  MAKE_API_TOKEN   Make API token (scopes: organizations:read,
                   datastores:read, datastores:write)
  ZERNIO_API_KEY   Zernio API key   (TikTok)
  BUFFER_API_KEY   Buffer API key   (Threads)
  FB_PAGE_TOKEN    long-lived Facebook Page token (Facebook + Instagram);
                   optional - FB/IG records are left pending without it.
Env: FORCE=1 runs even if Make is active; DRY_RUN=1 posts nothing.
"""
import json, os, sys, time, urllib.request, urllib.parse, urllib.error
from datetime import datetime, timezone

MAKE = "https://us2.make.com/api/v2"
ORG, STORE = 9362514, 195844
PAGE_ID, IG_ID = "1204974132695138", "17841469376262589"
GRAPH = "https://graph.facebook.com/v27.0"

MAKE_TOKEN = os.environ.get("MAKE_API_TOKEN", "")
ZERNIO = os.environ.get("ZERNIO_API_KEY", "")
BUFFER = os.environ.get("BUFFER_API_KEY", "")
FB = os.environ.get("FB_PAGE_TOKEN", "")
FORCE = os.environ.get("FORCE") == "1"
DRY = os.environ.get("DRY_RUN") == "1"


def req(method, url, body=None, headers=None, form=None, timeout=120):
    h = dict(headers or {})
    data = None
    if form is not None:
        data = urllib.parse.urlencode(form).encode()
        h["Content-Type"] = "application/x-www-form-urlencoded"
    elif body is not None:
        data = body.encode() if isinstance(body, str) else json.dumps(body).encode()
        h["Content-Type"] = "application/json"
    r = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            txt = resp.read().decode()
            return resp.status, (json.loads(txt) if txt.strip() else {})
    except urllib.error.HTTPError as e:
        txt = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(txt)
        except Exception:
            return e.code, {"raw": txt[:500]}


def make(method, path, body=None):
    return req(method, MAKE + path, body, {"Authorization": "Token " + MAKE_TOKEN})


def parse_time(s):
    s = (s or "").strip()
    if not s:
        return None
    try:
        d = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:  # queue times without zone are Asia/Tokyo
        from datetime import timedelta
        d = d.replace(tzinfo=timezone(timedelta(hours=9)))
    return d


def list_records():
    out, offset = [], 0
    while True:
        st, js = make("GET", f"/data-stores/{STORE}/data?pg%5Blimit%5D=100&pg%5Boffset%5D={offset}")
        if st != 200:
            raise RuntimeError(f"Make data store read failed: {st} {js}")
        recs = js.get("records", [])
        out += recs
        if len(recs) < 100:
            return out
        offset += 100


def set_record(key, status, result):
    if DRY:
        print(f"  [dry-run] would set {key}: {status} {result}")
        return
    st, js = make("PATCH", f"/data-stores/{STORE}/data/{urllib.parse.quote(key)}",
                  {"status": status, "result": str(result)[:900]})
    if st not in (200, 201):
        print(f"  !! could not update record {key}: {st} {js}")


# ---------- networks ----------
def post_tiktok(d):
    if not ZERNIO:
        return None
    st, js = req("POST", "https://zernio.com/api/v1/posts", d["media_json"],
                 {"Authorization": "Bearer " + ZERNIO}, timeout=300)
    pid = (js.get("post") or {}).get("_id")
    return ("posted", f"{st} {pid} (backup)") if st == 201 and pid else ("error", f"{st} {js}")


def post_threads(d):
    if not BUFFER:
        return None
    st, js = req("POST", "https://api.buffer.com", d["media_json"],
                 {"Authorization": "Bearer " + BUFFER})
    cp = ((js.get("data") or {}).get("createPost") or {})
    pid = (cp.get("post") or {}).get("id")
    return ("posted", f"{pid} (backup)") if pid else ("error", f"{st} {cp.get('message') or js}")


def g(method, path, **form):
    form["access_token"] = FB
    return req(method, GRAPH + path, form=form, timeout=300)


def wait_container(cid, tries=30):
    for _ in range(tries):
        st, js = req("GET", f"{GRAPH}/{cid}?fields=status_code&access_token={FB}")
        code = js.get("status_code")
        if code == "FINISHED":
            return True
        if code == "ERROR":
            return False
        time.sleep(10)
    return False


def comment_ig(media_id, text):
    if text:
        time.sleep(20)
        g("POST", f"/{media_id}/comments", message=text)


def post_ig_carousel(d):
    files = json.loads(d["media_json"])["files"]
    kids = []
    for f in files:
        st, js = g("POST", f"/{IG_ID}/media", image_url=f["image_url"], is_carousel_item="true")
        if "id" not in js:
            return "error", f"IG item {st} {js}"
        kids.append(js["id"])
    st, js = g("POST", f"/{IG_ID}/media", media_type="CAROUSEL", children=",".join(kids), caption=d.get("caption", ""))
    if "id" not in js or not wait_container(js["id"]):
        return "error", f"IG carousel {st} {js}"
    st, pub = g("POST", f"/{IG_ID}/media_publish", creation_id=js["id"])
    if "id" not in pub:
        return "error", f"IG publish {st} {pub}"
    comment_ig(pub["id"], d.get("first_comment"))
    return "posted", f"{pub['id']} (backup)"


def post_ig_reel(d):
    st, js = g("POST", f"/{IG_ID}/media", media_type="REELS", video_url=d["video_url"],
               caption=d.get("caption", ""), share_to_feed="true")
    if "id" not in js or not wait_container(js["id"], 60):
        return "error", f"IG reel {st} {js}"
    st, pub = g("POST", f"/{IG_ID}/media_publish", creation_id=js["id"])
    if "id" not in pub:
        return "error", f"IG reel publish {st} {pub}"
    comment_ig(pub["id"], d.get("first_comment"))
    return "posted", f"{pub['id']} (backup)"


def post_fb_photos(d):
    files = json.loads(d["media_json"])["files"]
    ids = []
    for f in files:
        st, js = g("POST", f"/{PAGE_ID}/photos", url=f["url"], published="false")
        if "id" not in js:
            return "error", f"FB photo {st} {js}"
        ids.append({"media_fbid": js["id"]})
    st, js = g("POST", f"/{PAGE_ID}/feed", message=d.get("caption", ""), attached_media=json.dumps(ids))
    if "id" not in js:
        return "error", f"FB post {st} {js}"
    if d.get("first_comment"):
        g("POST", f"/{js['id']}/comments", message=d["first_comment"])
    return "posted", f"{js['id']} (backup)"


def post_fb_reel(d):
    st, js = g("POST", f"/{PAGE_ID}/video_reels", upload_phase="start")
    vid, up = js.get("video_id"), js.get("upload_url")
    if not vid:
        return "error", f"FB reel start {st} {js}"
    st2, js2 = req("POST", up, b"", {"Authorization": "OAuth " + FB, "file_url": d["video_url"]}, timeout=300)
    if not js2.get("success"):
        return "error", f"FB reel upload {st2} {js2}"
    st3, js3 = g("POST", f"/{PAGE_ID}/video_reels", upload_phase="finish", video_id=vid,
                 video_state="PUBLISHED", description=d.get("caption", ""), title=d.get("title", ""))
    return ("posted", f"{vid} (backup)") if js3.get("success") else ("error", f"FB reel finish {st3} {js3}")


HANDLERS = {
    "tiktok": post_tiktok,
    "threads": post_threads,
    "ig_carousel": lambda d: post_ig_carousel(d) if FB else None,
    "ig_reel": lambda d: post_ig_reel(d) if FB else None,
    "fb_photos": lambda d: post_fb_photos(d) if FB else None,
    "fb_reel": lambda d: post_fb_reel(d) if FB else None,
}


def check_keys():
    st, js = req("GET", "https://zernio.com/api/v1/accounts", headers={"Authorization": "Bearer " + ZERNIO})
    print("Zernio key:", "OK" if st == 200 else f"FAILED {st} {str(js)[:200]}")
    st, js = req("POST", "https://api.buffer.com", {"query": "query { account { id } }"},
                 {"Authorization": "Bearer " + BUFFER})
    ok = st == 200 and not js.get("errors")
    print("Buffer key:", "OK" if ok else f"FAILED {st} {str(js)[:200]}")
    if FB:
        st, me = req("GET", f"{GRAPH}/me?fields=id,name&access_token={FB}")
        print("FB token is for:", me.get("name"), me.get("id"),
              "(Deco Dwelling page OK)" if me.get("id") == PAGE_ID else f"(NOT the page! {st} {str(me)[:200]})")
        st, ig = req("GET", f"{GRAPH}/{IG_ID}?fields=username&access_token={FB}")
        print("Instagram access:", ig.get("username") or f"FAILED {st} {str(ig)[:200]}")
        st, dbg = req("GET", f"{GRAPH}/debug_token?input_token={FB}&access_token={FB}")
        d = dbg.get("data") or {}
        print("Token expires:", "never" if d.get("expires_at") == 0 else d.get("expires_at"),
              "| scopes:", ",".join(d.get("scopes") or []))
    else:
        print("FB_PAGE_TOKEN not set")


def main():
    if os.environ.get("CHECK_KEYS") == "1":
        check_keys()
    if not MAKE_TOKEN:
        print("MAKE_API_TOKEN secret missing - nothing to do.")
        return 0
    st, org = make("GET", f"/organizations/{ORG}")
    paused = (org.get("organization") or org).get("isPaused")
    print(f"Make org status {st}, isPaused={paused}")
    if st != 200:
        print("Could not reach Make API - not posting anything (avoids double posts).")
        return 1
    if not paused and not FORCE:
        print("Make is running - backup stays idle.")
        return 0

    now = datetime.now(timezone.utc)
    due = []
    for r in list_records():
        d = r.get("data") or {}
        t = parse_time(d.get("publish_at"))
        if d.get("status") == "pending" and t and t <= now:
            due.append((t, r["key"], d))
    due.sort()
    print(f"{len(due)} due pending record(s)")
    for t, key, d in due:
        net = d.get("network")
        h = HANDLERS.get(net)
        if not h:
            print(f"- {key}: network {net} not handled by backup (left pending)")
            continue
        if DRY:
            print(f"- {key}: [dry-run] would post {net}")
            continue
        try:
            res = h(d)
        except Exception as e:  # never crash the whole run
            res = ("error", f"backup exception: {e}")
        if res is None:
            print(f"- {key}: {net} needs a secret that isn't set yet (left pending)")
            continue
        print(f"- {key}: {net} -> {res[0]} {res[1][:200]}")
        set_record(key, *res)
    return 0


if __name__ == "__main__":
    sys.exit(main())
