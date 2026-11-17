import json
import os
import smtplib
import ssl
from datetime import date
from email.message import EmailMessage
from pathlib import Path
from urllib.parse import urljoin

from playwright.sync_api import sync_playwright


BASE_URL = "https://ganadorsport.pl/rezerwacja-online/"

TARGET_TIME = "19:00"
TARGET_MINUTES = 19 * 60  # 1200

COURTS = [
    "BAD.1",
    "BAD.2",
    "BAD.3",
    "BAD.4",
    "BAD.5",
]

STATE_FILE = Path("state.json")
SCREENSHOT_FILE = Path("ganador-status.png")
HTML_FILE = Path("ganador-page.html")


def get_target_date() -> date:
    """
    Data sprawdzana przez skrypt.

    W GitHub Actions można ustawić:
    TARGET_DATE=2026-11-19
    """
    raw_date = os.getenv("TARGET_DATE", "2026-11-19").strip()

    try:
        return date.fromisoformat(raw_date)
    except ValueError as exc:
        raise RuntimeError(
            f"Nieprawidłowy TARGET_DATE: {raw_date!r}. "
            "Oczekiwany format: RRRR-MM-DD."
        ) from exc


def build_schedule_url(target_date: date) -> str:
    return (
        f"{BASE_URL}"
        "index.php?s=grafik_zajec_korty_badminton"
        f"&date={target_date.isoformat()}"
    )


def load_previous_state() -> dict:
    if not STATE_FILE.exists():
        return {}

    try:
        data = json.loads(STATE_FILE.read_text(encoding="utf-8"))

        if isinstance(data, dict):
            return data

    except (json.JSONDecodeError, OSError) as exc:
        print(f"OSTRZEŻENIE: nie można odczytać state.json: {exc}")

    return {}


def save_state(
    target_date: date,
    available_courts: list[str],
) -> None:
    state = {
        "date": target_date.isoformat(),
        "time": TARGET_TIME,
        "available_courts": available_courts,
    }

    STATE_FILE.write_text(
        json.dumps(
            state,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"Zapisano stan: {state}")


def split_recipients(value: str) -> list[str]:
    """
    Pozwala używać przecinków lub średników:
    EMAIL_TO=a@example.com;b@example.com
    """
    return [
        item.strip()
        for item in value.replace(";", ",").split(",")
        if item.strip()
    ]


def send_email(
    target_date: date,
    available_courts: list[str],
    booking_links: dict[str, str],
) -> None:
    smtp_host = os.getenv("SMTP_HOST", "").strip()
    smtp_port = int(os.getenv("SMTP_PORT", "587"))
    smtp_username = os.getenv("SMTP_USERNAME", "").strip()
    smtp_password = os.getenv("SMTP_PASSWORD", "").strip()

    email_from = os.getenv(
        "EMAIL_FROM",
        smtp_username,
    ).strip()

    recipients = split_recipients(
        os.getenv("EMAIL_TO", "")
    )

    missing = []

    if not smtp_host:
        missing.append("SMTP_HOST")

    if not smtp_username:
        missing.append("SMTP_USERNAME")

    if not smtp_password:
        missing.append("SMTP_PASSWORD")

    if not email_from:
        missing.append("EMAIL_FROM")

    if not recipients:
        missing.append("EMAIL_TO")

    if missing:
        raise RuntimeError(
            "Brakuje konfiguracji e-mail: "
            + ", ".join(missing)
        )

    courts_text = ", ".join(available_courts)

    lines = [
        "Pojawiła się dostępność kortu w Ganadorze.",
        "",
        f"Data: {target_date.isoformat()}",
        f"Godzina: {TARGET_TIME}",
        f"Wolne korty: {courts_text}",
        "",
        "Linki do rezerwacji:",
    ]

    for court in available_courts:
        link = booking_links.get(court)

        if link:
            lines.append(f"- {court}: {link}")
        else:
            lines.append(f"- {court}")

    message = EmailMessage()
    message["Subject"] = (
        f"Ganador: wolny kort o {TARGET_TIME} "
        f"({target_date.isoformat()})"
    )
    message["From"] = email_from
    message["To"] = ", ".join(recipients)
    message.set_content("\n".join(lines))

    context = ssl.create_default_context()

    if smtp_port == 465:
        with smtplib.SMTP_SSL(
            smtp_host,
            smtp_port,
            context=context,
            timeout=30,
        ) as server:
            server.login(
                smtp_username,
                smtp_password,
            )
            server.send_message(message)

    else:
        with smtplib.SMTP(
            smtp_host,
            smtp_port,
            timeout=30,
        ) as server:
            server.ehlo()
            server.starttls(context=context)
            server.ehlo()
            server.login(
                smtp_username,
                smtp_password,
            )
            server.send_message(message)

    print(
        "Wysłano powiadomienie e-mail do: "
        + ", ".join(recipients)
    )


def save_diagnostics(page) -> None:
    try:
        page.screenshot(
            path=str(SCREENSHOT_FILE),
            full_page=True,
        )
        print(f"Zapisano screenshot: {SCREENSHOT_FILE}")

    except Exception as exc:
        print(f"Nie udało się zapisać screenshotu: {exc}")

    try:
        HTML_FILE.write_text(
            page.content(),
            encoding="utf-8",
        )
        print(f"Zapisano HTML: {HTML_FILE}")

    except Exception as exc:
        print(f"Nie udało się zapisać HTML: {exc}")


def check_availability(
    target_date: date,
) -> tuple[list[str], dict[str, str]]:
    url = build_schedule_url(target_date)

    print(f"Sprawdzam datę: {target_date.isoformat()}")
    print(f"Sprawdzam godzinę: {TARGET_TIME}")
    print(f"URL: {url}")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        context = browser.new_context(
            viewport={
                "width": 1600,
                "height": 1200,
            },
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/141.0.0.0 Safari/537.36"
            ),
            extra_http_headers={
                "Accept-Language": (
                    "pl-PL,pl;q=0.9,en;q=0.8"
                ),
            },
        )

        page = context.new_page()

        try:
            response = page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000,
            )

            if response is None:
                raise RuntimeError(
                    "Brak odpowiedzi HTTP ze strony Ganadora."
                )

            print(f"HTTP status: {response.status}")
            print(f"Końcowy URL: {page.url}")

            if response.status == 403:
                raise RuntimeError(
                    "Ganador zwrócił HTTP 403 Forbidden. "
                    "Serwer może blokować adres IP GitHub Actions."
                )

            if response.status >= 400:
                raise RuntimeError(
                    "Ganador zwrócił błąd HTTP "
                    f"{response.status}."
                )

            page.wait_for_selector(
                ".i-table-h-event-row",
                timeout=30000,
            )

            rows = page.locator(".i-table-h-event-row")
            row_count = rows.count()

            print(f"Liczba znalezionych wierszy: {row_count}")

            if row_count < len(COURTS):
                raise RuntimeError(
                    "Znaleziono zbyt mało wierszy kortów: "
                    f"{row_count}. Oczekiwano co najmniej "
                    f"{len(COURTS)}."
                )

            available_courts = []
            booking_links = {}

            for index, court in enumerate(COURTS):
                row = rows.nth(index)

                slot =row.locator(
                    ".i-table-h-event-body"
                    f'[data-start="{TARGET_MINUTES}"]'
                )

                slot_count = slot.count()

                if slot_count != 1:
                    raise RuntimeError(
                        f"{court}: znaleziono {slot_count} "
                        f"elementów dla godziny {TARGET_TIME}; "
                        "oczekiwano dokładnie jednego."
                    )

                slot = slot.first

                classes = (
                    slot.get_attribute("class") or ""
                ).split()

                data_link = (
                    slot.get_attribute("data-link") or ""
                ).strip()

                if "green" in classes:
                    status = "WOLNY"
                    available_courts.append(court)

                    if data_link:
                        booking_links[court] = urljoin(
                            BASE_URL,
                            data_link,
                        )

                elif "red" in classes:
                    status = "zajęty"

                else:
                    status = (
                        "nieznany: "
                        + " ".join(classes)
                    )

                print(
                    f"{court} o {TARGET_TIME}: {status}"
                )

            print(
                "Wolne korty: "
                + (
                    ", ".join(available_courts)
                    if available_courts
                    else "brak"
                )
            )

            return available_courts, booking_links

        except Exception:
            save_diagnostics(page)
            raise

        finally:
            context.close()
            browser.close()


def main() -> None:
    target_date = get_target_date()
    previous_state = load_previous_state()

    available_courts, booking_links = check_availability(
        target_date
    )

    previous_available = (
        previous_state.get("available_courts", [])
        if (
            previous_state.get("date")
            == target_date.isoformat()
            and previous_state.get("time")
            == TARGET_TIME
        )
        else []
    )

    new_available = [
        court
        for court in available_courts
        if court not in previous_available
    ]

    print(
        "Poprzednio dostępne: "
        + (
            ", ".join(previous_available)
            if previous_available
            else "brak"
        )
    )

    if new_available:
        print(
            "Nowo dostępne korty: "
            + ", ".join(new_available)
        )

        send_email(
            target_date,
            new_available,
            booking_links,
        )

    else:
        print(
            "Brak nowej dostępności. "
            "Powiadomienie nie zostanie wysłane."
        )

    save_state(
        target_date,
        available_courts,
    )


if __name__ == "__main__":
    main()
