import argparse
import logging
import os
import re
import time
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from tqdm import tqdm

try:
    from camoufox.sync_api import Camoufox
except ImportError as exc:  # pragma: no cover - shown to the user at startup
    raise SystemExit(
        "Camoufox is not installed.\n"
        "Install it (and its browser) with:\n"
        '    pip install -U "camoufox[geoip]"\n'
        "    python -m camoufox fetch"
    ) from exc

# Configure logging
log_level = logging.INFO  # Use INFO to show only necessary outputs
logging.basicConfig(level=log_level, format='%(asctime)s - %(levelname)s - %(message)s')

# Base URL of the website to scrape
BASE_URL = os.getenv("BASE_URL", "https://hshop.erista.me")

# Markers that identify a Cloudflare / "verify you are human" interstitial page.
_CHALLENGE_TITLE_MARKERS = (
    "just a moment",
    "verifying you are human",
    "checking your browser",
    "attention required",
    "one more step",
)
_CHALLENGE_BODY_MARKERS = (
    "cf_chl_opt",
    'id="challenge-stage"',
    "id='challenge-stage'",
    "challenge-running",
    "cf-browser-verification",
    "verifying you are human",
    "checking your browser before accessing",
    "enable javascript and cookies to continue",
)


def is_verification_page(html, title=""):
    """Return True when the page is a captcha / Cloudflare interstitial."""
    title = (title or "").lower()
    if any(marker in title for marker in _CHALLENGE_TITLE_MARKERS):
        return True
    body = (html or "").lower()
    return any(marker in body for marker in _CHALLENGE_BODY_MARKERS)


class HShopBrowser:
    """
    Stealth browser session based on Camoufox.

    Camoufox is a modified Firefox build that spoofs a real device fingerprint
    (OS, fonts, WebGL, canvas, headers, ...) and humanizes cursor movement, so
    Cloudflare's bot detection / "verify you are human" challenges pass without
    manual intervention - unlike Selenium/ChromeDriver, which is trivially
    fingerprinted.

    The browser's cookies (most importantly Cloudflare's ``cf_clearance``) are
    mirrored into a ``requests.Session`` so the actual file downloads go
    through the same verified session.
    """

    CHALLENGE_TIMEOUT = 120       # seconds to wait for an automatic solve (headless)
    MANUAL_SOLVE_TIMEOUT = 300    # seconds to wait for a manual solve (--headed)
    DOWNLOAD_LINK_TIMEOUT = 240   # seconds to wait for the Turnstile-gated download link

    def __init__(self, headless=True):
        self.headless = headless
        self.http = requests.Session()
        self.http.headers.update({
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.5",
            "Referer": BASE_URL + "/",
        })
        self._camoufox_cm = None
        self.browser = None
        self.page = None

    # -- lifecycle ---------------------------------------------------------
    def __enter__(self):
        self._start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self._stop()

    def _start(self):
        try:
            from camoufox.pkgman import camoufox_path
            camoufox_path(download_if_missing=True)
        except Exception as exc:
            logging.debug("Could not verify the Camoufox installation: %s", exc)

        # Try the fullest launch configuration first and degrade gracefully if
        # an optional feature (e.g. the geoip extra) is unavailable.
        launch_attempts = (
            {"headless": self.headless, "humanize": True, "locale": "en-US", "geoip": True},
            {"headless": self.headless, "humanize": True},
            {"headless": self.headless},
        )
        last_error = None
        for launch_options in launch_attempts:
            try:
                self._camoufox_cm = Camoufox(**launch_options)
                self.browser = self._camoufox_cm.__enter__()
                break
            except Exception as exc:
                last_error = exc
                logging.debug("Camoufox launch options %s failed: %s", launch_options, exc)
        if self.browser is None:
            raise RuntimeError(
                "Could not launch Camoufox. Have you run 'python -m camoufox fetch'? "
                f"Last error: {last_error}"
            )

        self.page = self.browser.new_page()
        logging.info("Camoufox started (%s mode).", "headless" if self.headless else "headed")
        self._sync_http_session()

    def _stop(self):
        try:
            if self._camoufox_cm is not None:
                self._camoufox_cm.__exit__(None, None, None)
        except Exception as exc:
            logging.debug("Error while closing Camoufox: %s", exc)
        finally:
            self.http.close()

    # -- page access -------------------------------------------------------
    def fetch(self, url, timeout_ms=90000, wait_for_download_link=False):
        """Navigate to *url*, wait out any captcha challenge, and return the HTML."""
        logging.info("Fetching %s", url)
        self.page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")
        self._wait_out_challenge()
        if wait_for_download_link:
            self._wait_for_download_link()
        self._sync_http_session()
        return self.page.content()

    def _wait_for_download_link(self):
        """
        Wait for the Cloudflare Turnstile security check on a title page.

        hShop hides the QR code and direct download link behind a Turnstile
        widget ("Please complete this security check to view the QR code and
        download link."). Camoufox solves the widget automatically; its
        ``submitCaptcha`` callback then populates ``#landing-box`` with the
        download link. Wait until that happens.
        """
        if not self.headless:
            logging.info(
                "If a 'Verify you are human' checkbox is shown, click it in the browser window."
            )
        try:
            if 'landing-box' not in self.page.content():
                return  # not a title page (or the layout changed) - nothing to wait for
        except Exception:
            return
        try:
            self.page.wait_for_selector(
                # The "Download seed for FBI" link is a data: URL, so exclude those.
                '#landing-box a:not([href^="data:"])',
                timeout=self.DOWNLOAD_LINK_TIMEOUT * 1000,
            )
        except Exception:
            logging.warning(
                "Timed out after %ds waiting for the security check to reveal the "
                "download link. If this keeps happening, re-run with --headed.",
                self.DOWNLOAD_LINK_TIMEOUT,
            )

    def _wait_out_challenge(self):
        """Wait until a Cloudflare / captcha interstitial clears."""
        started = time.time()
        manual_deadline = None
        while True:
            try:
                html = self.page.content()
                title = self.page.title()
            except Exception:
                time.sleep(1.0)
                continue

            if not is_verification_page(html, title):
                return

            if self.headless:
                if time.time() - started > self.CHALLENGE_TIMEOUT:
                    logging.warning(
                        "Still on a verification page after %ds. Re-run with --headed "
                        "to solve the captcha manually.",
                        self.CHALLENGE_TIMEOUT,
                    )
                    return
            else:
                if manual_deadline is None:
                    logging.warning(
                        "Captcha / verification page detected. Solve it in the browser "
                        "window if it does not clear automatically (waiting up to %ds).",
                        self.MANUAL_SOLVE_TIMEOUT,
                    )
                    manual_deadline = time.time() + self.MANUAL_SOLVE_TIMEOUT
                if time.time() > manual_deadline:
                    logging.warning("Timed out waiting for the captcha to be solved.")
                    return
            time.sleep(1.5)

    def _sync_http_session(self):
        """Copy browser cookies + user agent into the requests session used for downloads."""
        try:
            for cookie in self.page.context.cookies():
                self.http.cookies.set(
                    cookie["name"],
                    cookie["value"],
                    domain=cookie.get("domain") or "",
                    path=cookie.get("path") or "/",
                )
        except Exception as exc:
            logging.debug("Could not sync cookies into the HTTP session: %s", exc)
        try:
            user_agent = self.page.evaluate("navigator.userAgent")
            if user_agent:
                self.http.headers["User-Agent"] = user_agent
        except Exception:
            pass

def get_main_categories(browser):
    """Retrieve main categories from the homepage."""
    html = browser.fetch(BASE_URL)
    soup = BeautifulSoup(html, "html.parser")
    return soup.find_all("a", href=re.compile(r'^/c/'))

def sanitize_filename(filename):
    """Sanitize file names by removing invalid characters."""
    filename = re.sub(r'[<>:\"/\\|?*\x00-\x1F]', '', filename)
    return filename

def html_decode(filename):
    """Decode special HTML characters in file names."""
    replacements = {
        '%3A': ':',
        '%2F': '/',
        '%2C': ',',
        '%5F': '_',
        '%28': '(',
        '%29': ')',
        "'": ''
    }
    for old, new in replacements.items():
        filename = filename.replace(old, new)
    return filename

def prompt_user_for_selection(items, prompt_message):
    """
    Prompt the user to select items from a list.

    Args:
        items (list): List of items to choose from.
        prompt_message (str): The message to display to the user.

    Returns:
        list: A list of selected items.
    """
    logging.info(prompt_message)
    for i, item in enumerate(items, start=1):
        print(f"{i}. {item.text.strip() if hasattr(item, 'text') else item[0]}")
    selections = input("Enter your selections: ")

    if selections.strip() == '*':
        return items
    else:
        selected_items = []
        for selection in selections.split(','):
            selection = selection.strip()
            if not selection.isdigit() or int(selection) not in range(1, len(items) + 1):
                logging.error(f"Invalid selection '{selection}', please try again. Example: 1,2,3")
                exit(1)
            selected_items.append(items[int(selection) - 1])
        return selected_items

def get_games(browser, speed_limit=None, output_dir="./downloads"):
    """Retrieve games from selected categories and download them."""
    categories = get_main_categories(browser)
    selected_categories = prompt_user_for_selection(categories, "Select main categories (comma separated, '*' for all):")

    for selected_category in selected_categories:
        category_url = BASE_URL + selected_category['href']
        download_games_in_category(browser, category_url, speed_limit=speed_limit, output_dir=output_dir)

def download_games_in_category(browser, category_url, speed_limit=None, output_dir="./downloads"):
    """
    Download games from a specific category.

    Args:
        browser (HShopBrowser): The Camoufox browser session.
        category_url (str): URL of the category to scrape.
        speed_limit (float): Optional download speed limit in bytes per second.
        output_dir (str): Base directory to save downloads into (default: ./downloads).
    """
    html = browser.fetch(category_url)
    soup_region = BeautifulSoup(html, "html.parser")
    
    # Find all subcategory links and names
    subcategory_elements = soup_region.find_all("a", class_="list-entry block-link")
    
    warning_displayed = False  # Track whether the warning has been displayed

    sub_categories = {}
    for element in subcategory_elements:
        subcategory_link = element['href']
        subcategory_name_element = element.find("h3", class_="green bold")
        
        if subcategory_name_element is None:
            if not warning_displayed:
                logging.warning(f"Some subcategories are missing <h3> elements.")
                warning_displayed = True
            continue
        
        subcategory_name = subcategory_name_element.text.strip()
        sub_categories[subcategory_name] = subcategory_link

    sub_category_list = list(sub_categories.items())
    
    # Prompt user for selection
    selected_sub_categories = prompt_user_for_selection(
        sub_category_list,
        f"Select subcategories for {category_url.replace(BASE_URL + '/c/', '')} (comma separated, '*' for all):"
    )

    for sub_category_name, sub_category_link in selected_sub_categories:
        download_path = os.path.join(
            os.path.expanduser(output_dir),
            category_url.replace(BASE_URL + '/c/', ''),
            sanitize_filename(sub_category_name)
        )
        os.makedirs(download_path, exist_ok=True)

        offset = 0
        while True:
            url = BASE_URL + sub_category_link + f"?count=100&offset={offset}"
            soup_offset = BeautifulSoup(browser.fetch(url), "html.parser")
            
            # Find all content links with pattern /t/{id}
            game_links = [a['href'] for a in soup_offset.find_all('a', href=True) if re.match(r'^/t/\d+$', a['href'])]

            if not game_links:
                logging.info(f"No more content found at {url}.")
                break

            # For each game link, find the direct download link
            for game_link in game_links:
                game_url = BASE_URL + game_link
                # Title pages hide the QR code and download link behind a Cloudflare
                # Turnstile security check, which Camoufox solves automatically.
                soup_game = BeautifulSoup(
                    browser.fetch(game_url, wait_for_download_link=True), "html.parser"
                )

                # Find the direct download link; its label can be e.g. "Direct Download (.cia)"
                direct_download_element = soup_game.find(
                    lambda tag: tag.name == 'a'
                    and tag.get('href')
                    and tag.get_text(strip=True).lower().startswith('direct download')
                )
                if direct_download_element:
                    download_url = urljoin(BASE_URL, direct_download_element['href'])
                    # Do not print the URL, just download
                    download_game(browser, download_url, download_path, speed_limit=speed_limit)
                else:
                    logging.warning(f"Direct download link not found for a game.")

            if len(game_links) < 100:
                break

            offset += 100

def download_game(browser, url, download_path, speed_limit=None):
    """
    Download a single game and save it to disk.

    Args:
        browser (HShopBrowser): Browser session whose cookies are reused for the download.
        url (str): URL of the game to download.
        download_path (str): The directory path to save the downloaded game.
        speed_limit (float): Optional download speed limit in bytes per second.
    """
    session = browser.http
    try:
        response = session.get(url, stream=True, timeout=60)
        content_type = response.headers.get('content-type', '').lower()

        # Cloudflare may challenge even the direct download link. When that
        # happens, refresh the clearance cookies from the browser and retry once.
        if response.status_code != 200 or 'text/html' in content_type:
            response.close()
            logging.info("Download link was blocked; refreshing Cloudflare clearance...")
            browser.fetch(BASE_URL)
            response = session.get(url, stream=True, timeout=60)
            content_type = response.headers.get('content-type', '').lower()

        if response.status_code == 200 and 'text/html' not in content_type:
            content_disposition = response.headers.get('content-disposition')
            if content_disposition:
                matches = re.findall("filename=\"(.+)\"", content_disposition)
                filename = matches[0] if matches else url.split('/')[-1]
            else:
                filename = url.split('/')[-1]

            game_id = url.split('/')[-1].split('?')[0]
            filename = sanitize_filename(filename)
            filename = html_decode(filename)

            filename_parts = filename.rsplit('.', 1)
            if len(filename_parts) == 2:
                filename = f"{filename_parts[0]}.[hID-{game_id}].{filename_parts[1]}"
            else:
                filename = f"{filename_parts[0]}.[hID-{game_id}]"

            full_final_path = os.path.join(download_path, filename)
            tempfilename = f"{filename}.part"
            full_temp_path = os.path.join(download_path, tempfilename)

            total_length = int(response.headers.get('content-length', 0))

            if os.path.exists(full_final_path) and os.path.getsize(full_final_path) == total_length:
                logging.info(f"{filename} already downloaded and matches the expected size.")
                response.close()
                return
            chunk_size = 4096
            if speed_limit:
                chunk_time = chunk_size / speed_limit
            with open(full_temp_path, 'wb') as f, tqdm(
                total=total_length,
                unit='B',
                unit_scale=True,
                unit_divisor=1024,
                desc=f"{filename} ({total_length/1024/1024:.2f} MB)"
            ) as bar:
                start_time = time.time()
                for data in response.iter_content(chunk_size=chunk_size):
                    f.write(data)
                    bar.update(len(data))
                    if speed_limit:
                        elapsed = time.time() - start_time
                        if elapsed < chunk_time:
                            time.sleep(chunk_time - elapsed)
                        start_time = time.time()

            os.rename(full_temp_path, full_final_path)
            response.close()
        else:
            logging.warning(f"Failed to download from {url} (HTTP {response.status_code})")
            response.close()

    except requests.exceptions.RequestException as e:
        logging.error(f"An error occurred while downloading the game: {e}")
    except Exception as e:
        logging.error(f"An unexpected error occurred: {e}")

def main():
    parser = argparse.ArgumentParser(description='Download games with optional speed limit.')
    parser.add_argument('--speed-limit', type=float, default=None, help='Download speed limit in bytes per second')
    parser.add_argument('-o', '--output-dir', default='./downloads', help='Directory to save downloads into (default: ./downloads)')
    parser.add_argument('--headed', action='store_true', help='Show the browser window (useful for solving a captcha manually)')
    args = parser.parse_args()

    try:
        with HShopBrowser(headless=not args.headed) as browser:
            get_games(browser, speed_limit=args.speed_limit, output_dir=args.output_dir)
    except KeyboardInterrupt:
        logging.info("Download interrupted by user. Exiting...")
        exit(0)

if __name__ == "__main__":
    main()