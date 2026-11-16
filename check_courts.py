from playwright.sync_api import sync_playwright
from datetime import date

COURTS = ["BAD.1", "BAD.2", "BAD.3", "BAD.4", "BAD.5"]


def build_url(target_date):
    return (
        "https://ganadorsport.pl/rezerwacja-online/"
        "index.php?s=grafik_zajec_korty_badminton"
        f"&date={target_date.isoformat()}"
    )


def main():

    # Testujemy stronę, na której wiemy,
    # że BAD.2 o 21:00 jest dostępny
    target_date = date(2026, 11, 19)

    url = build_url(target_date)

    print(f"Sprawdzam: {target_date}")
    print(f"URL: {url}")

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
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response:
                print(f"HTTP: {response.status}")

            page.wait_for_timeout(2000)

            print("\n===== ELEMENTY BADMINTON =====")

            # Szukamy każdego BAD.1 - BAD.5
            for court in COURTS:

                locator = page.get_by_text(court, exact=True)

                print(f"\n===== {court} =====")
                print(f"Liczba znalezionych: {locator.count()}")

                if locator.count() > 0:
                    element = locator.first

                    print("\nELEMENT:")
                    print(
                        element.evaluate(
                            "(el) => el.outerHTML"
                        )
                    )

                    print("\nPARENT:")
                    print(
                        element.evaluate(
                            "(el) => el.parentElement.outerHTML"
                        )
                    )

                    print("\nGRANDPARENT:")
                    print(
                        element.evaluate(
                            "(el) => el.parentElement.parentElement.outerHTML"
                        )
                    )

            print("\n===== LINKI / ELEMENTY KLIKALNE =====")

            elements = page.locator(
                "a, button, [onclick]"
            )

            print(
                f"Liczba elementów klikanych: "
                f"{elements.count()}"
            )

            for i in range(elements.count()):

                el = elements.nth(i)

                try:
                    html = el.evaluate(
                        "(e) => e.outerHTML"
                    )

                    # pokazujemy elementy związane z kortami
                    if (
                        "BAD." in html
                        or "badminton" in html.lower()
                        or "rezerw" in html.lower()
                    ):
                        print(f"\nCLICKABLE {i}:")
                        print(html)

                except Exception:
                    pass

            print("\n===== KONIEC DIAGNOSTYKI =====")

        finally:
            context.close()
            browser.close()


if __name__ == "__main__":
    main()
