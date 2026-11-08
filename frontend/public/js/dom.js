// Небольшие помощники для работы с DOM, общие для обеих страниц.

export const $ = (selector) => document.querySelector(selector);

export function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  Object.assign(node, attrs);
  node.append(...children);
  return node;
}

export function show(container, ...children) {
  container.replaceChildren(...children);
  container.hidden = false;
}

export function showError(container, error) {
  show(container, el('p', { className: 'error', textContent: error.message }));
}

export function clear(container) {
  container.replaceChildren();
  container.hidden = true;
}

/** Блокирует первую кнопку формы на время действия, чтобы не отправить запрос дважды. */
export async function withBusy(form, action) {
  const button = form.querySelector('button');
  button.disabled = true;
  try {
    await action();
  } finally {
    button.disabled = false;
  }
}

export function debounce(fn, delayMs) {
  let timer;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), delayMs);
  };
}
