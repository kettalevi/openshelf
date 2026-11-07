// SPDX-License-Identifier: AGPL-3.0-or-later
// Copyright (C) 2026 kettalevi
//
// Asks for confirmation before submitting any form with a data-confirm
// attribute. Kept in a file (not inline) so the Content-Security-Policy can
// forbid inline scripts.
document.addEventListener("submit", function (event) {
  var message = event.target.dataset && event.target.dataset.confirm;
  if (message && !window.confirm(message)) {
    event.preventDefault();
  }
});
