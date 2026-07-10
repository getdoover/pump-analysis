"""Manufacturer pump-curve model: interpolation, affinity scaling, inversion.

The curve is a list of (flow, head[, npshr]) points at a stated reference
speed. Inversion (head → flow) is the step that infers flow from measured
head, and it is only trustworthy where the curve has usable slope — every
inversion result carries a sensitivity-derived confidence for exactly that
reason.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CurvePoint:
    flow_m3h: float
    head_m: float
    npshr_m: float | None = None


@dataclass(frozen=True)
class FlowEstimate:
    flow_m3h: float
    #: |dH/dQ| at the solution, m per m³/h — the local slope the inversion
    #: relied on. Near-zero slope means the estimate is ill-conditioned.
    slope_m_per_m3h: float
    #: 0..1 heuristic: 1 where the curve is steep, → 0 as it flattens.
    confidence: float
    #: True when the target head cut the curve in more than one segment
    #: (droop/hump near shutoff) and the highest-flow crossing was chosen.
    ambiguous: bool


class PumpCurve:
    """A pump curve at a fixed reference speed.

    Confidence scaling: ``full_confidence_slope`` is the |dH/dQ| at which an
    inversion counts as fully conditioned. Defaults to the curve's own mean
    slope, so a uniformly steep curve self-calibrates.
    """

    def __init__(
        self,
        points: list[CurvePoint],
        reference_rpm: float,
        full_confidence_slope: float | None = None,
    ):
        if len(points) < 2:
            raise ValueError("pump curve needs at least 2 points")
        if reference_rpm <= 0:
            raise ValueError("reference_rpm must be positive")
        self.points = sorted(points, key=lambda p: p.flow_m3h)
        flows = [p.flow_m3h for p in self.points]
        if len(set(flows)) != len(flows):
            raise ValueError("pump curve has duplicate flow values")
        self.reference_rpm = reference_rpm

        total_span = abs(self.points[0].head_m - self.points[-1].head_m)
        flow_span = self.points[-1].flow_m3h - self.points[0].flow_m3h
        self.full_confidence_slope = (
            full_confidence_slope
            if full_confidence_slope is not None
            else max(total_span / flow_span, 1e-9)
        )

    # ------------------------------------------------------------ interpolation

    def head_at_flow(self, flow_m3h: float) -> float | None:
        """Linear interpolation; None outside the curve's flow range."""
        return self._interp(flow_m3h, [(p.flow_m3h, p.head_m) for p in self.points])

    def npshr_at_flow(self, flow_m3h: float) -> float | None:
        """NPSHr at a flow, from the points that carry npshr; None if <2 do."""
        pts = [(p.flow_m3h, p.npshr_m) for p in self.points if p.npshr_m is not None]
        if len(pts) < 2:
            return None
        return self._interp(flow_m3h, pts)

    @staticmethod
    def _interp(x: float, pts: list[tuple[float, float]]) -> float | None:
        if x < pts[0][0] or x > pts[-1][0]:
            return None
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            if x0 <= x <= x1:
                if x1 == x0:
                    return y0
                return y0 + (y1 - y0) * (x - x0) / (x1 - x0)
        return None

    # --------------------------------------------------------------- inversion

    def flow_at_head(self, head_m: float) -> FlowEstimate | None:
        """Invert the curve: which flow produces this head (at reference speed)?

        Scans every segment for a crossing. Real curves can droop near
        shutoff, giving two crossings — the highest-flow one is returned
        (the normal operating region, right of any hump) and the estimate is
        marked ambiguous.
        """
        crossings: list[tuple[float, float]] = []  # (flow, |slope|)
        for p0, p1 in zip(self.points, self.points[1:]):
            lo, hi = sorted((p0.head_m, p1.head_m))
            if not (lo <= head_m <= hi):
                continue
            dq = p1.flow_m3h - p0.flow_m3h
            dh = p1.head_m - p0.head_m
            if dh == 0.0:
                # Flat segment: the crossing is the whole segment. Take its
                # midpoint with zero slope — confidence will be zero.
                crossings.append(((p0.flow_m3h + p1.flow_m3h) / 2.0, 0.0))
                continue
            flow = p0.flow_m3h + dq * (head_m - p0.head_m) / dh
            crossings.append((flow, abs(dh / dq)))

        if not crossings:
            return None

        # A head landing exactly on a shared node registers once per adjoining
        # segment — collapse crossings at (near-)identical flows, keeping the
        # shallower slope so the confidence stays conservative.
        flow_span = self.points[-1].flow_m3h - self.points[0].flow_m3h
        epsilon = flow_span * 1e-6
        deduped: list[tuple[float, float]] = []
        for flow, slope in sorted(crossings):
            if deduped and abs(flow - deduped[-1][0]) <= epsilon:
                deduped[-1] = (deduped[-1][0], min(deduped[-1][1], slope))
            else:
                deduped.append((flow, slope))

        flow, slope = deduped[-1]  # highest-flow crossing: normal operating region
        ambiguous = len(deduped) > 1
        confidence = min(slope / self.full_confidence_slope, 1.0)
        if ambiguous:
            # Multiple genuinely distinct flows produce this head — the
            # estimate cannot be better than a coin toss between regions.
            confidence = min(confidence, 0.5)
        return FlowEstimate(
            flow_m3h=flow,
            slope_m_per_m3h=slope,
            confidence=confidence,
            ambiguous=ambiguous,
        )

    # --------------------------------------------------------- affinity-scaled

    def flow_from_measured_head(
        self, measured_head_m: float, pump_rpm: float
    ) -> FlowEstimate | None:
        """Infer live flow from measured head at the live speed.

        Scales the measurement back to reference speed (H ∝ N²), inverts the
        curve there, then scales the flow forward (Q ∝ N).
        """
        if pump_rpm <= 0:
            return None
        ref_head = measured_head_m * (self.reference_rpm / pump_rpm) ** 2
        est = self.flow_at_head(ref_head)
        if est is None:
            return None
        scale = pump_rpm / self.reference_rpm
        return FlowEstimate(
            flow_m3h=est.flow_m3h * scale,
            slope_m_per_m3h=est.slope_m_per_m3h,
            confidence=est.confidence,
            ambiguous=est.ambiguous,
        )

    def npshr_at_operating_point(
        self, flow_m3h: float, pump_rpm: float
    ) -> float | None:
        """NPSHr at a live operating point (flow at live speed).

        Looks up NPSHr on the reference curve at the affinity-equivalent flow
        and scales by (N/Nref)² — the standard approximation.
        """
        if pump_rpm <= 0:
            return None
        ref_flow = flow_m3h * self.reference_rpm / pump_rpm
        ref_npshr = self.npshr_at_flow(ref_flow)
        if ref_npshr is None:
            return None
        return ref_npshr * (pump_rpm / self.reference_rpm) ** 2

    def predicted_head_at(self, flow_m3h: float, pump_rpm: float) -> float | None:
        """Curve-predicted head at a live (flow, speed) — for degradation checks."""
        if pump_rpm <= 0:
            return None
        ref_flow = flow_m3h * self.reference_rpm / pump_rpm
        ref_head = self.head_at_flow(ref_flow)
        if ref_head is None:
            return None
        return ref_head * (pump_rpm / self.reference_rpm) ** 2
