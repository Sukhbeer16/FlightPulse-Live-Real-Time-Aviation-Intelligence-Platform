// ─────────────────────────────────────────────────────────
// FlightPulse Live — GSAP Controlled Cinematic Timelines
// Used for controlled cinematic sequences, HUD reveals & telemetry tickers
// ─────────────────────────────────────────────────────────

import gsap from 'gsap';

export function isReducedMotion(): boolean {
  if (typeof window === 'undefined') return false;
  return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Initial Tactical Dashboard boot sequence
 * Staggers HUD headers, telemetry gauges, and radar border glows
 */
export function playBootSequence(containerSelector: string, onComplete?: () => void) {
  if (isReducedMotion()) {
    if (onComplete) onComplete();
    return;
  }

  const ctx = gsap.context(() => {
    const tl = gsap.timeline({ onComplete });

    tl.fromTo(
      `${containerSelector} [data-gsap="tactical-header"]`,
      { y: -20, opacity: 0 },
      { y: 0, opacity: 1, duration: 0.6, ease: 'power3.out' }
    )
      .fromTo(
        `${containerSelector} [data-gsap="hud-panel"]`,
        { opacity: 0, scale: 0.98 },
        { opacity: 1, scale: 1, duration: 0.5, stagger: 0.08, ease: 'power2.out' },
        '-=0.3'
      )
      .fromTo(
        `${containerSelector} [data-gsap="telemetry-item"]`,
        { opacity: 0, x: -10 },
        { opacity: 1, x: 0, duration: 0.4, stagger: 0.04, ease: 'sine.out' },
        '-=0.2'
      );
  });

  return () => ctx.revert();
}

/**
 * Animated number ticker for altitude, groundspeed, squawk
 */
export function animateTelemetryNumber(
  element: HTMLElement | null,
  targetValue: number,
  duration: number = 0.8
) {
  if (!element || isReducedMotion()) {
    if (element) element.textContent = targetValue.toLocaleString();
    return;
  }

  const current = parseFloat(element.textContent?.replace(/,/g, '') || '0') || 0;
  const obj = { val: current };

  gsap.to(obj, {
    val: targetValue,
    duration,
    ease: 'power2.out',
    onUpdate: () => {
      element.textContent = Math.round(obj.val).toLocaleString();
    },
  });
}

/**
 * Subtle pulse alert highlight for critical anomaly notifications
 */
export function pulseCriticalAlert(element: HTMLElement | null) {
  if (!element || isReducedMotion()) return;

  gsap.fromTo(
    element,
    { borderColor: 'rgba(239, 68, 68, 0.9)', boxShadow: '0 0 25px rgba(239, 68, 68, 0.4)' },
    {
      borderColor: 'rgba(239, 68, 68, 0.3)',
      boxShadow: '0 0 5px rgba(239, 68, 68, 0.1)',
      duration: 1.2,
      repeat: 3,
      yoyo: true,
      ease: 'power1.inOut',
    }
  );
}
