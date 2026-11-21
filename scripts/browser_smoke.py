"""Run against local development services. Creates one labelled in-memory demonstration alert."""

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
        pattern = "**/historical/processed-flights?*"
        page.route(pattern, lambda route: route.abort())
        visit("live-tracking")
        expect(page.get_by_role("button", name="Retry historical data")).to_be_visible()
        page.unroute(pattern)
        page.get_by_role("button", name="Retry historical data").click()
        expect(
            page.get_by_role("heading", name="Historical BTS record")
        ).to_be_visible()
        page.get_by_title("Close Drawer").click()
        page.get_by_role("button", name="3D GLOBE").click()
        expect(page.get_by_text("3D ORBITAL VIEW")).to_be_visible()
        page.locator("canvas").first.wait_for()
        page.get_by_role("button", name="2D RADAR").click()
        page.locator(".maplibregl-canvas").wait_for()
        page.get_by_title("Toggle between historical replay and live OpenSky").click()
        expect(page.get_by_text("LOADING BACKEND DATA", exact=False)).to_have_count(
            0, timeout=20000
        )
        provider = page.request.get(
            "http://127.0.0.1:8000/api/v1/live/provider-status"
        ).json()
        if not provider["oauth_configured"]:
            expect(page.get_by_text("credentials_missing", exact=False)).to_be_visible()
        visit("delay-prediction")
        for model in [
            "logistic-regression",
            "decision-tree",
            "random-forest",
            "xgboost",
        ]:
            page.locator("select").last.select_option(model)
            with page.expect_response(
                lambda r: "/predictions/delay?" in r.url
            ) as response:
                page.get_by_role("button", name="COMPUTE").click()
            value = response.value.json()
            assert value["status"] == "available", value
            expect(
                page.get_by_text("Model: " + value["model_id"], exact=False)
            ).to_be_visible()
            print(model, value["model_score"])
        for route in ["disruption", "anomaly-detection"]:
            visit(route)
            page.get_by_label("Historical flight", exact=True).select_option(index=1)
            expect(
                page.get_by_text("Isolation Forest anomaly score", exact=False)
            ).to_be_visible()
            expect(
                page.get_by_text("Observed arrival delay", exact=False).first
            ).to_be_visible()
        page.get_by_role("button", name="Create demonstration alert").click()
        expect(
            page.get_by_text("Demonstration alert recorded for", exact=False)
        ).to_be_visible()
        visit("alerts")
        expect(
            page.get_by_text("Demonstration Risk Alert", exact=True).first
        ).to_be_visible()
        for route in ["overview", "settings", "assistant", "system-status"]:
            visit(route)
            expect(page.get_by_role("heading").first).to_be_visible()
        assert 200 in tiles, tiles
        assert not errors, errors
        print("All routes passed. Successful tile responses:", tiles.count(200))
        browser.close()


if __name__ == "__main__":
    run()
