import json
import os
import re
import smtplib
import sys
from datetime import datetime
from email.message import EmailMessage
from pathlib import Path
from zoneinfo import ZoneInfo

from playwright.sync_api import sync_playwright


URL = (
    "https://ganadorsport.pl/rezerwacja-online/"
    "index.php?s=grafik_zajec_korty_badminton&date=2026-11-02"
)

TARGET_TIME = "20:00"
REFERENCE_COURT = "BAD.2"
REFERENCE_TIME = "22:00"
COURTS = ["BAD.1", "BAD.2", "BAD.3", "BAD.4", "BAD.5"]

STATE_FILE = Path("state.json")
SCREENSHOT_FILE = Path("ganador-status.png")
HTML_FILE = Path("ganador-page.html")

WARSAW_TZ = ZoneInfo("Europe/Warsaw")


def normalize_text(value):
    if value is None:
        return ""

    value = value.replace("\xa0", " ")
    value = re.sub(r"\s+", " ", value)

    return value.strip().upper()


def load_previous_state():
    if not STATE_FILE.exists():
        return {
            "available_courts": [],
            "last_check": None
        }

    try:
        return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {
            "available_courts": [],
            "last_check": None
        }


def save_state(available_courts):
    state = {
        "available_courts": available_courts,
        "last_check": datetime.now(WARSAW_TZ).isoformat()
    }

    STATE_FILE.write_text(
        json.dumps(state, indent=2, ensure_ascii=False),
        encoding="utf-8"
    )


def send_email(available_courts):
    smtp_host = os.environ.get("SMTP_HOST")
    smtp_port = int(os.environ.get("SMTP_PORT", "587"))
    smtp_username = os.environ.get("SMTP_USERNAME")
    smtp_password = os.environ.get("SMTP_PASSWORD")
    email_from = os.environ.get("EMAIL_FROM", smtp_username)
    email_to = os.environ.get("EMAIL_TO")

    missing = []

    for name, value in [
        ("SMTP_HOST", smtp_host),
        ("SMTP_USERNAME", smtp_username),
        ("SMTP_PASSWORD", smtp_password),
        ("EMAIL_TO", email_to),
    ]:
        if not value:
            missing.append(name)

    if missing:
        raise RuntimeError(
            "Brakuje konfiguracji SMTP: " + ", ".join(missing)
        )

    now = datetime.now(WARSAW_TZ)
    courts_text = ", ".join(available_courts)

    message = EmailMessage()
    message["Subject"] = (
        f"🏸 Wolny kort Ganador: {courts_text}, 02.11.2026 o 20:00"
    )
    message["From"] = email_from
    message["To"] = email_to

    message.set_content(
        f"""Dostępny jest kort do badmintona w Ganador Sport.

Data: 02.11.2026
Godzina: 20:00
Wolne korty: {courts_text}
Sprawdzono: {now.strftime("%d.%m.%Y %H:%M:%S")}

Rezerwacja:
{URL}

Wiadomość została wysłana automatycznie po zmianie statusu kortu z zajętego na wolny.
"""
    )

    with smtplib.SMTP(smtp_host, smtp_port, timeout=30) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(smtp_username, smtp_password)
        smtp.send_message(message)

    print(f"Wysłano e-mail: {courts_text}")


def get_cell_data(cell):
    return cell.evaluate(
        """
        element => {
            const style = window.getComputedStyle(element);
            const link = element.querySelector("a");

            return {
                text: (element.innerText || "").trim(),
                className: element.className || "",
                backgroundColor: style.backgroundColor || "",
                color: style.color || "",
                cursor: style.cursor || "",
                href: link ? link.href : "",
                onclick:
                    element.getAttribute("onclick") ||
                    (link ? link.getAttribute("onclick") : "") ||
                    "",
                title:
                    element.getAttribute("title") ||
                    (link ? link.getAttribute("title") : "") ||
                    "",
                ariaLabel:
                    element.getAttribute("aria-label") ||
                    (link ? link.getAttribute("aria-label") : "") ||
                    "",
                hasLink: Boolean(link)
            };
        }
        """
    )


def find_schedule_table(page):
    tables = page.locator("table")

    for table_number in range(tables.count()):
        table = tables.nth(table_number)
        text = normalize_text(table.inner_text())

        if "BAD.2" in text and "20:00" in text and "22:00" in text:
            return table

    raise RuntimeError(
        "Nie znaleziono tabeli zawierającej korty BAD.2 oraz godziny "
        "20:00 i 22:00."
    )


def find_time_column(rows, target_time):
    target = normalize_text(target_time)

    for row_number in range(rows.count()):
        cells = rows.nth(row_number).locator("th, td")

        for column_number in range(cells.count()):
            cell_text = normalize_text(cells.nth(column_number).inner_text())

            if cell_text == target:
                return column_number

    raise RuntimeError(
        f"Nie znaleziono kolumny dla godziny {target_time}."
    )


def find_court_cell(rows, court_name, column_number):
    expected = normalize_text(court_name)

    for row_number in range(rows.count()):
        cells = rows.nth(row_number).locator("th, td")

        if cells.count() <= column_number:
            continue

        row_values = [
            normalize_text(cells.nth(i).inner_text())
            for i in range(cells.count())
        ]

        if expected in row_values:
            return cells.nth(column_number)

    raise RuntimeError(
        f"Nie znaleziono wiersza kortu {court_name}."
    )


def looks_like_reference(candidate, reference):
    candidate_text = " ".join(
        [
            candidate.get("text", ""),
            candidate.get("className", ""),
            candidate.get("title", ""),
            candidate.get("ariaLabel", ""),
            candidate.get("onclick", ""),
            candidate.get("href", ""),
        ]
    ).lower()

    unavailable_words = [
        "zajęty",
        "zajety",
        "occupied",
        "unavailable",
        "niedostępny",
        "niedostepny",
        "brak miejsc",
        "reserved",
        "rezerwacja zamknięta",
        "rezerwacja zamknieta",
    ]

    if any(word in candidate_text for word in unavailable_words):
        return False

    available_words = [
        "wolny",
        "dostępny",
        "dostepny",
        "available",
        "rezerwuj",
        "zarezerwuj",
    ]

    if any(word in candidate_text for word in available_words):
        return True

    if reference["hasLink"] and candidate["hasLink"]:
        return True

    if reference["onclick"] and candidate["onclick"]:
        return True

    reference_classes = set(reference["className"].lower().split())
    candidate_classes = set(candidate["className"].lower().split())

    meaningful_reference_classes = {
        value
        for value in reference_classes
        if value not in {"", "td", "cell", "slot"}
    }

    if (
        meaningful_reference_classes
        and meaningful_reference_classes.intersection(candidate_classes)
    ):
        return True

    if (
        reference["backgroundColor"]
        and candidate["backgroundColor"] == reference["backgroundColor"]
    ):
        return True

    return False


def check_availability():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        page = browser.new_page(
            viewport={"width": 1600, "height": 1200},
            locale="pl-PL",
            timezone_id="Europe/Warsaw",
        )

        print(f"Otwieram stronę: {URL}")

        page.goto(
            URL,
            wait_until="domcontentloaded",
            timeout=60000
        )

        page.wait_for_timeout(4000)

        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            print(
                "Strona nie osiągnęła networkidle. "
                "Kontynuuję po załadowaniu DOM."
            )

        page.screenshot(
            path=str(SCREENSHOT_FILE),
            full_page=True
        )

        HTML_FILE.write_text(
            page.content(),
            encoding="utf-8"
        )

        table = find_schedule_table(page)
        rows = table.locator("tr")

        target_column = find_time_column(rows, TARGET_TIME)
        reference_column = find_time_column(rows, REFERENCE_TIME)

        reference_cell = find_court_cell(
            rows,
            REFERENCE_COURT,
            reference_column
        )

        reference_data = get_cell_data(reference_cell)

        print(
            f"Wzorzec dostępności: "
            f"{REFERENCE_COURT} o {REFERENCE_TIME}"
        )
        print(
            json.dumps(
                reference_data,
                indent=2,
                ensure_ascii=False
            )
        )

        available_courts = []

        for court in COURTS:
            target_cell = find_court_cell(
                rows,
                court,
                target_column
            )

            target_data = get_cell_data(target_cell)
            available = looks_like_reference(
                target_data,
                reference_data
            )

            status = "🟢 WOLNY" if available else "🔴 ZAJĘTY"
            print(f"{court} o {TARGET_TIME}: {status}")

            print(
                json.dumps(
                    target_data,
                    indent=2,
                    ensure_ascii=False
                )
            )

            if available:
                available_courts.append(court)

        browser.close()

        return available_courts


def main():
    previous_state = load_previous_state()
    previous_available = set(
        previous_state.get("available_courts", [])
    )

    print(
        "Poprzednio dostępne korty:",
        sorted(previous_available)
    )

    current_available = check_availability()
    current_available_set = set(current_available)

    newly_available = sorted(
        current_available_set - previous_available
    )

    print("Obecnie dostępne:", sorted(current_available_set))
    print("Nowo dostępne:", newly_available)

    save_state(sorted(current_available_set))

    if newly_available:
        send_email(newly_available)
    else:
        print(
            "Brak zmiany 🔴→🟢. "
            "E-mail nie zostanie wysłany."
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"BŁĄD: {error}", file=sys.stderr)
        raise
