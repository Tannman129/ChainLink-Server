const dialog = document.querySelector('#login-dialog');
const form = document.querySelector('#login-form');
const message = document.querySelector('#login-message');
const signIn = document.querySelector('#sign-in');
const signOut = document.querySelector('#sign-out');
let csrf;

async function session() {
  const response = await fetch('/v1/auth/session', { cache: 'no-store' });
  if (!response.ok) throw new Error('Sign in is unavailable. Try again.');
  const data = await response.json();
  csrf = data.csrf_token;
  document.querySelector('#account-name').textContent = data.user?.username || '';
  signIn.hidden = !!data.user;
  signOut.hidden = !data.user;
}
signIn.addEventListener('click', async () => {
  message.textContent = '';
  dialog.showModal();
  try { await session(); } catch (error) { message.textContent = error.message; }
});
document.querySelector('#login-cancel').addEventListener('click', () => {
  form.reset();
  dialog.close();
});
dialog.addEventListener('close', () => form.reset());
form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const submit = form.querySelector('[type=submit]');
  submit.disabled = true;
  message.textContent = '';
  try {
    if (!csrf) await session();
    const response = await fetch('/v1/auth/login', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': csrf },
      body: JSON.stringify({ username: form.elements.username.value, password: form.elements.password.value }),
    });
    form.elements.password.value = '';
    if (!response.ok) {
      if (response.status === 403) { await session(); throw new Error('Session expired. Please try again.'); }
      throw new Error(response.status === 429 ? 'Too many attempts. Please try again later.' : 'Unable to sign in. Check your username and password.');
    }
    window.dispatchEvent(new Event('chainlink-auth-changed'));
    await session();
    dialog.close();
  } catch (error) { message.textContent = error.message; }
  finally { form.elements.password.value = ''; submit.disabled = false; }
});
signOut.addEventListener('click', async () => {
  signOut.disabled = true;
  try {
    await session();
    const response = await fetch('/v1/auth/logout', { method: 'POST', headers: { 'X-CSRF-Token': csrf } });
    if (!response.ok) throw new Error('Sign out failed. Try again.');
    window.dispatchEvent(new Event('chainlink-auth-changed'));
    await session();
  } catch (error) {
    message.textContent = error.message;
    if (!dialog.open) dialog.showModal();
  } finally { signOut.disabled = false; }
});
// Browsing remains available if authentication or the database is unavailable.
session().catch(() => {});
