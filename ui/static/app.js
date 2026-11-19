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
