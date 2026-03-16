"""Deploy HTML report to Cloudflare Pages for sharing.

Uses `npx wrangler pages deploy` — the officially recommended method.
Wrangler reads CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID from env vars.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config


PROJECT_NAME = "marking-eval-report"


def deploy_report(html_path: str | Path) -> str | None:
    """Deploy the HTML report to Cloudflare Pages.

    Creates a temp directory with the HTML file as index.html, then runs
    ``npx wrangler pages deploy`` to upload it. Wrangler auto-creates
    the project on first deploy.

    Returns the production URL, or None on failure.
    """
    if not config.CLOUDFLARE_API_TOKEN or not config.CLOUDFLARE_ACCOUNT_ID:
        print("  SKIP deploy: CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID not set in .env")
        print("  To set up Cloudflare Pages deployment:")
        print("    1. Go to https://dash.cloudflare.com/")
        print("    2. Account ID is in the URL: dash.cloudflare.com/<ACCOUNT_ID>")
        print("    3. Create an API Token: My Profile > API Tokens > Create Token")
        print("       Use the 'Edit Cloudflare Pages' template")
        print("    4. Add both to your .env file:")
        print("       CLOUDFLARE_API_TOKEN=your-token")
        print("       CLOUDFLARE_ACCOUNT_ID=your-account-id")
        return None

    html_path = Path(html_path)
    if not html_path.exists():
        print(f"  ERROR: HTML file not found: {html_path}")
        return None

    print(f"\n  Deploying to Cloudflare Pages...")

    # Create temp directory with index.html (wrangler deploys a directory)
    tmp_dir = tempfile.mkdtemp(prefix="cf-deploy-")
    try:
        shutil.copy2(html_path, os.path.join(tmp_dir, "index.html"))

        result = subprocess.run(
            [
                "npx", "wrangler", "pages", "deploy",
                tmp_dir,
                f"--project-name={PROJECT_NAME}",
                "--branch=main",
                "--commit-dirty=true",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env={
                **os.environ,
                "CLOUDFLARE_API_TOKEN": config.CLOUDFLARE_API_TOKEN,
                "CLOUDFLARE_ACCOUNT_ID": config.CLOUDFLARE_ACCOUNT_ID,
            },
        )

        if result.returncode == 0:
            project_url = f"https://{PROJECT_NAME}.pages.dev"
            print(f"  Deployment successful!")
            print(f"    URL: {project_url}")

            # Try to extract preview URL from wrangler output
            for line in result.stdout.splitlines():
                stripped = line.strip()
                if stripped.startswith("https://") and ".pages.dev" in stripped:
                    print(f"    Preview: {stripped}")
                    break

            return project_url
        else:
            print(f"  ERROR deploying:")
            if result.stderr:
                for line in result.stderr.strip().splitlines()[-5:]:
                    print(f"    {line}")
            if result.stdout:
                for line in result.stdout.strip().splitlines()[-5:]:
                    print(f"    {line}")
            return None

    except FileNotFoundError:
        print("  ERROR: npx/wrangler not found. Install Node.js to enable deployment.")
        return None
    except subprocess.TimeoutExpired:
        print("  ERROR: Deployment timed out after 120s.")
        return None
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
