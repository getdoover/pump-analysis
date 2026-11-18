"""Pure hydraulic maths for pump analysis.

No pydoover imports — everything here is a plain function of floats, so it can
be golden-tested against hand-worked numbers. All internal units are SI-ish:
pressures in kPa, heads in metres, flows in m³/h, temperatures in °C.

Sign/reference conventions:
- Gauge pressures are relative to local atmospheric.
- Heights are positive-up. ``gauge_height_m`` is the height of the transmitter
  tapping point ABOVE the pump impeller eye (negative if below).
"""

from __future__ import annotations

import math

G = 9.80665  # m/s²

STANDARD_ATMOSPHERE_KPA = 101.325


def barometric_pressure_kpa(elevation_m: float) -> float:
    """Standard-atmosphere barometric pressure at a site elevation."""
    return STANDARD_ATMOSPHERE_KPA * (1.0 - 2.25577e-5 * elevation_m) ** 5.25588


def water_vapour_pressure_kpa(temp_c: float) -> float:
    """Saturation vapour pressure of water (Buck equation, 1996).

    Within ~0.05% of reference values over 0…100 °C.
    """
    return 0.61121 * math.exp((18.678 - temp_c / 234.5) * (temp_c / (257.14 + temp_c)))


def water_density_kg_m3(temp_c: float) -> float:
    """Fresh-water density (UNESCO/Bigg polynomial, 0…50 °C)."""
    t = temp_c
    return (
        999.842594
        + 6.793952e-2 * t
        - 9.095290e-3 * t**2
        + 1.001685e-4 * t**3
        - 1.120083e-6 * t**4
        + 6.536332e-9 * t**5
    )


def velocity_m_s(flow_m3h: float | None, pipe_id_mm: float | None) -> float:
    """Mean pipe velocity; 0.0 when flow or bore is unknown.

    Treating unknown as zero deliberately degrades the velocity-head terms to
    nil rather than poisoning the whole calculation with None.
    """
    if not flow_m3h or not pipe_id_mm:
        return 0.0
    area_m2 = math.pi * (pipe_id_mm / 2000.0) ** 2
    if area_m2 <= 0.0:
        return 0.0
    return (flow_m3h / 3600.0) / area_m2


def velocity_head_m(v_m_s: float) -> float:
    return v_m_s**2 / (2.0 * G)


def total_differential_head_m(
    suction_kpa_g: float,
    discharge_kpa_g: float,
    density_kg_m3: float,
    *,
    gauge_separation_m: float = 0.0,
    suction_velocity_m_s: float = 0.0,
    discharge_velocity_m_s: float = 0.0,
) -> float:
    """Total differential head between the two transmitter tappings.

    ``gauge_separation_m`` is discharge-gauge height minus suction-gauge
    height (positive when the discharge tapping is higher).
    """
    pressure_head = (discharge_kpa_g - suction_kpa_g) * 1000.0 / (density_kg_m3 * G)
    velocity_head = velocity_head_m(discharge_velocity_m_s) - velocity_head_m(
        suction_velocity_m_s
    )
    return pressure_head + gauge_separation_m + velocity_head


def npsh_available_m(
    suction_kpa_g: float,
    barometric_kpa: float,
    vapour_pressure_kpa: float,
    density_kg_m3: float,
    *,
    suction_velocity_m_s: float = 0.0,
    gauge_height_above_impeller_m: float = 0.0,
) -> float:
    """NPSH available at the impeller eye.

    NPSHa = (Ps_abs − Pvap)/ρg + v²/2g + (gauge height above eye).

    The gauge-height term translates the reading from the tapping point down
    to the impeller eye: a gauge mounted above the eye reads LOW relative to
    the eye, so its height is added back.
    """
    absolute_kpa = suction_kpa_g + barometric_kpa
    static_head = (absolute_kpa - vapour_pressure_kpa) * 1000.0 / (density_kg_m3 * G)
    return (
        static_head
        + velocity_head_m(suction_velocity_m_s)
        + gauge_height_above_impeller_m
    )


def suction_kpa_at_npsha(
    npsha_m: float,
    barometric_kpa: float,
    vapour_pressure_kpa: float,
    density_kg_m3: float,
    *,
    gauge_height_above_impeller_m: float = 0.0,
) -> float:
    """Suction gauge pressure at which NPSHa equals ``npsha_m``.

    The inverse of :func:`npsh_available_m` with the velocity head left out
    (flow is not known when gauge bands are laid out; it is small and leaving
    it out puts the threshold slightly on the cautious side).
    """
    static_head = npsha_m - gauge_height_above_impeller_m
    return (
        static_head * density_kg_m3 * G / 1000.0
        + vapour_pressure_kpa
        - barometric_kpa
    )


# ---------------------------------------------------------------- affinity laws


def affinity_flow(flow: float, from_rpm: float, to_rpm: float) -> float:
    """Q ∝ N."""
    return flow * (to_rpm / from_rpm)


def affinity_head(head: float, from_rpm: float, to_rpm: float) -> float:
    """H ∝ N²."""
    return head * (to_rpm / from_rpm) ** 2


def pump_rpm_from_engine(engine_rpm: float, ratio: float, offset: float) -> float:
    """Linear engine→pump speed transform (gearing / pulley ratio)."""
    return engine_rpm * ratio + offset


def bar_to_kpa(bar: float) -> float:
    return bar * 100.0


def bar_to_metres_head(bar: float, density_kg_m3: float) -> float:
    """Convert a gauge pressure to an equivalent column of the pumped fluid."""
    return bar * 100_000.0 / (density_kg_m3 * G)


def metres_head_per_bar(temp_c: float) -> float:
    """m of water head per bar at a given temperature (~10.20 m/bar at 20 °C)."""
    return bar_to_metres_head(1.0, water_density_kg_m3(temp_c))


def scale_4_20ma(
    reading_ma: float | None,
    range_low: float,
    range_high: float,
    *,
    fault_below_ma: float = 3.8,
    fault_above_ma: float = 20.5,
) -> float | None:
    """Scale a 4–20 mA reading to engineering units.

    Returns None outside the plausible loop band — an out-of-band current is a
    sensor/loop fault, never a legitimate reading, and must not become a
    number downstream. The −0.5…0 mA droop band below 4 mA clamps to
    range_low, matching the house 4-20ma-sensor convention.
    """
    if reading_ma is None:
        return None
    if reading_ma < fault_below_ma or reading_ma > fault_above_ma:
        return None
    fraction = (reading_ma - 4.0) / 16.0
    if -0.5 / 16.0 < fraction < 0.0:
        fraction = 0.0
    return fraction * (range_high - range_low) + range_low


# --------------------------------------------------------- NPSHr estimation
#
# For curves published without NPSHr. A rule of thumb, not a datasheet: real
# inlets vary enough that the result is good to roughly +/-40% at best
# efficiency and worse away from it. Callers must present it as an estimate
# and must not alarm or trip on it.

_USGPM_PER_M3H = 4.402868
_M_PER_FT = 0.3048


def npshr_at_bep_m(
    rpm: float,
    bep_flow_m3h: float,
    *,
    suction_specific_speed: float = 9000.0,
    double_suction: bool = False,
) -> float:
    """NPSHr at best-efficiency flow from an assumed suction specific speed.

    Nss = N * sqrt(Q) / NPSHr^0.75 in US units (rpm, US gpm, ft), with Q the
    flow per impeller eye — half the pump flow for a double-suction impeller.
    """
    q_gpm = bep_flow_m3h * _USGPM_PER_M3H
    if double_suction:
        q_gpm /= 2.0
    npshr_ft = (rpm * q_gpm**0.5 / suction_specific_speed) ** (4.0 / 3.0)
    return npshr_ft * _M_PER_FT


def npshr_flow_factor(flow_ratio: float) -> float:
    """NPSHr at a flow relative to NPSHr at best-efficiency flow.

    Flat up to BEP, then rising with the square of flow — the usual shape of
    the right-hand side of an NPSHr curve. Mirrored in the widget
    (``estimatedNpshr`` in widget/src/lib/pump.ts); change both together.
    """
    return max(1.0, flow_ratio**2)
