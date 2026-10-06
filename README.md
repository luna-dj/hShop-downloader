# hShop Downloader

## Overview
https://github.com/Ghost0159/hShop-downloader/assets/66320002/1f61a252-d788-4f8d-8aaf-d89166e244e8

The **hShop Downloader** is a Python script designed to facilitate the downloading of games and related content from the hShop website. It supports various categories such as games, updates, DLC, virtual console, DSiWare, videos, extras, and themes. The script leverages web scraping techniques to gather information and provides a streamlined interface for downloading content directly to your local machine.

## Features

### Supported Categories

- DLC
- DSiWare
- Extras
- Games
- Themes
- Updates
- Videos
- Virtual Console

### How It Works

1. **Web Scraping:** The script utilizes the `requests` library along with `BeautifulSoup` for web scraping. It extracts relevant information, such as download links and file names, from the hShop website.

2. **Camoufox Stealth Browser:** The script drives [Camoufox](https://camoufox.com), a hardened, anti-fingerprinting Firefox build, to load pages and automatically clear Cloudflare / "verify you are human" captcha challenges that block traditional automation tools such as Selenium.

3. **Threaded Downloads:** To enhance performance, the script uses multiple threads to download games concurrently. This allows for faster retrieval of content.

4. **HTML Decoding:** The `html_decode` function handles HTML-encoded characters in filenames, ensuring accurate and readable file names.

5. **Download Progress:** The script displays a progress bar using `tqdm` to provide real-time feedback on the download process.

6. **Organized Directories:** The downloaded content is organized into directories based on their respective categories. Each item is stored in a dedicated folder for ease of access.

7. **Limiting Download Speed:** The download speed can be limited so you can have it running in the background without it consuming all your network bandwith allowing you to do other activities such as gaming or video streaming.
The limit can be set during the script call:
```
python hshop_downloader.py --speed-limit 1048576  # Sets speed limit to 1 MB/s
```
The speed-limit argument can be omitted to use the full speed of your connection.

8. **Custom Output Directory:** By default, downloads are saved into `./downloads` (organized into category/subcategory folders). Use `--output-dir` to save elsewhere:
```
python hshop_downloader.py --output-dir ~/Games/hShop      # Absolute or ~ path
python hshop_downloader.py -o "/Volumes/External/hShop"    # Short form, paths with spaces
```
The directory (including category subfolders) is created automatically if it does not exist.


#### Technical Details
- **Web Scraping:** The script sends HTTP requests to the hShop website and parses the HTML response using BeautifulSoup. It then extracts relevant information such as download links and file names using regular expressions.
- **Camoufox Integration:** The script uses Camoufox, a stealth browser built on a custom Firefox build, to navigate the site and retrieve pages. Camoufox spoofs a realistic device fingerprint (OS, fonts, WebGL, screen size, ...) and humanizes cursor movement, so Cloudflare's bot detection / captcha challenges are passed automatically instead of blocking the scraper.
- **Shared Cloudflare Clearance:** Cookies acquired by the browser (most importantly Cloudflare's `cf_clearance`) plus the spoofed user agent are copied into the `requests` session used for downloads, so direct download links are not challenged either. If a download is still blocked, the clearance is refreshed from the browser and the request is retried once.
- **Captcha-Aware Navigation:** Every page load is checked for a Cloudflare interstitial, and title pages hide their QR code / download link behind a Turnstile "security check". Camoufox solves both automatically; the script waits until the check clears and the download link is revealed before parsing the HTML (with a manual-solve fallback when running `--headed`).
- **Threaded Downloads:** The script utilizes Python's ``threading`` module to create multiple threads for downloading games concurrently. This helps in maximizing bandwidth utilization and reducing download times, especially when downloading multiple files.
- **HTML Decoding:** The ``html_decode`` function handles HTML-encoded characters in filenames by replacing percent-encoded characters with their corresponding ASCII characters. This ensures that filenames are correctly decoded and readable.
- **Download Progress:** The script uses ``tqdm``, a Python library for creating progress bars, to display real-time download progress. This gives users visibility into the download process and estimated time remaining.
- **Organized Directories:** The script organizes downloaded content into directories based on their categories. This helps in keeping the downloaded files well-organized and easily accessible.

## Prerequisites

Ensure you have the following dependencies installed:

- Python 3.10 or newer
- `camoufox` (with the `geoip` extra) — includes the stealth Firefox browser and Playwright driver
- `requests`
- `beautifulsoup4`
- `tqdm`

Install the required Python packages using:

```bash
pip install -r requirements.txt

# Download the Camoufox browser (only needed once, ~150 MB)
python -m camoufox fetch
```

## Usage
1. **Clone this repository:**
```bash
git clone https://github.com/Ghost0159/hShop-downloader/
```
2. **Navigate to the project directory:**
```bash
cd hShop-downloader
```
3. **Run the Script:**
Execute the script with the following command:
```bash
python hshop_downloader.py
```
If a captcha hangs (Cloudflare occasionally escalates to an interactive challenge), run with a visible browser window instead and solve it once manually:
```bash
python hshop_downloader.py --headed
```
The clearance cookie obtained this way is reused by the script for the rest of the session, including the downloads.
4. **Follow the On-Screen Instructions:**
    - After running the script, you will be prompted to select the main categories from which you want to download games. Enter the numbers corresponding to your desired categories, separated by commas, or type `*` to select all.
    - Next, you will choose the subcategories of the games you want to download using a similar selection process.
    - The files will be downloaded and organized into directories based on the categories you selected.

### Command-line options
```
python hshop_downloader.py [--speed-limit BYTES_PER_SECOND] [-o|--output-dir DIR] [--headed]
```
| Option | Description |
| ------ | ----------- |
| `--speed-limit BYTES` | Cap the download speed, e.g. `1048576` for 1 MB/s. |
| `-o`, `--output-dir DIR` | Base directory for downloads (default: `./downloads`). Created automatically; `~` is expanded. |
| `--headed` | Show the browser window so a captcha can be solved manually. |
    

## Troubleshooting

- **`Camoufox is not installed` / browser not found:** install the package and fetch the browser:
  ```bash
  pip install -U "camoufox[geoip]"
  python -m camoufox fetch
  ```
- **Stuck on a "Verify you are human" / "Just a moment..." page:** the script already waits for the challenge to clear automatically. If it keeps failing, run with `--headed` and solve the challenge in the visible window; wait a few minutes between attempts, as repeatedly hitting the challenge can raise the site's suspicion level.
- **Downloads return an HTML page instead of a file:** this is a Cloudflare block. The script automatically refreshes the browser clearance and retries once; if it persists, use `--headed` so the challenge can be cleared interactively.
- **GeoIP warnings:** `geoip` is optional. If the extra is unavailable the script logs a warning and continues with automatic (non-geolocated) fingerprinting.


## Additional Functionality
The script can be extended and enhanced in several ways:

1. **User Interface:** Develop a graphical user interface (GUI) for a more user-friendly experience.

2. **Configuration File:** Implement a configuration file for easier customization of settings, such as the download directory and thread count.

3. **Error Handling:** Enhance error handling to gracefully manage unexpected scenarios during the download process.

4. **Logging:** Integrate a logging mechanism to keep track of download activities and any potential issues.

5. **Pause and Resume:** Add functionality to pause and resume downloads, especially useful for large files or intermittent internet connections.


## Credits
This script was developed by [Ghost0159](https://github.com/Ghost0159/).<br>
Special thanks to [Léon Le Breton](https://github.com/LeonLeBreton) for the help with the first version<br>
and to Kloklojul for the Download Limiter.

## License
This project is licensed under the GNU General Public License Version 3.0. See the [LICENSE](LICENSE) file for details.

## Disclaimer
This script is intended for educational and personal use only. The act of web scraping may be subject to legal and ethical considerations, and it is important to ensure compliance with the relevant terms of service and policies of the website being scraped.

Downloading copyrighted material without proper authorization may infringe upon intellectual property rights and violate applicable laws. Users are solely responsible for their actions while using this script, and the developer assumes no liability for any misuse or unlawful activity.

It is crucial to emphasize that this script should only be used to download games that the user owns and has legally purchased. It is not intended to facilitate piracy or unauthorized distribution of copyrighted content. The developer strongly encourages users to respect intellectual property rights and only download games for which they have legitimate ownership.

By using this script, you agree to use it responsibly and in accordance with applicable laws and regulations. It is provided solely for educational purposes and to satisfy curiosity.
