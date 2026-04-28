document.addEventListener('submit', async (event) => {
  const form = event.target;
  if (!(form instanceof HTMLFormElement)) {
    return;
  }
  if (form.matches('[data-question-form]')) {
    event.preventDefault();
    const question = new FormData(form).get('question')?.toString().trim();
    if (!question) {
      return;
    }
    const response = await fetch(form.action, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ user_id: 'owner', question }),
    });
    const payload = await response.json();
    writeFormOutput(form, payload.answer || '暂无可回答内容。');
    return;
  }
  if (!form.matches('[data-json-form]')) {
    return;
  }
  event.preventDefault();
  const payload = formPayload(form);
  const response = await fetch(form.action, {
    method: 'POST',
    headers: { 'content-type': 'application/json' },
    body: JSON.stringify(payload),
  });
  const body = await response.json();
  writeFormOutput(form, body.status || body.watchlist_id || body.prediction_id || '已记录');
});

function formPayload(form) {
  const data = new FormData(form);
  const payload = {};
  for (const key of new Set(data.keys())) {
    const values = data.getAll(key).map((value) => value.toString());
    payload[key] = values.length > 1 || key.endsWith('preferences') ? values : values[0];
  }
  return payload;
}

function writeFormOutput(form, message) {
  let output = form.querySelector('[data-answer-output]');
  if (!output) {
    output = document.createElement('p');
    output.setAttribute('data-answer-output', 'true');
    form.appendChild(output);
  }
  output.textContent = message;
}
