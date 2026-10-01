let currentTripId = null;
let currentTrip = null;

const $ = (id) => document.getElementById(id);

function money(n) {
  return "₹" + Number(n).toFixed(2);
}

async function api(url, options = {}) {
  const res = await fetch(url, {
    headers: {"Content-Type": "application/json"},
    ...options
  });

  const data = await res.json().catch(() => ({}));

  if (!res.ok) {
    throw new Error(data.detail || "Something went wrong");
  }

  return data;
}

function toast(message) {
  const el = $("toast");
  el.textContent = message;
  el.style.display = "block";
  setTimeout(() => el.style.display = "none", 2500);
}

async function loadTrips() {
  const trips = await api("/api/trips");
  const select = $("tripSelect");

  select.innerHTML = trips.length
    ? trips.map(t => `<option value="${t.id}">${escapeHtml(t.name)}</option>`).join("")
    : `<option value="">No trips</option>`;

  if (currentTripId && trips.some(t => t.id == currentTripId)) {
    select.value = currentTripId;
  } else if (trips.length) {
    currentTripId = trips[0].id;
    select.value = currentTripId;
  }

  if (currentTripId) {
    await loadTrip();
  } else {
    $("emptyState").classList.remove("hidden");
    $("appContent").classList.add("hidden");
  }
}

async function loadTrip() {
  currentTripId = Number($("tripSelect").value);
  if (!currentTripId) return;

  currentTrip = await api(`/api/trips/${currentTripId}`);

  $("emptyState").classList.add("hidden");
  $("appContent").classList.remove("hidden");
  $("tripName").textContent = currentTrip.trip.name;

  renderMembers();
  renderExpenseForm();
  renderBalances();
  renderSettlements();
  renderExpenses();
  renderCompleted();
}

function renderMembers() {
  $("members").innerHTML = currentTrip.members.length
    ? currentTrip.members.map(m => `
        <div class="member">
          <strong>${escapeHtml(m.name)}</strong>
        </div>
      `).join("")
    : `<div class="muted">No members yet.</div>`;
}

function renderExpenseForm() {
  const members = currentTrip.members;

  $("expensePaidBy").innerHTML = members.map(m =>
    `<option value="${m.id}">${escapeHtml(m.name)}</option>`
  ).join("");

  $("splitMembers").innerHTML = members.map(m => `
    <label class="checkbox">
      <input type="checkbox" class="split-member" value="${m.id}">
      <span>${escapeHtml(m.name)}</span>
    </label>
  `).join("");
}

function renderBalances() {
  $("balances").innerHTML = currentTrip.balances.map(b => {
    const cls = b.net > 0.009 ? "positive" : b.net < -0.009 ? "negative" : "zero";
    const text = b.net > 0.009
      ? `Gets back ${money(b.net)}`
      : b.net < -0.009
        ? `Owes ${money(Math.abs(b.net))}`
        : "Settled";

    return `
      <div class="balance">
        <div class="name">${escapeHtml(b.name)}</div>
        <div class="muted">Paid: ${money(b.paid)}</div>
        <div class="muted">Share: ${money(b.share)}</div>
        <div class="net ${cls}">${text}</div>
      </div>
    `;
  }).join("");
}

function renderSettlements() {
  const list = currentTrip.settlements;

  if (!list.length) {
    $("settlements").innerHTML = `
      <div class="empty">
        All balances are settled. 🎉
      </div>
    `;
    return;
  }

  $("settlements").innerHTML = list.map(s => `
    <div class="settlement">
      <div>
        <strong>${escapeHtml(s.from_name)}</strong>
        <span> → </span>
        <strong>${escapeHtml(s.to_name)}</strong>
        <div class="muted">Payment required</div>
      </div>
      <div>
        <span class="amount">${money(s.amount)}</span>
        <button onclick="completeSettlement(${s.from_member}, ${s.to_member}, ${s.amount})">
          Mark as Done
        </button>
      </div>
    </div>
  `).join("");
}

function renderExpenses() {
  const total = currentTrip.expenses.reduce((sum, e) => sum + Number(e.amount), 0);
  $("totalExpenses").textContent = `Total: ${money(total)}`;

  $("expenses").innerHTML = currentTrip.expenses.length
    ? currentTrip.expenses.map(e => `
      <tr>
        <td><strong>${escapeHtml(e.description)}</strong></td>
        <td>${money(e.amount)}</td>
        <td>${escapeHtml(e.paid_by_name)}</td>
        <td>${e.splits.map(s => `${escapeHtml(s.name)} (${money(s.share)})`).join(", ")}</td>
        <td>${escapeHtml(e.category)}</td>
      </tr>
    `).join("")
    : `<tr><td colspan="5">No expenses yet.</td></tr>`;
}

function renderCompleted() {
  const list = currentTrip.completed_settlements;

  $("completedSettlements").innerHTML = list.length
    ? list.map(s => `
      <div class="completed">
        ✓ ${escapeHtml(s.from_name)} paid
        <strong>${money(s.amount)}</strong>
        to ${escapeHtml(s.to_name)}
      </div>
    `).join("")
    : `<div class="muted">No completed settlements.</div>`;
}

$("expenseForm").addEventListener("submit", async (e) => {
  e.preventDefault();

  const memberIds = [...document.querySelectorAll(".split-member:checked")]
    .map(x => Number(x.value));

  if (!memberIds.length) {
    toast("Select at least one member.");
    return;
  }

  try {
    await api(`/api/trips/${currentTripId}/expenses`, {
      method: "POST",
      body: JSON.stringify({
        description: $("expenseDescription").value,
        amount: Number($("expenseAmount").value),
        paid_by: Number($("expensePaidBy").value),
        member_ids: memberIds,
        category: $("expenseCategory").value
      })
    });

    $("expenseForm").reset();
    toast("Expense added.");
    await loadTrip();
  } catch (err) {
    toast(err.message);
  }
});

async function completeSettlement(from, to, amount) {
  try {
    await api(`/api/trips/${currentTripId}/settlements`, {
      method: "POST",
      body: JSON.stringify({
        from_member: from,
        to_member: to,
        amount: amount
      })
    });

    toast("Settlement marked as done.");
    await loadTrip();
  } catch (err) {
    toast(err.message);
  }
}

function openTripModal() {
  $("modalTitle").textContent = "Create New Trip";
  $("modalForm").innerHTML = `
    <input id="modalTripName" placeholder="Trip name e.g. Goa Trip" required>
    <button type="submit">Create Trip</button>
  `;

  $("modalForm").onsubmit = async (e) => {
    e.preventDefault();
    try {
      const result = await api("/api/trips", {
        method: "POST",
        body: JSON.stringify({name: $("modalTripName").value})
      });
      closeModal();
      currentTripId = result.id;
      await loadTrips();
      toast("Trip created.");
    } catch (err) {
      toast(err.message);
    }
  };

  $("modal").classList.remove("hidden");
}

function openMemberModal() {
  $("modalTitle").textContent = "Add Member";
  $("modalForm").innerHTML = `
    <input id="modalMemberName" placeholder="Member name" required>
    <button type="submit">Add Member</button>
  `;

  $("modalForm").onsubmit = async (e) => {
    e.preventDefault();
    try {
      await api(`/api/trips/${currentTripId}/members`, {
        method: "POST",
        body: JSON.stringify({name: $("modalMemberName").value})
      });
      closeModal();
      await loadTrip();
      toast("Member added.");
    } catch (err) {
      toast(err.message);
    }
  };

  $("modal").classList.remove("hidden");
}

function closeModal() {
  $("modal").classList.add("hidden");
}

async function createDemo() {
  try {
    const result = await api("/api/demo", {method: "POST"});
    currentTripId = result.trip_id;
    await loadTrips();
    toast("Demo trip loaded.");
  } catch (err) {
    toast(err.message);
  }
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

loadTrips().catch(err => toast(err.message));
