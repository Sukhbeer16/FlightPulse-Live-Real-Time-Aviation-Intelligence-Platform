"""Memory-conscious EDA summaries and plots for processed BTS flight chunks."""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


class EDAAccumulator:
    """Accumulate flight and delay metrics from one bounded chunk at a time."""

    def __init__(self) -> None:
        self.total_flights = 0
        self.cancelled_flights = 0
        self.known_cancellation_status = 0
        self.delay_bins = np.zeros(62, dtype=np.int64)
        self._aggregates: dict[str, pd.DataFrame] = {}

    def add(self, frame: pd.DataFrame) -> None:
        """Add a cleaned chunk to the in-memory group summaries."""
        self.total_flights += len(frame)
        cancelled_flag = pd.to_numeric(
            frame.get("Cancelled", pd.Series(pd.NA, index=frame.index)),
            errors="coerce",
        )
        cancelled = cancelled_flag.eq(1).fillna(False)
        status_known = cancelled_flag.isin([0, 1])
        self.cancelled_flights += int(cancelled.sum())
        self.known_cancellation_status += int(status_known.sum())

        eligible = frame.get(
            "is_trainable", pd.Series(True, index=frame.index)
        ).fillna(False).astype(bool)
        if "ArrDelay" in frame:
            delays = pd.to_numeric(frame["ArrDelay"], errors="coerce")
            values = delays.loc[eligible].dropna().to_numpy(dtype=float)
            self.delay_bins[0] += int((values < -300).sum())
            self.delay_bins[61] += int((values > 600).sum())
            in_range = values[(values >= -300) & (values <= 600)]
            self.delay_bins[1:61] += np.histogram(
                in_range, bins=np.arange(-300, 601, 15)
            )[0]

        if "is_trainable" not in frame or "is_delayed" not in frame:
            return
        eligible = frame["is_trainable"].fillna(False).astype(bool)
        delayed = frame["is_delayed"].fillna(0).astype("int8").eq(1)
        base = pd.DataFrame(
            {
                "flight_count": 1,
                "eligible_count": eligible.astype("int64"),
                "delayed_count": (eligible & delayed).astype("int64"),
                "cancelled_count": cancelled.astype("int64"),
                "status_known_count": status_known.astype("int64"),
            },
            index=frame.index,
        )
        dimensions = {
            "airline": ["Reporting_Airline"],
            "airport": ["Dest"],
            "route": ["route"],
            "hour": ["departure_hour"],
        }
        for name, keys in dimensions.items():
            if not set(keys).issubset(frame.columns):
                continue
            grouped = base.assign(**{key: frame[key] for key in keys})
            grouped = grouped.dropna(subset=keys).groupby(keys, observed=True).sum()
            self._merge(name, grouped)

    def _merge(self, name: str, values: pd.DataFrame) -> None:
        current = self._aggregates.get(name)
        self._aggregates[name] = (
            values
            if current is None
            else pd.concat([current, values])
            .groupby(level=list(range(values.index.nlevels)), sort=False)
            .sum()
        )

    def save(self, output_directory: Path) -> dict[str, int | float]:
        """Save EDA tables and PNG charts, returning measured overview counts."""
        output_directory.mkdir(parents=True, exist_ok=True)
        eligible_count = 0
        delayed_count = 0
        if "airline" in self._aggregates:
            eligible_count = int(self._aggregates["airline"]["eligible_count"].sum())
            delayed_count = int(self._aggregates["airline"]["delayed_count"].sum())

        summary = {
            "total_flights": self.total_flights,
            "cancelled_flights": self.cancelled_flights,
            "cancellation_percentage": (
                100 * self.cancelled_flights / self.known_cancellation_status
                if self.known_cancellation_status
                else 0.0
            ),
            "eligible_flights": eligible_count,
            "delayed_flights": delayed_count,
            "arrival_delay_percentage": (
                100 * delayed_count / eligible_count if eligible_count else 0.0
            ),
        }
        pd.DataFrame([summary]).to_csv(output_directory / "overview.csv", index=False)
        bin_labels = ["< -300"] + [
            f"{lower} to <{lower + 15}"
            for lower in range(-300, 600, 15)
        ] + ["> 600"]
        bin_labels[-2] = "585 to 600"
        pd.DataFrame(
            {"arrival_delay_bin_minutes": bin_labels, "flight_count": self.delay_bins}
        ).to_csv(output_directory / "arrival_delay_distribution.csv", index=False)

        for name, aggregate in self._aggregates.items():
            table = aggregate.copy()
            table["delay_percentage"] = np.where(
                table["eligible_count"] > 0,
                table["delayed_count"] / table["eligible_count"] * 100,
                np.nan,
            )
            table["cancellation_percentage"] = np.where(
                table["status_known_count"] > 0,
                table["cancelled_count"] / table["status_known_count"] * 100,
                np.nan,
            )
            table.to_csv(output_directory / f"{name}_delays.csv")

        self._plot_group(
            "airline",
            output_directory / "airline_delay_rates.png",
            "Airline arrival delay rate (eligible flights)",
            top=15,
        )
        self._plot_group(
            "airport",
            output_directory / "airport_delay_rates.png",
            "Arrival airport delay rate (eligible flights)",
            top=15,
        )
        self._plot_group(
            "route",
            output_directory / "route_delay_rates.png",
            "Route arrival delay rate (eligible flights)",
            top=20,
        )
        self._plot_group(
            "hour",
            output_directory / "hourly_delay_rates.png",
            "Arrival delay rate by scheduled departure hour",
            top=24,
            hourly=True,
        )
        self._plot_delay_distribution(output_directory / "arrival_delay_distribution.png")
        return summary

    def _plot_group(
        self,
        name: str,
        output_path: Path,
        title: str,
        top: int,
        hourly: bool = False,
    ) -> None:
        aggregate = self._aggregates.get(name)
        if aggregate is None or aggregate.empty:
            return
        table = aggregate.loc[aggregate["eligible_count"] > 0].copy()
        table["delay_percentage"] = (
            table["delayed_count"] / table["eligible_count"] * 100
        )
        table = table.sort_values("delay_percentage").tail(top)
        labels = table.index.get_level_values(0).astype(str)
        if hourly:
            table = table.sort_index()
            labels = table.index.get_level_values(0).astype(str)

        figure, axis = plt.subplots(figsize=(10, 5))
        axis.bar(labels, table["delay_percentage"], color="#168a82")
        axis.set_title(title)
        axis.set_ylabel("Delayed arrivals (%)")
        axis.set_xlabel(name.replace("_", " ").title())
        axis.tick_params(axis="x", labelrotation=55 if not hourly else 0)
        figure.tight_layout()
        figure.savefig(output_path, dpi=140)
        plt.close(figure)

    def _plot_delay_distribution(self, output_path: Path) -> None:
        figure, axis = plt.subplots(figsize=(10, 5))
        positions = np.arange(len(self.delay_bins))
        axis.bar(positions, self.delay_bins, width=0.9, color="#168a82")
        tick_positions = [0, 1, *range(5, 61, 4), 61]
        tick_labels = ["< -300"] + [
            str(-300 + (position - 1) * 15) for position in tick_positions[1:-1]
        ] + ["> 600"]
        axis.set_xticks(tick_positions, tick_labels, rotation=45, ha="right")
        axis.set_title("Arrival delay distribution (15-minute interior bins)")
        axis.set_xlabel("Arrival delay in minutes (tail bins show outliers)")
        axis.set_ylabel("Flights")
        figure.tight_layout()
        figure.savefig(output_path, dpi=140)
        plt.close(figure)
