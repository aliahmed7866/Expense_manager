document.querySelectorAll("form[data-confirm]").forEach((form) => {
  form.addEventListener("submit", (event) => {
    if (!window.confirm(form.dataset.confirm)) event.preventDefault();
  });
});

const kindInputs = document.querySelectorAll('input[name="kind"]');
const categorySelect = document.querySelector('select[name="category_id"]');
function syncCategories() {
  if (!categorySelect || !kindInputs.length) return;
  const kind = document.querySelector('input[name="kind"]:checked')?.value || "expense";
  let selectedVisible = false;
  [...categorySelect.options].forEach((option) => {
    option.hidden = option.dataset.kind !== kind;
    if (option.selected && !option.hidden) selectedVisible = true;
  });
  if (!selectedVisible) {
    const first = [...categorySelect.options].find((option) => !option.hidden);
    if (first) first.selected = true;
  }
}
kindInputs.forEach((input) => input.addEventListener("change", syncCategories));
syncCategories();

if (window.location.hash === "#add") {
  window.setTimeout(() => document.querySelector('#add input[name="amount"]')?.focus(), 250);
}
