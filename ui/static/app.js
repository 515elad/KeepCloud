// "i" popovers. Clicking works without this file (native popover attribute).
// This adds: open on keyboard focus, close when focus leaves, and placement
// next to the button that opened it.
(() => {
  "use strict";
  let invoker = null;
  let openedByFocus = false;

  const popoverFor = (button) => document.getElementById(button.getAttribute("popovertarget"));

  const place = (popover, button) => {
    popover.classList.add("is-anchored");
    const gap = 6;
    const edge = 8;
    const b = button.getBoundingClientRect();
    const p = popover.getBoundingClientRect();
    const vw = window.innerWidth;
    const vh = window.innerHeight;
    const clamp = (value, size, limit) => Math.max(edge, Math.min(value, limit - size - edge));
    let left = clamp(b.left, p.width, vw);
    let top = b.bottom + gap;
    if (top + p.height > vh - edge) {
      if (b.top - gap - p.height >= edge) {
        top = b.top - gap - p.height;
      } else {
        // Fits neither below nor above: sit beside the button so it stays visible.
        top = clamp(b.top, p.height, vh);
        if (b.right + gap + p.width <= vw - edge) left = b.right + gap;
        else if (b.left - gap - p.width >= edge) left = b.left - gap - p.width;
      }
    }
    popover.style.left = `${left}px`;
    popover.style.top = `${top}px`;
  };

  document.addEventListener("click", (event) => {
    const button = event.target.closest(".info");
    if (button) {
      invoker = button;
      openedByFocus = false;
    }
  }, true);

  document.addEventListener("focusin", (event) => {
    const button = event.target.closest?.(".info");
    if (!button || !button.matches(":focus-visible")) return;
    const popover = popoverFor(button);
    if (!popover || popover.matches(":popover-open")) return;
    invoker = button;
    openedByFocus = true;
    popover.showPopover();
  });

  document.addEventListener("focusout", (event) => {
    const button = event.target.closest?.(".info");
    if (!button || !openedByFocus) return;
    const popover = popoverFor(button);
    if (popover && popover.matches(":popover-open")) popover.hidePopover();
  });

  document.addEventListener("toggle", (event) => {
    const popover = event.target;
    if (!(popover instanceof HTMLElement) || !popover.classList.contains("help")) return;
    const open = event.newState === "open";
    document.querySelectorAll(`.info[popovertarget="${popover.id}"]`).forEach((button) => {
      button.setAttribute("aria-expanded", String(open && button === invoker));
    });
    if (open && invoker) place(popover, invoker);
    if (!open) openedByFocus = false;
  }, true);
})();

// Fail-open banner (UX-7): notice a change within a few seconds without a manual reload.
(() => {
  "use strict";
  const known = document.body.dataset.failOpen;
  if (known === undefined) return;
  const check = async () => {
    try {
      const response = await fetch("/api/fail-open", { cache: "no-store" });
      if (!response.ok) return;
      const { signature } = await response.json();
      // Do not reload over text the user is typing.
      const typing = document.activeElement && /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement.tagName);
      if (signature !== known && !typing) window.location.reload();
    } catch (error) {
      // The UI server did not answer; the next round tries again.
    }
  };
  window.setInterval(check, 4000);
})();

// Demo mode: keep the authenticator code shown next to a code input current, so a
// second sensitive action does not need a reload (which would clear what was typed).
(() => {
  "use strict";
  const spots = document.querySelectorAll(".demo-code");
  if (!spots.length) return;
  const show = (spot, code) => {
    const label = document.createElement("strong");
    label.textContent = "DEMO";
    spot.replaceChildren(label, " ");
    if (code) {
      const shown = document.createElement("code");
      shown.textContent = code;
      spot.append("Your authenticator would show ", shown, " now.");
      spot.dataset.demoCode = code;
    } else {
      spot.append("The next code is not valid yet. It appears here in a few seconds.");
      delete spot.dataset.demoCode;
    }
  };
  const refresh = async () => {
    try {
      const response = await fetch("/api/demo-code", { cache: "no-store" });
      if (!response.ok) return;
      const { code } = await response.json();
      spots.forEach((spot) => { if (spot.dataset.demoCode !== (code || undefined)) show(spot, code); });
    } catch (error) {
      // The UI server did not answer; the next round tries again.
    }
  };
  window.setInterval(refresh, 3000);
})();
