"""Run against local development services. Saves one real, labelled historical alert in the local inbox."""

from playwright.sync_api import sync_playwright, expect


def run():
    expect.set_options(timeout=20000)
    with sync_playwright() as api:
        browser = api.chromium.launch(
            channel="msedge", args=["--enable-unsafe-swiftshader"]
        )
        page = browser.new_page(viewport={"width": 1440, "height": 900})
        page.set_default_timeout(20000)
        errors, tiles = [], []
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "response",
            lambda r: tiles.append(r.status)
            if "tile.openstreetmap.org/" in r.url
            else None,
        )

        def visit(route):
            page.goto("http://127.0.0.1:5173/" + route, wait_until="domcontentloaded")

        visit("historical")
        search = page.get_by_role("button", name="Search records")
        page.get_by_label("BTS origin", exact=True).fill("JFK")
        page.get_by_label("Flight date", exact=True).fill("2024-01-10")
        search.click()
        expect(page.locator("tbody tr").first).to_contain_text("2024-01-10")
        expect(page.locator("tbody tr").first).to_contain_text("JFK")
        page.get_by_role("button", name="Next", exact=True).click()
        expect(page.get_by_text("Page 2", exact=True)).to_be_visible()
        pattern = "**/live/airspace/new-york"
        page.route(pattern, lambda route: route.abort())
        visit("live-tracking")
        expect(page.get_by_text("Recorded snapshot", exact=True)).to_be_visible()
        expect(page.locator(".traffic-list button").first).to_be_visible()
        page.unroute(pattern)
        page.get_by_role("button", name="Retry", exact=True).click()
        expect(page.get_by_text("Live feed", exact=True)).to_be_visible()
        aircraft = page.locator(".traffic-list button")
        expect(aircraft.first).to_be_visible()
        aircraft.first.click()
        expect(page.get_by_text("Position time", exact=True)).to_be_visible()
        for mode in ["3D", "2D"]:
            toggle = page.get_by_role("button", name=mode, exact=True)
            toggle.click()
            expect(toggle).to_have_attribute("aria-pressed", "true")
            expect(page.locator(".maplibregl-canvas")).to_be_visible()
            expect(page.locator(".aircraft-title")).to_be_visible()
        visit("delay-prediction")
        with page.expect_response(lambda r: "/predictions/delay?model=best" in r.url) as response:
            page.get_by_role("button", name="Get best-model forecast").click()
        value = response.value.json()
        assert value["status"] == "available", value
        assert value["selection"]["compared_models"] == 4
        assert value["model_id"] == "phase4.2-retrained-logistic-regression-unweighted"
        assert 0 < value["threshold"] < 0.5
        expect(page.get_by_text("selected from 4 models", exact=False)).to_be_visible()
        expect(page.get_by_role("heading", name="What influenced the forecast?")).to_be_visible()
        expect(page.get_by_role("heading", name="Why was this flight late?")).to_be_visible()
        print("Validation winner", value["model_id"], value["model_score"])
        visit("live-tracking")
        page.get_by_role("button", name="Dataset flights", exact=True).click()
        expect(page.get_by_role("heading", name="Flights in your dataset")).to_be_visible()
        expect(page.get_by_label("Dataset city")).to_contain_text("Atlanta, GA")
        page.get_by_label("Dataset city").select_option("Atlanta, GA")
        expect(page.locator(".dataset-route-list button").first).to_be_visible()
        page.get_by_label("Dataset airport").select_option("ATL")
        expect(page.locator(".dataset-route-list button").first).to_be_visible()
        page.locator(".dataset-route-list button").first.click()
        expect(page.get_by_label("Dataset origin")).not_to_have_value("")
        page.locator(".traffic-list button").first.click()
        expect(page.get_by_role("heading", name="Why was this flight late?")).to_be_visible()
        page.get_by_role("button", name="Kafka stream", exact=True).click()
        expect(page.get_by_text("Kafka · Live observations", exact=True)).to_be_visible()
        for route in ["disruption", "anomaly-detection"]:
            visit(route)
            page.get_by_label("Historical flight", exact=True).select_option(index=1)
            expect(
                page.get_by_text("Isolation Forest anomaly score", exact=False)
            ).to_be_visible()
            expect(
                page.get_by_text("Observed arrival delay", exact=False).first
            ).to_be_visible()
        with page.expect_response(lambda r: r.url.endswith('/alerts/historical')) as response:
            page.get_by_role("button", name="Save historical alert").click()
        alert = response.value.json()
        expect(
            page.get_by_text("Historical alert saved to the inbox for", exact=False)
        ).to_be_visible()
        visit("alerts")
        expect(
            page.get_by_text(alert["title"], exact=True).first
        ).to_be_visible()
        page.get_by_label("Alert type").select_option("historical_delay")
        page.get_by_label("Search alerts").fill(alert["flight_reference"])
        record=page.locator(".ops-inbox-list details").filter(has_text=alert["title"]).first
        expect(record).to_be_visible()
        record.locator("summary").click()
        if record.get_by_role("button",name="Acknowledge").count():
            record.get_by_role("button",name="Acknowledge").click()
            expect(record.get_by_text("Acknowledged",exact=True)).to_be_visible()
        if record.get_by_role("button",name="Resolve").count():
            record.get_by_role("button",name="Resolve").click()
            expect(record.get_by_text("Resolved",exact=True)).to_be_visible()
        for route in ["overview", "settings", "assistant", "system-status"]:
            visit(route)
            expect(page.get_by_role("heading").first).to_be_visible()
        assert 200 in tiles, tiles
        assert not errors, errors
        print("All routes passed. Successful tile responses:", tiles.count(200))
        browser.close()


if __name__ == "__main__":
    run()
