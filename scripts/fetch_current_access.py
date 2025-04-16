#!/usr/bin/env python3
"""
Fetch a full snapshot of the usdot‑fhwa‑stol organization’s
  • teams  (+ members + repo roles)
  • org admins / members
  • outside collaborators (+ repo roles)
  • individual repo collaborators (org members with one‑off access)

Results are written to `initial_current_access.json`, which you can
hand‑curate into `authorized_access.json`.
"""

import json
import os
import sys
from typing import Dict, List

import requests

ORG_NAME = "usdot-fhwa-stol"          # <-- change if you run for another org
OUTFILE  = "initial_current_access.json"

# --------------------------------------------------------------------------- #
#                             Helper: paginated GET                           #
# --------------------------------------------------------------------------- #
def github_api_get(url: str, params: Dict = None) -> List[Dict]:
    """
    GET with GitHub API v3, following pagination links automatically.
    Returns a list with ALL results across pages.
    """
    if params is None:
        params = {}

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        sys.exit("ERROR: GITHUB_TOKEN environment variable not set")

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept":        "application/vnd.github+json"
    }

    all_items: List[Dict] = []

    while url:
        resp = requests.get(url, headers=headers, params=params, timeout=30)
        resp.raise_for_status()

        data = resp.json()
        all_items.extend(data if isinstance(data, list) else [data])

        # Follow Link header pagination
        next_url = None
        if link_hdr := resp.headers.get("Link"):
            for link in link_hdr.split(","):
                seg_url, seg_rel = link.split(";")
                seg_rel = seg_rel.strip()
                if seg_rel == 'rel="next"':
                    next_url = seg_url.strip()[1:-1]  # drop < >
                    break
        url = next_url

    return all_items


# --------------------------------------------------------------------------- #
#                             Fetch teams + members                           #
# --------------------------------------------------------------------------- #
def fetch_teams_and_members() -> List[Dict]:
    teams_url = f"https://api.github.com/orgs/{ORG_NAME}/teams"
    teams     = github_api_get(teams_url)
    results   = []

    for t in teams:
        slug         = t["slug"]
        display_name = t["name"]

        # Team members
        members_url    = f"https://api.github.com/orgs/{ORG_NAME}/teams/{slug}/members"
        member_logins  = [m["login"] for m in github_api_get(members_url)]

        # Team repo permissions
        repos_url      = f"https://api.github.com/orgs/{ORG_NAME}/teams/{slug}/repos"
        repo_access    = []
        for repo in github_api_get(repos_url):
            repo_name = repo["name"]
            perms     = repo.get("permissions", {})
            role      = (
                "admin"    if perms.get("admin")    else
                "maintain" if perms.get("maintain") else
                "write"    if perms.get("push")     else
                "triage"   if perms.get("triage")   else
                "read"
            )
            repo_access.append({"name": repo_name, "role": role})

        results.append(
            {
                "name":        slug,          # canonical team slug
                "description": display_name,  # friendly display name
                "members":     member_logins,
                "repos":       repo_access
            }
        )

    return results


# --------------------------------------------------------------------------- #
#                      Fetch org‑level outside collaborators                  #
# --------------------------------------------------------------------------- #
def fetch_outside_collaborators() -> List[Dict]:
    collab_url  = f"https://api.github.com/orgs/{ORG_NAME}/outside_collaborators"
    outsiders   = [{"username": c["login"], "repos": []} for c in github_api_get(collab_url)]

    # Build quick lookup for speed
    outsider_index = {o["username"]: o for o in outsiders}

    # Loop through repos to capture each outsider’s repo‑specific role
    repos_url = f"https://api.github.com/orgs/{ORG_NAME}/repos"
    for repo in github_api_get(repos_url):
        repo_name     = repo["name"]
        collabs_url   = f"https://api.github.com/repos/{ORG_NAME}/{repo_name}/collaborators"
        for rc in github_api_get(collabs_url):
            user = rc["login"]
            if user in outsider_index:           # only care about outsiders
                perms = rc.get("permissions", {})
                role = (
                    "admin"    if perms.get("admin")    else
                    "maintain" if perms.get("maintain") else
                    "write"    if perms.get("push")     else
                    "triage"   if perms.get("triage")   else
                    "read"
                )
                outsider_index[user]["repos"].append({"name": repo_name, "role": role})

    return outsiders


# --------------------------------------------------------------------------- #
#       Fetch org members who have individual collaborator permissions       #
# --------------------------------------------------------------------------- #
def fetch_individual_collaborators() -> List[Dict]:
    """
    Captures org members who have direct repo access *outside* of their team rights.
    If your org uses only team‑based permissions you can skip this.
    """
    indiv: List[Dict] = []
    repos_url         = f"https://api.github.com/orgs/{ORG_NAME}/repos"

    # Build a set of all org members (to distinguish from outside collabs)
    members_url       = f"https://api.github.com/orgs/{ORG_NAME}/members?role=all"
    org_members       = {m["login"] for m in github_api_get(members_url)}

    for repo in github_api_get(repos_url):
        repo_name   = repo["name"]
        collabs_url = f"https://api.github.com/repos/{ORG_NAME}/{repo_name}/collaborators"

        for rc in github_api_get(collabs_url):
            user = rc["login"]
            if user in org_members:  # internal user
                perms = rc.get("permissions", {})
                role = (
                    "admin"    if perms.get("admin")    else
                    "maintain" if perms.get("maintain") else
                    "write"    if perms.get("push")     else
                    "triage"   if perms.get("triage")   else
                    "read"
                )
                indiv.append({"username": user, "repo": repo_name, "role": role})

    return indiv


# --------------------------------------------------------------------------- #
#                                     main                                   #
# --------------------------------------------------------------------------- #
def main() -> None:
    print(f"Fetching access snapshot for org: {ORG_NAME}")

    # org admins / members
    admins_url   = f"https://api.github.com/orgs/{ORG_NAME}/members?role=admin"
    members_url  = f"https://api.github.com/orgs/{ORG_NAME}/members?role=member"
    org_admins   = [a["login"] for a in github_api_get(admins_url)]
    org_members  = [m["login"] for m in github_api_get(members_url)]

    # data collections
    teams_data   = fetch_teams_and_members()
    outside_coll = fetch_outside_collaborators()
    indiv_collab = fetch_individual_collaborators()

    snapshot = {
        "organization":                ORG_NAME,
        "org_admins":                  org_admins,
        "org_members":                 org_members,
        "teams":                       teams_data,
        "outside_collaborators":       outside_coll,
        "individual_repo_collaborators": indiv_collab
    }

    with open(OUTFILE, "w", encoding="utf-8") as fh:
        json.dump(snapshot, fh, indent=2)

    print(f"✓ Wrote {OUTFILE} ({len(snapshot['teams'])} teams, "
          f"{len(snapshot['outside_collaborators'])} outside collaborators)")


if __name__ == "__main__":
    main()
