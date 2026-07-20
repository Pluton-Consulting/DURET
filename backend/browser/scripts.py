"""
Scripts Python auto-contenus exécutés dans les sandboxes Daytona.

Chaque script :
- Est une string Python complète et autonome
- Installe ses propres dépendances si absentes
- Communique via stdout (JSON)
- Ne dépend d'aucun module du backend Duret & Sols

Format de sortie systématique :
{
  "success": bool,
  "results": [...],      # Liste de { url, title, content }
  "error": str | null,
  "execution_time_ms": int
}
"""

SEARCH_SCRIPT = '''
import asyncio, json, sys, time
from urllib.parse import quote_plus

async def main(query: str, max_results: int, timeout_ms: int):
    start = time.monotonic()
    results = []

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        import subprocess
        subprocess.run(["pip", "install", "playwright", "-q"], check=True)
        subprocess.run(
            ["python", "-m", "playwright", "install", "chromium", "--with-deps"],
            check=True
        )
        from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage",
                "--disable-extensions", "--mute-audio", "--no-first-run",
            ]
        )

        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (compatible; Duret & Sols-Agent/1.0)",
            accept_downloads=False,
        )
        page = await ctx.new_page()
        await page.route("**/*.{png,jpg,jpeg,gif,webp,ico,woff,woff2,mp4}", lambda r: r.abort())

        search_url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        await page.goto(search_url, timeout=timeout_ms, wait_until="domcontentloaded")

        links = await page.evaluate("""
            () => {
                const out = [];
                document.querySelectorAll("a.result__url").forEach(el => {
                    const h = el.getAttribute("href") || "";
                    if (h.startsWith("http")) out.push(h);
                });
                return out;
            }
        """)
        await ctx.close()

        for url in links[:max_results]:
            try:
                ctx2 = await browser.new_context(
                    user_agent="Mozilla/5.0 (compatible; Duret & Sols-Agent/1.0)",
                    accept_downloads=False,
                )
                p2 = await ctx2.new_page()
                await p2.route(
                    "**/*.{png,jpg,jpeg,gif,webp,ico,woff,woff2,mp4,mp3}",
                    lambda r: r.abort()
                )
                await p2.goto(url, timeout=10000, wait_until="domcontentloaded")
                title = await p2.title()
                content = await p2.evaluate("""
                    () => {
                        ["script","style","nav","footer","header","aside","iframe"]
                            .forEach(t => document.querySelectorAll(t).forEach(e => e.remove()));
                        return (document.body.innerText || "")
                            .replace(/\\n{3,}/g, "\\n\\n")
                            .replace(/[ \\t]{2,}/g, " ")
                            .trim()
                            .slice(0, 6000);
                    }
                """)
                results.append({"url": p2.url, "title": title, "content": content})
                await ctx2.close()
                await asyncio.sleep(0.4)
            except Exception as e:
                results.append({"url": url, "title": None, "content": None, "error": str(e)})

        await browser.close()

    elapsed = int((time.monotonic() - start) * 1000)
    print(json.dumps({
        "success": len([r for r in results if r.get("content")]) > 0,
        "results": results,
        "error": None,
        "execution_time_ms": elapsed,
    }))

QUERY = "{query}"
MAX_RESULTS = {max_results}
TIMEOUT_MS = {timeout_ms}
asyncio.run(main(QUERY, MAX_RESULTS, TIMEOUT_MS))
'''


FETCH_SCRIPT = '''
import asyncio, json, time

async def main(url: str, timeout_ms: int):
    start = time.monotonic()

    try:
        from playwright.async_api import async_playwright
    except ImportError:
        import subprocess
        subprocess.run(["pip", "install", "playwright", "-q"], check=True)
        subprocess.run(
            ["python", "-m", "playwright", "install", "chromium", "--with-deps"],
            check=True
        )
        from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=["--no-sandbox", "--disable-gpu", "--disable-dev-shm-usage"],
        )
        ctx = await browser.new_context(
            user_agent="Mozilla/5.0 (compatible; Duret & Sols-Agent/1.0)",
            accept_downloads=False,
        )
        page = await ctx.new_page()
        await page.route(
            "**/*.{png,jpg,jpeg,gif,webp,ico,woff,woff2,mp4}",
            lambda r: r.abort()
        )

        try:
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
            title = await page.title()
            content = await page.evaluate("""
                () => {
                    ["script","style","nav","footer","header","aside","iframe"]
                        .forEach(t => document.querySelectorAll(t).forEach(e => e.remove()));
                    return (document.body.innerText || "")
                        .replace(/\\n{3,}/g, "\\n\\n")
                        .replace(/[ \\t]{2,}/g, " ")
                        .trim()
                        .slice(0, 8000);
                }
            """)
            elapsed = int((time.monotonic() - start) * 1000)
            print(json.dumps({
                "success": True,
                "results": [{"url": page.url, "title": title, "content": content}],
                "error": None,
                "execution_time_ms": elapsed,
            }))
        except Exception as e:
            elapsed = int((time.monotonic() - start) * 1000)
            print(json.dumps({
                "success": False,
                "results": [],
                "error": str(e),
                "execution_time_ms": elapsed,
            }))

        await ctx.close()
        await browser.close()

URL = "{url}"
TIMEOUT_MS = {timeout_ms}
asyncio.run(main(URL, TIMEOUT_MS))
'''
