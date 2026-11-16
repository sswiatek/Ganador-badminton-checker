from playwright.sync_api import sync_playwright
from datetime import date, timedelta
from zoneinfo import ZoneInfo

WARSAW_TZ = ZoneInfo("Europe/Warsaw")

TARGET_TIME = "20:00"
COURTS = ["BAD.1", "BAD.2", "BAD.3", "BAD.4", "BAD.5"]


def build_url(target_date):
    return (
        "https://ganadorsport.pl/rezerwacja-online/"
        "index.php?s=grafik_zajec_korty_badminton"
        f"&date={target_date.isoformat()}"
    )


def check_day(page, target_date):
    url = build_url(target_date)

    print(f"\nSprawdzam: {target_date}")
    print(f"URL: {url}")

    response = page.goto(
        url,
        wait_until="domcontentloaded",
        timeout=60000,
    )

    if response:
        print(f"HTTP: {response.status}")

        if response.status == 403:
            raise RuntimeError(
                "Ganador zwrócił HTTP 403. "
                "GitHub Runner może być blokowany."
            )

    page.wait_for_timeout(2000)

    # Diagnostyka: pokaż tekst strony
    text = page.locator("body").inner_text()

    print("--- fragment strony ---")
    print(text[:3000])
    print("-----------------------")

    available = []

    # Szukamy wiersza każdego kortu
    for court in COURTS:

        court_locator = page.get_by_text(court, exact=True)

        if court_locator.count() == 0:
            print(f"{court}: nie znaleziono")
            continue

        court_element = court_locator.first

        # znajdujemy najbliższy wiersz tabeli
        row = court_element.locator("xpath=ancestor::tr[1]")

        if row.count() == 0:
            print(f"{court}: brak wiersza TR")
            continue

        cells = row.locator("td")

        print(
            f"{court}: znaleziono wiersz, "
            f"liczba komórek={cells.count()}"
        )

        # tymczasowo wypisz wszystkie komórki
        for i in range(cells.count()):
            cell = cells.nth(i)

            try:
                value = cell.inner_text().strip()
            except:
                value = ""

            classes = cell.get_attribute("class") or ""

            print(
                f"  [{i}] text={value!r} "
                f"class={classes!r}"
            )

    return available


def main():
    # na początek testujemy konkretnie 19 listopada
    target_date = date(2026, 11, 19)

    with sync_playwright() as p:

        browser = p.chromium.launch(
            headless=True,
            args=["--disable-dev-shm-usage"],
        )

        context = browser.new_context(
            viewport={"width": 1600, "height": 1200},
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/141.0.0.0 Safari/537.36"
            ),
        )

        page = context.new_page()

        try:
            check_day(page, target_date)

            page.screenshot(
                path="ganador-debug.png",
                full_page=True,
            )

        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
